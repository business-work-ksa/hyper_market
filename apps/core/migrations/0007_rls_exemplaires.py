"""Barrière 3 sur les exemplaires suivis à l'unité et leurs passages à l'atelier.

Ces deux tables portent des noms de clients, des IMEI et des dates de garantie :
la liste exacte de qui a acheté quoi, et quand. C'est le contenu le plus
identifiant du système après la comptabilité, et le seul que le voisin de palier
aurait un intérêt direct à lire.

Comme toujours ici : une table scopée sans politique ne lève aucune erreur. Elle
se contente de n'être protégée par rien, et `make securite` est le seul endroit
où cela se voit.
"""

from django.db import migrations

from apps.core.rls import sql_activation, sql_desactivation

TABLES = ["inventory_numeroserie", "inventory_passageatelier"]


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
        ("core", "0006_rls_compatibilites"),
        ("inventory", "0004_numeroserie_passageatelier_and_more"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
