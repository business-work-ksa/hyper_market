"""Espace personnalisé d'une boutique : charte graphique et liens marketing.

Ce que ces tests protègent est d'abord une propriété de lisibilité, et elle a
une histoire : le premier teal du produit, `#0F6F5C`, avait été rejeté par le
validateur de palette avec un chroma de 0,088, sous le plancher de 0,1 — il
« lisait gris » sur une barre de graphique (docs/19, §2.1). **Le même validateur
s'applique maintenant au logo du commerçant**, et le premier test ci-dessous
reproduit ce verdict-là : si le module cesse de le retrouver, il a cessé d'être
le validateur du produit.

Le reste tient en trois règles :

* la **teinte** du commerçant n'est jamais modifiée — c'est la seule chose qu'il
  reconnaît dans son logo ;
* la version sombre est **éclaircie, jamais inversée** ;
* une couleur neutre est **refusée**, pas inventée : lui donner une teinte
  reviendrait à choisir sa marque à sa place.
"""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.core.tenancy import contexte_boutique, contexte_plateforme
from apps.marketplace import charte
from apps.marketplace.models import IdentiteVisuelle, LienMarketing
from tests import fabrique


def rattacher(utilisateur, boutique, code_role=Role.GERANT):
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    return Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


def logo_de_test(couleur=(30, 136, 229)) -> SimpleUploadedFile:
    """Un PNG uni : suffisant pour vérifier l'extraction, sans fichier binaire au dépôt."""
    from PIL import Image

    image = Image.new("RGB", (64, 64), couleur)
    tampon = BytesIO()
    image.save(tampon, format="PNG")
    return SimpleUploadedFile("logo.png", tampon.getvalue(), content_type="image/png")


class ValidateurTest(TestCase):
    def test_il_retrouve_le_verdict_qui_a_rejete_le_premier_teal(self):
        """docs/19, §2.1 : chroma 0,088, sous le plancher de 0,1."""
        self.assertAlmostEqual(charte.chroma("#0F6F5C"), 0.088, places=3)
        self.assertLess(charte.chroma("#0F6F5C"), charte.PLANCHER_CHROMA)

    def test_la_couleur_retenue_du_produit_passe_le_plancher(self):
        self.assertGreaterEqual(charte.chroma("#00806a"), charte.PLANCHER_CHROMA)

    def test_une_couleur_pale_est_saturee_sans_changer_de_teinte(self):
        """La teinte est la seule chose que le commerçant reconnaît.

        La tolérance est de 3°, et ce n'est pas de la complaisance : une couleur
        sortie du correcteur est arrondie sur 8 bits par canal, ce qui déplace la
        teinte d'un peu moins d'un degré. Le seuil de perception d'un écart de
        teinte est d'un ordre de grandeur au-dessus — exiger l'égalité exacte
        testerait la quantification, pas la règle.
        """
        for essai in ("#0F6F5C", "#1e88e5", "#c62828", "#FFD700"):
            with self.subTest(couleur=essai):
                avant = charte._oklch(essai)[2]
                apres = charte._oklch(charte.ajuster(essai)[0])[2]
                self.assertLess(abs(avant - apres), 0.05)

    def test_une_couleur_trop_claire_est_assombrie_et_le_dit(self):
        couleur, motif = charte.ajuster("#FFD700")
        self.assertGreaterEqual(charte.contraste(couleur, charte.FOND_CLAIR), 3.0)
        self.assertIn("assombrie", motif)

    def test_la_version_sombre_est_eclaircie_pas_inversee(self):
        """Une couleur retournée n'est plus la vôtre."""
        sombre = charte.variante_sombre("#00806a")
        self.assertGreater(charte._oklch(sombre)[0], charte._oklch("#00806a")[0])
        self.assertGreaterEqual(
            charte.contraste(sombre, charte.FOND_SOMBRE), charte.CONTRASTE_SOMBRE
        )

    def test_une_couleur_neutre_est_refusee_pas_inventee(self):
        palette = charte.charte_depuis_couleur("#9E9E9E")
        self.assertTrue(palette["refusee"])
        self.assertEqual(palette["marque"], charte.PALETTE_PAR_DEFAUT["marque"])
        self.assertIn("neutre", palette["motif"])

    def test_toute_couleur_produite_est_lisible_dans_les_deux_modes(self):
        """La propriété qui justifie tout le module."""
        for essai in ("#1e88e5", "#c62828", "#0F6F5C", "#FFD700", "#4A148C", "#00E5FF"):
            with self.subTest(couleur=essai):
                palette = charte.charte_depuis_couleur(essai)
                self.assertGreaterEqual(
                    charte.contraste(palette["marque"], charte.FOND_CLAIR), 3.0
                )
                self.assertGreaterEqual(
                    charte.contraste(palette["marque_sombre"], charte.FOND_SOMBRE),
                    charte.CONTRASTE_SOMBRE,
                )

    def test_une_couleur_illisible_est_refusee_franchement(self):
        for essai in ("", "bleu", "#12"):
            with self.subTest(saisie=essai):
                with self.assertRaises(ValueError):
                    charte.chroma(essai)

    def test_les_couleurs_du_logo_ecartent_le_blanc_et_le_noir(self):
        """Proposer « noir » comme couleur de marque est une lecture correcte et un conseil inutile."""
        couleurs = charte.couleurs_du_logo(logo_de_test((30, 136, 229)))
        self.assertTrue(couleurs)
        for hexa in couleurs:
            self.assertGreater(charte.chroma(hexa), 0.04)

    def test_toutes_les_polices_sont_des_piles_systeme(self):
        """Aucun fichier téléchargé : la donnée est payante au mégaoctet."""
        for _, _, pile in charte.POLICES:
            with self.subTest(pile=pile):
                self.assertNotIn("http", pile)
                self.assertNotIn("url(", pile)


class SocleIdentite(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Ateba")
        self.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(self.gerant, self.boutique, Role.GERANT)
        self.client.force_login(self.gerant)

    def identite(self):
        with contexte_boutique(self.boutique):
            return IdentiteVisuelle.objects.get(boutique=self.boutique)


class EcranCharteTest(SocleIdentite):
    def test_l_ecran_s_ouvre_et_cree_la_charte_a_la_volee(self):
        """Une boutique sans charte n'est pas une erreur : c'est l'état initial."""
        reponse = self.client.get(reverse("identite"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(self.identite().couleur_marque, "#00806a")

    def test_une_couleur_valide_est_enregistree_telle_quelle(self):
        self.client.post(
            reverse("identite"), {"couleur_marque": "#1e88e5", "police": "systeme"}
        )
        identite = self.identite()
        self.assertEqual(identite.couleur_marque, "#1e88e5")
        self.assertEqual(identite.motif_ajustement, "")

    def test_une_couleur_pale_est_corrigee_et_la_correction_est_montree(self):
        """Une couleur changée sans explication passe pour un bogue."""
        self.client.post(
            reverse("identite"), {"couleur_marque": "#0F6F5C", "police": "systeme"}
        )
        identite = self.identite()
        self.assertNotEqual(identite.couleur_marque, "#0F6F5C")
        self.assertIn("saturation", identite.motif_ajustement)

    def test_la_charte_est_injectee_dans_le_back_office(self):
        self.client.post(
            reverse("identite"), {"couleur_marque": "#c62828", "police": "serif"}
        )
        corps = self.client.get(reverse("boutique")).content.decode()
        self.assertIn("--marque: #c62828", corps)
        self.assertIn("Georgia", corps)

    def test_une_boutique_sans_charte_n_injecte_rien(self):
        """Pas de bloc de style inutile sur chaque page de chaque boutique."""
        self.assertNotIn("--marque:", self.client.get(reverse("boutique")).content.decode())

    def test_le_logo_televerse_propose_ses_couleurs(self):
        self.client.post(
            reverse("identite"),
            {"couleur_marque": "#00806a", "police": "systeme", "logo": logo_de_test()},
        )
        reponse = self.client.get(reverse("identite"))
        self.assertTrue(reponse.context["proposees"])

    def test_une_couleur_illisible_est_refusee_par_le_formulaire(self):
        self.client.post(reverse("identite"), {"couleur_marque": "bleu", "police": "systeme"})
        self.assertEqual(self.identite().couleur_marque, "#00806a")

    def test_un_caissier_n_ouvre_pas_cet_ecran(self):
        caissier = fabrique.creer_utilisateur("Caissier")
        rattacher(caissier, self.boutique, Role.CAISSIER)
        self.client.force_login(caissier)
        self.assertEqual(self.client.get(reverse("identite")).status_code, 403)


class LiensMarketingTest(SocleIdentite):
    def _creer(self, libelle="Flyer marché", **extra):
        return self.client.post(
            reverse("lien_creer"), {"libelle": libelle, "article": "", **extra}
        )

    def lien(self):
        with contexte_boutique(self.boutique):
            return LienMarketing.objects.first()

    def test_un_lien_a_un_code_court_et_dictable(self):
        """Il finit toujours par être lu à voix haute une fois."""
        self._creer()
        lien = self.lien()
        self.assertEqual(len(lien.code), 7)
        for ambigu in "0O1I":
            self.assertNotIn(ambigu, lien.code)

    def test_le_lien_ouvre_la_vitrine_de_la_boutique(self):
        self._creer()
        reponse = self.client.get(f"/l/{self.lien().code}/")
        self.assertEqual(
            reponse["Location"], f"/marche/boutique/{self.boutique.slug}/"
        )

    def test_chaque_visite_est_comptee(self):
        self._creer()
        code = self.lien().code
        for _ in range(3):
            self.client.get(f"/l/{code}/")
        self.assertEqual(self.lien().clics, 3)

    def test_un_lien_peut_porter_un_code_de_parrainage(self):
        self._creer(code_apporteur="HM-ABC123")
        reponse = self.client.get(f"/l/{self.lien().code}/")
        self.assertIn("ref=HM-ABC123", reponse["Location"])

    def test_un_lien_retire_ne_redirige_plus_mais_n_est_pas_efface(self):
        """Le lien est peut-être imprimé sur un flyer distribué la semaine dernière."""
        self._creer()
        lien = self.lien()
        self.client.post(reverse("lien_retirer", args=[lien.pk]))

        self.assertEqual(self.client.get(f"/l/{lien.code}/").status_code, 404)
        with contexte_boutique(self.boutique):
            self.assertTrue(LienMarketing.objects.filter(pk=lien.pk).exists())

    def test_un_code_inconnu_repond_404(self):
        self.assertEqual(self.client.get("/l/ZZZZZZZ/").status_code, 404)

    def test_le_lien_d_une_autre_boutique_est_introuvable_a_la_gestion(self):
        voisine = fabrique.creer_boutique("Voisine")
        with contexte_boutique(voisine):
            etranger = LienMarketing.objects.create(
                boutique=voisine, libelle="Chez le voisin", code="ABCDEFG"
            )

        reponse = self.client.post(reverse("lien_retirer", args=[etranger.pk]))
        self.assertEqual(reponse.status_code, 404)

    def test_le_lien_d_une_autre_boutique_fonctionne_quand_meme_en_public(self):
        """Un lien court est public : il n'appartient pas au contexte de qui le suit."""
        voisine = fabrique.creer_boutique("Voisine publique")
        with contexte_boutique(voisine):
            LienMarketing.objects.create(
                boutique=voisine, libelle="Voisin", code="PUBLIC1"
            )

        reponse = self.client.get("/l/PUBLIC1/")
        self.assertEqual(reponse["Location"], f"/marche/boutique/{voisine.slug}/")


class VitrinePersonnaliseeTest(SocleIdentite):
    def test_la_page_de_la_boutique_porte_ses_couleurs(self):
        self.client.post(
            reverse("identite"), {"couleur_marque": "#c62828", "police": "systeme"}
        )
        self.client.logout()

        corps = self.client.get(
            reverse("vitrine_boutique", args=[self.boutique.slug])
        ).content.decode()
        self.assertIn("--marque: #c62828", corps)

    def test_le_catalogue_de_tout_le_marche_garde_la_charte_du_marche(self):
        """Mélanger dix chartes sur une même grille ne servirait personne."""
        self.client.post(
            reverse("identite"), {"couleur_marque": "#c62828", "police": "systeme"}
        )
        self.client.logout()

        corps = self.client.get(reverse("vitrine_catalogue")).content.decode()
        self.assertNotIn("--marque: #c62828", corps)
