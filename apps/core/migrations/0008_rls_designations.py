"""Barrière 3 sur les désignations d'articles.

Une désignation dit peu de choses isolément — « PARACÉTAMOL 500 MG », « W
712/75 ». L'ensemble, lui, dit tout : c'est l'assortiment complet d'une
boutique, lisible d'un coup d'œil et exploitable par un concurrent qui voudrait
savoir quelles références sont tenues en face.

Comme toujours ici : une table scopée sans politique ne lève aucune erreur. Elle
se contente de n'être protégée par rien, et `make securite` est le seul endroit
où cela se voit.
"""

from django.db import migrations

from apps.core.rls import sql_activation, sql_desactivation

TABLES = ["catalog_designation"]


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
        ("core", "0007_rls_exemplaires"),
        ("catalog", "0007_designation"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
