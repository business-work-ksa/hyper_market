"""Les tableaux de bord et écrans de suivi de la console (ADR-012).

Ce que ces tests défendent, dans l'ordre où un incident coûterait le plus cher :

1. **La frontière de confidentialité.** L'écran d'activité lit des tables scopées : il ne doit en
   sortir que des agrégats — jamais une marge, un coût, un stock, un client ou une écriture, ni
   dans le contexte du gabarit, ni dans la page rendue.
2. **Le journal.** Chaque affichage d'un écran d'activité écrit exactement une ligne ; aucun autre
   écran n'en écrit. Sans motif, pas d'écran.
3. **Les portes.** Chaque écran s'ouvre aux deux administrateurs ; la santé technique au seul
   superadministrateur.
4. **Les calculs**, qui se testent sans gabarit : recouvrement, prorata, séries vides.
5. **La performance** de la liste des boutiques : un nombre de requêtes qui ne dépend pas du
   nombre de boutiques.
"""

import re
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Appartenance, Role
from apps.core.models import AccesPlateforme
from apps.core.tenancy import contexte_boutique
from apps.marketplace.models import Bail, Boutique, EmplacementPremium, FactureLoyer
from apps.plateforme import indicateurs as ind
from apps.plateforme.vues_boutiques import PAR_PAGE
from tests import fabrique
from tests.test_console import PersonnagesMixin

# Ce que l'administrateur du marché n'a pas à lire chez un commerçant (ADR-012, §3). Cherché
# dans les clés du contexte et dans le texte de la page, sans accents ni casse.
MOTS_INTERDITS = ["marge", "cout", "cmp", "stock", "cahier", "client", "ecriture", "achat"]


def _sans_accents(texte: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn"
    ).lower()


def _contenu_principal(reponse) -> str:
    """Le texte visible de `<main>` — le rail et les pictogrammes (`#ic-marge`, `#ic-stock`)
    appartiennent au gabarit commun et ne disent rien de ce que l'écran a lu."""
    html = reponse.content.decode()
    principal = html[html.index("<main"): html.index("</main>")]
    principal = re.sub(r"<[^>]+>", " ", principal)
    return _sans_accents(principal)


class SocleTableaux(PersonnagesMixin, TestCase):
    """Un marché minimal mais complet : boutiques dans chaque état, loyers, emplacements."""

    def setUp(self):
        self.poser_les_personnages()
        self.aujourdhui = timezone.localdate()
        self.mois = ind.debut_du_mois(self.aujourdhui)

        self.active = fabrique.creer_boutique("Quincaillerie Témoin", avec_comptabilite=False)
        self.active.ville = "Yaoundé"
        self.active.telephone = "+237677112233"
        self.active.rccm = "RC/YAO/2026/B/4242"
        self.active.niu = "M012600009999Z"
        self.active.save()
        self.bail = self.active.bail_actif

        self.candidature = fabrique.creer_boutique("Candidate Kribi", avec_comptabilite=False)
        Boutique.objects.filter(pk=self.candidature.pk).update(etat=Boutique.CANDIDATURE, ville="Kribi")
        Bail.objects.filter(boutique=self.candidature).update(etat=Bail.BROUILLON)

        self.suspendue = fabrique.creer_boutique("Suspendue Garoua", avec_comptabilite=False)
        Boutique.objects.filter(pk=self.suspendue.pk).update(etat=Boutique.SUSPENDUE, ville="Garoua")

        # Deux loyers : le mois précédent payé, le mois courant échu.
        precedent = ind.decaler_mois(self.mois, -1)
        FactureLoyer.objects.create(
            bail=self.bail, periode=precedent, montant_ht=Decimal("45000"),
            echeance=precedent + timedelta(days=9), etat=FactureLoyer.PAYEE, paye_le=timezone.now(),
        )
        self.echue = FactureLoyer.objects.create(
            bail=self.bail, periode=self.mois, montant_ht=Decimal("45000"),
            echeance=self.aujourdhui - timedelta(days=1), etat=FactureLoyer.EMISE,
        )
        self.emplacement = EmplacementPremium.objects.create(
            type=EmplacementPremium.TETE_DE_GONDOLE, debut=self.aujourdhui - timedelta(days=2),
            fin=self.aujourdhui + timedelta(days=4), tarif=Decimal("21000"),
            boutique_occupante=self.active,
        )

    def ouvrir_suivi(self, compte):
        self.client.force_login(compte)
        self.client.post(reverse("plateforme:suivi_ouvrir"), {"motif": "suivi_mensuel"})

    def vendre(self, boutique, montant, *, il_y_a=0, client_nom=""):
        """Un ticket clôturé, posé dans le contexte de sa boutique (barrière 3)."""
        from apps.pos.models import SessionCaisse, Ticket

        if not hasattr(self, "_sessions"):
            self._sessions = {}
        if boutique.pk not in self._sessions:
            depot = fabrique.creer_depot(boutique)
            with contexte_boutique(boutique):
                self._sessions[boutique.pk] = SessionCaisse.objects.create(
                    boutique=boutique, depot=depot, caissier=self.commercant
                )
        session = self._sessions[boutique.pk]
        with contexte_boutique(boutique):
            return Ticket.objects.create(
                boutique=boutique, session=session, numero=f"T-{Ticket.objects.count() + 1:06d}",
                total_ttc=Decimal(montant), etat=Ticket.CLOTURE, client_nom=client_nom,
                cloture_le=timezone.now() - timedelta(days=il_y_a),
            )


# ----------------------------------------------------------------------------
# Les portes
# ----------------------------------------------------------------------------
class ChaqueEcranRepondTest(SocleTableaux):
    def ecrans(self):
        return [
            reverse("plateforme:tableau_de_bord"),
            reverse("plateforme:tableau_de_bord") + "?periode=6",
            reverse("plateforme:journal"),
            reverse("plateforme:boutiques"),
            reverse("plateforme:boutique", args=[self.active.pk]),
            reverse("plateforme:boutique", args=[self.candidature.pk]),
            reverse("plateforme:loyers"),
            reverse("plateforme:loyers") + "?mois=tous&etat=echues",
            reverse("plateforme:rayons"),
            reverse("plateforme:emplacements") + "?vue=a_venir",
            reverse("plateforme:activite"),
            reverse("plateforme:boutique_activite", args=[self.active.pk]),
        ]

    def test_les_deux_administrateurs_ouvrent_chaque_ecran(self):
        for compte in (self.superadmin, self.administrateur):
            self.ouvrir_suivi(compte)
            for url in self.ecrans():
                with self.subTest(compte=compte.nom_complet, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_la_sante_technique_est_reservee_au_superadministrateur(self):
        self.client.force_login(self.administrateur)
        self.assertEqual(self.client.get(reverse("plateforme:technique")).status_code, 403)
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.get(reverse("plateforme:technique")).status_code, 200)

    def test_le_commercant_ne_voit_aucun_ecran(self):
        self.client.force_login(self.commercant)
        for url in (reverse("plateforme:boutiques"), reverse("plateforme:loyers")):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_une_boutique_inconnue_donne_404(self):
        import uuid

        self.client.force_login(self.administrateur)
        reponse = self.client.get(reverse("plateforme:boutique", args=[uuid.uuid4()]))
        self.assertEqual(reponse.status_code, 404)

    def test_la_gouvernance_n_apparait_qu_au_superadministrateur(self):
        self.client.force_login(self.administrateur)
        reponse = self.client.get(reverse("plateforme:tableau_de_bord"))
        self.assertNotIn("gouvernance", reponse.context)
        self.client.force_login(self.superadmin)
        reponse = self.client.get(reverse("plateforme:tableau_de_bord"))
        self.assertIn("gouvernance", reponse.context)
        self.assertContains(reponse, reverse("plateforme:technique"))


# ----------------------------------------------------------------------------
# Le journal
# ----------------------------------------------------------------------------
class LectureJournaliseeTest(SocleTableaux):
    def test_sans_motif_l_activite_renvoie_au_formulaire_de_suivi(self):
        self.client.force_login(self.administrateur)
        for url in (
            reverse("plateforme:activite"),
            reverse("plateforme:boutique_activite", args=[self.active.pk]),
        ):
            reponse = self.client.get(url)
            self.assertEqual(reponse.status_code, 302)
            self.assertIn(reverse("plateforme:suivi_ouvrir"), reponse["Location"])
        self.assertEqual(AccesPlateforme.objects.count(), 0)

    def test_chaque_affichage_de_l_activite_ecrit_une_ligne(self):
        self.ouvrir_suivi(self.administrateur)
        self.client.get(reverse("plateforme:activite"))
        self.client.get(reverse("plateforme:activite"))
        lignes = AccesPlateforme.objects.filter(ecran="plateforme:activite")
        self.assertEqual(lignes.count(), 2)
        self.assertTrue(all(l.boutique_id is None for l in lignes))
        self.assertEqual(lignes.first().utilisateur, self.administrateur)
        self.assertIn("Suivi mensuel", lignes.first().motif)

    def test_l_activite_d_une_boutique_nomme_la_boutique(self):
        self.ouvrir_suivi(self.superadmin)
        self.client.get(reverse("plateforme:boutique_activite", args=[self.active.pk]))
        ligne = AccesPlateforme.objects.get()
        self.assertEqual(ligne.boutique_id, self.active.pk)
        self.assertEqual(ligne.ecran, "plateforme:boutique_activite")

    def test_les_contrats_du_bailleur_ne_sont_pas_journalises(self):
        """Lire un bail ou un loyer ne franchit aucune barrière : le journal ne doit pas se
        remplir de consultations qui ne regardent pas chez le commerçant."""
        self.ouvrir_suivi(self.administrateur)
        for url in (
            reverse("plateforme:tableau_de_bord"),
            reverse("plateforme:boutiques"),
            reverse("plateforme:boutique", args=[self.active.pk]),
            reverse("plateforme:loyers"),
            reverse("plateforme:journal"),
        ):
            self.client.get(url)
        self.assertEqual(AccesPlateforme.objects.count(), 0)

    def test_la_fiche_montre_les_acces_qui_la_concernent(self):
        self.ouvrir_suivi(self.administrateur)
        self.client.get(reverse("plateforme:boutique_activite", args=[self.active.pk]))
        reponse = self.client.get(reverse("plateforme:boutique", args=[self.active.pk]))
        self.assertEqual(reponse.context["nb_journal"], 1)
        self.assertContains(reponse, "Suivi mensuel")


class ConfidentialiteDeLActiviteTest(SocleTableaux):
    def cles(self, valeur, profondeur=0):
        """Toutes les clés de dictionnaire atteignables depuis le contexte."""
        if profondeur > 4:
            return set()
        trouvees = set()
        if isinstance(valeur, dict):
            for cle, v in valeur.items():
                trouvees.add(str(cle))
                trouvees |= self.cles(v, profondeur + 1)
        elif isinstance(valeur, (list, tuple)):
            for v in valeur[:5]:
                trouvees |= self.cles(v, profondeur + 1)
        return trouvees

    def verifier(self, reponse):
        self.assertEqual(reponse.status_code, 200)
        contexte = {}
        for couche in reponse.context:
            contexte.update(couche.flatten() if hasattr(couche, "flatten") else couche)
        # Les clés du socle commun (`motifs_de_suivi` et consorts) ne sont pas des données lues.
        cles = {_sans_accents(c) for c in self.cles(contexte)}
        for mot in MOTS_INTERDITS:
            with self.subTest(mot=mot, lieu="contexte"):
                self.assertFalse([c for c in cles if mot in c], mot)
            with self.subTest(mot=mot, lieu="page"):
                self.assertNotIn(mot, _contenu_principal(reponse))

    def test_la_vue_d_ensemble_ne_montre_que_des_agregats(self):
        self.vendre(self.active, "12500", client_nom="Mme Confidentielle")
        self.ouvrir_suivi(self.administrateur)
        reponse = self.client.get(reverse("plateforme:activite"))
        self.verifier(reponse)
        self.assertNotContains(reponse, "Confidentielle")
        ligne = next(l for l in reponse.context["lignes"] if l["b"].pk == self.active.pk)
        self.assertEqual(set(ligne), {"b", "ca", "tickets", "commandes", "derniere", "jours", "endormie", "largeur"})

    def test_la_fiche_d_activite_ne_montre_que_des_agregats(self):
        self.vendre(self.active, "12500", client_nom="Mme Confidentielle")
        self.ouvrir_suivi(self.superadmin)
        reponse = self.client.get(reverse("plateforme:boutique_activite", args=[self.active.pk]))
        self.verifier(reponse)
        self.assertNotContains(reponse, "Confidentielle")

    def test_les_agregats_sont_justes(self):
        self.vendre(self.active, "10000")
        self.vendre(self.active, "2500", il_y_a=3)
        self.vendre(self.active, "99999", il_y_a=45)  # hors fenêtre de 30 jours
        self.ouvrir_suivi(self.administrateur)
        reponse = self.client.get(reverse("plateforme:boutique_activite", args=[self.active.pk]))
        ligne = reponse.context["ligne"]
        self.assertEqual(ligne["ca"], Decimal("12500"))
        self.assertEqual(ligne["tickets"], 2)
        self.assertEqual(ligne["jours"], 0)
        self.assertFalse(ligne["endormie"])
        serie = reponse.context["graphe"].serie
        self.assertEqual(len(serie), ind.FENETRE_ACTIVITE)
        self.assertEqual(serie[-1]["valeur"], Decimal("10000"))
        self.assertEqual(serie[-4]["valeur"], Decimal("2500"))

    def test_une_boutique_sans_vente_recente_est_endormie(self):
        self.vendre(self.active, "5000", il_y_a=20)
        self.ouvrir_suivi(self.administrateur)
        reponse = self.client.get(reverse("plateforme:activite") + "?vue=endormies")
        enseignes = [l["b"].enseigne for l in reponse.context["lignes"]]
        self.assertIn(self.active.enseigne, enseignes)
        # Une boutique suspendue n'est pas « endormie » : c'est une décision du marché.
        self.assertNotIn(self.suspendue.enseigne, enseignes)


# ----------------------------------------------------------------------------
# La liste des boutiques
# ----------------------------------------------------------------------------
class ListeDesBoutiquesTest(SocleTableaux):
    url = reverse("plateforme:boutiques")

    def enseignes(self, **params):
        reponse = self.client.get(self.url, params)
        self.assertEqual(reponse.status_code, 200)
        return [b.enseigne for b in reponse.context["page_obj"].object_list]

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrateur)

    def test_recherche_par_enseigne_ville_telephone_rccm_et_niu(self):
        for texte in ("témoin", "Yaoundé", "677 11 22 33", "4242", "M0126000"):
            with self.subTest(texte=texte):
                self.assertEqual(self.enseignes(q=texte), ["Quincaillerie Témoin"])

    def test_filtres_par_etat_ville_rayon_et_offre(self):
        self.assertEqual(self.enseignes(etat="candidature"), ["Candidate Kribi"])
        self.assertEqual(self.enseignes(ville="Garoua"), ["Suspendue Garoua"])
        self.assertEqual(
            self.enseignes(rayon=self.active.rayon_principal.code), ["Quincaillerie Témoin"]
        )
        self.assertEqual(
            self.enseignes(offre=self.bail.type_emplacement_id), ["Quincaillerie Témoin"]
        )

    def test_les_compteurs_d_onglet_suivent_la_recherche(self):
        reponse = self.client.get(self.url, {"q": "Kribi"})
        compteurs = {o["code"]: o["nombre"] for o in reponse.context["onglets"]}
        self.assertEqual(compteurs[""], 1)
        self.assertEqual(compteurs["candidature"], 1)
        self.assertEqual(compteurs["active"], 0)

    def test_le_bail_actif_est_aplati_en_colonnes(self):
        reponse = self.client.get(self.url, {"q": "Témoin"})
        b = reponse.context["page_obj"].object_list[0]
        self.assertEqual(b.loyer, self.bail.loyer_mensuel)
        self.assertEqual(b.offre_code, self.bail.type_emplacement_id)
        # La candidature n'a qu'un bail brouillon : pas d'offre affichée.
        reponse = self.client.get(self.url, {"q": "Kribi"})
        self.assertIsNone(reponse.context["page_obj"].object_list[0].loyer)

    def test_tri_par_loyer_et_parametres_inconnus(self):
        self.assertEqual(self.enseignes(tri="n_importe_quoi", etat="bidon")[0], "Candidate Kribi")
        self.assertEqual(self.enseignes(tri="loyer")[-1], "Candidate Kribi")

    def test_etat_vide_explique_le_filtre(self):
        reponse = self.client.get(self.url, {"q": "introuvable-xyz"})
        self.assertContains(reponse, "Aucune boutique ne correspond")

    def test_pagination(self):
        for n in range(PAR_PAGE):
            fabrique.creer_boutique(f"Lot {n:02d}", avec_comptabilite=False)
        reponse = self.client.get(self.url, {"page": 2})
        self.assertEqual(reponse.context["page_obj"].number, 2)
        self.assertContains(reponse, "Page 2 /")

    def test_le_nombre_de_requetes_ne_depend_pas_du_nombre_de_boutiques(self):
        """Pas de N+1 : bail, offre, loyer et rayon viennent dans la même requête que la page."""
        self.client.get(self.url)  # chauffe : session, droits

        with CaptureQueriesContext(connection) as avant:
            self.client.get(self.url)
        for n in range(12):
            fabrique.creer_boutique(f"Nombre {n:02d}", avec_comptabilite=False)
        with self.assertNumQueries(len(avant.captured_queries)):
            self.client.get(self.url)
        # Borne absolue : 6 requêtes du socle (session, compte, contexte de boutique, droits de
        # plateforme, compteurs du rail) et 8 pour l'écran — onglets, compte, page, listes des
        # filtres. Une de plus veut dire qu'une boucle du gabarit s'est mise à interroger la base.
        self.assertLessEqual(len(avant.captured_queries), 14)

    def test_la_fiche_propose_les_gestes_de_l_etat_courant(self):
        fiche = self.client.get(reverse("plateforme:boutique", args=[self.candidature.pk]))
        etat = reverse("plateforme:boutique_etat", args=[self.candidature.pk])
        self.assertContains(fiche, f"{etat}?action=valider")
        self.assertNotContains(fiche, f"{etat}?action=suspendre")

        fiche = self.client.get(reverse("plateforme:boutique", args=[self.active.pk]))
        etat = reverse("plateforme:boutique_etat", args=[self.active.pk])
        self.assertContains(fiche, f"{etat}?action=suspendre")
        self.assertContains(fiche, reverse("plateforme:loyer_encaisser", args=[self.echue.pk]))


# ----------------------------------------------------------------------------
# Loyers, journal, technique
# ----------------------------------------------------------------------------
class AutresEcransTest(SocleTableaux):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrateur)

    def test_l_onglet_echues_ne_montre_que_les_retards(self):
        reponse = self.client.get(reverse("plateforme:loyers"), {"mois": "tous", "etat": "echues"})
        self.assertEqual(list(reponse.context["page_obj"].object_list), [self.echue])
        self.assertContains(reponse, reverse("plateforme:loyer_encaisser", args=[self.echue.pk]))

    def test_un_mois_illisible_retombe_sur_le_mois_courant(self):
        reponse = self.client.get(reverse("plateforme:loyers"), {"mois": "2026-99"})
        self.assertEqual(reponse.context["mois"], self.mois)

    def test_le_journal_se_filtre_et_supporte_un_identifiant_illisible(self):
        AccesPlateforme.objects.create(
            utilisateur=self.superadmin, boutique_id=self.active.pk, ecran="plateforme:boutique_activite", motif="Contrôle"
        )
        AccesPlateforme.objects.create(
            utilisateur=self.administrateur, boutique_id=None, ecran="plateforme:activite", motif="Suivi"
        )
        url = reverse("plateforme:journal")
        reponse = self.client.get(url, {"utilisateur": self.superadmin.pk})
        self.assertEqual(reponse.context["page_obj"].paginator.count, 1)
        reponse = self.client.get(url, {"boutique": "ensemble"})
        self.assertEqual(reponse.context["page_obj"].paginator.count, 1)
        reponse = self.client.get(url, {"boutique": "pas-un-uuid", "du": "hier"})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context["page_obj"].paginator.count, 0)
        self.assertContains(self.client.get(url), "ajout seul")

    def test_la_sante_technique_n_affiche_aucun_secret(self):
        from django.conf import settings

        self.client.force_login(self.superadmin)
        reponse = self.client.get(reverse("plateforme:technique"))
        page = reponse.content.decode()
        base = settings.DATABASES["default"]
        for secret in (settings.SECRET_KEY, base.get("PASSWORD"), base.get("HOST"), str(base.get("NAME"))):
            if secret and len(str(secret)) > 3:
                self.assertNotIn(str(secret), page)
        self.assertIn("rls", reponse.context)

    def test_rayons_verrouille_le_taux_de_celui_qui_y_vend(self):
        role, _ = Role.objects.get_or_create(
            code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
        )
        Appartenance.objects.create(utilisateur=self.administrateur, boutique=self.active, role=role)
        reponse = self.client.get(reverse("plateforme:rayons"))
        rayon = next(r for r in reponse.context["rayons"] if r.pk == self.active.rayon_principal_id)
        self.assertTrue(rayon.en_conflit)
        self.assertNotContains(reponse, reverse("plateforme:rayon_taux", args=[rayon.pk]))


# ----------------------------------------------------------------------------
# Les calculs
# ----------------------------------------------------------------------------
class IndicateursTest(SocleTableaux):
    def test_recouvrement_du_mois(self):
        synthese = ind.synthese_loyers(self.mois)
        self.assertEqual(synthese["encaisse"], Decimal("0"))
        self.assertEqual(synthese["taux"], 0.0)
        precedent = ind.synthese_loyers(ind.decaler_mois(self.mois, -1))
        self.assertEqual(precedent["taux"], 100.0)
        self.assertEqual(precedent["emis"], Decimal("53662.50"))  # 45 000 + TVA à 19,25 %

    def test_un_mois_sans_facture_n_a_pas_de_taux(self):
        self.assertIsNone(ind.synthese_loyers(ind.decaler_mois(self.mois, -30))["taux"])

    def test_impayes_echus(self):
        impayes = ind.synthese_impayes(self.aujourdhui)
        self.assertEqual(impayes["nombre"], 1)
        self.assertEqual(impayes["boutiques"], 1)

    def test_revenu_premium_au_prorata(self):
        # Un emplacement de 10 jours à cheval sur deux mois : chaque mois en porte sa part.
        EmplacementPremium.objects.all().delete()
        mois = ind.decaler_mois(self.mois, 2)
        fin_precedent = mois - timedelta(days=1)
        EmplacementPremium.objects.create(
            type=EmplacementPremium.ACCUEIL, debut=fin_precedent - timedelta(days=3),
            fin=mois + timedelta(days=5), tarif=Decimal("10000"),
        )
        self.assertEqual(ind.revenu_premium(mois), Decimal("6000"))
        self.assertEqual(ind.revenu_premium(ind.decaler_mois(mois, -1)), Decimal("4000"))

    def test_statut_d_une_facture(self):
        self.assertEqual(ind.statut_facture(self.echue, self.aujourdhui)[0], "echue")
        self.echue.echeance = self.aujourdhui + timedelta(days=3)
        self.assertEqual(ind.statut_facture(self.echue, self.aujourdhui)[0], "emise")

    def test_repartition_replie_les_petits_en_autres(self):
        parts = ind.repartition(Boutique.objects.all(), "ville", limite=2)
        self.assertEqual(len(parts), 3)
        self.assertTrue(parts[-1]["autres"])
        self.assertEqual(sum(p["nombre"] for p in parts), Boutique.objects.count())
        self.assertEqual(max(p["largeur"] for p in parts), 100.0)

    def test_la_serie_mensuelle_contient_tous_les_mois(self):
        serie = ind.loyers_encaisses_par_mois(self.mois, 12)
        self.assertEqual(len(serie), 12)
        self.assertEqual(serie[-1]["mois"], self.mois)
        self.assertEqual(serie[-2]["valeur"], Decimal("45000"))  # HT : la TVA n'est pas un revenu

    def test_decaler_mois_traverse_les_annees(self):
        from datetime import date

        self.assertEqual(ind.decaler_mois(date(2026, 1, 1), -1), date(2025, 12, 1))
        self.assertEqual(ind.decaler_mois(date(2026, 11, 1), 3), date(2027, 2, 1))


class GrapheTest(TestCase):
    def test_une_serie_vide_donne_une_geometrie_valide(self):
        graphe = ind.graphe_de([])
        self.assertTrue(graphe.vide)
        self.assertEqual(graphe.large["barres"], [])
        self.assertEqual(len(graphe.large["lignes"]), 5)
        self.assertEqual(graphe.total, Decimal("0"))

    def test_une_serie_nulle_ne_dessine_aucune_barre(self):
        serie = [{"valeur": Decimal("0"), "libelle": str(i), "libelle_long": str(i)} for i in range(12)]
        graphe = ind.graphe_de(serie)
        self.assertTrue(graphe.vide)
        self.assertTrue(all(b["chemin"] == "" for b in graphe.large["barres"]))
        self.assertFalse(any(b["est_max"] for b in graphe.large["barres"]))
        self.assertEqual(ind.trace(serie), "")

    def test_la_derniere_etiquette_est_toujours_visible(self):
        serie = [{"valeur": Decimal(i), "libelle": str(i), "libelle_long": str(i)} for i in range(30)]
        graphe = ind.graphe_de(serie)
        for geometrie in (graphe.large, graphe.compact):
            self.assertTrue(geometrie["barres"][-1]["tick_visible"])
            self.assertLess(sum(b["tick_visible"] for b in geometrie["barres"]), 30)
        self.assertTrue(graphe.large["barres"][-1]["est_max"])


class TableauDeBordVideTest(PersonnagesMixin, TestCase):
    """Le premier jour du marché : aucune facture, aucun emplacement, aucun accès."""

    def test_le_tableau_de_bord_d_un_marche_vide(self):
        self.poser_les_personnages()
        self.client.force_login(self.administrateur)
        reponse = self.client.get(reverse("plateforme:tableau_de_bord"))
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.context["graphe"].vide)
        self.assertEqual(reponse.context["file"], [])
        self.assertContains(reponse, "Aucun loyer encaissé sur la période.")
        self.assertContains(reponse, "Rien n'attend")
        # Aucune coordonnée à virgule : le navigateur rejetterait silencieusement le SVG.
        self.assertIsNone(re.search(r'(?:x|y|width|height)="\d+,\d', reponse.content.decode()))


class ClesPoseesTest(TestCase):
    """L'écran technique dit quelles clés sont posées — oui ou non, jamais leur valeur (docs/28)."""

    def lignes(self):
        from apps.plateforme.vues_tableau import cles_posees

        return {l["nom"]: l for l in cles_posees()}

    def test_aucune_valeur_n_est_affichee(self):
        from django.test import override_settings

        secret = "cle-tres-secrete-123"
        with override_settings(
            PAIEMENTS_OPERATEURS={"MTN_MOMO": {"cle_abonnement_collecte": secret, "utilisateur_api_collecte": secret,
                                               "cle_api_collecte": secret}},
            WHATSAPP={}, PAIEMENTS_SIMULES=False, URL_PUBLIQUE="https://exemple.cm",
        ):
            lignes = self.lignes()
        self.assertNotIn(secret, repr(lignes))
        self.assertTrue(lignes["MTN_MOMO (collecte)"]["bon"])
        self.assertIsNone(lignes["WHATSAPP"]["bon"], "une clé facultative absente n'est pas une faute")

    def test_le_simulateur_avec_des_cles_reelles_est_une_faute(self):
        from django.test import override_settings

        with override_settings(
            PAIEMENTS_OPERATEURS={"ORANGE_MONEY": {"id_client": "a", "secret_client": "b", "cle_marchand": "c"}},
            PAIEMENTS_SIMULES=True, URL_PUBLIQUE="",
        ):
            lignes = self.lignes()
        self.assertIs(lignes["PAIEMENTS_SIMULES"]["bon"], False)
        self.assertIs(lignes["URL_PUBLIQUE"]["bon"], False, "Orange sans URL publique ne démarre pas")
