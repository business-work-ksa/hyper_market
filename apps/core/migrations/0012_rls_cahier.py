"""Barrière 3 sur le cahier de crédit client.

C'est la table la plus sensible ajoutée depuis le début du projet, et il faut le dire clairement :
elle contient **le nom, le numéro de téléphone et la dette** de personnes qui ne sont pas les
clients de la plateforme, mais ceux du commerçant. Une fuite ici n'expose pas un assortiment ou une
marge — elle expose qui, dans un quartier, n'a pas pu payer son riz.

Deux conséquences, et elles ne sont pas symboliques.

La première est ici : les deux tables sont scopées, avec politique, comme le reste. Un
`objects_all_tenants` mal filtré ne suffit plus à les lire.

La seconde est ailleurs et ne se code pas dans une migration : l'exploitant de la plateforme n'a
**aucun** droit qui ouvre ce cahier (ADR-012 — `plateforme.litiges` porte sur une commande
contestée, pas sur les dettes des clients d'un commerçant). Y accéder passerait par
`acces_plateforme()`, avec un motif et une trace en ajout seul.

Comme toujours ici : une table scopée sans politique ne lève aucune erreur. Elle se contente de
n'être protégée par rien, et `make securite` est le seul endroit où cela se voit.
"""

from django.db import migrations

from apps.core.rls import sql_activation, sql_desactivation

TABLES = ["pos_clientcahier", "pos_reglementcahier"]


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
        ("core", "0011_acces_plateforme_ajout_seul"),
        ("pos", "0003_cahier_de_credit_client"),
    ]

    operations = [migrations.RunPython(installer, desinstaller)]
