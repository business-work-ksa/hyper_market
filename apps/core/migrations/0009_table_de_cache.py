"""Table du cache partagé, pour les exécutions sans serveur.

Sur une plateforme sans serveur, chaque invocation repart d'un processus neuf.
Un cache en mémoire n'y compte jamais au-delà de un, et le compteur d'essais de
mot de passe (`apps/accounts/limitation.py`) devient décoratif : dix mille
essais passent, et rien dans les journaux ne le signale. La base est alors le
seul état partagé dont on soit sûr.

Pourquoi une migration plutôt que `createcachetable`
----------------------------------------------------

La commande de Django existe et fait exactement cela. Mais c'est **un geste de
plus à ne pas oublier**, exécuté à la main, sur une plateforme où l'on ne
dispose pas toujours d'un terminal. Une table de cache absente ne se voit pas
au démarrage : l'application se lance, les écrans s'affichent, et la première
tentative de connexion échoue sur une table manquante — ou, pire, le verrou ne
compte rien et personne ne le remarque.

Posée en migration, elle suit le schéma comme le reste. Et elle ne coûte rien
là où elle ne sert pas : quelques kilooctets et une table qu'aucun code ne
touche.

**Elle n'est pas scopée par boutique**, et c'est voulu. Elle ne contient pas de
données de commerçant : des compteurs d'essais associés à un numéro de
téléphone, effacés au bout d'un quart d'heure. La barrière 3 n'a rien à y faire,
et l'y appliquer empêcherait justement le compteur de fonctionner pour quelqu'un
qui n'est pas encore connecté — c'est-à-dire dans le seul cas où il sert.
"""

from django.db import migrations


# Le nom est fixé ici et dans `config/settings.py` (`CACHES["default"]["LOCATION"]`).
# Les deux doivent rester d'accord ; un test le vérifie.
NOM_TABLE = "cache_partage"


def creer(apps, schema_editor):
    """Crée la table avec le schéma exact qu'attend le moteur de cache de Django.

    Le schéma est demandé à Django lui-même plutôt que recopié : les colonnes,
    leurs types et leurs index appartiennent à son implémentation, et une copie
    figée ici se désynchroniserait à la première version qui les ajuste.
    """
    from django.core.management import call_command

    call_command("createcachetable", NOM_TABLE, verbosity=0)


def supprimer(apps, schema_editor):
    schema_editor.execute(f"DROP TABLE IF EXISTS {schema_editor.quote_name(NOM_TABLE)}")


class Migration(migrations.Migration):
    dependencies = [("core", "0008_rls_designations")]

    operations = [migrations.RunPython(creer, supprimer)]
