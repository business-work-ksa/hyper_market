"""Gestes du catalogue qui touchent à plusieurs tables : corriger, retirer.

Un article n'est pas un enregistrement isolé. Il se compose d'un `Produit` et
d'au moins une `Variante`, il porte un seuil d'alerte rangé sur son
`NiveauStock`, et surtout **il laisse des traces** : mouvements de stock, lignes
de ticket, lignes de commande, exemplaires suivis à l'unité.

D'où la règle de ce module, qui vaut pour tous les écrans de liste du
back-office :

    **On supprime ce qui n'a pas d'histoire, on retire ce qui en a une.**

Effacer un article vendu l'an dernier arracherait son libellé de tickets déjà
imprimés et d'écritures comptables déjà validées — le journal est en ajout seul
précisément pour que cela n'arrive pas. Mais interdire toute suppression serait
l'excès inverse : une référence créée par erreur il y a trois minutes, jamais
vendue, doit pouvoir disparaître sans laisser un fantôme dans la liste.

Le logiciel tranche donc **en fonction de la ligne**, et **dit ce qu'il a fait** :
c'est la seule façon d'être à la fois sûr et utilisable.
"""

from django.db import transaction
from django.db.models import ProtectedError

__all__ = ["SUPPRIME", "RETIRE", "retirer_du_catalogue", "supprimable"]

SUPPRIME = "supprime"
RETIRE = "retire"


def supprimable(variante) -> str:
    """Chaîne vide si la variante peut disparaître, sinon le motif qui l'en empêche.

    Sert à **prévenir avant d'agir** : la ligne du tableau porte ce motif, et la
    barre d'outils l'affiche au lieu de laisser cliquer pour rien.
    """
    from apps.inventory.models import MouvementStock, NumeroSerie

    if MouvementStock.objects.filter(variante=variante).exists():
        return "A déjà bougé en stock : sera retiré de la vente, pas supprimé."
    if NumeroSerie.objects.filter(variante=variante).exists():
        return "Des exemplaires sont suivis : sera retiré de la vente, pas supprimé."
    return ""


@transaction.atomic
def retirer_du_catalogue(variante) -> str:
    """Supprime la variante si rien ne la retient, la désactive sinon.

    Renvoie `SUPPRIME` ou `RETIRE`. La distinction remonte jusqu'au message
    affiché : « supprimé » et « retiré de la vente » ne sont pas la même chose,
    et laisser croire à l'un quand c'est l'autre ferait chercher longtemps un
    article toujours présent dans les listes.

    Le `savepoint` n'est pas une précaution de style : une `ProtectedError`
    rompt la transaction courante sous PostgreSQL, et tout ce qui suivrait dans
    le même bloc échouerait avec une erreur qui ne parle plus de l'article.
    """
    produit = variante.produit
    point = transaction.savepoint()
    try:
        variante.delete()
        transaction.savepoint_commit(point)
    except ProtectedError:
        transaction.savepoint_rollback(point)
        type(variante).objects.filter(pk=variante.pk).update(actif=False)
        produit.__class__.objects.filter(pk=produit.pk).update(actif=False)
        return RETIRE

    # Le produit ne survit pas à sa dernière variante : il n'a ni prix ni stock,
    # il ne serait plus vendable ni visible nulle part — un orphelin que seule
    # la base connaîtrait.
    if not produit.variantes.exists():
        point = transaction.savepoint()
        try:
            produit.delete()
            transaction.savepoint_commit(point)
        except ProtectedError:
            transaction.savepoint_rollback(point)
            produit.__class__.objects.filter(pk=produit.pk).update(actif=False)
    return SUPPRIME
