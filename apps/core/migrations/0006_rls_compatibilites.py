"""Barrière 3 sur les compatibilités véhicule.

Le tableau de compatibilité d'un vendeur de pièces est son fonds de commerce :
c'est le fruit d'années de « ça, ça va aussi sur la Hilux ». Une table scopée de
plus, donc une politique de plus — le geste est mécanique, et c'est précisément
pourquoi il est risqué : une table scopée sans politique ne lève aucune erreur,
elle se contente de n'être protégée par rien.
"""

from django.db import migrations

from apps.core.rls import sql_activation, sql_desactivation

TABLES = ["catalog_compatibilitevehicule"]


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
        ("core", "0005_rls_recettes"),
        ("catalog", "0004_variante_reference_constructeur_and_more"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
