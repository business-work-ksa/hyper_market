"""Barrière 3 : sécurité au niveau ligne sur toutes les tables scopées.

Les barrières 1 et 2 vivent dans Python et protègent le code qui les respecte.
Celle-ci vit dans PostgreSQL et protège de tout le reste — y compris d'une
requête brute, d'un script d'exploitation ou d'un `objects_all_tenants` mal
filtré. Le détail du mécanisme est dans `apps/core/rls.py`.

Sur SQLite (tests hors infrastructure), la migration est un no-op : seules les
barrières Python s'appliquent alors, ce qui suffit aux tests unitaires et
**jamais à la production**.

La dépendance porte sur la dernière migration de chaque application qui possède
des tables scopées : les tables doivent exister avant qu'on puisse les protéger.
"""

from django.db import migrations

from apps.core.rls import TABLES_SCOPEES, sql_activation, sql_desactivation


def installer(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES_SCOPEES:
        schema_editor.execute(sql_activation(table), params=None)


def desinstaller(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES_SCOPEES:
        schema_editor.execute(sql_desactivation(table), params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("accounting", "0003_journal_ajout_seul"),
        ("catalog", "0002_produit_produit_marge_revendeur_entre_0_et_1"),
        ("inventory", "0001_initial"),
        ("orders", "0001_initial"),
        ("payments", "0001_initial"),
        ("pos", "0001_initial"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
