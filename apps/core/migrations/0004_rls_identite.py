"""Barrière 3 sur l'identité visuelle et les liens marketing.

Deux tables scopées de plus, donc deux politiques de plus. Le geste est
mécanique et c'est précisément pourquoi il est risqué : une table scopée sans
politique ne lève aucune erreur, elle se contente de n'être protégée par rien.
`make securite` et `tests/test_rls_postgres.py` sont là pour que l'oubli se voie.

La charte d'un commerçant est une donnée de sa boutique — ses couleurs, son
logo — et ses liens marketing portent ses compteurs d'audience. Ni l'une ni les
autres n'ont à être lisibles par un confrère.
"""

from django.db import migrations

from apps.core.rls import sql_activation, sql_desactivation

TABLES = ["marketplace_identitevisuelle", "marketplace_lienmarketing"]


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
        ("core", "0003_rls_lots"),
        ("marketplace", "0004_lienmarketing_identitevisuelle"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
