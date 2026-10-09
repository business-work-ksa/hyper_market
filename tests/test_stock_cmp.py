"""Tests du moteur de stock et de la valorisation en coût moyen pondéré."""

from decimal import Decimal

from django.test import TestCase

from apps.core.tenancy import contexte_boutique
from apps.inventory.models import Inventaire, LigneInventaire, MouvementStock, NiveauStock
from apps.inventory.services import (
    MouvementInvalide,
    entrer_stock,
    regulariser_inventaire,
    sortir_stock,
    transferer_stock,
    valeur_stock,
)
from tests import fabrique


class CoutMoyenPondereTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique(avec_comptabilite=False)
        self.contexte = contexte_boutique(self.boutique)
        self.contexte.__enter__()
        self.addCleanup(self.contexte.__exit__, None, None, None)
        self.depot = fabrique.creer_depot(self.boutique)
        self.variante = fabrique.creer_variante(self.boutique)

    def _niveau(self) -> NiveauStock:
        return NiveauStock.objects.get(depot=self.depot, variante=self.variante)

    def test_premiere_entree_fixe_le_cmp(self):
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("1000")
        )
        niveau = self._niveau()
        self.assertEqual(niveau.quantite, Decimal("10.0000"))
        self.assertEqual(niveau.cmp, Decimal("1000.0000"))

    def test_seconde_entree_pondere_le_cmp(self):
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("1000")
        )
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("2000")
        )
        # (10 × 1000 + 10 × 2000) / 20 = 1500
        self.assertEqual(self._niveau().cmp, Decimal("1500.0000"))

    def test_ponderation_asymetrique(self):
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=30, cout_unitaire=Decimal("1000")
        )
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("2000")
        )
        # (30 × 1000 + 10 × 2000) / 40 = 1250
        self.assertEqual(self._niveau().cmp, Decimal("1250.0000"))

    def test_sortie_ne_modifie_pas_le_cmp(self):
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("1500")
        )
        sortir_stock(depot=self.depot, variante=self.variante, quantite=4)
        niveau = self._niveau()
        self.assertEqual(niveau.quantite, Decimal("6.0000"))
        self.assertEqual(niveau.cmp, Decimal("1500.0000"))

    def test_sortie_valorisee_au_cmp_courant(self):
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("1000")
        )
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("2000")
        )
        mouvement = sortir_stock(depot=self.depot, variante=self.variante, quantite=5)
        self.assertEqual(mouvement.cout_unitaire, Decimal("1500.0000"))

    def test_cmp_historise_sur_chaque_mouvement(self):
        """Le CMP ne pourra jamais être recalculé a posteriori : il est figé ligne à ligne."""
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("1000")
        )
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("3000")
        )
        historique = list(
            MouvementStock.objects.filter(variante=self.variante).order_by("cree_le")
        )
        self.assertEqual(historique[0].cmp_apres, Decimal("1000.0000"))
        self.assertEqual(historique[1].cmp_apres, Decimal("2000.0000"))

    def test_stock_negatif_autorise_et_signale(self):
        """ADR-005 : refuser une vente déjà encaissée serait pire qu'un compteur faux."""
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=2, cout_unitaire=Decimal("1000")
        )
        sortir_stock(depot=self.depot, variante=self.variante, quantite=5)
        niveau = self._niveau()
        self.assertEqual(niveau.quantite, Decimal("-3.0000"))
        self.assertTrue(niveau.en_anomalie)

    def test_entree_apres_stock_negatif_repart_du_cout_reel(self):
        """Pondérer par une quantité négative produirait un CMP aberrant."""
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=2, cout_unitaire=Decimal("1000")
        )
        sortir_stock(depot=self.depot, variante=self.variante, quantite=5)
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("1800")
        )
        self.assertEqual(self._niveau().cmp, Decimal("1800.0000"))

    def test_mouvement_immuable(self):
        mouvement = entrer_stock(
            depot=self.depot, variante=self.variante, quantite=5, cout_unitaire=Decimal("1000")
        )
        mouvement.quantite = Decimal("999")
        with self.assertRaises(ValueError):
            mouvement.save()
        with self.assertRaises(ValueError):
            mouvement.delete()

    def test_quantite_nulle_refusee(self):
        with self.assertRaises(MouvementInvalide):
            entrer_stock(
                depot=self.depot, variante=self.variante, quantite=0, cout_unitaire=Decimal("100")
            )

    def test_idempotence_de_la_synchronisation_hors_ligne(self):
        """Une opération hors ligne retransmise ne doit pas dédoubler le mouvement."""
        import uuid

        operation = uuid.uuid4()
        premier = entrer_stock(
            depot=self.depot,
            variante=self.variante,
            quantite=5,
            cout_unitaire=Decimal("1000"),
            operation_id=operation,
        )
        second = entrer_stock(
            depot=self.depot,
            variante=self.variante,
            quantite=5,
            cout_unitaire=Decimal("1000"),
            operation_id=operation,
        )
        self.assertEqual(premier.pk, second.pk)
        self.assertEqual(self._niveau().quantite, Decimal("5.0000"))

    def test_valeur_du_stock(self):
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("1250")
        )
        self.assertEqual(valeur_stock(depot=self.depot), Decimal("12500.00"))


class TransfertTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique(avec_comptabilite=False)
        self.contexte = contexte_boutique(self.boutique)
        self.contexte.__enter__()
        self.addCleanup(self.contexte.__exit__, None, None, None)
        self.magasin = fabrique.creer_depot(self.boutique, "Magasin")
        self.reserve = fabrique.creer_depot(self.boutique, "Réserve")
        self.variante = fabrique.creer_variante(self.boutique)

    def test_transfert_conserve_la_valeur(self):
        entrer_stock(
            depot=self.magasin, variante=self.variante, quantite=10, cout_unitaire=Decimal("1500")
        )
        transferer_stock(
            depot_source=self.magasin,
            depot_cible=self.reserve,
            variante=self.variante,
            quantite=4,
        )
        source = NiveauStock.objects.get(depot=self.magasin, variante=self.variante)
        cible = NiveauStock.objects.get(depot=self.reserve, variante=self.variante)
        self.assertEqual(source.quantite, Decimal("6.0000"))
        self.assertEqual(cible.quantite, Decimal("4.0000"))
        self.assertEqual(cible.cmp, Decimal("1500.0000"))
        self.assertEqual(valeur_stock(), Decimal("15000.00"))

    def test_transfert_hors_boutique_refuse(self):
        autre = fabrique.creer_boutique(avec_comptabilite=False)
        depot_etranger = fabrique.creer_depot(autre)
        with self.assertRaises(MouvementInvalide):
            transferer_stock(
                depot_source=self.magasin,
                depot_cible=depot_etranger,
                variante=self.variante,
                quantite=1,
            )


class InventaireTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique(avec_comptabilite=False)
        self.contexte = contexte_boutique(self.boutique)
        self.contexte.__enter__()
        self.addCleanup(self.contexte.__exit__, None, None, None)
        self.depot = fabrique.creer_depot(self.boutique)
        self.variante = fabrique.creer_variante(self.boutique)

    def test_regularisation_ecrit_un_ajustement(self):
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("1000")
        )
        inventaire = Inventaire.objects.create(boutique=self.boutique, depot=self.depot)
        LigneInventaire.objects.create(
            boutique=self.boutique,
            inventaire=inventaire,
            variante=self.variante,
            qte_theorique=Decimal("10"),
            qte_comptee=Decimal("7"),
            motif="Casse non déclarée",
        )

        mouvements = regulariser_inventaire(inventaire)

        self.assertEqual(len(mouvements), 1)
        self.assertEqual(mouvements[0].type, MouvementStock.AJUSTEMENT)
        self.assertEqual(mouvements[0].quantite, Decimal("-3.0000"))
        niveau = NiveauStock.objects.get(depot=self.depot, variante=self.variante)
        self.assertEqual(niveau.quantite, Decimal("7.0000"))
        self.assertEqual(niveau.cmp, Decimal("1000.0000"))

    def test_inventaire_sans_ecart_n_ecrit_rien(self):
        entrer_stock(
            depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("1000")
        )
        inventaire = Inventaire.objects.create(boutique=self.boutique, depot=self.depot)
        LigneInventaire.objects.create(
            boutique=self.boutique,
            inventaire=inventaire,
            variante=self.variante,
            qte_theorique=Decimal("10"),
            qte_comptee=Decimal("10"),
        )
        self.assertEqual(regulariser_inventaire(inventaire), [])
