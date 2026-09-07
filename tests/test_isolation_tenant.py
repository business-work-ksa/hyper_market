"""Tests d'isolation multi-tenant.

**Critère de sortie bloquant du lot 0** (docs/11, §3 et jalon G1) : aucun accès croisé entre
boutiques ne doit être possible. Une seule fuite dans un module comptable et le produit est mort
commercialement.
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounting.models import EcritureComptable
from apps.catalog.models import Produit, Variante
from apps.core.tenancy import contexte_boutique, contexte_plateforme
from apps.inventory.models import MouvementStock, NiveauStock
from apps.inventory.services import entrer_stock
from tests import fabrique


class IsolationTenantTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boutique_a = fabrique.creer_boutique("Alpha")
        cls.boutique_b = fabrique.creer_boutique("Beta")

        with contexte_boutique(cls.boutique_a):
            cls.variante_a = fabrique.creer_variante(cls.boutique_a, sku="A-001")
            cls.depot_a = fabrique.creer_depot(cls.boutique_a)
            entrer_stock(
                depot=cls.depot_a,
                variante=cls.variante_a,
                quantite=Decimal("10"),
                cout_unitaire=Decimal("1000"),
            )

        with contexte_boutique(cls.boutique_b):
            cls.variante_b = fabrique.creer_variante(cls.boutique_b, sku="B-001")
            cls.depot_b = fabrique.creer_depot(cls.boutique_b)
            entrer_stock(
                depot=cls.depot_b,
                variante=cls.variante_b,
                quantite=Decimal("5"),
                cout_unitaire=Decimal("2000"),
            )

    def test_lecture_bornee_a_la_boutique_courante(self):
        with contexte_boutique(self.boutique_a):
            self.assertEqual(list(Variante.objects.values_list("sku", flat=True)), ["A-001"])
            self.assertEqual(Produit.objects.count(), 1)
            self.assertEqual(NiveauStock.objects.count(), 1)

        with contexte_boutique(self.boutique_b):
            self.assertEqual(list(Variante.objects.values_list("sku", flat=True)), ["B-001"])

    def test_objet_d_une_autre_boutique_introuvable(self):
        with contexte_boutique(self.boutique_a):
            self.assertFalse(Variante.objects.filter(pk=self.variante_b.pk).exists())
            with self.assertRaises(Variante.DoesNotExist):
                Variante.objects.get(pk=self.variante_b.pk)

    def test_agregats_ne_franchissent_pas_la_frontiere(self):
        """Un compteur ou une somme est une fuite d'information autant qu'une liste."""
        with contexte_boutique(self.boutique_a):
            self.assertEqual(MouvementStock.objects.count(), 1)
            total = sum(n.quantite for n in NiveauStock.objects.all())
            self.assertEqual(total, Decimal("10"))

    def test_absence_de_contexte_ne_renvoie_rien(self):
        """Un oubli de contexte produit une absence de données, jamais une fuite."""
        self.assertEqual(Variante.objects.count(), 0)
        self.assertEqual(NiveauStock.objects.count(), 0)
        self.assertEqual(EcritureComptable.objects.count(), 0)

    def test_contexte_plateforme_leve_le_filtrage(self):
        with contexte_plateforme():
            self.assertEqual(Variante.objects.count(), 2)

    def test_gestionnaire_non_filtre_reste_disponible(self):
        self.assertEqual(Variante.objects_all_tenants.count(), 2)

    def test_le_contexte_est_restaure_apres_le_bloc(self):
        with contexte_boutique(self.boutique_a):
            with contexte_boutique(self.boutique_b):
                self.assertEqual(Variante.objects.get().sku, "B-001")
            self.assertEqual(Variante.objects.get().sku, "A-001")

    def test_ecriture_comptable_isolee(self):
        """Le module le plus sensible : une fuite y est commercialement fatale."""
        from apps.accounting.services import passer_ecriture

        passer_ecriture(
            boutique_id=self.boutique_a.pk,
            code_journal="OD",
            date_ecriture="2026-06-15",
            libelle="Test A",
            lignes=[("571", Decimal("1000"), Decimal("0")), ("701", Decimal("0"), Decimal("1000"))],
        )

        with contexte_boutique(self.boutique_b):
            self.assertEqual(EcritureComptable.objects.count(), 0)
        with contexte_boutique(self.boutique_a):
            self.assertEqual(EcritureComptable.objects.count(), 1)
