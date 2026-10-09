"""Barrière 3 sur les avis de commande.

Un avis dit à qui, dans une boutique, la plateforme a écrit au sujet de quelle commande : c'est une
donnée de la boutique, scopée comme la sous-commande qu'il concerne.
"""

from django.db import migrations

from apps.core.rls import sql_activation, sql_desactivation

TABLES = ["orders_aviscommande"]


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
        ("core", "0013_rls_litige"),
        ("orders", "0006_avis_commandes"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
