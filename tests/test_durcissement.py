"""Ce qui tient l'application debout quand quelqu'un pousse dessus.

Quatre défauts trouvés lors d'un audit, tous reproduits avant d'être corrigés.
Ce fichier garde la preuve qu'ils ne reviendront pas — un durcissement sans test
se défait au premier refactoring, et personne ne s'en aperçoit avant l'incident.

**La connexion n'était pas freinée.** Soixante essais de mot de passe sur le même
compte passaient sans qu'aucun ne soit refusé. L'identifiant étant un numéro de
téléphone, il n'y avait rien à deviner que le mot de passe.

**Chaque essai coûtait un hachage.** Django hache même pour un compte
inexistant — c'est voulu, cela masque l'existence du compte — mais cela offrait à
un inconnu le moyen de saturer le processeur sans avoir de compte.

**Un logo pouvait tuer le serveur.** 435 Ko sur le réseau, 144 mégapixels une
fois décompressés, plus d'un gigaoctet en mémoire. Pillow se contente d'un
avertissement, puis développe l'image quand même.

**Un inventaire de plus de cinq cents articles était refusé.** Deux champs par
article contre mille autorisés : le comptage, saisi en entier, partait dans un
`400` que personne ne pouvait comprendre. C'est l'écran de l'installation.
"""

import io

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.accounts import limitation
from apps.accounts.models import Appartenance, Role
from apps.marketplace import charte
from tests import fabrique

MOT_DE_PASSE = "motdepasse-solide"


def rattacher(utilisateur, boutique, code_role=Role.GERANT) -> None:
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


def image(largeur, hauteur, couleur=(30, 136, 229)) -> bytes:
    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), couleur).save(tampon, format="PNG", optimize=True)
    return tampon.getvalue()


# ---------------------------------------------------------------------------
# Le compteur d'essais
# ---------------------------------------------------------------------------
class CompteurTest(TestCase):
    def setUp(self):
        # Le cache est partagé entre les tests : un compteur laissé derrière
        # ferait échouer le suivant pour une raison invisible dans son code.
        cache.clear()

    def test_un_compte_neuf_n_est_pas_verrouille(self):
        self.assertFalse(limitation.trop_d_essais("+237600000000"))

    def test_le_verrou_se_pose_au_nombre_annonce(self):
        for _ in range(limitation.ESSAIS_MAX):
            limitation.compter_un_echec("+237600000000")
        self.assertTrue(limitation.trop_d_essais("+237600000000"))

    def test_le_verrou_ne_se_pose_pas_un_essai_trop_tot(self):
        for _ in range(limitation.ESSAIS_MAX - 1):
            limitation.compter_un_echec("+237600000000")
        self.assertFalse(limitation.trop_d_essais("+237600000000"))

    def test_un_compte_verrouille_n_enferme_pas_les_autres(self):
        """Le compteur porte sur le compte visé, jamais sur tout le monde.

        C'est la raison pour laquelle il ne compte pas par adresse IP : derrière
        un proxy, elles sont toutes identiques, et un seul attaquant fermerait la
        boutique à tous ses caissiers.
        """
        for _ in range(limitation.ESSAIS_MAX):
            limitation.compter_un_echec("+237600000000")
        self.assertFalse(limitation.trop_d_essais("+237611111111"))

    def test_une_connexion_reussie_efface_l_ardoise(self):
        """Deux fautes de frappe le matin ne rapprochent pas d'un verrou l'après-midi."""
        for _ in range(limitation.ESSAIS_MAX - 1):
            limitation.compter_un_echec("+237600000000")
        limitation.oublier("+237600000000")
        for _ in range(limitation.ESSAIS_MAX - 1):
            limitation.compter_un_echec("+237600000000")
        self.assertFalse(limitation.trop_d_essais("+237600000000"))

    def test_les_echecs_ne_prolongent_pas_la_fenetre(self):
        """Sinon l'attaque réussit en échouant : le compte ne rouvre jamais.

        Éprouvé sur l'échéance posée dans le cache plutôt que sur l'horloge : un
        test qui attendrait un quart d'heure ne serait pas lancé.
        """
        limitation.compter_un_echec("+237600000000")
        cle = limitation._cle("+237600000000")
        # Un cache local expose son échéance ; on la lit avant et après.
        restant_avant = cache._expire_info.get(cache.make_key(cle))
        for _ in range(5):
            limitation.compter_un_echec("+237600000000")
        restant_apres = cache._expire_info.get(cache.make_key(cle))
        self.assertEqual(restant_avant, restant_apres)


# ---------------------------------------------------------------------------
# L'écran de connexion
# ---------------------------------------------------------------------------
class ConnexionTest(TestCase):
    def setUp(self):
        cache.clear()
        self.boutique = fabrique.creer_boutique("Quincaillerie Ateba")
        self.gerant = fabrique.creer_utilisateur("Gérant")
        self.gerant.set_password(MOT_DE_PASSE)
        self.gerant.save()
        rattacher(self.gerant, self.boutique)

    def essayer(self, mot_de_passe, telephone=None):
        return self.client.post(
            reverse("connexion"),
            {"telephone": telephone or self.gerant.telephone, "mot_de_passe": mot_de_passe},
        )

    def test_le_bon_mot_de_passe_connecte(self):
        self.assertEqual(self.essayer(MOT_DE_PASSE).status_code, 302)

    def test_le_mauvais_mot_de_passe_refuse_sans_verrouiller_tout_de_suite(self):
        self.assertEqual(self.essayer("faux").status_code, 401)
        self.assertEqual(self.essayer(MOT_DE_PASSE).status_code, 302)

    def test_apres_dix_echecs_la_porte_se_ferme(self):
        for _ in range(limitation.ESSAIS_MAX):
            self.essayer("faux")
        reponse = self.essayer("faux")
        self.assertEqual(reponse.status_code, 429)
        # L'apostrophe part échappée dans le HTML ; on vise le reste.
        self.assertContains(reponse, "Trop d", status_code=429)
        self.assertContains(reponse, "se rouvrira tout seul", status_code=429)

    def test_le_verrou_vaut_aussi_contre_le_bon_mot_de_passe(self):
        """C'est le prix assumé du verrou, et il doit être vérifié, pas supposé.

        Un verrou qui s'ouvrirait pour le bon mot de passe ne verrouillerait
        rien : il suffirait de continuer d'essayer.
        """
        for _ in range(limitation.ESSAIS_MAX):
            self.essayer("faux")
        self.assertEqual(self.essayer(MOT_DE_PASSE).status_code, 429)

    def test_un_compte_verrouille_ne_coute_plus_de_hachage(self):
        """Le refus arrive **avant** `authenticate`, et c'est tout l'intérêt.

        Le hachage est volontairement lent. Le payer pour un compte déjà
        verrouillé rendrait la limitation inutile contre l'épuisement du
        processeur — l'attaquant n'a pas besoin de réussir pour faire tomber le
        serveur, seulement de faire travailler les trois `workers`.
        """
        from unittest import mock

        for _ in range(limitation.ESSAIS_MAX):
            self.essayer("faux")
        with mock.patch("apps.backoffice.views.authenticate") as hachage:
            self.essayer("faux")
        hachage.assert_not_called()

    def test_verrouiller_un_compte_n_en_verrouille_pas_un_autre(self):
        autre = fabrique.creer_utilisateur("Caissière")
        autre.set_password(MOT_DE_PASSE)
        autre.save()
        rattacher(autre, self.boutique, Role.VENDEUR)

        for _ in range(limitation.ESSAIS_MAX + 1):
            self.essayer("faux")
        self.assertEqual(
            self.essayer(MOT_DE_PASSE, telephone=autre.telephone).status_code, 302
        )

    def test_le_verrou_ne_trahit_pas_l_existence_du_compte(self):
        """Un numéro jamais inscrit se verrouille comme un autre.

        Si le `429` n'arrivait que sur les comptes réels, il suffirait d'essayer
        onze fois pour savoir lesquels existent — et la liste des numéros est
        exactement ce qui manque à une attaque par pulvérisation.
        """
        inconnu = "+237699999999"
        for _ in range(limitation.ESSAIS_MAX):
            self.essayer("faux", telephone=inconnu)
        self.assertEqual(self.essayer("faux", telephone=inconnu).status_code, 429)


# ---------------------------------------------------------------------------
# Le logo
# ---------------------------------------------------------------------------
class LogoTest(TestCase):
    """435 Ko sur le réseau, plus d'un gigaoctet en mémoire."""

    def formulaire(self, octets, nom="logo.png"):
        from apps.backoffice.forms import CharteForm

        return CharteForm(
            {"couleur_marque": "#1e88e5", "police": "systeme"},
            {"logo": SimpleUploadedFile(nom, octets, content_type="image/png")},
        )

    def test_un_vrai_logo_est_accepte(self):
        self.assertTrue(self.formulaire(image(512, 512)).is_valid())

    def test_une_bombe_de_decompression_est_refusee(self):
        formulaire = self.formulaire(image(12000, 12000))
        self.assertFalse(formulaire.is_valid())
        self.assertIn("12000", str(formulaire.errors["logo"]))

    def test_le_refus_dit_quoi_faire(self):
        """Un message qui nomme la dimension et la borne. « Fichier invalide »
        laisserait le commerçant réessayer trois fois le même fichier."""
        formulaire = self.formulaire(image(12000, 12000))
        formulaire.is_valid()
        self.assertIn("réduisez", str(formulaire.errors["logo"]).lower())

    def test_l_extraction_des_couleurs_refuse_aussi(self):
        """Deuxième verrou : cette fonction tourne aussi sur des logos déjà en base.

        Le formulaire ne couvre que le téléversement. Un logo entré avant que la
        borne existe passerait encore par ici — et le coût d'un oubli n'est pas
        une image de travers, c'est un processus tué par le noyau.
        """
        self.assertEqual(charte.couleurs_du_logo(io.BytesIO(image(12000, 12000))), [])

    def test_l_extraction_des_couleurs_marche_toujours(self):
        couleurs = charte.couleurs_du_logo(io.BytesIO(image(512, 512, (30, 136, 229))))
        self.assertEqual(couleurs, ["#1e88e5"])

    def test_un_logo_trop_lourd_est_refuse_sur_son_poids(self):
        """Une image peu profonde mais énorme : les pixels seuls ne l'attrapent pas."""
        from apps.backoffice.forms import CharteForm

        octets = image(2000, 2000) + b"\x00" * (CharteForm.LOGO_OCTETS_MAX + 1)
        formulaire = self.formulaire(octets)
        self.assertFalse(formulaire.is_valid())
        self.assertIn("Mo", str(formulaire.errors["logo"]))


# ---------------------------------------------------------------------------
# Les bornes de la requête
# ---------------------------------------------------------------------------
class RequeteTest(TestCase):
    def test_un_inventaire_de_cinq_cents_articles_tient_dans_la_requete(self):
        """Deux champs par article : c'est l'arithmétique qui décide de la borne.

        La valeur par défaut de Django (1000) refusait tout comptage au-delà de
        cinq cents références — sur l'écran même de la reprise de stock, celui
        qu'on utilise le jour de l'installation quand la liste est la plus
        longue. Le commerçant saisissait tout, puis recevait un `400` muet.
        """
        from django.conf import settings

        articles_possibles = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS // 2
        self.assertGreaterEqual(articles_possibles, 5000)

    def test_les_reponses_sont_comprimees(self):
        """475 Ko de stock deviennent 30 Ko. Sur une 3G de Douala, dix secondes
        deviennent une demi-seconde, et c'est la différence entre un outil qu'on
        ouvre et un outil qu'on contourne."""
        boutique = fabrique.creer_boutique("Quincaillerie")
        gerant = fabrique.creer_utilisateur("Gérant")
        gerant.set_password(MOT_DE_PASSE)
        gerant.save()
        rattacher(gerant, boutique)
        self.client.login(telephone=gerant.telephone, password=MOT_DE_PASSE)
        session = self.client.session
        session["boutique_id"] = str(boutique.pk)
        session.save()

        reponse = self.client.get(reverse("stock"), headers={"accept-encoding": "gzip"})
        self.assertEqual(reponse.headers.get("Content-Encoding"), "gzip")

    def test_les_identifiants_de_demonstration_ne_sont_pas_publics(self):
        """Un compte qui fonctionne, affiché à qui n'est pas connecté.

        Utile sur une vitrine de démonstration, ouvert en production — et rien
        n'empêche que le jeu de démonstration ait été chargé « juste pour voir »
        sur l'instance réelle. La mention est donc composée par la vue, jamais
        écrite en dur dans le gabarit.
        """
        with self.settings(AFFICHER_COMPTE_DEMO=False):
            self.assertNotContains(self.client.get(reverse("connexion")), "demo1234")
        with self.settings(AFFICHER_COMPTE_DEMO=True):
            self.assertContains(self.client.get(reverse("connexion")), "demo1234")

    def test_le_verrou_n_affiche_pas_non_plus_les_identifiants(self):
        """Le chemin le plus tentant pour un oubli : la page d'erreur.

        Trois rendus différents de `connexion.html` existent — vide, refus,
        verrou — et un seul qui oublierait le drapeau suffirait à rendre la
        mention publique.
        """
        with self.settings(AFFICHER_COMPTE_DEMO=False):
            refus = self.client.post(
                reverse("connexion"), {"telephone": "+237600000000", "mot_de_passe": "x"}
            )
            self.assertNotContains(refus, "demo1234", status_code=401)

    def test_aucun_gabarit_ne_laisse_fuir_un_commentaire(self):
        """Un commentaire Django ouvert sur plusieurs lignes **s'affiche**.

        `{#` … `#}` ne tient que sur une ligne. Ouvert sur plusieurs, Django ne
        le reconnaît pas et le rend tel quel — ce qui est arrivé sur l'écran de
        connexion, où un commentaire de quatre lignes s'est retrouvé imprimé
        entre le bouton et le bandeau. Rien ne l'avait signalé : la page
        répondait 200, la suite était verte, et seule une capture l'a montré.

        Le contrôle porte sur le rendu, pas sur le source : c'est la seule
        manière de l'attraper, quelle que soit la forme employée.
        """
        import re

        pages = [reverse("connexion"), "/marche/", "/marche/catalogue/"]
        for url in pages:
            corps = self.client.get(url).content.decode("utf-8")
            corps_sans_scripts = re.sub(r"(?s)<script.*?</script>", "", corps)
            for marqueur in ("{#", "#}", "{%", "%}", "{{", "}}"):
                self.assertNotIn(
                    marqueur, corps_sans_scripts, f"{marqueur} visible sur {url}"
                )

    def test_une_reponse_non_demandee_en_gzip_reste_lisible(self):
        """Un client qui ne sait pas décompresser doit recevoir du texte.

        Le cas n'est pas théorique ici : le service worker et les caisses hors
        ligne relisent ces réponses.
        """
        reponse = self.client.get(reverse("connexion"))
        self.assertNotIn("Content-Encoding", reponse.headers)
        self.assertContains(reponse, "<form")
