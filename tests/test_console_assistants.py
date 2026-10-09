"""Les assistants et les gestes de la console (ADR-012).

Ce que ces tests défendent, dans l'ordre où un administrateur le rencontrerait :

* un assistant se parcourt étape par étape, revient en arrière sans rien perdre, et **ne crée rien
  avant la confirmation** — puis crée tout d'un coup, ou rien ;
* la confirmation **rejoue** toutes les étapes : une session vieillie ou altérée ne passe pas ;
* aucun mot de passe en clair ne dort en session ;
* les règles de gouvernance tiennent : deux casquettes, deux comptes ; une dérogation de
  commission se motive ; un emplacement ne se cède jamais à zéro ; le juge et partie ne fixe pas
  le taux de son rayon ; on retire ce qui a une histoire, on ne le supprime pas ;
* **chaque geste laisse sa ligne au journal des accès**.
"""

import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import Journal
from apps.accounts.administration import NOM_GROUPE
from apps.accounts.models import Appartenance, Role, RolePlateforme, Utilisateur
from apps.core.models import AccesPlateforme
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import Depot
from apps.marketplace.models import Bail, Boutique, EmplacementPremium, FactureLoyer
from apps.plateforme import services
from tests import fabrique

MOT_DE_PASSE = "Kribi-Limbe-2026"


class Personnages:
    """Le superadministrateur, l'administrateur du marché, un commerçant, et un marché garni."""

    def poser(self):
        self.boutique = fabrique.creer_boutique("Chez un tiers")
        self.rayon = fabrique.creer_rayon("0.0500")
        self.offre = fabrique.creer_offre(quota_depots=3, quota_utilisateurs=5)

        self.superadmin = fabrique.creer_utilisateur("Superadministratrice")
        self.superadmin.is_superuser = True
        self.superadmin.is_staff = True
        self.superadmin.save(update_fields=["is_superuser", "is_staff"])

        self.administrateur = fabrique.creer_utilisateur("Administrateur du marché")
        call_command("preparer_administrateur", administrateur=self.administrateur.telephone, verbosity=0)
        self.administrateur.refresh_from_db()

        self.commercant = fabrique.creer_utilisateur("Commerçant")
        self.role_gerant, _ = Role.objects.get_or_create(
            code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
        )
        Appartenance.objects.create(utilisateur=self.commercant, boutique=self.boutique, role=self.role_gerant)

    def traces(self, ecran):
        return AccesPlateforme.objects.filter(ecran=ecran)


def _etape(nom, code):
    return reverse(f"plateforme:assistant_{nom}_etape", args=[code])


# ============================================================================
# 1. Ouvrir une boutique
# ============================================================================
class OuvrirUneBoutiqueTest(Personnages, TestCase):
    def setUp(self):
        self.poser()
        self.client.force_login(self.administrateur)
        # « Ouvrir tout de suite » passe par le verrou d'activation (docs/23, §2.3). Une boutique
        # qui naît ne peut pas avoir de dossier vérifié — ses pièces et son compte de versement se
        # rattachent à elle, et le second regard doit venir d'un autre administrateur que celui
        # qui l'ouvre. Ces tests portent sur la naissance ; ils prennent donc le dossier pour
        # complet. Le verrou lui-même est éprouvé dans `tests/test_verification.py`.
        patcher = mock.patch("apps.confiance.verification.manques_pour_activer", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def saisies(self, **surcharges):
        s = {
            "identite": {
                "enseigne": "Quincaillerie Ateba",
                "raison_sociale": "Ets Ateba et Fils SARL",
                "metier": "QUINCAILLERIE",
                "ville": "Douala",
                "telephone": "+237 699 55 44 33",
            },
            "legal": {"rccm": "rc/dla/2024/b/1234", "niu": "M0123 45678", "regime_fiscal": Boutique.REEL_SIMPLIFIE},
            "offre": {
                "offre": self.offre.code,
                "rayon": str(self.rayon.pk),
                "debut": timezone.localdate().isoformat(),
                "loyer_mensuel": "",
                "depot_garantie": "90 000",
                "taux_commission": "",
                "motif_derogation": "",
            },
            "gerant": {
                "mode": "nouveau",
                "telephone": "+237699777001",
                "nom": "Paul Ateba",
                "mot_de_passe": MOT_DE_PASSE,
                "mot_de_passe_confirmation": MOT_DE_PASSE,
            },
        }
        for code, valeurs in surcharges.items():
            s[code].update(valeurs)
        return s

    def remplir(self, jusqu_a="gerant", **surcharges):
        for code, donnees in self.saisies(**surcharges).items():
            reponse = self.client.post(_etape("boutique", code), donnees)
            self.assertEqual(reponse.status_code, 302, (code, getattr(reponse, "context", None) and reponse.context["form"].errors))
            if code == jusqu_a:
                return reponse
        return reponse

    # --- Parcours ---------------------------------------------------------------------------
    def test_l_entree_mene_a_la_premiere_etape(self):
        reponse = self.client.get(reverse("plateforme:assistant_boutique"))
        self.assertRedirects(reponse, _etape("boutique", "identite"), fetch_redirect_response=False)
        page = self.client.get(_etape("boutique", "identite"))
        self.assertContains(page, 'aria-current="step"')
        self.assertContains(page, "Étape 1 sur 5")

    def test_on_ne_saute_pas_au_recapitulatif_par_l_adresse(self):
        reponse = self.client.get(_etape("boutique", "recapitulatif"))
        self.assertRedirects(reponse, _etape("boutique", "identite"), fetch_redirect_response=False)

    def test_une_etape_inconnue_est_un_404(self):
        self.assertEqual(self.client.get(_etape("boutique", "nimporte")).status_code, 404)

    def test_le_parcours_complet_cree_tout_d_un_coup(self):
        derniere = self.remplir()
        self.assertRedirects(derniere, _etape("boutique", "recapitulatif"), fetch_redirect_response=False)
        self.assertFalse(Boutique.objects.filter(enseigne="Quincaillerie Ateba").exists(), "rien avant la confirmation")

        recap = self.client.get(_etape("boutique", "recapitulatif"))
        self.assertContains(recap, "/marche/boutique/quincaillerie-ateba/")
        self.assertContains(recap, "Modifier")

        reponse = self.client.post(_etape("boutique", "recapitulatif"), {"ouverture": "active"})
        boutique = Boutique.objects.get(enseigne="Quincaillerie Ateba")
        self.assertRedirects(reponse, reverse("plateforme:boutique", args=[boutique.pk]), fetch_redirect_response=False)

        self.assertEqual(boutique.etat, Boutique.ACTIVE)
        self.assertEqual(boutique.slug, "quincaillerie-ateba")
        self.assertEqual(boutique.metier, "QUINCAILLERIE")
        self.assertEqual(boutique.telephone, "+237699554433")
        self.assertEqual(boutique.rccm, "RC/DLA/2024/B/1234")
        self.assertEqual(boutique.rayon_principal, self.rayon)

        bail = boutique.baux.get()
        self.assertEqual(bail.etat, Bail.ACTIF)
        self.assertEqual(bail.loyer_mensuel, self.offre.loyer_mensuel, "loyer vide = loyer de l'offre")
        self.assertEqual(bail.taux_commission, self.offre.taux_commission_defaut)
        self.assertEqual(bail.depot_garantie, Decimal("90000"))

        gerant = Utilisateur.objects.get(telephone="+237699777001")
        self.assertTrue(gerant.check_password(MOT_DE_PASSE))
        self.assertFalse(gerant.is_staff)
        self.assertTrue(Appartenance.objects.filter(utilisateur=gerant, boutique=boutique, role_id=Role.GERANT, actif=True).exists())

        with contexte_boutique(boutique):
            self.assertTrue(Journal.objects.exists(), "plan comptable initialisé")
            self.assertTrue(Depot.objects.filter(principal=True).exists(), "dépôt principal créé")

        trace = self.traces("assistant_boutique").get()
        self.assertEqual(trace.boutique_id, boutique.pk)
        self.assertEqual(trace.utilisateur, self.administrateur)
        self.assertIn("Ouverture de la boutique « Quincaillerie Ateba »", trace.motif)

        self.assertNotIn("assistant_boutique", self.client.session, "l'état de l'assistant est effacé")

    def test_laisser_en_candidature_garde_le_bail_en_brouillon(self):
        self.remplir()
        self.client.post(_etape("boutique", "recapitulatif"), {"ouverture": "candidature"})
        boutique = Boutique.objects.get(enseigne="Quincaillerie Ateba")
        self.assertEqual(boutique.etat, Boutique.CANDIDATURE)
        self.assertEqual(boutique.baux.get().etat, Bail.BROUILLON)

    def test_le_slug_est_rendu_unique(self):
        Boutique.objects.create(raison_sociale="X", enseigne="Quincaillerie Ateba", slug="quincaillerie-ateba")
        self.remplir()
        self.client.post(_etape("boutique", "recapitulatif"), {"ouverture": "active"})
        self.assertTrue(Boutique.objects.filter(slug="quincaillerie-ateba-2").exists())

    def test_un_compte_existant_devient_gerant(self):
        futur = fabrique.creer_utilisateur("Marie Ekedi")
        self.remplir(gerant={"mode": "existant", "telephone": futur.telephone, "mot_de_passe": "", "mot_de_passe_confirmation": ""})
        self.client.post(_etape("boutique", "recapitulatif"), {"ouverture": "active"})
        boutique = Boutique.objects.get(enseigne="Quincaillerie Ateba")
        self.assertTrue(Appartenance.objects.filter(utilisateur=futur, boutique=boutique).exists())

    # --- Retour arrière -----------------------------------------------------------------------
    def test_revenir_en_arriere_conserve_les_saisies(self):
        self.remplir(jusqu_a="legal")
        page = self.client.get(_etape("boutique", "identite"))
        self.assertContains(page, 'value="Quincaillerie Ateba"')
        self.assertContains(page, "etape--faite")

        # « Précédent » depuis l'offre, avec une saisie incomplète : gardée en brouillon.
        reponse = self.client.post(
            _etape("boutique", "offre"), {"offre": self.offre.code, "depot_garantie": "12 345", "_precedent": "1"}
        )
        self.assertRedirects(reponse, _etape("boutique", "legal"), fetch_redirect_response=False)
        page = self.client.get(_etape("boutique", "legal"))
        self.assertContains(page, 'value="rc/dla/2024/b/1234"', msg_prefix="la saisie telle que tapée")
        page = self.client.get(_etape("boutique", "offre"))
        self.assertContains(page, 'value="12 345"')

    def test_une_etape_faite_est_un_lien_de_la_barre(self):
        self.remplir(jusqu_a="legal")
        page = self.client.get(_etape("boutique", "offre"))
        self.assertContains(page, f'href="{_etape("boutique", "identite")}"')
        self.assertNotContains(page, f'href="{_etape("boutique", "gerant")}"')

    def test_abandonner_efface_tout_et_ne_cree_rien(self):
        self.remplir(jusqu_a="legal")
        reponse = self.client.post(_etape("boutique", "offre"), {"_abandonner": "1"})
        self.assertRedirects(reponse, reverse("plateforme:boutiques"), fetch_redirect_response=False)
        self.assertNotIn("assistant_boutique", self.client.session)

    # --- Mots de passe -------------------------------------------------------------------------
    def test_aucun_mot_de_passe_en_clair_dans_la_session(self):
        self.remplir()
        brut = json.dumps(dict(self.client.session.items()))
        self.assertNotIn(MOT_DE_PASSE, brut)
        saisie = self.client.session["assistant_boutique"]["saisies"]["gerant"]
        self.assertNotIn("mot_de_passe", saisie)
        self.assertTrue(saisie["_hache"].startswith(("pbkdf2", "argon2", "bcrypt", "scrypt", "md5")))

    def test_une_empreinte_postee_par_le_navigateur_est_ignoree(self):
        self.remplir(jusqu_a="offre")
        reponse = self.client.post(
            _etape("boutique", "gerant"),
            {"mode": "nouveau", "telephone": "+237699777001", "nom": "Paul Ateba", "_hache": "pbkdf2_sha256$faux"},
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertFormError(reponse.context["form"], "mot_de_passe", "Saisissez le mot de passe initial du compte.")

    def test_le_mot_de_passe_passe_les_validateurs_de_django(self):
        self.remplir(jusqu_a="offre")
        reponse = self.client.post(
            _etape("boutique", "gerant"),
            {"mode": "nouveau", "telephone": "+237699777001", "nom": "Paul Ateba", "mot_de_passe": "123", "mot_de_passe_confirmation": "123"},
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.context["form"].errors["mot_de_passe"])
        self.assertContains(reponse, 'aria-invalid="true"')
        self.assertContains(reponse, "autofocus")

    def test_revenir_sur_le_gerant_ne_redemande_pas_le_mot_de_passe(self):
        self.remplir()
        reponse = self.client.post(
            _etape("boutique", "gerant"), {"mode": "nouveau", "telephone": "+237699777001", "nom": "Paul Ateba"}
        )
        self.assertEqual(reponse.status_code, 302)

    # --- Deux casquettes, deux comptes ----------------------------------------------------------
    def test_refuse_un_compte_d_administration_comme_gerant(self):
        self.remplir(jusqu_a="offre")
        for compte, attendu in (
            (self.administrateur, "votre propre compte"),
            (self.superadmin, "superadministrateur"),
        ):
            reponse = self.client.post(_etape("boutique", "gerant"), {"mode": "existant", "telephone": compte.telephone})
            self.assertEqual(reponse.status_code, 200, compte)
            self.assertIn(attendu, " ".join(reponse.context["form"].errors["telephone"]))

        autre = fabrique.creer_utilisateur("Autre administrateur")
        autre.is_staff = True
        autre.save(update_fields=["is_staff"])
        reponse = self.client.post(_etape("boutique", "gerant"), {"mode": "existant", "telephone": autre.telephone})
        self.assertIn("deux casquettes", " ".join(reponse.context["form"].errors["telephone"]))

    def test_le_service_refuse_aussi_les_deux_casquettes(self):
        refus = services.refus_gerant(self.administrateur, par=self.superadmin)
        self.assertIn("administre le marché", refus)

    # --- Dérogation ------------------------------------------------------------------------------
    def test_un_taux_derogatoire_sans_motif_est_refuse(self):
        self.remplir(jusqu_a="legal")
        donnees = {**self.saisies()["offre"], "taux_commission": "3"}
        reponse = self.client.post(_etape("boutique", "offre"), donnees)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("s'écarte de celui de l'offre", " ".join(reponse.context["form"].errors["motif_derogation"]))

        donnees["motif_derogation"] = "Grossiste historique : volume garanti au contrat."
        self.assertEqual(self.client.post(_etape("boutique", "offre"), donnees).status_code, 302)
        self.client.post(_etape("boutique", "gerant"), self.saisies()["gerant"])
        self.client.post(_etape("boutique", "recapitulatif"), {"ouverture": "active"})
        bail = Bail.objects.get(boutique__enseigne="Quincaillerie Ateba")
        self.assertEqual(bail.taux_commission, Decimal("0.0300"))
        self.assertIn("Grossiste historique", bail.motif_derogation_commission)

    # --- Revalidation et transaction -------------------------------------------------------------
    def test_une_session_alteree_est_rejouee_a_la_confirmation(self):
        self.remplir()
        session = self.client.session
        session["assistant_boutique"]["saisies"]["offre"]["taux_commission"] = "2"
        session.save()
        reponse = self.client.post(_etape("boutique", "recapitulatif"), {"ouverture": "active"})
        self.assertRedirects(reponse, _etape("boutique", "offre"), fetch_redirect_response=False)
        self.assertFalse(Boutique.objects.filter(enseigne="Quincaillerie Ateba").exists())
        page = self.client.get(_etape("boutique", "offre"))
        self.assertIn("motif_derogation", page.context["form"].errors)

    def test_une_etape_perimee_est_rouverte(self):
        self.remplir()
        # Entre-temps, un autre administrateur a pris le numéro du futur gérant.
        fabrique.creer_utilisateur("Homonyme", telephone="+237699777001")
        reponse = self.client.post(_etape("boutique", "recapitulatif"), {"ouverture": "active"})
        self.assertRedirects(reponse, _etape("boutique", "gerant"), fetch_redirect_response=False)
        self.assertFalse(Boutique.objects.filter(enseigne="Quincaillerie Ateba").exists())

    def test_une_session_perimee_repart_de_zero(self):
        self.remplir(jusqu_a="legal")
        session = self.client.session
        session["assistant_boutique"]["debut"] = (timezone.now() - timedelta(days=2)).isoformat()
        session.save()
        reponse = self.client.get(_etape("boutique", "offre"))
        self.assertRedirects(reponse, _etape("boutique", "identite"), fetch_redirect_response=False)

    def test_rien_n_est_cree_si_une_etape_de_la_creation_echoue(self):
        self.remplir()
        avant = (Boutique.objects.count(), Bail.objects.count(), Utilisateur.objects.count(), Appartenance.objects.count())
        with mock.patch(
            "apps.accounting.referentiel.initialiser_boutique", side_effect=ValidationError("Plan comptable introuvable.")
        ):
            reponse = self.client.post(_etape("boutique", "recapitulatif"), {"ouverture": "active"})
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Rien n'a été créé")
        self.assertEqual(
            avant,
            (Boutique.objects.count(), Bail.objects.count(), Utilisateur.objects.count(), Appartenance.objects.count()),
        )
        self.assertFalse(self.traces("assistant_boutique").exists())
        self.assertIn("assistant_boutique", self.client.session, "la saisie reste, pour réessayer")

    def test_le_service_seul_refuse_la_derogation_sans_motif_et_ne_cree_rien(self):
        demande = services.DemandeOuverture(
            enseigne="Pharmacie du Port", raison_sociale="Pharmacie du Port SARL", metier="PHARMACIE",
            ville="Douala", telephone="", rccm="", niu="", regime_fiscal=Boutique.IGS,
            offre=self.offre, rayon=self.rayon, debut=timezone.localdate(),
            loyer_mensuel=Decimal("45000"), depot_garantie=Decimal("0"),
            taux_commission=Decimal("0.0200"), motif_derogation="",
            gerant_existant=None, gerant_telephone="+237699777002", gerant_nom="Dr Ngo",
            gerant_mot_de_passe_hache="pbkdf2_sha256$1$x$y", activer=True,
        )
        with self.assertRaises(ValidationError):
            services.ouvrir_boutique(demande, par=self.administrateur)
        self.assertFalse(Boutique.objects.filter(enseigne="Pharmacie du Port").exists())
        self.assertFalse(Utilisateur.objects.filter(telephone="+237699777002").exists())

    # --- La porte ---------------------------------------------------------------------------------
    def test_un_commercant_n_entre_pas(self):
        self.client.force_login(self.commercant)
        self.assertEqual(self.client.get(_etape("boutique", "identite")).status_code, 403)

    def test_un_responsable_de_rayon_n_ouvre_pas_de_boutique(self):
        responsable = fabrique.creer_utilisateur("Responsable de rayon")
        services.nommer_administrateur(
            par=self.superadmin, code_role=Role.RESP_RAYON, motif="Gère le rayon quincaillerie.",
            compte_existant=responsable,
        )
        self.client.force_login(responsable)
        self.assertEqual(self.client.get(_etape("boutique", "identite")).status_code, 403)
        self.assertEqual(self.client.post(_etape("boutique", "identite"), self.saisies()["identite"]).status_code, 403)


# ============================================================================
# 2. Vendre un emplacement premium
# ============================================================================
class VendreUnEmplacementTest(Personnages, TestCase):
    def setUp(self):
        self.poser()
        self.client.force_login(self.administrateur)
        self.aujourdhui = timezone.localdate()

    def remplir(self, tarif="75 000"):
        etapes = [
            ("boutique", {"boutique": str(self.boutique.pk)}),
            ("type", {"type": EmplacementPremium.TETE_DE_GONDOLE, "rayon": str(self.rayon.pk)}),
            ("periode", {"debut": self.aujourdhui.isoformat(), "fin": (self.aujourdhui + timedelta(days=6)).isoformat()}),
            ("tarif", {"tarif": tarif}),
        ]
        for code, donnees in etapes:
            reponse = self.client.post(_etape("emplacement", code), donnees)
            if reponse.status_code != 302:
                return reponse
        return reponse

    def test_le_parcours_complet_vend_a_son_prix_et_trace(self):
        self.assertEqual(self.remplir().status_code, 302)
        self.assertFalse(EmplacementPremium.objects.exists())
        reponse = self.client.post(_etape("emplacement", "recapitulatif"), {})
        self.assertRedirects(reponse, reverse("plateforme:emplacements"), fetch_redirect_response=False)
        emplacement = EmplacementPremium.objects.get()
        self.assertEqual(emplacement.tarif, Decimal("75000"))
        self.assertEqual(emplacement.boutique_occupante, self.boutique)
        self.assertEqual(emplacement.rayon, self.rayon)
        trace = self.traces("assistant_emplacement").get()
        self.assertEqual(trace.boutique_id, self.boutique.pk)

    def test_un_tarif_nul_est_refuse_avec_la_raison(self):
        reponse = self.remplir(tarif="0")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("ne se cède jamais à zéro", " ".join(reponse.context["form"].errors["tarif"]))
        with self.assertRaises(ValidationError):
            services.vendre_emplacement(
                par=self.administrateur, boutique=self.boutique, type_emplacement=EmplacementPremium.ACCUEIL,
                rayon=None, debut=self.aujourdhui, fin=self.aujourdhui + timedelta(days=1), tarif=Decimal("0"),
            )
        self.assertFalse(EmplacementPremium.objects.exists())

    def test_la_fin_doit_venir_apres_le_debut(self):
        self.client.post(_etape("emplacement", "boutique"), {"boutique": str(self.boutique.pk)})
        self.client.post(_etape("emplacement", "type"), {"type": EmplacementPremium.ACCUEIL})
        reponse = self.client.post(
            _etape("emplacement", "periode"), {"debut": self.aujourdhui.isoformat(), "fin": self.aujourdhui.isoformat()}
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("fin", reponse.context["form"].errors)

    def test_une_tete_de_gondole_exige_un_rayon(self):
        self.client.post(_etape("emplacement", "boutique"), {"boutique": str(self.boutique.pk)})
        reponse = self.client.post(_etape("emplacement", "type"), {"type": EmplacementPremium.TETE_DE_GONDOLE})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("rayon", reponse.context["form"].errors)

    def test_seule_une_boutique_active_est_proposee(self):
        self.boutique.etat = Boutique.SUSPENDUE
        self.boutique.save(update_fields=["etat"])
        reponse = self.client.post(_etape("emplacement", "boutique"), {"boutique": str(self.boutique.pk)})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("boutique", reponse.context["form"].errors)

    def test_la_recherche_filtre_les_boutiques(self):
        fabrique.creer_boutique("Pharmacie du Port")
        page = self.client.get(_etape("emplacement", "boutique") + "?q=pharma")
        self.assertContains(page, "Pharmacie du Port")
        self.assertNotContains(page, "Chez un tiers")

    def test_arriver_depuis_la_fiche_preselectionne_la_boutique(self):
        reponse = self.client.get(reverse("plateforme:assistant_emplacement") + f"?boutique={self.boutique.pk}")
        self.assertRedirects(reponse, _etape("emplacement", "type"), fetch_redirect_response=False)
        page = self.client.get(_etape("emplacement", "type"))
        # Le rayon par défaut est celui de la boutique.
        self.assertContains(page, f'<option value="{self.boutique.rayon_principal_id}" selected>')


# ============================================================================
# 3 et 4. Nommer et retirer un administrateur
# ============================================================================
class NommerUnAdministrateurTest(Personnages, TestCase):
    def setUp(self):
        self.poser()
        self.client.force_login(self.superadmin)

    def test_l_administrateur_du_marche_recoit_un_403(self):
        self.client.force_login(self.administrateur)
        for url in (
            reverse("plateforme:assistant_administrateur"),
            _etape("administrateur", "compte"),
            reverse("plateforme:administrateurs"),
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        reponse = self.client.post(_etape("administrateur", "compte"), {"mode": "existant", "telephone": self.commercant.telephone})
        self.assertEqual(reponse.status_code, 403)

    def test_le_parcours_complet_pose_l_administrateur_sans_superutilisateur(self):
        self.assertEqual(
            self.client.post(
                _etape("administrateur", "compte"),
                {"mode": "nouveau", "telephone": "+237699888001", "nom": "Aïcha Bello",
                 "mot_de_passe": MOT_DE_PASSE, "mot_de_passe_confirmation": MOT_DE_PASSE},
            ).status_code,
            302,
        )
        self.assertNotIn(MOT_DE_PASSE, json.dumps(dict(self.client.session.items())))
        self.assertEqual(
            self.client.post(
                _etape("administrateur", "role"),
                {"role": Role.ADMIN_MARCHE, "motif": "Reprend l'exploitation de la zone de Bonabéri."},
            ).status_code,
            302,
        )
        recap = self.client.get(_etape("administrateur", "recapitulatif"))
        self.assertContains(recap, "Aïcha Bello")
        reponse = self.client.post(_etape("administrateur", "recapitulatif"), {})
        self.assertEqual(reponse.status_code, 302)

        compte = Utilisateur.objects.get(telephone="+237699888001")
        self.assertTrue(compte.is_staff)
        self.assertFalse(compte.is_superuser)
        self.assertTrue(compte.check_password(MOT_DE_PASSE))
        self.assertTrue(compte.groups.filter(name=NOM_GROUPE).exists())
        role = RolePlateforme.objects.get(utilisateur=compte, actif=True)
        self.assertEqual(role.role_id, Role.ADMIN_MARCHE)
        self.assertIn("Bonabéri", role.motif)
        trace = self.traces("assistant_administrateur").get()
        self.assertEqual(trace.utilisateur, self.superadmin)
        self.assertIn("Aïcha Bello", trace.motif)

    def test_refuse_un_compte_qui_tient_une_boutique(self):
        reponse = self.client.post(_etape("administrateur", "compte"), {"mode": "existant", "telephone": self.commercant.telephone})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("Deux casquettes", " ".join(reponse.context["form"].errors["telephone"]))
        with self.assertRaises(ValidationError):
            services.nommer_administrateur(
                par=self.superadmin, code_role=Role.ADMIN_MARCHE, motif="Contournement de l'assistant.",
                compte_existant=self.commercant,
            )
        self.commercant.refresh_from_db()
        self.assertFalse(self.commercant.is_staff)

    def test_refuse_un_superadministrateur(self):
        autre = fabrique.creer_utilisateur("Autre super")
        autre.is_superuser = True
        autre.save(update_fields=["is_superuser"])
        reponse = self.client.post(_etape("administrateur", "compte"), {"mode": "existant", "telephone": autre.telephone})
        self.assertIn("superadministrateur", " ".join(reponse.context["form"].errors["telephone"]))

    def test_le_motif_est_obligatoire_et_le_role_ne_se_double_pas(self):
        self.client.post(_etape("administrateur", "compte"), {"mode": "existant", "telephone": self.administrateur.telephone})
        reponse = self.client.post(_etape("administrateur", "role"), {"role": Role.ADMIN_MARCHE, "motif": ""})
        self.assertIn("motif", reponse.context["form"].errors)
        self.assertIn("role", reponse.context["form"].errors, "il porte déjà ce rôle")
        reponse = self.client.post(_etape("administrateur", "role"), {"role": Role.RESP_RAYON, "motif": "Renfort sur les commissions du rayon."})
        self.assertEqual(reponse.status_code, 302)

    def test_la_page_montre_les_roles_et_avertit_des_deux_casquettes(self):
        Appartenance.objects.create(utilisateur=self.superadmin, boutique=self.boutique, role=self.role_gerant)
        page = self.client.get(reverse("plateforme:administrateurs"))
        self.assertContains(page, "Administrateur du marché")
        self.assertContains(page, "deux casquettes sur un seul compte")
        self.assertContains(page, reverse("plateforme:assistant_administrateur"))


class RetirerUnAdministrateurTest(Personnages, TestCase):
    def setUp(self):
        self.poser()
        self.client.force_login(self.superadmin)
        self.role = RolePlateforme.objects.get(utilisateur=self.administrateur, actif=True)
        self.url = reverse("plateforme:administrateur_retirer", args=[self.role.pk])

    def test_le_motif_est_obligatoire(self):
        reponse = self.client.post(self.url, {"motif": ""})
        self.assertEqual(reponse.status_code, 400)
        self.role.refresh_from_db()
        self.assertTrue(self.role.actif)

    def test_retirer_le_dernier_role_retire_is_staff_et_le_groupe_sans_rien_supprimer(self):
        reponse = self.client.post(self.url, {"motif": "Fin de mission le 30 septembre."})
        self.assertRedirects(reponse, reverse("plateforme:administrateurs"), fetch_redirect_response=False)
        self.role.refresh_from_db()
        self.assertFalse(self.role.actif)
        self.assertEqual(self.role.jusqu_a, timezone.localdate())
        self.administrateur.refresh_from_db()
        self.assertFalse(self.administrateur.is_staff)
        self.assertFalse(self.administrateur.groups.filter(name=NOM_GROUPE).exists())
        self.assertTrue(RolePlateforme.objects.filter(pk=self.role.pk).exists(), "retiré, pas supprimé")
        self.assertIn("Fin de mission", self.traces("administrateur_retirer").get().motif)
        self.client.force_login(self.administrateur)
        self.assertEqual(self.client.get(reverse("plateforme:tableau_de_bord")).status_code, 403)

    def test_un_autre_role_actif_garde_l_acces(self):
        services.nommer_administrateur(
            par=self.superadmin, code_role=Role.RESP_RAYON, motif="Garde les commissions du rayon.",
            compte_existant=self.administrateur,
        )
        self.client.post(self.url, {"motif": "Ne gère plus le marché entier."})
        self.administrateur.refresh_from_db()
        self.assertTrue(self.administrateur.is_staff)

    def test_jamais_sur_un_superadministrateur(self):
        role = RolePlateforme.objects.create(
            utilisateur=self.superadmin, role=Role.objects.get(code=Role.ADMIN_MARCHE), motif="Historique."
        )
        autre_super = fabrique.creer_utilisateur("Second super")
        autre_super.is_superuser = autre_super.is_staff = True
        autre_super.save(update_fields=["is_superuser", "is_staff"])
        self.client.force_login(autre_super)
        self.client.post(reverse("plateforme:administrateur_retirer", args=[role.pk]), {"motif": "Rôle redondant."})
        self.superadmin.refresh_from_db()
        self.assertTrue(self.superadmin.is_staff)
        self.assertTrue(self.superadmin.is_superuser)

    def test_l_administrateur_du_marche_ne_retire_personne(self):
        self.client.force_login(self.administrateur)
        self.assertEqual(self.client.post(self.url, {"motif": "Tentative de retrait."}).status_code, 403)


# ============================================================================
# 5. Changer l'état d'une boutique
# ============================================================================
class EtatDUneBoutiqueTest(Personnages, TestCase):
    def setUp(self):
        self.poser()
        self.client.force_login(self.administrateur)
        # Valider et réactiver passent par le verrou d'activation : la boutique est vérifiée,
        # pour de vrai, par deux personnes distinctes (docs/23, §2.3).
        from tests.test_verification import verifier_entierement

        verifier_entierement(
            self.boutique, self.commercant, declarant=self.administrateur, verificateur=self.superadmin
        )

    def url(self, action, boutique=None):
        return reverse("plateforme:boutique_etat", args=[(boutique or self.boutique).pk]) + f"?action={action}"

    def test_la_page_explique_les_consequences(self):
        page = self.client.get(self.url("suspendre"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "disparaît de la vitrine")
        self.assertContains(page, "back-office reste ouvert")

    def test_suspendre_exige_un_motif_puis_trace(self):
        self.assertEqual(self.client.post(self.url("suspendre"), {"motif": ""}).status_code, 400)
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.etat, Boutique.ACTIVE)

        reponse = self.client.post(self.url("suspendre"), {"motif": "Loyer de juillet impayé après relance."})
        self.assertRedirects(reponse, reverse("plateforme:boutique", args=[self.boutique.pk]), fetch_redirect_response=False)
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.etat, Boutique.SUSPENDUE)
        trace = self.traces("boutique_etat").get()
        self.assertEqual(trace.boutique_id, self.boutique.pk)
        self.assertIn("Loyer de juillet", trace.motif)

        self.client.post(self.url("reactiver"), {"motif": "Loyer régularisé en espèces."})
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.etat, Boutique.ACTIVE)

    def test_valider_une_candidature_active_son_bail_sans_motif(self):
        self.boutique.etat = Boutique.CANDIDATURE
        self.boutique.save(update_fields=["etat"])
        Bail.objects.filter(boutique=self.boutique).update(etat=Bail.BROUILLON)
        reponse = self.client.post(self.url("valider"), {"motif": ""})
        self.assertEqual(reponse.status_code, 302)
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.etat, Boutique.ACTIVE)
        self.assertEqual(self.boutique.baux.get().etat, Bail.ACTIF)
        self.assertTrue(self.traces("boutique_etat").exists())

    def test_resilier_clot_le_bail(self):
        self.client.post(self.url("resilier"), {"motif": "Départ du commerçant, fin de bail convenue."})
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.etat, Boutique.RESILIEE)
        bail = self.boutique.baux.get()
        self.assertEqual(bail.etat, Bail.RESILIE)
        self.assertEqual(bail.fin, timezone.localdate())
        self.assertIn("Départ du commerçant", bail.motif_resiliation)

    def test_les_transitions_interdites_repondent_400_et_disent_pourquoi(self):
        cas = [("reactiver", "Seule une boutique suspendue"), ("valider", "Seule une candidature"), ("envoler", "Action inconnue")]
        for action, attendu in cas:
            reponse = self.client.get(self.url(action))
            self.assertContains(reponse, attendu, status_code=400)
            reponse = self.client.post(self.url(action), {"motif": "Tentative interdite."})
            self.assertEqual(reponse.status_code, 400, action)
        self.boutique.etat = Boutique.RESILIEE
        self.boutique.save(update_fields=["etat"])
        for action in ("suspendre", "reactiver", "valider", "resilier"):
            self.assertEqual(self.client.post(self.url(action), {"motif": "Tentative interdite."}).status_code, 400, action)
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.etat, Boutique.RESILIEE)
        self.assertFalse(self.traces("boutique_etat").exists())

    def test_sans_le_droit_des_boutiques_c_est_un_403(self):
        responsable = fabrique.creer_utilisateur("Responsable de rayon")
        services.nommer_administrateur(
            par=self.superadmin, code_role=Role.RESP_RAYON, motif="Gère un rayon, pas les baux.",
            compte_existant=responsable,
        )
        self.client.force_login(responsable)
        self.assertEqual(self.client.post(self.url("suspendre"), {"motif": "Pas son geste."}).status_code, 403)


# ============================================================================
# 6. Encaisser un loyer
# ============================================================================
class EncaisserUnLoyerTest(Personnages, TestCase):
    def setUp(self):
        self.poser()
        self.client.force_login(self.administrateur)
        bail = self.boutique.baux.get()
        aujourdhui = timezone.localdate()
        self.facture = FactureLoyer.objects.create(
            bail=bail, periode=aujourdhui.replace(day=1), montant_ht=Decimal("45000"),
            echeance=aujourdhui - timedelta(days=12),
        )
        self.url = reverse("plateforme:loyer_encaisser", args=[self.facture.pk])

    def test_la_confirmation_montre_les_montants_et_le_retard(self):
        page = self.client.get(self.url)
        self.assertContains(page, "12 jours de retard")
        self.assertContains(page, "53 662")  # 45 000 + 19,25 % de TVA (8 662,50), sans centimes

    def test_encaisser_marque_payee_et_trace(self):
        reponse = self.client.post(self.url)
        self.assertRedirects(reponse, reverse("plateforme:loyers"), fetch_redirect_response=False)
        self.facture.refresh_from_db()
        self.assertEqual(self.facture.etat, FactureLoyer.PAYEE)
        self.assertIsNotNone(self.facture.paye_le)
        self.assertEqual(self.traces("loyer_encaisser").get().boutique_id, self.boutique.pk)

    def test_une_facture_payee_ou_annulee_ne_s_encaisse_pas(self):
        self.client.post(self.url)
        self.assertEqual(self.client.post(self.url).status_code, 400)
        annulee = FactureLoyer.objects.create(
            bail=self.facture.bail, periode=self.facture.periode - timedelta(days=40), montant_ht=Decimal("45000"),
            echeance=timezone.localdate(), etat=FactureLoyer.ANNULEE,
        )
        reponse = self.client.post(reverse("plateforme:loyer_encaisser", args=[annulee.pk]))
        self.assertContains(reponse, "annulée", status_code=400)
        self.assertEqual(self.traces("loyer_encaisser").count(), 1)

    def test_la_suite_ne_mene_pas_hors_du_site(self):
        reponse = self.client.post(self.url, {"suite": "https://exemple.invalid/"})
        self.assertRedirects(reponse, reverse("plateforme:loyers"), fetch_redirect_response=False)


# ============================================================================
# 7. Fixer le taux d'un rayon
# ============================================================================
class FixerLeTauxDUnRayonTest(Personnages, TestCase):
    def setUp(self):
        self.poser()
        self.client.force_login(self.administrateur)
        self.url = reverse("plateforme:rayon_taux", args=[self.rayon.pk])

    def test_la_saisie_en_pourcent_montre_l_effet_puis_s_applique(self):
        apercu = self.client.post(self.url, {"pourcent": "7,5", "motif": "Alignement sur le rayon voisin."})
        self.assertEqual(apercu.status_code, 200)
        self.assertContains(apercu, "Appliquer 7,5")
        self.rayon.refresh_from_db()
        self.assertEqual(self.rayon.taux_commission, Decimal("0.0500"), "rien avant la confirmation")

        reponse = self.client.post(
            self.url, {"pourcent": "7,5", "motif": "Alignement sur le rayon voisin.", "confirmer": "1", "apercu_de": "7.5"}
        )
        self.assertRedirects(reponse, reverse("plateforme:rayons"), fetch_redirect_response=False)
        self.rayon.refresh_from_db()
        self.assertEqual(self.rayon.taux_commission, Decimal("0.0750"))
        self.assertIn("Alignement", AccesPlateforme.objects.get(ecran="marketplace/rayon/taux").motif)

    def test_un_taux_modifie_apres_l_apercu_est_remontre(self):
        reponse = self.client.post(
            self.url, {"pourcent": "9", "motif": "Alignement sur le rayon voisin.", "confirmer": "1", "apercu_de": "7.5"}
        )
        self.assertEqual(reponse.status_code, 200)
        self.rayon.refresh_from_db()
        self.assertEqual(self.rayon.taux_commission, Decimal("0.0500"))

    def test_un_pourcentage_hors_borne_est_refuse(self):
        reponse = self.client.post(self.url, {"pourcent": "80", "motif": "Erreur de saisie probable."})
        self.assertIn("pourcent", reponse.context["form"].errors)

    def test_le_juge_et_partie_voit_le_refus(self):
        boutique = fabrique.creer_boutique("Boutique de l'administrateur")
        boutique.rayon_principal = self.rayon
        boutique.save(update_fields=["rayon_principal"])
        Appartenance.objects.create(utilisateur=self.administrateur, boutique=boutique, role=self.role_gerant)

        page = self.client.get(self.url)
        self.assertContains(page, "Conflit d'intérêts")
        reponse = self.client.post(
            self.url, {"pourcent": "2", "motif": "Baisse opportune.", "confirmer": "1", "apercu_de": "2"}
        )
        self.assertEqual(reponse.status_code, 403)
        self.rayon.refresh_from_db()
        self.assertEqual(self.rayon.taux_commission, Decimal("0.0500"))

    def test_le_superadministrateur_sans_role_est_prevenu_avant_la_saisie(self):
        # `gouvernance.fixer_taux_rayon` exige le droit par un rôle de plateforme ; la page le dit
        # d'emblée, au lieu de laisser saisir un taux pour le refuser ensuite.
        self.client.force_login(self.superadmin)
        page = self.client.get(self.url)
        self.assertContains(page, "demande un rôle de plateforme")
        self.assertNotContains(page, 'name="pourcent"')
        reponse = self.client.post(self.url, {"pourcent": "6", "motif": "Essai sans rôle.", "confirmer": "1", "apercu_de": "6"})
        self.assertEqual(reponse.status_code, 403)
