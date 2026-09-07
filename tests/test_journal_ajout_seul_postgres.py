"""Le journal comptable résiste au SQL brut, pas seulement à l'ORM.

Les protections Python (`EcritureComptable.save()` / `delete()`) sont contournables par un
script, un client `psql` ou un ORM tiers. Le trigger installé par la migration 0003 est la seule
qui tienne. Ces tests ne s'exécutent que sur PostgreSQL — sur SQLite, ils sont ignorés, ce qui est
aussi un rappel que **SQLite n'est pas un environnement de production acceptable pour ce module**.
"""

from datetime import date
from decimal import Decimal

from django.db import connection, transaction
from django.db.utils import InternalError, ProgrammingError
from django.test import TestCase

from apps.accounting.services import passer_ecriture
from apps.core.tenancy import contexte_boutique
from tests import fabrique


class JournalAjoutSeulPostgresTest(TestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Trigger spécifique à PostgreSQL.")
        self.boutique = fabrique.creer_boutique()
        self.contexte = contexte_boutique(self.boutique)
        self.contexte.__enter__()
        self.addCleanup(self.contexte.__exit__, None, None, None)
        self.ecriture = passer_ecriture(
            boutique_id=self.boutique.pk,
            code_journal="OD",
            date_ecriture=date(date.today().year, 6, 15),
            libelle="Écriture protégée",
            lignes=[
                ("571", Decimal("1000"), Decimal("0")),
                ("701", Decimal("0"), Decimal("1000")),
            ],
        )

    def test_update_sql_brut_rejete(self):
        with self.assertRaises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as curseur:
                curseur.execute(
                    "UPDATE accounting_ecriturecomptable SET libelle = 'falsifiée' WHERE id = %s",
                    [str(self.ecriture.pk)],
                )

    def test_delete_sql_brut_rejete(self):
        with self.assertRaises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as curseur:
                curseur.execute(
                    "DELETE FROM accounting_ecriturecomptable WHERE id = %s",
                    [str(self.ecriture.pk)],
                )

    def test_modification_d_une_ligne_rejetee(self):
        """Falsifier un montant sans toucher à l'en-tête doit être impossible aussi."""
        with self.assertRaises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as curseur:
                curseur.execute(
                    "UPDATE accounting_ligneecriture SET debit = 99999 WHERE ecriture_id = %s",
                    [str(self.ecriture.pk)],
                )

    def test_rattachement_de_contrepassation_reste_possible(self):
        """Dérogation volontaire : `contrepassee_par` est un champ de suivi, pas un montant."""
        from apps.accounting.services import contrepasser

        inverse = contrepasser(self.ecriture, motif="Erreur de saisie")
        self.ecriture.refresh_from_db()
        self.assertEqual(self.ecriture.contrepassee_par_id, inverse.pk)
