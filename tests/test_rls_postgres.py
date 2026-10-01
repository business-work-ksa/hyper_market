"""Barrière 3 : la base refuse ce que le code aurait pu laisser passer.

Les barrières 1 et 2 protègent le code qui les respecte. Celle-ci protège de
tout le reste : une requête brute, un script d'exploitation, un
`objects_all_tenants` mal filtré. Ces tests l'attaquent donc **par en dessous**,
en SQL, là où l'ORM ne peut plus rien filtrer.

Sur SQLite ils sont ignorés — ce qui est aussi un rappel que SQLite n'offre
aucune isolation au niveau ligne, et n'est donc jamais un environnement de
production acceptable.

Un seul test s'exécute partout : celui qui vérifie que la liste des tables
protégées couvre bien tous les modèles scopés. C'est le garde-fou contre le
modèle ajouté un jour sans migration de protection — le défaut le plus probable
et le plus silencieux de tout ce dispositif.
"""

from decimal import Decimal

from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.test import TestCase

from apps.accounting.models import EcritureComptable
from apps.catalog.models import Variante
from apps.core.rls import (
    NOM_REGLAGE,
    TABLES_SCOPEES,
    VALEUR_PLATEFORME,
    etat_des_tables,
    role_contourne_la_securite,
    tables_des_modeles_scopes,
)
from apps.core.tenancy import contexte_boutique, contexte_plateforme
from apps.inventory.services import entrer_stock
from tests import fabrique


class CouvertureDesTablesTest(TestCase):
    """S'exécute partout : c'est un contrôle de cohérence, pas de comportement."""

    def test_toutes_les_tables_scopees_sont_declarees(self):
        """Un modèle scopé ajouté sans migration de protection est une fuite en attente."""
        self.assertEqual(
            sorted(TABLES_SCOPEES),
            tables_des_modeles_scopes(),
            "Un modèle scopé n'est pas couvert par la politique RLS : "
            "ajoutez sa table à `TABLES_SCOPEES` et écrivez la migration.",
        )


class SocleRlsTest(TestCase):
    """Ce que le catalogue PostgreSQL dit réellement de nos tables."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Sécurité au niveau ligne spécifique à PostgreSQL.")

    def test_chaque_table_scopee_est_protegee(self):
        etat = etat_des_tables(connection)
        for table in TABLES_SCOPEES:
            with self.subTest(table=table):
                self.assertIn(table, etat)
                self.assertTrue(etat[table]["activee"], "RLS désactivée")
                self.assertTrue(etat[table]["politique"], "politique absente")

    def test_le_role_applicatif_ne_contourne_pas_la_securite(self):
        """Le piège le plus coûteux du dispositif, et le plus silencieux.

        Un rôle `SUPERUSER` ou `BYPASSRLS` ignore toutes les politiques sans
        lever la moindre erreur. Les tests d'isolation passent alors
        triomphalement — en ne prouvant rien du tout. C'est exactement ce qui
        s'est produit ici au premier essai.
        """
        self.assertFalse(
            role_contourne_la_securite(connection),
            "Le rôle de connexion est SUPERUSER ou BYPASSRLS : la barrière 3 est décorative. "
            "ALTER ROLE <role> NOSUPERUSER NOBYPASSRLS;",
        )

    def test_le_proprietaire_ne_contourne_pas_la_politique(self):
        """Sans FORCE, le rôle applicatif — propriétaire des tables — voit tout.

        C'est l'erreur classique : la politique existe, elle est correcte, et
        elle ne s'applique à personne.
        """
        etat = etat_des_tables(connection)
        for table in TABLES_SCOPEES:
            with self.subTest(table=table):
                self.assertTrue(etat[table]["forcee"], "FORCE ROW LEVEL SECURITY manquant")


class IsolationEnSqlBrutTest(TestCase):
    """L'attaque que les barrières Python ne peuvent pas parer."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Sécurité au niveau ligne spécifique à PostgreSQL.")

        self.boutique_a = fabrique.creer_boutique("Alpha")
        self.boutique_b = fabrique.creer_boutique("Beta")

        with contexte_boutique(self.boutique_a):
            self.variante_a = fabrique.creer_variante(self.boutique_a, sku="RLS-A")
            depot_a = fabrique.creer_depot(self.boutique_a)
            entrer_stock(
                depot=depot_a, variante=self.variante_a, quantite=5, cout_unitaire=Decimal("100")
            )
        with contexte_boutique(self.boutique_b):
            self.variante_b = fabrique.creer_variante(self.boutique_b, sku="RLS-B")

    def _compter_en_sql(self, reglage) -> int:
        """Compte les variantes en SQL brut, sous un réglage de session donné."""
        with connection.cursor() as curseur:
            curseur.execute("SELECT set_config(%s, %s, true)", [NOM_REGLAGE, reglage])
            curseur.execute("SELECT count(*) FROM catalog_variante")
            return curseur.fetchone()[0]

    def test_le_sql_brut_ne_voit_que_la_boutique_du_reglage(self):
        with transaction.atomic():
            self.assertEqual(self._compter_en_sql(str(self.boutique_a.pk)), 1)
        with transaction.atomic():
            self.assertEqual(self._compter_en_sql(str(self.boutique_b.pk)), 1)

    def test_sans_reglage_le_sql_brut_ne_voit_rien(self):
        """Fermer par défaut : un oubli produit une absence, jamais une fuite."""
        with transaction.atomic():
            self.assertEqual(self._compter_en_sql(""), 0)

    def test_le_reglage_plateforme_ouvre_l_acces_transverse(self):
        with transaction.atomic():
            self.assertEqual(self._compter_en_sql(VALEUR_PLATEFORME), 2)

    def test_une_ecriture_chez_le_voisin_ne_touche_aucune_ligne(self):
        """Une ligne invisible n'est pas modifiable : elle n'existe simplement pas.

        La clause `USING` filtre avant que `WITH CHECK` n'ait son mot à dire.
        L'`UPDATE` ne lève donc aucune erreur — il ne trouve rien. C'est le
        comportement voulu : discret, et sans effet.
        """
        with transaction.atomic(), connection.cursor() as curseur:
            curseur.execute(
                "SELECT set_config(%s, %s, true)", [NOM_REGLAGE, str(self.boutique_a.pk)]
            )
            curseur.execute(
                "UPDATE catalog_variante SET sku = 'VOLE' WHERE id = %s",
                [str(self.variante_b.pk)],
            )
            self.assertEqual(curseur.rowcount, 0)

        with contexte_boutique(self.boutique_b):
            self.variante_b.refresh_from_db()
        self.assertEqual(self.variante_b.sku, "RLS-B")

    def test_une_insertion_chez_le_voisin_est_rejetee(self):
        """`WITH CHECK` : on ne peut pas déposer une ligne dans une autre boutique.

        C'est la protection la plus utile en pratique. Elle a immédiatement
        attrapé un test qui créait un dépôt pour une seconde boutique sans
        changer de contexte — une préparation fausse depuis toujours, invisible
        tant que la base ne disait rien.
        """
        with self.assertRaises(ProgrammingError):
            with transaction.atomic(), contexte_boutique(self.boutique_a):
                fabrique.creer_depot_sans_contexte(self.boutique_b, "Chez le voisin")

    def test_un_deplacement_de_ligne_vers_une_autre_boutique_est_rejete(self):
        """Réétiqueter une ligne au nom d'une autre boutique reste impossible."""
        with self.assertRaises(ProgrammingError):
            with transaction.atomic(), connection.cursor() as curseur:
                curseur.execute(
                    "SELECT set_config(%s, %s, true)", [NOM_REGLAGE, str(self.boutique_a.pk)]
                )
                curseur.execute(
                    "UPDATE catalog_variante SET boutique_id = %s WHERE id = %s",
                    [str(self.boutique_b.pk), str(self.variante_a.pk)],
                )


class ConsequencesSurLOrmTest(TestCase):
    """Ce que la barrière 3 change pour le code Python qui croyait pouvoir s'en passer."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Sécurité au niveau ligne spécifique à PostgreSQL.")

        self.boutique = fabrique.creer_boutique("Gamma")
        with contexte_boutique(self.boutique):
            fabrique.creer_variante(self.boutique, sku="ORM-1")

    def test_objects_all_tenants_ne_contourne_plus_la_base(self):
        """Le gestionnaire non filtré contourne le filtre Python, jamais la politique SQL.

        C'est le changement de sens le plus important de cette barrière : un
        service de confiance doit désormais *annoncer* la boutique qu'il
        manipule, et pas seulement la connaître.
        """
        self.assertEqual(Variante.objects_all_tenants.count(), 0)

        with contexte_boutique(self.boutique):
            self.assertEqual(Variante.objects_all_tenants.count(), 1)
        with contexte_plateforme():
            self.assertEqual(Variante.objects_all_tenants.count(), 1)

    def test_le_contexte_descend_reellement_jusqu_a_la_connexion(self):
        def reglage_courant():
            with connection.cursor() as curseur:
                curseur.execute("SELECT current_setting(%s, true)", [NOM_REGLAGE])
                return curseur.fetchone()[0]

        with contexte_boutique(self.boutique):
            self.assertEqual(reglage_courant(), str(self.boutique.pk))
        self.assertIn(reglage_courant(), ("", None))

        with contexte_plateforme():
            self.assertEqual(reglage_courant(), VALEUR_PLATEFORME)

    def test_les_contextes_imbriques_se_restaurent_en_base(self):
        autre = fabrique.creer_boutique("Delta")

        def reglage_courant():
            with connection.cursor() as curseur:
                curseur.execute("SELECT current_setting(%s, true)", [NOM_REGLAGE])
                return curseur.fetchone()[0]

        with contexte_boutique(self.boutique):
            with contexte_boutique(autre):
                self.assertEqual(reglage_courant(), str(autre.pk))
            self.assertEqual(reglage_courant(), str(self.boutique.pk))

    def test_les_services_annoncent_leur_boutique(self):
        """`passer_ecriture` doit fonctionner hors de tout contexte ambiant."""
        from apps.accounting.services import passer_ecriture

        ecriture = passer_ecriture(
            boutique_id=self.boutique.pk,
            code_journal="OD",
            date_ecriture=fabrique_date(),
            libelle="Écriture sans contexte ambiant",
            lignes=[("571", Decimal("500"), Decimal("0")), ("701", Decimal("0"), Decimal("500"))],
        )
        with contexte_boutique(self.boutique):
            self.assertEqual(EcritureComptable.objects.filter(pk=ecriture.pk).count(), 1)


def fabrique_date():
    from datetime import date

    return date(date.today().year, 6, 15)
