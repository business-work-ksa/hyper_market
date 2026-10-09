"""Les données en base, en français et en anglais (`apps/core/bilingue.py`).

Ce que ces tests protègent :

* **l'anglais s'il existe, le français sinon** : une page anglaise ne montre jamais un nom vide ;
* **le français reste la référence** : la page française ignore les champs anglais ;
* **la recherche trouve un article par son nom anglais** ;
* **le commerçant saisit son nom et sa description en anglais**, sans obligation ;
* **les référentiels livrés** (rayons, offres, rôles, moyens de paiement) ont leur forme anglaise.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from apps.accounts.models import Role
from apps.catalog.models import Categorie, Produit
from apps.core.bilingue import traduit
from apps.core.tenancy import contexte_boutique
from apps.marketplace.models import Rayon, TypeEmplacement
from apps.payments.models import Prestataire
from tests import test_backoffice_gestion
from tests.test_backoffice_gestion import BaseGestionTest
from tests.test_vitrine import SocleVitrine


class TraduitTest(TestCase):
    def test_l_anglais_s_il_existe_sinon_le_francais(self):
        rayon = Rayon(libelle="Quincaillerie", libelle_en="Hardware")
        sans = Rayon(libelle="Électroménager", libelle_en="")
        with translation.override("fr"):
            self.assertEqual(traduit(rayon), "Quincaillerie")
            self.assertEqual(rayon.libelle_affiche, "Quincaillerie")
        with translation.override("en"):
            self.assertEqual(traduit(rayon), "Hardware")
            self.assertEqual(rayon.libelle_affiche, "Hardware")
            self.assertEqual(traduit(sans), "Électroménager")
            self.assertEqual(traduit({"libelle": "Ciment", "libelle_en": "Cement"}), "Cement")
            self.assertEqual(traduit({"libelle": "Ciment"}), "Ciment")
            self.assertEqual(traduit(None), "")


class VitrineBilingueTest(SocleVitrine):
    def setUp(self):
        super().setUp()
        with contexte_boutique(self.ateba):
            Produit.objects.filter(pk=self.brouette.produit_id).update(
                libelle="Brouette galvanisée", libelle_en="Galvanised wheelbarrow",
                description="Cuve de 90 litres.", description_en="90-litre tray.",
            )
        Rayon.objects.filter(pk=self.ateba.rayon_principal_id).update(libelle="Quincaillerie", libelle_en="Hardware")

    def anglais(self):
        self.client.cookies["hm_langue"] = "en"

    def test_la_fiche_article_en_anglais(self):
        url = reverse("vitrine_article", args=[self.brouette.pk])
        francais = self.client.get(url)
        self.assertContains(francais, "Brouette galvanisée")
        self.assertContains(francais, "Cuve de 90 litres.")
        self.assertNotContains(francais, "Galvanised wheelbarrow")
        self.anglais()
        anglais = self.client.get(url)
        self.assertContains(anglais, "Galvanised wheelbarrow")
        self.assertContains(anglais, "90-litre tray.")
        self.assertNotContains(anglais, "Cuve de 90 litres.")

    def test_sans_nom_anglais_le_nom_francais(self):
        self.anglais()
        reponse = self.client.get(reverse("vitrine_article", args=[self.creme.pk]))
        self.assertContains(reponse, self.creme.produit.libelle)

    def test_la_recherche_trouve_le_nom_anglais(self):
        reponse = self.client.get(reverse("vitrine_catalogue"), {"q": "wheelbarrow"})
        self.assertContains(reponse, "Brouette galvanisée")
        self.assertNotContains(reponse, self.creme.produit.libelle)

    def test_rayons_et_categories_en_anglais(self):
        categorie = Categorie.objects.create(
            rayon_id=self.ateba.rayon_principal_id, libelle="Outillage", libelle_en="Tools", slug="outillage"
        )
        with contexte_boutique(self.ateba):
            Produit.objects.filter(pk=self.brouette.produit_id).update(categorie=categorie)
        self.anglais()
        accueil = self.client.get(reverse("vitrine_accueil"))
        self.assertContains(accueil, "Hardware")
        self.assertContains(accueil, "Tools")
        catalogue = self.client.get(reverse("vitrine_catalogue"))
        self.assertContains(catalogue, "Tools")
        self.assertNotContains(catalogue, ">Outillage<")


class ArticleBilingueTest(BaseGestionTest):
    DONNEES = test_backoffice_gestion.NouvelArticleTest.DONNEES

    def test_le_commercant_saisit_l_anglais_et_la_description(self):
        self.client.post(
            reverse("nouvel_article"),
            {**self.DONNEES, "libelle_en": "CIMENCAM cement 50 kg", "description": "Sac de 50 kg.",
             "description_en": "50 kg bag."},
        )
        with contexte_boutique(self.boutique):
            produit = Produit.objects.get(libelle="Ciment CIMENCAM 50 kg")
        self.assertEqual(produit.libelle_en, "CIMENCAM cement 50 kg")
        self.assertEqual(produit.description, "Sac de 50 kg.")
        self.assertEqual(produit.description_en, "50 kg bag.")

    def test_l_anglais_reste_facultatif(self):
        self.client.post(reverse("nouvel_article"), self.DONNEES)
        with contexte_boutique(self.boutique):
            produit = Produit.objects.get(libelle="Ciment CIMENCAM 50 kg")
        self.assertEqual(produit.libelle_en, "")


class ReferentielsBilinguesTest(TestCase):
    def test_les_referentiels_livres_ont_leur_anglais(self):
        call_command("initialiser_referentiels", stdout=StringIO())
        self.assertEqual(Rayon.objects.get(code="quincaillerie").libelle_en, "Hardware & DIY")
        self.assertEqual(TypeEmplacement.objects.get(code=TypeEmplacement.ETAL).libelle_en, "Stall")
        self.assertEqual(Role.objects.get(code=Role.CAISSIER).libelle_en, "Cashier")
        self.assertEqual(
            Prestataire.objects.get(code=Prestataire.PAIEMENT_LIVRAISON).libelle_en, "Cash on delivery"
        )


class PourcentsDansLesScriptsTest(BaseGestionTest):
    """Un texte de script qui porte une variable (`%(n)s`) sort tel quel, dans les deux langues.

    `{{ _("… %(n)s …") }}` affichait « %%(n)s » : Django double le `%` à l'exécution, pas à
    l'extraction, et la traduction n'était jamais trouvée. Ces textes passent par
    `{% translate … as … %}`, qui rétablit le `%`.
    """

    def test_le_compteur_hors_ligne_et_la_caisse(self):
        for langue, attendu in (("fr", "opérations en attente d’envoi"), ("en", "operations waiting to be sent")):
            self.client.cookies["hm_langue"] = langue
            for nom in ("tableau_de_bord", "caisse"):
                with self.subTest(langue=langue, page=nom):
                    contenu = self.client.get(reverse(nom)).content.decode()
                    self.assertNotIn("%%(", contenu)
                    self.assertIn(attendu, contenu)
