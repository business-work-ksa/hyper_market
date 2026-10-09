"""Les signaux de risque : des indices, présentés à un humain qui décide.

Pour chaque détecteur, un vrai positif **et** un faux positif évité — un détecteur qui crie pour
tout apprend à ne plus lire la file. Puis la déduplication, la décision tracée, la console, et la
règle de l'ADR-013 : rien dans `apps/confiance/` ne modifie l'état d'une boutique.
"""

import pathlib
import re
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Appartenance, Role
from apps.confiance import signaux
from apps.confiance.models import SignalRisque
from apps.core.models import AccesPlateforme
from apps.core.tenancy import contexte_boutique
from apps.marketplace.models import Boutique, CompteVersement
from apps.orders.models import Commande, Litige, SousCommande
from apps.payments.models import Prestataire, Transaction
from tests import fabrique
from tests.test_paliers import acheteurs, vieillir

_n = {"i": 0}


def signaux_de(boutique, type_=None):
    qs = SignalRisque.objects.filter(boutique=boutique)
    return qs.filter(type=type_) if type_ else qs


def commandes(boutique, nombre, *, prepayee=True, il_y_a_jours=0, etat=SousCommande.EN_ATTENTE, montant="10000"):
    """`nombre` sous-commandes passées il y a `il_y_a_jours` jours, prépayées ou non."""
    client = acheteurs(1)[0]
    prestataire, _ = Prestataire.objects.get_or_create(code=Prestataire.MTN_MOMO, defaults={"libelle": "MTN"})
    moment = timezone.now() - timedelta(days=il_y_a_jours)
    mode = {}
    if any(f.name == "mode_paiement" for f in SousCommande._meta.get_fields()):
        mode = {"mode_paiement": "prepaye" if prepayee else "livraison"}
    parts = []
    for _ in range(nombre):
        _n["i"] += 1
        c = Commande.objects.create(numero=f"S-{_n['i']:07d}", acheteur=client, etat=Commande.CONFIRMEE)
        if prepayee:
            Transaction.objects.create(
                commande=c, prestataire=prestataire, sens=Transaction.ENCAISSEMENT, montant=Decimal(montant),
                etat=Transaction.REUSSIE, cle_idempotence=f"cle-{_n['i']}",
            )
        with contexte_boutique(boutique):
            sc = SousCommande.objects.create(boutique=boutique, commande=c, etat=etat, total_ttc=Decimal(montant), **mode)
            SousCommande.objects.filter(pk=sc.pk).update(cree_le=moment)
        parts.append(sc)
    return parts


class Detecteur(TestCase):
    def evaluer(self, detecteur):
        return signaux.evaluer_signaux(detecteurs=(detecteur,))


# ----------------------------------------------------------------------------
# 1. Identités partagées
# ----------------------------------------------------------------------------
class IdentitesPartageesTest(Detecteur):
    def test_meme_telephone_qu_une_boutique_suspendue(self):
        ancienne = fabrique.creer_boutique("Téléphones Express")
        nouvelle = fabrique.creer_boutique("Phone Discount")
        Boutique.objects.filter(pk=ancienne.pk).update(telephone="699 12 34 56", etat=Boutique.SUSPENDUE)
        Boutique.objects.filter(pk=nouvelle.pk).update(telephone="+237699123456")
        self.evaluer(signaux.detecter_identites_partagees)

        s = signaux_de(nouvelle).get()
        self.assertEqual(s.gravite, SignalRisque.CRITIQUE)
        self.assertIn("Même téléphone que « Téléphones Express »", s.resume)
        self.assertIn("suspendue", s.resume)
        self.assertFalse(signaux_de(ancienne).exists(), "une boutique déjà fermée n'est pas le sujet")

    def test_meme_compte_de_versement_masque_dans_la_preuve(self):
        a, b = fabrique.creer_boutique("A"), fabrique.creer_boutique("B")
        for x in (a, b):
            CompteVersement.objects.create(
                boutique=x, operateur="MTN_MOMO", numero="+237677001122", titulaire="Jean", etat=CompteVersement.EN_ATTENTE
            )
        self.evaluer(signaux.detecter_identites_partagees)
        s = signaux_de(a).get()
        self.assertIn("compte de versement", s.resume)
        self.assertNotIn("677001122", str(s.preuves), "un numéro de compte n'est jamais recopié en entier")

    def test_un_rccm_bidon_partage_n_est_pas_un_lien(self):
        a, b = fabrique.creer_boutique("A"), fabrique.creer_boutique("B")
        Boutique.objects.filter(pk__in=[a.pk, b.pk]).update(rccm="N/A", niu="0000000", telephone="")
        self.evaluer(signaux.detecter_identites_partagees)
        self.assertFalse(SignalRisque.objects.exists())


class DeduplicationTest(Detecteur):
    def setUp(self):
        self.a, self.b = fabrique.creer_boutique("A"), fabrique.creer_boutique("B")
        Boutique.objects.filter(pk__in=[self.a.pk, self.b.pk]).update(rccm="RC/DLA/2026/B/1234")

    def test_un_signal_ouvert_est_mis_a_jour_pas_duplique(self):
        self.evaluer(signaux.detecter_identites_partagees)
        premier = signaux_de(self.a).get()
        bilan = self.evaluer(signaux.detecter_identites_partagees)
        self.assertEqual(bilan["crees"], 0)
        self.assertEqual(signaux_de(self.a).count(), 1)
        self.assertGreater(signaux_de(self.a).get().constate_le, premier.constate_le)

    def test_un_signal_ecarte_ne_revient_que_si_les_faits_changent(self):
        self.evaluer(signaux.detecter_identites_partagees)
        juge = fabrique.creer_utilisateur("Arbitre")
        signaux.trancher(signaux_de(self.a).get(), decision="ecarter", motif="Même propriétaire, vérifié par appel.", par=juge)
        self.evaluer(signaux.detecter_identites_partagees)
        self.assertFalse(signaux_de(self.a).filter(etat=SignalRisque.OUVERT).exists())

        c = fabrique.creer_boutique("C")
        Boutique.objects.filter(pk=c.pk).update(rccm="RC/DLA/2026/B/1234")
        self.evaluer(signaux.detecter_identites_partagees)
        self.assertTrue(signaux_de(self.a).filter(etat=SignalRisque.OUVERT).exists())


# ----------------------------------------------------------------------------
# 2. Prix d'appât
# ----------------------------------------------------------------------------
class PrixAppatTest(Detecteur):
    ARTICLES = [("Ciment CPJ 42,5 — 50 kg", 5200), ("Fer à béton 10 mm", 4800), ("Tôle ondulée 3 m", 6500)]

    def setUp(self):
        for i in range(3):
            b = vieillir(fabrique.creer_boutique(f"Établie {i}"), 200)
            for libelle, prix in self.ARTICLES:
                fabrique.creer_variante(b, prix=str(prix + 100 * i), libelle=libelle)

    def _vendeur(self, jours, facteur):
        b = vieillir(fabrique.creer_boutique("Nouveau venu"), jours)
        for libelle, prix in self.ARTICLES:
            fabrique.creer_variante(b, prix=str(int(prix * facteur)), libelle=libelle.upper())
        return b

    def test_une_boutique_recente_a_moitie_prix(self):
        b = self._vendeur(5, 0.4)
        self.evaluer(signaux.detecter_prix_appat)
        s = signaux_de(b).get()
        self.assertEqual(s.gravite, SignalRisque.ELEVEE)
        self.assertEqual(len(s.preuves["appats"]), 3)

    def test_une_boutique_etablie_qui_casse_les_prix_n_est_pas_signalee(self):
        self._vendeur(90, 0.4)
        self.evaluer(signaux.detecter_prix_appat)
        self.assertFalse(SignalRisque.objects.exists())

    def test_une_seule_promotion_n_est_pas_un_appat(self):
        b = vieillir(fabrique.creer_boutique("Nouveau venu"), 5)
        for (libelle, prix), facteur in zip(self.ARTICLES, (0.4, 1, 1)):
            fabrique.creer_variante(b, prix=str(int(prix * facteur)), libelle=libelle)
        self.evaluer(signaux.detecter_prix_appat)
        self.assertFalse(signaux_de(b).exists())


# ----------------------------------------------------------------------------
# 3. Pic de prépaiement
# ----------------------------------------------------------------------------
class PicPrepaiementTest(Detecteur):
    def test_une_boutique_jeune_qui_encaisse_d_un_coup(self):
        b = vieillir(fabrique.creer_boutique("Flash Vente"), 20)
        commandes(b, 12, il_y_a_jours=1)
        self.evaluer(signaux.detecter_pic_prepaiement)
        s = signaux_de(b).get()
        self.assertTrue(s.preuves["jamais_livre"])
        self.assertEqual(s.gravite, SignalRisque.ELEVEE)

    def test_le_paiement_a_la_livraison_et_les_petits_volumes_ne_comptent_pas(self):
        b = vieillir(fabrique.creer_boutique("Tranquille"), 20)
        commandes(b, 5, il_y_a_jours=1)
        commandes(b, 12, il_y_a_jours=1, prepayee=False)
        self.evaluer(signaux.detecter_pic_prepaiement)
        self.assertFalse(SignalRisque.objects.exists())

    def test_une_boutique_etablie_reguliere_n_est_pas_un_pic(self):
        b = vieillir(fabrique.creer_boutique("Régulière"), 200)
        for semaine in range(0, 12):
            commandes(b, 12, il_y_a_jours=semaine * 7 + 1)
        self.evaluer(signaux.detecter_pic_prepaiement)
        self.assertFalse(SignalRisque.objects.exists())

    def test_l_escroquerie_longue_au_palier_sans_plafond(self):
        b = vieillir(fabrique.creer_boutique("Établie depuis longtemps"), 300)
        Boutique.objects.filter(pk=b.pk).update(palier_confiance=3)
        for semaine in range(1, 12):
            commandes(b, 2, il_y_a_jours=semaine * 7 + 1, montant="10000")
        commandes(b, 15, il_y_a_jours=1, montant="80000")
        self.evaluer(signaux.detecter_pic_prepaiement)
        s = signaux_de(b).get()
        self.assertEqual(s.preuves["lecture"], "etablie")
        self.assertTrue(s.preuves["sans_plafond"])
        self.assertEqual(s.gravite, SignalRisque.CRITIQUE)


# ----------------------------------------------------------------------------
# 4. Litiges et annulations
# ----------------------------------------------------------------------------
class LitigesAnnulationsTest(Detecteur):
    def _litiges(self, boutique, parts):
        with contexte_boutique(boutique):
            for sc in parts:
                Litige.objects.create(boutique=boutique, sous_commande=sc, motif=Litige.NON_RECUE, description="?")

    def test_une_boutique_bien_au_dessus_du_marche(self):
        suspecte, saine = fabrique.creer_boutique("Suspecte"), fabrique.creer_boutique("Saine")
        self._litiges(suspecte, commandes(suspecte, 20, il_y_a_jours=3)[:6])
        self._litiges(saine, commandes(saine, 40, il_y_a_jours=3)[:1])
        self.evaluer(signaux.detecter_litiges_annulations)
        self.assertTrue(signaux_de(suspecte).exists())
        self.assertFalse(signaux_de(saine).exists())

    def test_quand_tout_le_marche_souffre_ce_n_est_pas_une_boutique(self):
        a, b = fabrique.creer_boutique("A"), fabrique.creer_boutique("B")
        for x in (a, b):
            self._litiges(x, commandes(x, 20, il_y_a_jours=3)[:6])
        self.evaluer(signaux.detecter_litiges_annulations)
        self.assertFalse(SignalRisque.objects.exists())

    def test_trois_commandes_ne_font_pas_une_statistique(self):
        a, _ = fabrique.creer_boutique("A"), fabrique.creer_boutique("B")
        self._litiges(a, commandes(a, 3, il_y_a_jours=3))
        self.evaluer(signaux.detecter_litiges_annulations)
        self.assertFalse(SignalRisque.objects.exists())


# ----------------------------------------------------------------------------
# 5. Changement de compte, puis versement
# ----------------------------------------------------------------------------
class ChangementCompteTest(Detecteur):
    def setUp(self):
        self.b = fabrique.creer_boutique("Boutique")
        self.ancien = CompteVersement.objects.create(
            boutique=self.b, operateur="MTN_MOMO", numero="+237677000001", titulaire="Awa Bello", etat=CompteVersement.RETIRE
        )
        CompteVersement.objects.filter(pk=self.ancien.pk).update(cree_le=timezone.now() - timedelta(days=200))

    def _demande(self, boutique_ids, depuis):
        return [{"boutique_id": self.b.pk, "le": timezone.now(), "montant": Decimal("900000"), "demande_par": "X"}]

    def test_nouveau_compte_puis_versement_sous_7_jours(self):
        CompteVersement.objects.create(
            boutique=self.b, operateur="ORANGE_MONEY", numero="+237655999888", titulaire="Paul Inconnu"
        )
        with mock.patch.object(signaux, "_demandes_de_versement", self._demande):
            self.evaluer(signaux.detecter_changement_compte)
        s = signaux_de(self.b).get()
        self.assertEqual(s.gravite, SignalRisque.CRITIQUE)
        self.assertTrue(s.preuves["titulaire_change"])
        self.assertNotIn("655999888", s.resume + str(s.preuves))

    def test_un_premier_compte_n_est_pas_un_changement(self):
        autre = fabrique.creer_boutique("Première fois")
        CompteVersement.objects.create(boutique=autre, operateur="MTN_MOMO", numero="+237677555444", titulaire="Z")
        with mock.patch.object(signaux, "_demandes_de_versement", lambda ids, depuis: [
            {"boutique_id": autre.pk, "le": timezone.now(), "montant": Decimal("1")}
        ]):
            self.evaluer(signaux.detecter_changement_compte)
        self.assertFalse(SignalRisque.objects.exists())

    def test_se_tait_sans_modele_versement(self):
        CompteVersement.objects.create(boutique=self.b, operateur="ORANGE_MONEY", numero="+237655999888", titulaire="P")
        with mock.patch.object(signaux, "_demandes_de_versement", lambda ids, depuis: None):
            self.evaluer(signaux.detecter_changement_compte)
        self.assertFalse(SignalRisque.objects.exists())


# ----------------------------------------------------------------------------
# 6. Boutique active non vérifiée
# ----------------------------------------------------------------------------
class NonVerifieeTest(Detecteur):
    def test_une_boutique_active_a_qui_il_manque_une_piece(self):
        b = fabrique.creer_boutique("Pressée")
        candidate = fabrique.creer_boutique("Candidate")
        Boutique.objects.filter(pk=candidate.pk).update(etat=Boutique.CANDIDATURE)
        with mock.patch.object(signaux, "_fonction_manques", lambda: lambda boutique: ["Pièce du gérant non vérifiée."]):
            self.evaluer(signaux.detecter_non_verifiees)
        self.assertEqual(signaux_de(b).get().preuves["manques"], ["Pièce du gérant non vérifiée."])
        self.assertFalse(signaux_de(candidate).exists(), "une candidature n'est pas encore active")

    def test_une_boutique_complete_ou_sans_module_ne_signale_rien(self):
        fabrique.creer_boutique("Complète")
        with mock.patch.object(signaux, "_fonction_manques", lambda: lambda boutique: []):
            self.evaluer(signaux.detecter_non_verifiees)
        with mock.patch.object(signaux, "_fonction_manques", lambda: None):
            self.evaluer(signaux.detecter_non_verifiees)
        self.assertFalse(SignalRisque.objects.exists())


# ----------------------------------------------------------------------------
# La décision humaine, et la console
# ----------------------------------------------------------------------------
class ConsoleDesSignauxTest(TestCase):
    def setUp(self):
        self.admin = fabrique.creer_utilisateur("Administrateur du marché")
        call_command("preparer_administrateur", administrateur=self.admin.telephone, verbosity=0)
        self.admin.refresh_from_db()
        self.a = fabrique.creer_boutique("Téléphones Express")
        self.b = fabrique.creer_boutique("Phone Discount")
        Boutique.objects.filter(pk__in=[self.a.pk, self.b.pk]).update(telephone="+237699123456")
        Boutique.objects.filter(pk=self.a.pk).update(etat=Boutique.SUSPENDUE)
        signaux.evaluer_signaux(detecteurs=(signaux.detecter_identites_partagees,))
        self.signal = SignalRisque.objects.get(boutique=self.b)
        self.client.force_login(self.admin)

    def test_la_file_et_la_fiche_montrent_la_preuve_lisible(self):
        reponse = self.client.get(reverse("plateforme:signaux"))
        self.assertContains(reponse, "Phone Discount")
        self.assertContains(reponse, "Même téléphone que « Téléphones Express »")
        self.assertContains(reponse, "Critique")
        fiche = self.client.get(reverse("plateforme:signal", args=[self.signal.pk]))
        self.assertContains(fiche, "Pourquoi ce n'est pas une preuve")
        self.assertContains(fiche, f"{reverse('plateforme:boutique_etat', args=[self.b.pk])}?action=suspendre")

    def test_la_decision_est_tracee_et_ne_se_rejoue_pas(self):
        url = reverse("plateforme:signal", args=[self.signal.pk])
        reponse = self.client.post(url, {"decision": "confirmer", "motif": "Même gérant que la boutique suspendue."})
        self.assertRedirects(reponse, url, fetch_redirect_response=False)
        self.signal.refresh_from_db()
        self.assertEqual((self.signal.etat, self.signal.traite_par), (SignalRisque.CONFIRME, self.admin))
        trace = AccesPlateforme.objects.get(ecran="plateforme:signal")
        self.assertEqual(trace.boutique_id, self.b.pk)
        self.assertIn("confirmé", trace.motif)
        self.b.refresh_from_db()
        self.assertEqual(self.b.etat, Boutique.ACTIVE, "confirmer un signal ne suspend pas")

        rejoue = self.client.post(url, {"decision": "ecarter", "motif": "Je change d'avis, finalement."})
        self.assertEqual(rejoue.status_code, 400)
        self.assertEqual(AccesPlateforme.objects.filter(ecran="plateforme:signal").count(), 1)

    def test_un_motif_trop_court_est_refuse(self):
        reponse = self.client.post(
            reverse("plateforme:signal", args=[self.signal.pk]), {"decision": "ecarter", "motif": "ok"}
        )
        self.assertEqual(reponse.status_code, 400)
        self.assertFalse(AccesPlateforme.objects.filter(ecran="plateforme:signal").exists())

    def test_le_tableau_de_bord_le_rail_et_la_fiche_boutique(self):
        tableau = self.client.get(reverse("plateforme:tableau_de_bord"))
        self.assertContains(tableau, "à trancher")
        self.assertContains(tableau, reverse("plateforme:signaux"))
        fiche = self.client.get(reverse("plateforme:boutique", args=[self.b.pk]))
        self.assertContains(fiche, "Confiance")
        self.assertContains(fiche, reverse("plateforme:signal", args=[self.signal.pk]))

    def test_un_commercant_n_entre_pas(self):
        commercant = fabrique.creer_utilisateur("Commerçant")
        role, _ = Role.objects.get_or_create(code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE})
        Appartenance.objects.create(utilisateur=commercant, boutique=self.b, role=role)
        self.client.force_login(commercant)
        self.assertEqual(self.client.get(reverse("plateforme:signaux")).status_code, 403)

    def test_chaque_type_de_preuve_s_affiche(self):
        preuves = {
            "prix_appat": {"anciennete_jours": 5, "comparables": 3, "part": "100 %", "appats": [
                {"article": "Ciment", "prix": "2000", "mediane": "5000", "ecart": "60 %", "references": 3, "variante": "x"}]},
            "pic_prepaiement": {"lecture": "etablie", "recentes": 15, "montant": "1200000", "reference": "20000",
                                "ratio": "60.0", "anciennete_jours": 300, "jamais_livre": False,
                                "plafond_sequestre": None, "au_plafond": False, "sans_plafond": True},
            "litiges_annulations": {"fenetre_jours": 30, "commandes": 20, "litiges": 6, "litiges_non_recues": 6,
                                    "annulations": 0, "taux_litiges": "30 %", "taux_annulations": "0 %",
                                    "marche_litiges": "2 %", "marche_annulations": "0 %"},
            "changement_compte": {"ancien": {"numero": "•••• 0001", "operateur": "MTN", "titulaire": "A", "depuis": "1er mai 2026"},
                                  "nouveau": {"numero": "•••• 9888", "operateur": "Orange", "titulaire": "B", "declare_le": "2 mai",
                                              "declare_par": "X", "declare_par_administration": True, "verifie_par": "Y", "etat": "Vérifié"},
                                  "titulaire_change": True, "versements": [{"le": "3 mai", "montant": "900000", "demande_par": "X"}]},
            "non_verifiee": {"manques": ["Pièce du gérant non vérifiée."]},
        }
        for type_, p in preuves.items():
            s = SignalRisque.objects.create(
                boutique=self.b, type=type_, gravite=2, score=50, resume=f"Résumé {type_}", preuves=p,
                empreinte=type_, constate_le=timezone.now(),
            )
            with self.subTest(type=type_):
                self.assertContains(self.client.get(reverse("plateforme:signal", args=[s.pk])), f"Résumé {type_}")


class AucuneSuspensionAutomatiqueTest(TestCase):
    def test_aucun_code_de_la_confiance_ne_modifie_l_etat_d_une_boutique(self):
        """ADR-013 : un signal est un indice ; suspendre est le geste d'un humain, dans la console."""
        motif = re.compile(r"(boutique|\bb)\.etat\s*=[^=]|Boutique\.objects[^\n]*update\([^)]*\betat\s*=")
        coupables = [
            str(f) for f in sorted(pathlib.Path("apps/confiance").rglob("*.py")) if motif.search(f.read_text())
        ]
        self.assertEqual(coupables, [])
