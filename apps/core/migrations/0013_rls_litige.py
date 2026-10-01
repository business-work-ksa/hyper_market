"""Barrière 3 sur les litiges.

Un litige porte la parole d'un acheteur contre un commerçant, et la sous-commande qu'il conteste :
c'est une donnée de la boutique, scopée comme le reste. La plateforme y accède par
`plateforme.litiges`, sous motif et avec une trace (ADR-012) — jamais par un gestionnaire non
filtré qui passerait inaperçu.
"""

from django.db import migrations

from apps.core.rls import sql_activation, sql_desactivation

TABLES = ["orders_litige"]


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
        ("core", "0012_rls_cahier"),
        ("orders", "0004_confiance_et_versement"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
