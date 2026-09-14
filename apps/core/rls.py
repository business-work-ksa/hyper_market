"""Barrière 3 du multi-tenant : sécurité au niveau ligne (Row Level Security).

Les deux premières barrières vivent dans Python : le contexte de requête
(`ContextVar`) et le gestionnaire par défaut filtrant. Elles protègent le code
qui les respecte. Celle-ci vit dans PostgreSQL, et protège de tout le reste : un
`objects_all_tenants` mal filtré, une requête brute, un script d'exploitation,
un client `psql`, un ORM tiers.

C'est la seule barrière qui tienne face à une erreur de code.

Comment elle fonctionne
-----------------------

Chaque table scopée porte une politique qui compare `boutique_id` à un réglage
de session PostgreSQL, `hypermarche.boutique_id` :

* réglage égal à l'identifiant d'une boutique → seules ses lignes sont visibles,
  et une écriture vers une autre boutique est **rejetée** (`WITH CHECK`) ;
* réglage égal à ``plateforme`` → accès transverse assumé, journalisé par
  l'appelant (`contexte_plateforme()`) ;
* réglage absent ou vide → **rien n'est visible**. C'est exactement le choix
  déjà fait à la barrière 2 : un oubli de contexte produit une absence de
  données, jamais une fuite.

`FORCE ROW LEVEL SECURITY` est indispensable : sans lui, le propriétaire des
tables — c'est-à-dire le rôle applicatif — contourne silencieusement toutes les
politiques, et la barrière ne protège personne.

Ce que cela change pour le code appelant
----------------------------------------

`objects_all_tenants` ne contourne plus que le **gestionnaire**, jamais la base.
Un service de confiance qui manipule une boutique doit donc l'annoncer :

    with contexte_boutique(boutique_id):
        Journal.objects_all_tenants.get_or_create(...)

C'est une contrainte, et c'est le but : le tenant manipulé devient explicite
partout, y compris dans le code qui croyait pouvoir s'en passer.
"""

NOM_REGLAGE = "hypermarche.boutique_id"
VALEUR_PLATEFORME = "plateforme"
NOM_POLITIQUE = "hm_isolation_boutique"

# Tables scopées, à jour. La liste est figée en code volontairement — une
# migration est un instantané, pas une introspection — et chaque nouvelle table
# scopée demande donc deux gestes : l'ajouter ici, et écrire la migration qui
# installe sa politique. Le garde-fou contre l'oubli est un test
# (`tests/test_rls_postgres.py`), qui compare cette liste aux modèles réels, et
# `make securite`, qui compare la liste à l'état réel de la base.
TABLES_SCOPEES = [
    "catalog_produit",
    "catalog_variante",
    "catalog_mediaproduit",
    "catalog_recette",
    "catalog_lignerecette",
    "catalog_compatibilitevehicule",
    "inventory_depot",
    "inventory_niveaustock",
    "inventory_mouvementstock",
    "inventory_inventaire",
    "inventory_ligneinventaire",
    "inventory_fournisseur",
    "inventory_lotstock",
    "inventory_numeroserie",
    "inventory_passageatelier",
    "marketplace_identitevisuelle",
    "marketplace_lienmarketing",
    "pos_sessioncaisse",
    "pos_ticket",
    "pos_ligneticket",
    "pos_reglementticket",
    "orders_souscommande",
    "orders_lignecommande",
    "orders_retour",
    "payments_portefeuillemarchand",
    "payments_mouvementportefeuille",
    "accounting_compteboutique",
    "accounting_exercice",
    "accounting_journal",
    "accounting_ecriturecomptable",
    "accounting_ligneecriture",
    "accounting_declarationtva",
]

_CONDITION = (
    "boutique_id::text = current_setting('{reglage}', true) "
    "OR current_setting('{reglage}', true) = '{plateforme}'"
).format(reglage=NOM_REGLAGE, plateforme=VALEUR_PLATEFORME)


def sql_activation(table: str) -> str:
    """DDL d'activation de la politique sur une table."""
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
-- Sans FORCE, le propriétaire des tables — le rôle applicatif — contourne
-- toutes les politiques et la barrière ne protège personne.
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {NOM_POLITIQUE} ON {table};
CREATE POLICY {NOM_POLITIQUE} ON {table}
    USING ({_CONDITION})
    WITH CHECK ({_CONDITION});
"""


def sql_desactivation(table: str) -> str:
    return f"""
DROP POLICY IF EXISTS {NOM_POLITIQUE} ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""


def tables_des_modeles_scopes() -> list[str]:
    """Tables réellement portées par un `TenantScopedModel`, à l'exécution.

    Sert au test de couverture et à la commande de vérification : c'est la liste
    à laquelle `TABLES_SCOPEES` doit rester égale.
    """
    from django.apps import apps as registre

    from apps.core.models import TenantScopedModel

    return sorted(
        modele._meta.db_table
        for modele in registre.get_models()
        if issubclass(modele, TenantScopedModel)
    )


def role_contourne_la_securite(connection) -> bool:
    """Le rôle connecté échappe-t-il aux politiques, quoi qu'elles disent ?

    Deux attributs suffisent à rendre toute la barrière décorative : `SUPERUSER`
    et `BYPASSRLS`. Aucune erreur n'est levée, aucune trace n'est écrite — les
    politiques sont simplement ignorées, et les tests d'isolation passent
    triomphalement en ne prouvant rien.

    C'est le piège le plus coûteux du dispositif : il est invisible dans le code,
    invisible dans le schéma, et n'apparaît que dans les attributs du rôle.
    """
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        ligne = curseur.fetchone()
        return bool(ligne and ligne[0])


def etat_des_tables(connection) -> dict[str, dict]:
    """État réel de la protection, lu dans le catalogue PostgreSQL."""
    with connection.cursor() as curseur:
        curseur.execute(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   EXISTS (SELECT 1 FROM pg_policy p
                           WHERE p.polrelid = c.oid AND p.polname = %s)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r' AND n.nspname = current_schema()
            """,
            [NOM_POLITIQUE],
        )
        return {
            nom: {"activee": activee, "forcee": forcee, "politique": politique}
            for nom, activee, forcee, politique in curseur.fetchall()
        }
