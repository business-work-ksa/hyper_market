"""Barrière 3 sur la table des lots.

Une table scopée qui arrive après `core.0002` n'hérite de rien : les politiques
sont posées table par table, et une table oubliée est une table où l'isolation
ne s'applique pas — **sans que rien ne le signale à l'exécution**. C'est
pourquoi `tests/test_rls_postgres.py` compare la liste déclarée aux modèles
réels, et pourquoi `make securite` compare la liste à l'état de la base.

Les lots disent ce qui périme dans quel dépôt : c'est une donnée de gestion
d'un commerçant, au même titre que son stock.
"""

from django.db import migrations

from apps.core.rls import sql_activation, sql_desactivation

TABLE = "inventory_lotstock"


def installer(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(sql_activation(TABLE), params=None)


def desinstaller(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(sql_desactivation(TABLE), params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_securite_niveau_ligne"),
        ("inventory", "0002_lotstock"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
