"""Filtres, tri, pagination et mégamenu du marché.

Ce que ces tests protègent :

* **chaque filtre filtre** — prix, commerçant, ville, identité vérifiée — et un filtre inconnu ou
  mal formé est ignoré, jamais une erreur ;
* **le tri** suit le prix dans les deux sens ;
* **les facettes** comptent sur la portée « recherche + rayon » : choisir un commerçant ne fait
  pas disparaître les autres ;
* **« Voir plus »** renvoie seulement les cartes de la page suivante ;
* **le mégamenu** nomme chaque rayon, ses commerçants et son illustration ;
* **le stock** n'apparaît nulle part, même filtré.
"""

from decimal import Decimal
from unittest import mock

from django.urls import reverse

from apps.core.tenancy import contexte_boutique
from apps.inventory.services import entrer_stock
from apps.marketplace.models import Boutique
from apps.vitrine.catalogue import PAR_PAGE
from tests import fabrique
from tests.test_vitrine import SocleVitrine


class FiltresTest(SocleVitrine):
    def page(self, **params):
        return self.client.get(reverse("vitrine_catalogue"), params)

    def test_le_prix_borne_les_resultats(self):
        reponse = self.page(prix_max="10000")
        self.assertContains(reponse, self.creme.produit.libelle)
        self.assertNotContains(reponse, self.brouette.produit.libelle)
        reponse = self.page(prix_min="10000")
        self.assertContains(reponse, self.brouette.produit.libelle)
        self.assertNotContains(reponse, self.creme.produit.libelle)

    def test_le_commercant_et_la_ville(self):
        reponse = self.page(boutique=self.bella.slug)
        self.assertContains(reponse, self.creme.produit.libelle)
        self.assertNotContains(reponse, self.brouette.produit.libelle)

        Boutique.objects.filter(pk=self.bella.pk).update(ville="Yaoundé")
        reponse = self.page(ville="Yaoundé")
        self.assertContains(reponse, self.creme.produit.libelle)
        self.assertNotContains(reponse, self.brouette.produit.libelle)

    def test_identite_verifiee_seulement(self):
        reponse = self.page(verifie="1")
        self.assertNotContains(reponse, self.brouette.produit.libelle)
        self.assertContains(reponse, "Aucun article avec ces filtres.")
        self.assertContains(reponse, "Effacer les filtres")

    def test_le_tri_par_prix(self):
        croissant = self.page(tri="prix-croissant").content.decode()
        self.assertLess(croissant.index(self.creme.produit.libelle), croissant.index(self.brouette.produit.libelle))
        decroissant = self.page(tri="prix-decroissant").content.decode()
        self.assertLess(decroissant.index(self.brouette.produit.libelle), decroissant.index(self.creme.produit.libelle))

    def test_un_filtre_mal_forme_est_ignore(self):
        reponse = self.page(prix_min="beaucoup", tri="n-importe-quoi", page="-3", rayon="inconnu")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, self.brouette.produit.libelle)
        self.assertContains(reponse, self.creme.produit.libelle)

    def test_les_facettes_restent_toutes_visibles(self):
        reponse = self.page(boutique=self.bella.slug)
        # La colonne de filtres propose encore Ateba, avec son compte.
        self.assertContains(reponse, f'value="{self.ateba.slug}"')
        self.assertContains(reponse, f'value="{self.bella.slug}" checked')

    def test_une_puce_par_filtre_avec_son_adresse_de_retrait(self):
        reponse = self.page(prix_max="10000", verifie="1")
        self.assertContains(reponse, "Jusqu&#x27;à 10")
        self.assertContains(reponse, "Retirer le filtre Identité vérifiée")
        self.assertContains(reponse, "Tout effacer")

    def test_le_stock_n_apparait_jamais(self):
        reponse = self.page(boutique=self.ateba.slug)
        for mot in ("en stock", "disponibles", "restant"):
            self.assertNotContains(reponse, mot)


class PaginationTest(SocleVitrine):
    def setUp(self):
        super().setUp()
        with contexte_boutique(self.ateba):
            for i in range(PAR_PAGE + 3):
                v = fabrique.creer_variante(self.ateba, prix=str(1000 + i), libelle=f"Clou lot {i:02d}")
                entrer_stock(depot=self.depot_ateba, variante=v, quantite=Decimal("1"), cout_unitaire=Decimal("500"))

    def test_voir_plus_rend_seulement_la_page_suivante(self):
        premiere = self.client.get(reverse("vitrine_catalogue"))
        self.assertContains(premiere, "data-voir-plus")
        suite = self.client.get(reverse("vitrine_catalogue"), {"page": 2}, HTTP_X_FRAGMENT="suite")
        contenu = suite.content.decode()
        self.assertNotIn("<html", contenu)
        self.assertNotIn("data-nombre-resultats", contenu)
        self.assertEqual(contenu.count('data-apparition'), PAR_PAGE + 5 - PAR_PAGE)
        self.assertNotIn("data-suite", contenu, "dernière page : plus de suite")


class MegamenuTest(SocleVitrine):
    def test_chaque_rayon_ses_commercants_et_son_illustration(self):
        reponse = self.client.get(reverse("vitrine_accueil"))
        self.assertContains(reponse, 'id="megamenu"')
        self.assertContains(reponse, 'aria-controls="megamenu"')
        self.assertContains(reponse, self.ateba.rayon_principal.libelle)
        self.assertContains(reponse, reverse("vitrine_boutique", args=[self.ateba.slug]))
        self.assertContains(reponse, "marque/illustrations/rayon-")
        self.assertContains(reponse, 'id="feuille-rayons"')

    def test_le_menu_n_est_pas_calcule_pour_un_fragment(self):
        with mock.patch("apps.vitrine.views.menu_rayons") as menu:
            self.client.get(reverse("vitrine_catalogue"), HTTP_X_FRAGMENT="suite")
            self.client.get(reverse("vitrine_catalogue"), HTTP_X_FRAGMENT="1")
            menu.assert_not_called()
            self.client.get(reverse("vitrine_catalogue"))
            menu.assert_called_once()
