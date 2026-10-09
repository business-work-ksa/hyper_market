"""Tests du noyau comptable : équilibre, immuabilité, contre-passation, chaîne caisse → écritures."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounting.models import EcritureComptable, LigneEcriture
from apps.accounting.services import (
    EcritureInvalide,
    balance,
    contrepasser,
    passer_ecriture,
    solde_compte,
)
from apps.core.tenancy import contexte_boutique
from apps.inventory.services import entrer_stock
from apps.pos import services as caisse
from tests import fabrique


class EcritureTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique()
        self.contexte = contexte_boutique(self.boutique)
        self.contexte.__enter__()
        self.addCleanup(self.contexte.__exit__, None, None, None)
        self.aujourdhui = date(date.today().year, 6, 15)

    def _ecriture_simple(self, montant="1000"):
        return passer_ecriture(
            boutique_id=self.boutique.pk,
            code_journal="OD",
            date_ecriture=self.aujourdhui,
            libelle="Écriture de test",
            lignes=[
                ("571", Decimal(montant), Decimal("0")),
                ("701", Decimal("0"), Decimal(montant)),
            ],
        )

    def test_ecriture_equilibree_acceptee(self):
        ecriture = self._ecriture_simple()
        self.assertTrue(ecriture.equilibree)
        self.assertTrue(ecriture.validee)
        self.assertEqual(ecriture.total_debit, Decimal("1000"))

    def test_ecriture_desequilibree_refusee(self):
        with self.assertRaises(EcritureInvalide):
            passer_ecriture(
                boutique_id=self.boutique.pk,
                code_journal="OD",
                date_ecriture=self.aujourdhui,
                libelle="Déséquilibrée",
                lignes=[
                    ("571", Decimal("1000"), Decimal("0")),
                    ("701", Decimal("0"), Decimal("900")),
                ],
            )
        self.assertEqual(EcritureComptable.objects.count(), 0)

    def test_ecriture_vide_refusee(self):
        with self.assertRaises(EcritureInvalide):
            passer_ecriture(
                boutique_id=self.boutique.pk,
                code_journal="OD",
                date_ecriture=self.aujourdhui,
                libelle="Vide",
                lignes=[],
            )

    def test_compte_inexistant_refuse(self):
        with self.assertRaises(EcritureInvalide):
            passer_ecriture(
                boutique_id=self.boutique.pk,
                code_journal="OD",
                date_ecriture=self.aujourdhui,
                libelle="Compte fantôme",
                lignes=[
                    ("999999", Decimal("100"), Decimal("0")),
                    ("701", Decimal("0"), Decimal("100")),
                ],
            )

    def test_ecriture_validee_immuable(self):
        """ADR-003 : on ne corrige que par contre-passation."""
        ecriture = self._ecriture_simple()
        ecriture.libelle = "Tentative de modification"
        with self.assertRaises(ValueError):
            ecriture.save()
        with self.assertRaises(ValueError):
            ecriture.delete()

    def test_contrepassation_annule_les_soldes(self):
        ecriture = self._ecriture_simple("2500")
        self.assertEqual(solde_compte("571", boutique_id=self.boutique.pk), Decimal("2500.00"))

        contrepasser(ecriture, date_ecriture=self.aujourdhui, motif="Erreur de saisie")

        self.assertEqual(solde_compte("571", boutique_id=self.boutique.pk), Decimal("0.00"))
        ecriture.refresh_from_db()
        self.assertIsNotNone(ecriture.contrepassee_par_id)
        # L'écriture d'origine reste au journal : elle n'est pas effacée, elle est neutralisée.
        self.assertEqual(EcritureComptable.objects.count(), 2)

    def test_double_contrepassation_refusee(self):
        ecriture = self._ecriture_simple()
        contrepasser(ecriture)
        ecriture.refresh_from_db()
        with self.assertRaises(EcritureInvalide):
            contrepasser(ecriture)

    def test_sequence_des_pieces_continue(self):
        pieces = [self._ecriture_simple().piece for _ in range(3)]
        self.assertEqual(pieces, ["OD-000001", "OD-000002", "OD-000003"])

    def test_ligne_a_debit_ou_credit_exclusivement(self):
        from django.db.utils import IntegrityError

        ecriture = passer_ecriture(
            boutique_id=self.boutique.pk,
            code_journal="OD",
            date_ecriture=self.aujourdhui,
            libelle="Base",
            lignes=[("571", Decimal("10"), Decimal("0")), ("701", Decimal("0"), Decimal("10"))],
            valider=False,
        )
        with self.assertRaises(IntegrityError):
            LigneEcriture.objects_all_tenants.create(
                boutique=self.boutique,
                ecriture=ecriture,
                compte=ecriture.lignes.first().compte,
                debit=Decimal("5"),
                credit=Decimal("5"),
            )


class ChaineCaisseComptabiliteTest(TestCase):
    """La promesse « zéro double saisie » : une vente au comptoir produit tout le reste."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique()
        self.contexte = contexte_boutique(self.boutique)
        self.contexte.__enter__()
        self.addCleanup(self.contexte.__exit__, None, None, None)
        self.caissier = fabrique.creer_utilisateur("Caissier")
        self.depot = fabrique.creer_depot(self.boutique)
        # Prix TTC 11 925 F → 10 000 F HT + 1 925 F de TVA à 19,25 %.
        self.variante = fabrique.creer_variante(self.boutique, prix="11925")
        entrer_stock(
            depot=self.depot,
            variante=self.variante,
            quantite=Decimal("10"),
            cout_unitaire=Decimal("6800"),
        )

    def _vendre(self, quantite=Decimal("1")):
        session = caisse.ouvrir_session(depot=self.depot, caissier=self.caissier)
        ticket = caisse.creer_ticket(session=session)
        caisse.ajouter_ligne(ticket=ticket, variante=self.variante, quantite=quantite)
        ticket.refresh_from_db()
        caisse.regler(ticket=ticket, moyen="especes", montant=ticket.total_ttc)
        return caisse.cloturer_ticket(ticket, cree_par=self.caissier)

    def test_totaux_du_ticket(self):
        ticket = self._vendre()
        self.assertEqual(ticket.total_ttc, Decimal("11925.00"))
        self.assertEqual(ticket.total_ht, Decimal("10000.00"))
        self.assertEqual(ticket.total_tva, Decimal("1925.00"))

    def test_la_vente_sort_le_stock(self):
        from apps.inventory.models import NiveauStock

        self._vendre(Decimal("3"))
        niveau = NiveauStock.objects.get(depot=self.depot, variante=self.variante)
        self.assertEqual(niveau.quantite, Decimal("7.0000"))

    def test_la_vente_genere_les_ecritures(self):
        """Trois écritures : vente + TVA, encaissement, sortie de stock (docs/07, §3.1)."""
        ticket = self._vendre()

        ecritures = EcritureComptable.objects.filter(
            origine_type="pos.Ticket", origine_id=ticket.pk
        )
        self.assertEqual(ecritures.count(), 3)

        b = self.boutique.pk
        self.assertEqual(solde_compte("701", boutique_id=b), Decimal("-10000.00"))  # produit
        self.assertEqual(solde_compte("4431", boutique_id=b), Decimal("-1925.00"))  # TVA collectée
        self.assertEqual(solde_compte("571", boutique_id=b), Decimal("11925.00"))  # caisse
        self.assertEqual(solde_compte("411", boutique_id=b), Decimal("0.00"))  # client soldé
        self.assertEqual(solde_compte("6031", boutique_id=b), Decimal("6800.00"))  # coût sorti
        self.assertEqual(solde_compte("311", boutique_id=b), Decimal("-6800.00"))  # stock

    def test_la_balance_est_equilibree(self):
        self._vendre(Decimal("2"))
        lignes = balance(boutique_id=self.boutique.pk)
        total_debit = sum(l["debit"] for l in lignes)
        total_credit = sum(l["credit"] for l in lignes)
        self.assertEqual(total_debit, total_credit)

    def test_marge_brute_calculable(self):
        """L'information que le commerçant n'a jamais eue : sa marge réelle."""
        self._vendre()
        b = self.boutique.pk
        chiffre_affaires = -solde_compte("701", boutique_id=b)
        cout_ventes = solde_compte("6031", boutique_id=b)
        self.assertEqual(chiffre_affaires - cout_ventes, Decimal("3200.00"))

    def test_cloture_idempotente(self):
        session = caisse.ouvrir_session(depot=self.depot, caissier=self.caissier)
        ticket = caisse.creer_ticket(session=session)
        caisse.ajouter_ligne(ticket=ticket, variante=self.variante, quantite=Decimal("1"))
        ticket.refresh_from_db()
        caisse.regler(ticket=ticket, moyen="especes", montant=ticket.total_ttc)

        caisse.cloturer_ticket(ticket)
        caisse.cloturer_ticket(ticket)  # retransmission hors ligne

        self.assertEqual(
            EcritureComptable.objects.filter(origine_id=ticket.pk).count(), 3
        )

    def test_reglement_incomplet_refuse(self):
        session = caisse.ouvrir_session(depot=self.depot, caissier=self.caissier)
        ticket = caisse.creer_ticket(session=session)
        caisse.ajouter_ligne(ticket=ticket, variante=self.variante, quantite=Decimal("1"))
        ticket.refresh_from_db()
        caisse.regler(ticket=ticket, moyen="especes", montant=Decimal("5000"))
        with self.assertRaises(caisse.TicketInvalide):
            caisse.cloturer_ticket(ticket)

    def test_ecart_de_caisse(self):
        ticket = self._vendre()
        session = ticket.session
        session.refresh_from_db()
        caisse.fermer_session(session, fonds_compte=session.fonds_theorique - Decimal("500"))
        session.refresh_from_db()
        self.assertEqual(session.ecart, Decimal("-500.00"))
