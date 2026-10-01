"""Trigger PostgreSQL : le journal des accès plateforme est en ajout seul.

Même motif que le journal comptable (ADR-003, `accounting/0003`), et pour une raison plus directe
encore : **un journal d'audit qu'on peut effacer ne prouve rien.** Il donne l'illusion d'une preuve,
ce qui est pire que son absence — on cesse de chercher ailleurs.

Les protections Python (`AccesPlateforme.save()` et `.delete()`) donnent un message clair au
développeur. Celle-ci rejette un `UPDATE` ou un `DELETE` même émis en SQL brut, depuis un script,
un client `psql` ou un ORM tiers. C'est la seule qui tienne face à quelqu'un qui veut effacer sa
trace, ce qui est précisément le cas contre lequel un journal d'audit existe.

**Aucune dérogation ici**, contrairement au journal comptable qui laisse modifier
`contrepassee_par` : une ligne de ce journal n'a pas de champ de suivi. Elle est vraie ou elle n'est
pas.

Sur SQLite (tests hors infrastructure), la migration est un no-op : seules les protections Python
s'appliquent alors, ce qui suffit pour les tests unitaires mais **jamais pour la production**.
"""

from django.db import migrations

SQL_INSTALLATION = """
CREATE OR REPLACE FUNCTION hm_acces_plateforme_ajout_seul() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'Journal des acces plateforme : ajout seul. Ni modification ni suppression (ADR-012).';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hm_acces_plateforme_ajout_seul_trg
    BEFORE UPDATE OR DELETE ON core_accesplateforme
    FOR EACH ROW EXECUTE FUNCTION hm_acces_plateforme_ajout_seul();
"""

SQL_DESINSTALLATION = """
DROP TRIGGER IF EXISTS hm_acces_plateforme_ajout_seul_trg ON core_accesplateforme;
DROP FUNCTION IF EXISTS hm_acces_plateforme_ajout_seul();
"""


def installer(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    # params=None : sans cela, psycopg interprète les « % » des messages RAISE comme des
    # marqueurs de paramètre.
    schema_editor.execute(SQL_INSTALLATION, params=None)


def desinstaller(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(SQL_DESINSTALLATION, params=None)


class Migration(migrations.Migration):
    dependencies = [("core", "0010_journal_acces_plateforme")]

    operations = [migrations.RunPython(installer, desinstaller)]
