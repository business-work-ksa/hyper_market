"""La vérification d'une boutique (docs/08 §5.3, docs/23 §2.3-2.4).

Ce que ces tests défendent :

* **le verrou** : aucun des quatre chemins d'activation — l'assistant « ouvrir tout de suite »,
  `valider`, `réactiver`, l'administration Django — ne rend active une boutique non vérifiée ;
  une boutique **déjà** active n'est pas coupée ;
* **les quatre yeux** : le déclarant, l'ouvreur et un membre de l'équipe ne valident pas ; le
  superadministrateur, si ;
* **les règles** : pièce expirée, NIU ou NIF selon le pays, pays non ouvert, opérateur hors pays,
  titulaire qui ne correspond pas, carence de 48 h et retrait de l'ancien compte ;
* **la minimisation** : aucun numéro de pièce en clair en base, aucun numéro complet dans une
  liste ; chaque décision et chaque dossier ouvert laissent leur ligne au journal.
"""

from datetime import timedelta
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Appartenance, DossierKyc, Role
from apps.confiance import verification
from apps.core.models import AccesPlateforme
from apps.marketplace import cemac
from apps.marketplace.models import Bail, Boutique, CompteVersement
from apps.plateforme import services
from tests import fabrique

NUMERO_CNI = "CE 1122 3344 5566"


def _admin(nom):
    compte = fabrique.creer_utilisateur(nom)
    call_command("preparer_administrateur", administrateur=compte.telephone, verbosity=0)
    compte.refresh_from_db()
    return compte


def rattacher_gerant(boutique, utilisateur):
    role, _ = Role.objects.get_or_create(code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE})
    return Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


def verifier_entierement(boutique, gerant, *, declarant, verificateur, nom_lu=None, numero_piece=None):
    """Un dossier complet, fait par les vrais services : deux administrateurs distincts.

    Utilisé aussi par `tests/test_console_assistants.py`, pour préparer les boutiques qu'on y
    valide ou réactive.
    """
    jour = timezone.localdate()
    if not boutique.rccm or not boutique.niu:
        boutique.rccm = boutique.rccm or f"RC/DLA/2024/B/{boutique.pk.int % 10000:04d}"
        boutique.niu = boutique.niu or f"M0{boutique.pk.int % 10**10:010d}X"
        boutique.save(update_fields=["rccm", "niu"])
    nom_lu = nom_lu or gerant.nom_complet
    piece = verification.attester_piece(
        boutique, par=declarant, type_piece=DossierKyc.CNI, utilisateur=gerant,
        numero=numero_piece or f"CE{gerant.pk.int % 10**9:09d}", pays="CM",
        expire_le=jour + timedelta(days=900), nom_lu=nom_lu, mode=DossierKyc.PRESENTIEL,
    )
    verification.valider_piece(piece, par=verificateur)
    for type_piece, numero in ((DossierKyc.RCCM, boutique.rccm), (verification.sigle_fiscal(boutique), boutique.niu)):
        d = verification.attester_piece(boutique, par=declarant, type_piece=type_piece, numero=numero, mode=DossierKyc.PRESENTIEL)
        verification.valider_piece(d, par=verificateur)
    verification.attester_appel(boutique, gerant, par=verificateur)
    compte = verification.declarer_compte(
        boutique, par=declarant, operateur=cemac.MTN_MOMO, numero="+237 677 00 11 22", titulaire=nom_lu, depuis_console=True
    )
    compte = verification.verifier_compte(compte, par=verificateur)
    gerant.refresh_from_db()
    return compte


class Marche:
    """Deux administrateurs du marché, un superadministrateur, une candidature et son gérant."""

    def poser(self):
        self.admin_a = _admin("Administratrice A")
        self.admin_b = _admin("Administrateur B")
        self.superadmin = fabrique.creer_utilisateur("Superadministratrice")
        self.superadmin.is_superuser = self.superadmin.is_staff = True
        self.superadmin.save(update_fields=["is_superuser", "is_staff"])

        self.boutique = fabrique.creer_boutique("Quincaillerie Ateba")
        self.boutique.etat = Boutique.CANDIDATURE
        self.boutique.raison_sociale = "Ets Ateba et Fils SARL"
        self.boutique.rccm = "RC/DLA/2024/B/1234"
        self.boutique.niu = "M012345678901X"
        self.boutique.save()
        Bail.objects.filter(boutique=self.boutique).update(etat=Bail.BROUILLON)
        self.gerant = fabrique.creer_utilisateur("Paul Atéba")
        rattacher_gerant(self.boutique, self.gerant)

    def attester_cni(self, par=None, **surcharges):
        valeurs = dict(
            type_piece=DossierKyc.CNI, utilisateur=self.gerant, numero=NUMERO_CNI, pays="CM",
            expire_le=timezone.localdate() + timedelta(days=400), nom_lu="ATEBA Paul", mode=DossierKyc.PRESENTIEL,
        )
        valeurs.update(surcharges)
        return verification.attester_piece(self.boutique, par=par or self.admin_a, **valeurs)


# ============================================================================
# Le verrou d'activation
# ============================================================================
class VerrouTest(Marche, TestCase):
    def setUp(self):
        self.poser()

    def test_la_liste_des_manques_est_lisible(self):
        manques = verification.manques_pour_activer(self.boutique)
        texte = " ".join(manques)
        self.assertIn("pièce d'identité du gérant Paul Atéba", texte)
        self.assertIn("téléphone du gérant Paul Atéba", texte)
        self.assertIn("RCCM de la boutique n'a pas été vérifié", texte)
        self.assertIn("NIU de la boutique n'a pas été vérifié", texte)
        self.assertIn("Aucun compte de versement vérifié", texte)

    def test_valider_est_refuse_puis_accepte_une_fois_verifiee(self):
        with self.assertRaises(verification.VerificationIncomplete) as refus:
            services.changer_etat_boutique(self.boutique, services.VALIDER, par=self.admin_a)
        self.assertTrue(refus.exception.manques)
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.etat, Boutique.CANDIDATURE)

        self.client.force_login(self.admin_a)
        url = reverse("plateforme:boutique_etat", args=[self.boutique.pk]) + "?action=valider"
        page = self.client.get(url)
        self.assertContains(page, "Vérification incomplète")
        self.assertContains(page, reverse("plateforme:verification_dossier", args=[self.boutique.pk]))
        reponse = self.client.post(url, {"motif": ""})
        self.assertContains(reponse, "n&#x27;a pas été vérifié", status_code=400)
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.etat, Boutique.CANDIDATURE)

        verifier_entierement(self.boutique, self.gerant, declarant=self.admin_a, verificateur=self.admin_b, nom_lu="ATEBA Paul")
        self.assertEqual(verification.manques_pour_activer(self.boutique), [])
        self.assertEqual(self.client.post(url, {"motif": ""}).status_code, 302)
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.etat, Boutique.ACTIVE)

    def test_reactiver_est_refuse_pour_une_boutique_non_verifiee(self):
        ancienne = fabrique.creer_boutique("Ancienne boutique")
        rattacher_gerant(ancienne, fabrique.creer_utilisateur("Marie Ekedi"))
        services.changer_etat_boutique(ancienne, services.SUSPENDRE, par=self.admin_a, motif="Loyer impayé depuis deux mois.")
        with self.assertRaises(verification.VerificationIncomplete):
            services.changer_etat_boutique(ancienne, services.REACTIVER, par=self.admin_a, motif="Loyer régularisé.")
        ancienne.refresh_from_db()
        self.assertEqual(ancienne.etat, Boutique.SUSPENDUE)

    def test_l_administration_django_ne_rend_pas_active(self):
        self.boutique.etat = Boutique.ACTIVE
        with self.assertRaises(ValidationError) as refus:
            self.boutique.full_clean()
        self.assertIn("etat", refus.exception.message_dict)
        self.assertIn("Vérification incomplète", " ".join(refus.exception.message_dict["etat"]))

    def test_l_administration_django_ne_coupe_pas_une_boutique_deja_active(self):
        active = fabrique.creer_boutique("Active d'avant la règle")
        active.enseigne = "Nouvelle enseigne"
        active.full_clean()  # ne lève pas : seule la transition est verrouillée

    def test_l_assistant_ouvrir_tout_de_suite_est_refuse_et_rien_n_est_cree(self):
        from tests.test_console_assistants import MOT_DE_PASSE, _etape

        offre, rayon = fabrique.creer_offre(), fabrique.creer_rayon()
        self.client.force_login(self.admin_a)
        etapes = {
            "identite": {"enseigne": "Pharmacie du Port", "raison_sociale": "Pharmacie du Port SARL",
                         "metier": "PHARMACIE", "ville": "Douala", "telephone": ""},
            "legal": {"rccm": "RC/DLA/2025/B/9", "niu": "M099", "regime_fiscal": Boutique.IGS},
            "offre": {"offre": offre.code, "rayon": str(rayon.pk), "debut": timezone.localdate().isoformat(),
                      "loyer_mensuel": "", "depot_garantie": "0", "taux_commission": "", "motif_derogation": ""},
            "gerant": {"mode": "nouveau", "telephone": "+237699777055", "nom": "Dr Ngo",
                       "mot_de_passe": MOT_DE_PASSE, "mot_de_passe_confirmation": MOT_DE_PASSE},
        }
        for code, donnees in etapes.items():
            self.assertEqual(self.client.post(_etape("boutique", code), donnees).status_code, 302, code)
        recap = self.client.get(_etape("boutique", "recapitulatif"))
        self.assertContains(recap, "Fermé tant que la vérification n'est pas faite")
        reponse = self.client.post(_etape("boutique", "recapitulatif"), {"ouverture": "active"})
        self.assertContains(reponse, "pièce d&#x27;identité du gérant Dr Ngo")
        self.assertFalse(Boutique.objects.filter(enseigne="Pharmacie du Port").exists())

    def test_une_boutique_deja_active_n_est_pas_coupee_mais_a_regulariser(self):
        active = fabrique.creer_boutique("Active d'avant la règle")
        self.assertTrue(verification.manques_pour_activer(active))
        active.refresh_from_db()
        self.assertEqual(active.etat, Boutique.ACTIVE)
        file = verification.file_des_verifications()
        self.assertIn(active, [x["boutique"] for x in file["a_regulariser"]])
        self.assertIn(self.boutique, [x["boutique"] for x in file["candidatures"]])

    def test_pays_non_ouvert_refuse(self):
        self.boutique.pays = "GA"
        self.boutique.save(update_fields=["pays"])
        texte = " ".join(verification.manques_pour_activer(self.boutique))
        self.assertIn("Gabon", texte)
        self.assertIn("pas encore ouvert", texte)


# ============================================================================
# Les quatre yeux
# ============================================================================
class QuatreYeuxTest(Marche, TestCase):
    def setUp(self):
        self.poser()

    def test_le_declarant_ne_valide_pas_sa_propre_attestation(self):
        piece = self.attester_cni(par=self.admin_a)
        with self.assertRaisesMessage(PermissionDenied, "Vous avez vous-même déclaré"):
            verification.valider_piece(piece, par=self.admin_a)
        verification.valider_piece(piece, par=self.admin_b)
        piece.refresh_from_db()
        self.assertEqual((piece.etat, piece.verifie_par, piece.declare_par), (DossierKyc.VALIDE, self.admin_b, self.admin_a))

    def test_la_base_refuse_aussi_le_meme_declarant_et_verificateur(self):
        from django.db import IntegrityError, transaction

        piece = self.attester_cni(par=self.admin_a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DossierKyc.objects.filter(pk=piece.pk).update(verifie_par=self.admin_a, etat=DossierKyc.VALIDE)

    def test_l_ouvreur_ne_valide_pas(self):
        piece = self.attester_cni(par=self.admin_a)
        self.boutique.cree_par = self.admin_b
        self.boutique.save(update_fields=["cree_par"])
        with self.assertRaisesMessage(PermissionDenied, "ouvert cette boutique"):
            verification.valider_piece(piece, par=self.admin_b)

    def test_l_ouvreur_se_reconnait_aussi_a_la_trace_de_l_assistant(self):
        piece = self.attester_cni(par=self.admin_a)
        AccesPlateforme.objects.create(utilisateur=self.admin_b, boutique_id=self.boutique.pk,
                                       ecran="assistant_boutique", motif="Ouverture de la boutique")
        with self.assertRaisesMessage(PermissionDenied, "ouvert cette boutique"):
            verification.valider_piece(piece, par=self.admin_b)

    def test_un_membre_de_l_equipe_ne_valide_pas(self):
        # Un compte d'administration rattaché à la boutique (héritage d'avant l'ADR-012, §5).
        vendeur = _admin("Administrateur et vendeur")
        role, _ = Role.objects.get_or_create(code=Role.VENDEUR, defaults={"libelle": "Vendeur", "portee": Role.BOUTIQUE})
        Appartenance.objects.create(utilisateur=vendeur, boutique=self.boutique, role=role, actif=False)
        piece = self.attester_cni(par=self.admin_a)
        with self.assertRaisesMessage(PermissionDenied, "membre de l'équipe"):
            verification.valider_piece(piece, par=vendeur)
        compte = verification.declarer_compte(self.boutique, par=self.gerant, operateur=cemac.MTN_MOMO,
                                              numero="+237677001122", titulaire="Paul Ateba")
        with self.assertRaisesMessage(PermissionDenied, "membre de l'équipe"):
            verification.verifier_compte(compte, par=vendeur)

    def test_le_superadministrateur_compte_comme_second_regard(self):
        piece = self.attester_cni(par=self.admin_a)
        verification.valider_piece(piece, par=self.superadmin)
        self.assertEqual(DossierKyc.objects.get(pk=piece.pk).etat, DossierKyc.VALIDE)

    def test_le_declarant_d_un_compte_ne_le_verifie_pas(self):
        verification.valider_piece(self.attester_cni(), par=self.admin_b)
        compte = verification.declarer_compte(self.boutique, par=self.admin_a, operateur=cemac.MTN_MOMO,
                                              numero="+237677001122", titulaire="Paul Ateba", depuis_console=True)
        with self.assertRaises(PermissionDenied):
            verification.verifier_compte(compte, par=self.admin_a)
        verification.verifier_compte(compte, par=self.admin_b)

    def test_le_refus_est_lisible_dans_la_console(self):
        piece = self.attester_cni(par=self.admin_a)
        self.client.force_login(self.admin_a)
        page = self.client.get(reverse("plateforme:verification_dossier", args=[self.boutique.pk]))
        self.assertContains(page, "Vous avez vous-même déclaré cette pièce")
        reponse = self.client.post(reverse("plateforme:verification_piece", args=[piece.pk]), {"decision": "valider"})
        self.assertContains(reponse, "Le second regard doit venir de quelqu&#x27;un d&#x27;autre", status_code=403)
        self.assertEqual(DossierKyc.objects.get(pk=piece.pk).etat, DossierKyc.EN_ATTENTE)

        self.client.force_login(self.admin_b)
        reponse = self.client.post(reverse("plateforme:verification_piece", args=[piece.pk]), {"decision": "valider"})
        self.assertRedirects(reponse, reverse("plateforme:verification_dossier", args=[self.boutique.pk]), fetch_redirect_response=False)
        self.assertEqual(DossierKyc.objects.get(pk=piece.pk).etat, DossierKyc.VALIDE)

    def test_rejeter_exige_un_motif_et_reste_ouvert_au_declarant(self):
        piece = self.attester_cni(par=self.admin_a)
        with self.assertRaises(ValidationError):
            verification.rejeter_piece(piece, par=self.admin_a, motif="")
        verification.rejeter_piece(piece, par=self.admin_a, motif="Photo floue, date illisible.")
        piece.refresh_from_db()
        self.assertEqual((piece.etat, piece.motif_rejet), (DossierKyc.REJETE, "Photo floue, date illisible."))

    def test_la_meme_piece_pour_deux_personnes_est_bloquee(self):
        verification.valider_piece(self.attester_cni(), par=self.admin_b)
        autre = fabrique.creer_boutique("Autre boutique")
        prete_nom = fabrique.creer_utilisateur("Prête-nom")
        rattacher_gerant(autre, prete_nom)
        piece = verification.attester_piece(
            autre, par=self.admin_a, type_piece=DossierKyc.CNI, utilisateur=prete_nom, numero="ce-1122-3344-5566",
            pays="CM", expire_le=timezone.localdate() + timedelta(days=100), nom_lu="Prête-nom", mode=DossierKyc.VISIO,
        )
        self.assertTrue(any("autre personne" in a for a in verification.alertes_piece(piece)))
        with self.assertRaisesMessage(ValidationError, "déjà validé pour une autre personne"):
            verification.valider_piece(piece, par=self.admin_b)


# ============================================================================
# Les règles des pièces
# ============================================================================
class PiecesTest(Marche, TestCase):
    def setUp(self):
        self.poser()

    def test_une_piece_expiree_ne_s_atteste_pas(self):
        with self.assertRaises(ValidationError) as refus:
            self.attester_cni(expire_le=timezone.localdate() - timedelta(days=1))
        self.assertIn("expirée ne s'atteste pas", " ".join(refus.exception.message_dict["expire_le"]))

    def test_une_piece_validee_puis_expiree_redevient_un_manque(self):
        piece = self.attester_cni()
        verification.valider_piece(piece, par=self.admin_b)
        self.assertFalse(any("pièce d'identité" in m for m in verification.manques_pour_activer(self.boutique)))
        DossierKyc.objects.filter(pk=piece.pk).update(expire_le=timezone.localdate() - timedelta(days=3))
        self.assertTrue(any("a expiré le" in m for m in verification.manques_pour_activer(self.boutique)))

    def test_niu_au_cameroun_nif_au_gabon(self):
        self.assertEqual(verification.sigle_fiscal(self.boutique), "NIU")
        verification.valider_piece(
            verification.attester_piece(self.boutique, par=self.admin_a, type_piece="NIU", numero="m012345678901x", mode="presentiel"),
            par=self.admin_b,
        )
        self.assertFalse(any("NIU" in m for m in verification.manques_pour_activer(self.boutique)))

        gabon = fabrique.creer_boutique("Boutique de Libreville")
        gabon.pays, gabon.niu = "GA", "GA-778899"
        gabon.save(update_fields=["pays", "niu"])
        with self.assertRaisesMessage(ValidationError, "Au Gabon, l'identifiant fiscal est le NIF, pas le NIU"):
            verification.attester_piece(gabon, par=self.admin_a, type_piece="NIU", numero="GA-778899", mode="presentiel")
        self.assertTrue(any("NIF" in m for m in verification.manques_pour_activer(gabon)))
        verification.attester_piece(gabon, par=self.admin_a, type_piece="NIF", numero="GA-778899", mode="presentiel")

    def test_un_rccm_change_depuis_sa_verification_redevient_un_manque(self):
        verification.valider_piece(
            verification.attester_piece(self.boutique, par=self.admin_a, type_piece="RCCM", numero="RC-DLA 2024 B 1234", mode="visio"),
            par=self.admin_b,
        )
        self.assertFalse(any("RCCM" in m for m in verification.manques_pour_activer(self.boutique)))
        self.boutique.rccm = "RC/DLA/2025/B/9999"
        self.boutique.save(update_fields=["rccm"])
        self.assertTrue(any("RCCM de la boutique a changé" in m for m in verification.manques_pour_activer(self.boutique)))

    def test_un_numero_different_de_la_fiche_est_refuse(self):
        with self.assertRaisesMessage(ValidationError, "diffère de celui de la fiche"):
            verification.attester_piece(self.boutique, par=self.admin_a, type_piece="RCCM", numero="RC/YDE/1999/A/1", mode="presentiel")

    def test_un_document_recu_exige_son_empreinte(self):
        with self.assertRaises(ValidationError) as refus:
            self.attester_cni(mode=DossierKyc.DOCUMENT_RECU)
        self.assertIn("empreinte", refus.exception.message_dict)
        piece = self.attester_cni(mode=DossierKyc.DOCUMENT_RECU, empreinte="A" * 64)
        self.assertEqual(piece.empreinte, "a" * 64)

    def test_aucune_copie_sans_stockage_persistant_designe(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        fichier = SimpleUploadedFile("cni.jpg", b"\xff\xd8 image", content_type="image/jpeg")
        with self.assertRaisesMessage(ValidationError, "Aucun stockage persistant"):
            self.attester_cni(copie=fichier)
        self.assertIsNone(verification.stockage_des_copies())
        with override_settings(KYC_STOCKAGE_COPIES="default"):
            self.assertIsNone(verification.stockage_des_copies(), "le stockage par défaut n'est ni persistant ni privé")

    @override_settings(
        KYC_STOCKAGE_COPIES="kyc",
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            "kyc": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        },
    )
    def test_avec_un_stockage_designe_la_copie_est_gardee_et_son_empreinte_calculee(self):
        import hashlib

        from django.core.files.uploadedfile import SimpleUploadedFile

        contenu = b"\xff\xd8 image de la piece"
        piece = self.attester_cni(copie=SimpleUploadedFile("cni.jpg", contenu, content_type="image/jpeg"))
        self.assertTrue(piece.copie.startswith(f"kyc/{piece.pk}/"))
        self.assertNotIn("1122", piece.copie)
        self.assertEqual(piece.empreinte, hashlib.sha256(contenu).hexdigest())

    def test_l_appel_verifie_le_telephone_et_se_trace(self):
        verification.attester_appel(self.boutique, self.gerant, par=self.admin_a)
        self.gerant.refresh_from_db()
        self.assertTrue(self.gerant.telephone_verifie)
        self.assertTrue(AccesPlateforme.objects.filter(ecran="verification_appel", utilisateur=self.admin_a).exists())

    def test_entreprenant_sans_societe(self):
        """OHADA : l'entreprenant se déclare au RCCM ; sa « raison sociale » est son propre nom."""
        self.boutique.raison_sociale = "Paul Atéba"
        self.boutique.rccm = "CM-DLA-01-2024-D12-00123"
        self.boutique.save(update_fields=["raison_sociale", "rccm"])
        compte = verifier_entierement(self.boutique, self.gerant, declarant=self.admin_a, verificateur=self.admin_b,
                                      nom_lu="ATEBA Paul")
        self.assertEqual(compte.etat, CompteVersement.VERIFIE)
        self.assertEqual(verification.manques_pour_activer(self.boutique), [])
        self.assertIn("entreprenant", dict(DossierKyc.TYPES_PIECE)[DossierKyc.RCCM])


# ============================================================================
# Le compte de versement
# ============================================================================
class CompteTest(Marche, TestCase):
    def setUp(self):
        self.poser()
        verification.valider_piece(self.attester_cni(), par=self.admin_b)

    def declarer(self, **surcharges):
        valeurs = dict(operateur=cemac.MTN_MOMO, numero="+237 677 00 11 22", titulaire="Paul ATEBA")
        valeurs.update(surcharges)
        return verification.declarer_compte(self.boutique, par=self.gerant, **valeurs)

    def test_titulaire_normalise_accents_casse_et_ordre(self):
        self.assertTrue(verification.noms_concordent("ATEBA Paul", "paul atéba"))
        self.assertTrue(verification.noms_concordent("NGONO MBARGA Marie-Claire", "Marie Claire Ngono Mbarga"))
        self.assertFalse(verification.noms_concordent("Paul Ateba", "Pierre Ateba"))
        verification.verifier_compte(self.declarer(), par=self.admin_a)

    def test_un_titulaire_qui_ne_correspond_pas_est_refuse(self):
        compte = self.declarer(titulaire="Jean Tiers")
        with self.assertRaisesMessage(ValidationError, "ne correspond ni à"):
            verification.verifier_compte(compte, par=self.admin_a)
        self.assertEqual(CompteVersement.objects.get(pk=compte.pk).etat, CompteVersement.EN_ATTENTE)

    def test_la_raison_sociale_est_admise(self):
        verification.verifier_compte(self.declarer(titulaire="ETS ATEBA ET FILS SARL"), par=self.admin_a)

    def test_carence_de_48_h_et_retrait_de_l_ancien(self):
        premier = verification.verifier_compte(self.declarer(), par=self.admin_a)
        maintenant = timezone.now()
        self.assertAlmostEqual(premier.utilisable_le, premier.verifie_le + timedelta(hours=48), delta=timedelta(seconds=1))
        self.assertIsNone(verification.compte_de_versement_utilisable(self.boutique))
        self.assertEqual(verification.compte_de_versement_utilisable(self.boutique, maintenant=maintenant + timedelta(hours=49)), premier)

        second = verification.verifier_compte(self.declarer(numero="+237677998877"), par=self.admin_a)
        premier.refresh_from_db()
        self.assertEqual(premier.etat, CompteVersement.RETIRE)
        self.assertIsNotNone(premier.retire_le)
        self.assertEqual(CompteVersement.objects.filter(boutique=self.boutique).count(), 2, "retiré, jamais supprimé")
        # Pendant la carence du nouveau, **aucun** compte n'est utilisable — pas même l'ancien.
        self.assertIsNone(verification.compte_de_versement_utilisable(self.boutique, maintenant=maintenant + timedelta(hours=47)))
        self.assertEqual(verification.compte_de_versement_utilisable(self.boutique, maintenant=maintenant + timedelta(hours=49)), second)

    def test_operateur_hors_pays_et_numero_invalide(self):
        with self.assertRaises(ValidationError) as refus:
            self.declarer(operateur=cemac.AIRTEL_MONEY)
        self.assertIn("pas proposé au Cameroun", refus.exception.message_dict["operateur"][0])
        with self.assertRaises(ValidationError) as refus:
            self.declarer(numero="+241 06 00 11 22")
        self.assertIn("+237", refus.exception.message_dict["numero"][0])
        self.declarer(operateur=cemac.VIREMENT_BANCAIRE, numero="CM21 10005 00001 12345678901 23")

    def test_une_nouvelle_declaration_retire_celle_en_attente(self):
        ancienne = self.declarer()
        self.declarer(numero="+237677998877")
        ancienne.refresh_from_db()
        self.assertEqual(ancienne.etat, CompteVersement.RETIRE)

    def test_decisions_tracees(self):
        compte = self.declarer()
        verification.verifier_compte(compte, par=self.admin_a)
        trace = AccesPlateforme.objects.get(ecran="verification_compte")
        self.assertEqual((trace.utilisateur, trace.boutique_id), (self.admin_a, self.boutique.pk))
        self.assertIn("utilisable le", trace.motif)
        self.assertTrue(AccesPlateforme.objects.filter(ecran="verification_piece", utilisateur=self.admin_b).exists())
        self.assertTrue(AccesPlateforme.objects.filter(ecran="verification_attester", utilisateur=self.admin_a).exists())


# ============================================================================
# Minimisation, écrans et journal
# ============================================================================
class EcransTest(Marche, TestCase):
    def setUp(self):
        self.poser()

    def test_le_numero_de_piece_n_est_nulle_part_en_base(self):
        piece = self.attester_cni()
        verification.valider_piece(piece, par=self.admin_b)
        self.assertEqual(piece.numero_fin, "5566")
        self.assertEqual(piece.numero_masque, "••••••5566")
        self.assertEqual(piece.numero_empreinte, verification.empreinte_numero("ce112233445566"))
        cle = "112233445566"
        with connection.cursor() as curseur:
            for table in (DossierKyc._meta.db_table, AccesPlateforme._meta.db_table):
                curseur.execute(f"SELECT * FROM {table}")
                for ligne in curseur.fetchall():
                    brut = " ".join(str(v) for v in ligne).replace(" ", "")
                    self.assertNotIn(cle, brut, table)
        self.assertNotIn(cle, str(piece))

    def test_la_file_ne_montre_aucun_numero_complet(self):
        self.attester_cni()
        verification.declarer_compte(self.boutique, par=self.gerant, operateur=cemac.MTN_MOMO,
                                     numero="+237677001122", titulaire="Paul Ateba")
        self.client.force_login(self.admin_b)
        page = self.client.get(reverse("plateforme:verifications"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "677001122")
        self.assertContains(page, "••••••1122")
        self.assertContains(page, "••••••5566")
        self.assertContains(page, "Quincaillerie Ateba")

    def test_le_dossier_se_journalise_et_montre_la_liste_de_controle(self):
        self.client.force_login(self.admin_b)
        page = self.client.get(reverse("plateforme:verification_dossier", args=[self.boutique.pk]))
        self.assertContains(page, "Liste de contrôle")
        self.assertContains(page, "Aucune copie n'est conservée")
        trace = AccesPlateforme.objects.get(ecran="verification_dossier")
        self.assertEqual((trace.utilisateur, trace.boutique_id), (self.admin_b, self.boutique.pk))

    def test_attester_depuis_la_console(self):
        self.client.force_login(self.admin_a)
        url = reverse("plateforme:verification_dossier", args=[self.boutique.pk])
        reponse = self.client.post(url, {
            "geste": "attester", "type_piece": "CNI", "gerant": str(self.gerant.pk), "numero": NUMERO_CNI,
            "pays": "CM", "expire_le": (timezone.localdate() + timedelta(days=30)).isoformat(),
            "nom_lu": "ATEBA Paul", "mode": "visio", "empreinte": "",
        })
        self.assertRedirects(reponse, url, fetch_redirect_response=False)
        self.assertEqual(DossierKyc.objects.get(utilisateur=self.gerant).mode_verification, DossierKyc.VISIO)
        reponse = self.client.post(url, {"geste": "attester", "type_piece": "CNI", "gerant": str(self.gerant.pk),
                                         "numero": "X1", "pays": "CM", "expire_le": "2001-01-01", "nom_lu": "A B", "mode": "presentiel"})
        self.assertContains(reponse, "expirée ne s&#x27;atteste pas", status_code=400)

    def test_la_console_est_fermee_sans_le_droit_des_boutiques(self):
        self.client.force_login(self.gerant)
        self.assertEqual(self.client.get(reverse("plateforme:verifications")).status_code, 403)

    def test_le_back_office_montre_ce_qui_manque_et_declare_le_compte(self):
        self.client.force_login(self.gerant)
        session = self.client.session
        session["boutique_id"] = str(self.boutique.pk)
        session.save()
        page = self.client.get(reverse("verification"))
        self.assertContains(page, "Présentez l&#x27;original de votre pièce d&#x27;identité")
        self.assertContains(page, "déclaration d&#x27;entreprenant")
        reponse = self.client.post(reverse("verification"), {"operateur": cemac.AIRTEL_MONEY, "numero": "+237677001122", "titulaire": "Paul Ateba"})
        self.assertEqual(reponse.status_code, 400)
        reponse = self.client.post(reverse("verification"), {"operateur": cemac.MTN_MOMO, "numero": "+237677001122", "titulaire": "Paul Ateba"})
        self.assertRedirects(reponse, reverse("verification"), fetch_redirect_response=False)
        compte = CompteVersement.objects.get(boutique=self.boutique)
        self.assertEqual((compte.declare_par, compte.etat), (self.gerant, CompteVersement.EN_ATTENTE))
        page = self.client.get(reverse("verification"))
        self.assertNotContains(page, "677001122")
        self.assertContains(page, "••••••1122")
        self.assertNotContains(page, self.admin_a.nom_complet)

    def test_le_back_office_refuse_la_declaration_a_qui_n_est_pas_gerant(self):
        rh = fabrique.creer_utilisateur("Responsable RH")
        role, _ = Role.objects.get_or_create(code=Role.RH, defaults={"libelle": "RH", "portee": Role.BOUTIQUE})
        Appartenance.objects.create(utilisateur=rh, boutique=self.boutique, role=role)
        self.client.force_login(rh)
        session = self.client.session
        session["boutique_id"] = str(self.boutique.pk)
        session.save()
        self.assertEqual(self.client.get(reverse("verification")).status_code, 200)
        reponse = self.client.post(reverse("verification"), {"operateur": cemac.MTN_MOMO, "numero": "+237677001122", "titulaire": "Paul Ateba"})
        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(CompteVersement.objects.exists())

    def test_verifier_entierement_rend_la_boutique_activable(self):
        with mock.patch.object(cemac, "PAYS_OUVERTS", ()):
            self.assertTrue(any("pas encore ouvert" in m for m in verification.manques_pour_activer(self.boutique)))
        verifier_entierement(self.boutique, self.gerant, declarant=self.admin_a, verificateur=self.superadmin, nom_lu="ATEBA Paul")
        self.assertEqual(verification.manques_pour_activer(self.boutique), [])
