"""Ce que chaque rôle voit, et surtout ce qu'il ne voit pas.

Le rattachement à une boutique n'est pas un droit sur tout ce qu'elle contient.
Ces tests protègent une frontière d'**exposition de données**, pas un confort
d'interface : le coût d'achat lu sur un écran ouvert au comptoir circule dans le
quartier avant la fin de la journée, et la marge du patron n'est pas une donnée
d'employé.

Un échec ici n'est jamais « à ajuster » : c'est une fuite.
"""

import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.accounts.permissions import TOUS, droits_de, droits_du_role
from apps.backoffice.templatetags.hm import ESPACE_FINE
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import NiveauStock
from apps.inventory.services import entrer_stock
from tests import fabrique

MOT_DE_PASSE = "motdepasse"

# Écrans du back-office et droit qui les ouvre.
ECRANS = {
    "tableau_de_bord": "tableau_de_bord",
    "caisse": "caisse.encaisser",
    "session_caisse": "caisse.encaisser",
    "stock": "stock.voir",
    "nouvel_article": "stock.mouvementer",
    "inventaire": "stock.mouvementer",
    "ventes": "ventes.voir",
    "comptabilite": "comptabilite.voir",
    "boutique": "boutique.voir",
    "export_donnees": "exporter",
    "nouveau_depot": "boutique.administrer",
}


def rattacher(utilisateur, boutique, code_role=Role.GERANT):
    role, _ = Role.objects.get_or_create(
        code=code_role,
        defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE},
    )
    return Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class AttributionDesDroitsTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Droits")

    def test_le_gerant_a_tous_les_droits(self):
        gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(gerant, self.boutique, Role.GERANT)
        self.assertEqual(droits_de(gerant, self.boutique), TOUS)

    def test_le_caissier_ne_voit_ni_le_cout_ni_la_marge(self):
        """La séparation qui justifie tout le reste."""
        self.assertNotIn("cout.voir", droits_du_role(Role.CAISSIER))
        self.assertNotIn("marge.voir", droits_du_role(Role.CAISSIER))
        self.assertIn("caisse.encaisser", droits_du_role(Role.CAISSIER))

    def test_le_magasinier_voit_le_cout_mais_pas_la_marge(self):
        """Il saisit des prix d'achat ; il n'a pas à savoir ce qu'ils rapportent."""
        droits = droits_du_role(Role.MAGASINIER)
        self.assertIn("cout.voir", droits)
        self.assertIn("stock.mouvementer", droits)
        self.assertNotIn("marge.voir", droits)
        self.assertNotIn("caisse.encaisser", droits)

    def test_les_droits_sont_relatifs_a_une_boutique(self):
        """Gérant ici, caissier ailleurs : le calcul n'est jamais global au compte."""
        autre = fabrique.creer_boutique("Ailleurs")
        personne = fabrique.creer_utilisateur("Double casquette")
        rattacher(personne, self.boutique, Role.GERANT)
        rattacher(personne, autre, Role.CAISSIER)

        self.assertIn("marge.voir", droits_de(personne, self.boutique))
        self.assertNotIn("marge.voir", droits_de(personne, autre))

    def test_les_roles_cumules_s_additionnent(self):
        personne = fabrique.creer_utilisateur("Comptable et magasinier")
        rattacher(personne, self.boutique, Role.COMPTABLE)
        rattacher(personne, self.boutique, Role.MAGASINIER)

        droits = droits_de(personne, self.boutique)
        self.assertIn("comptabilite.voir", droits)
        self.assertIn("stock.mouvementer", droits)

    def test_une_appartenance_desactivee_n_ouvre_rien(self):
        parti = fabrique.creer_utilisateur("Ancien caissier")
        appartenance = rattacher(parti, self.boutique, Role.CAISSIER)
        appartenance.actif = False
        appartenance.save(update_fields=["actif"])

        self.assertEqual(droits_de(parti, self.boutique), frozenset())

    def test_sans_boutique_aucun_droit(self):
        """Un droit absent ferme ; il ne dégrade jamais vers l'ensemble complet."""
        personne = fabrique.creer_utilisateur("Sans rattachement")
        self.assertEqual(droits_de(personne, None), frozenset())
        self.assertEqual(droits_de(personne, self.boutique), frozenset())


class PorteDesEcransTest(TestCase):
    """Chaque écran répond 200 au rôle qui l'ouvre, 403 aux autres."""

    @classmethod
    def setUpTestData(cls):
        cls.boutique = fabrique.creer_boutique("Porte", quota_depots=2)
        with contexte_boutique(cls.boutique):
            fabrique.creer_depot(cls.boutique)

        cls.comptes = {}
        for code_role in (Role.GERANT, Role.CAISSIER, Role.MAGASINIER, Role.COMPTABLE):
            utilisateur = fabrique.creer_utilisateur(code_role.title())
            rattacher(utilisateur, cls.boutique, code_role)
            cls.comptes[code_role] = utilisateur

    def test_chaque_ecran_ouvre_a_qui_de_droit(self):
        for code_role, utilisateur in self.comptes.items():
            acquis = droits_du_role(code_role)
            self.client.force_login(utilisateur)

            for nom, requis in ECRANS.items():
                with self.subTest(role=code_role, ecran=nom):
                    reponse = self.client.get(reverse(nom))
                    if requis in acquis:
                        self.assertIn(reponse.status_code, (200, 302))
                    else:
                        self.assertEqual(reponse.status_code, 403)

    def test_le_refus_est_explicite_et_nomme_le_droit_manquant(self):
        """Une redirection silencieuse ferait croire à une panne."""
        self.client.force_login(self.comptes[Role.CAISSIER])
        reponse = self.client.get(reverse("comptabilite"))

        self.assertEqual(reponse.status_code, 403)
        self.assertContains(reponse, "n'est pas ouvert à votre rôle", status_code=403)
        self.assertContains(reponse, "Consulter la comptabilité", status_code=403)

    def test_le_rail_ne_propose_pas_un_ecran_refuse(self):
        self.client.force_login(self.comptes[Role.CAISSIER])
        reponse = self.client.get(reverse("caisse"))

        self.assertNotContains(reponse, reverse("comptabilite"))
        self.assertContains(reponse, reverse("ventes"))


class MasquageDesMontantsTest(TestCase):
    """Les écrans autorisés eux-mêmes n'affichent pas tout à tout le monde."""

    @classmethod
    def setUpTestData(cls):
        cls.boutique = fabrique.creer_boutique("Masquage")
        with contexte_boutique(cls.boutique):
            depot = fabrique.creer_depot(cls.boutique)
            cls.variante = fabrique.creer_variante(cls.boutique, sku="MASQ-1", prix="11925")
            entrer_stock(
                depot=depot,
                variante=cls.variante,
                quantite=10,
                cout_unitaire=Decimal("6801"),  # coût reconnaissable dans la page
            )

        cls.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(cls.gerant, cls.boutique, Role.GERANT)
        cls.caissier = fabrique.creer_utilisateur("Caissier")
        rattacher(cls.caissier, cls.boutique, Role.CAISSIER)

    def test_le_cout_moyen_est_absent_de_la_liste_de_stock_pour_un_caissier(self):
        self.client.force_login(self.caissier)
        reponse = self.client.get(reverse("stock"))

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "MASQ-1")
        self.assertNotContains(reponse, "Coût moyen")
        self.assertNotContains(reponse, f"6{ESPACE_FINE}801")

    def test_le_gerant_voit_le_meme_ecran_avec_les_couts(self):
        self.client.force_login(self.gerant)
        reponse = self.client.get(reverse("stock"))

        self.assertContains(reponse, "Coût moyen")
        self.assertContains(reponse, f"6{ESPACE_FINE}801")

    def test_le_cout_est_absent_de_la_fiche_article_pour_un_caissier(self):
        self.client.force_login(self.caissier)
        reponse = self.client.get(reverse("article", args=[self.variante.pk]))

        self.assertEqual(reponse.status_code, 200)
        self.assertNotContains(reponse, "Coût moyen pondéré")
        self.assertNotContains(reponse, f"6{ESPACE_FINE}801")

    def test_la_marge_est_absente_du_tableau_de_bord_d_un_magasinier(self):
        magasinier = fabrique.creer_utilisateur("Magasinier")
        rattacher(magasinier, self.boutique, Role.MAGASINIER)

        self.client.force_login(magasinier)
        reponse = self.client.get(reverse("tableau_de_bord"))

        self.assertEqual(reponse.status_code, 200)
        self.assertNotContains(reponse, "Marge du jour")
        self.assertNotIn("marge_jour", reponse.context)
        self.assertContains(reponse, "Valeur du stock")  # le coût, lui, lui est utile

    def test_la_marge_n_est_meme_pas_calculee_sans_le_droit(self):
        """Le masquage n'est pas un `display:none` : la donnée ne quitte pas le serveur."""
        magasinier = fabrique.creer_utilisateur("Magasinier bis")
        rattacher(magasinier, self.boutique, Role.MAGASINIER)

        self.client.force_login(magasinier)
        contexte = self.client.get(reverse("tableau_de_bord")).context
        self.assertNotIn("ca_jour", contexte)
        self.assertNotIn("marge_jour", contexte)


class PorteJsonTest(TestCase):
    """Les points d'entrée de la caisse refusent en JSON, jamais en redirection."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Json")
        with contexte_boutique(self.boutique):
            self.depot = fabrique.creer_depot(self.boutique)
            self.variante = fabrique.creer_variante(self.boutique, prix="1000")

        self.magasinier = fabrique.creer_utilisateur("Magasinier")
        rattacher(self.magasinier, self.boutique, Role.MAGASINIER)

    def test_un_magasinier_ne_peut_pas_encaisser(self):
        self.client.force_login(self.magasinier)
        reponse = self.client.post(
            reverse("caisse_encaisser"),
            data=json.dumps(
                {"lignes": [{"variante": str(self.variante.pk), "quantite": 1}]}
            ),
            content_type="application/json",
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(reponse.json()["ok"])
        self.assertIn("caisse.encaisser", reponse.json()["droits_manquants"])

    def test_une_session_expiree_repond_401_et_non_une_page_de_connexion(self):
        """La file hors ligne prendrait une redirection HTML pour un succès."""
        reponse = self.client.post(
            reverse("caisse_encaisser"), data="{}", content_type="application/json"
        )
        self.assertEqual(reponse.status_code, 401)
        self.assertEqual(reponse["Content-Type"], "application/json")

    def test_un_caissier_ne_peut_pas_entrer_du_stock(self):
        caissier = fabrique.creer_utilisateur("Caissier")
        rattacher(caissier, self.boutique, Role.CAISSIER)

        self.client.force_login(caissier)
        reponse = self.client.post(
            reverse("entree_stock_json", args=[self.variante.pk]),
            data=json.dumps({"quantite": "5", "cout_unitaire": "800"}),
            content_type="application/json",
        )
        self.assertEqual(reponse.status_code, 403)
        with contexte_boutique(self.boutique):
            self.assertFalse(
                NiveauStock.objects.filter(variante=self.variante, quantite__gt=0).exists()
            )
