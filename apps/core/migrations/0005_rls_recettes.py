"""Barrière 3 sur les fiches techniques et leurs ingrédients.

Une fiche technique est le secret d'un commerce. Ce qu'un restaurateur met dans
son ndolé, dans quelles proportions, et ce que cela lui coûte : c'est
littéralement sa recette, et le concurrent d'en face ne doit pas pouvoir la
lire. Deux tables scopées de plus, donc deux politiques de plus — le geste est
mécanique, et c'est précisément pourquoi il est risqué : une table scopée sans
politique ne lève aucune erreur, elle se contente de n'être protégée par rien.
"""

from django.db import migrations

from apps.core.rls import sql_activation, sql_desactivation

TABLES = ["catalog_recette", "catalog_lignerecette"]


def installer(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(sql_activation(table), params=None)


def desinstaller(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(sql_desactivation(table), params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_rls_identite"),
        ("catalog", "0003_recette_lignerecette_and_more"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
