"""Panier de l'acheteur, tenu en session.

Trois décisions, et chacune répond à une contrainte du terrain.

**Le panier vit en session, pas en base.** Un acheteur compose son panier avant
de dire qui il est — lui demander de créer un compte pour poser un article
dedans est le moyen le plus sûr de le perdre. La session suffit, et elle ne
laisse aucune trace à nettoyer pour les paniers abandonnés, qui sont la majorité.

**Le panier ne stocke que des identifiants et des quantités.** Ni prix, ni
libellé : ils sont relus à chaque affichage. Un prix recopié dans la session
serait un prix figé au moment où l'acheteur a cliqué, et il finirait par
diverger de celui du marchand — l'acheteur verrait un total et paierait l'autre.

**Un panier traverse les boutiques.** C'est le principe même de la place de
marché : un panier, un paiement, N marchands. Le regroupement par boutique est
fait ici pour l'affichage, et refait par `passer_commande` pour l'éclatement —
les deux lisent la même donnée, la boutique portée par la variante.
"""

from decimal import Decimal

from apps.vitrine.catalogue import article_par_identifiant

__all__ = [
    "CLE_PANIER",
    "CLE_PARRAINAGE",
    "lire",
    "ajouter",
    "definir_quantite",
    "retirer",
    "vider",
    "lignes",
    "total",
    "nombre_articles",
]

CLE_PANIER = "panier"
CLE_PARRAINAGE = "code_apporteur"

QUANTITE_MAXI = 99


def lire(session) -> dict:
    contenu = session.get(CLE_PANIER)
    return dict(contenu) if isinstance(contenu, dict) else {}


def _ecrire(session, contenu: dict) -> None:
    session[CLE_PANIER] = contenu
    session.modified = True


def ajouter(session, identifiant, quantite=1) -> int:
    """Ajoute une quantité et retourne la nouvelle quantité de la ligne."""
    contenu = lire(session)
    cle = str(identifiant)
    nouvelle = min(int(contenu.get(cle, 0)) + int(quantite), QUANTITE_MAXI)
    if nouvelle <= 0:
        contenu.pop(cle, None)
    else:
        contenu[cle] = nouvelle
    _ecrire(session, contenu)
    return nouvelle


def definir_quantite(session, identifiant, quantite) -> int:
    contenu = lire(session)
    cle = str(identifiant)
    quantite = max(0, min(int(quantite), QUANTITE_MAXI))
    if quantite == 0:
        contenu.pop(cle, None)
    else:
        contenu[cle] = quantite
    _ecrire(session, contenu)
    return quantite


def retirer(session, identifiant) -> None:
    definir_quantite(session, identifiant, 0)


def vider(session) -> None:
    session.pop(CLE_PANIER, None)
    session.modified = True


def lignes(session) -> list[dict]:
    """Contenu du panier, relu depuis le catalogue.

    Un article devenu indisponible — retiré de la vente, boutique suspendue —
    **disparaît du panier**, et la session est nettoyée au passage. Le laisser
    afficher un article qu'on ne peut plus commander produirait un refus au
    dernier écran, c'est-à-dire au pire moment.
    """
    contenu = lire(session)
    if not contenu:
        return []

    resultat = []
    encore_valides = {}
    for identifiant, quantite in contenu.items():
        article = article_par_identifiant(identifiant)
        if article is None:
            continue
        quantite = int(quantite)
        resultat.append(
            {
                "article": article,
                "quantite": quantite,
                "total": (article.prix_vente * quantite).quantize(Decimal("0.01")),
            }
        )
        encore_valides[identifiant] = quantite

    if encore_valides != contenu:
        _ecrire(session, encore_valides)
    return resultat


def total(lignes_du_panier) -> Decimal:
    return sum((l["total"] for l in lignes_du_panier), Decimal("0")).quantize(Decimal("0.01"))


def nombre_articles(session) -> int:
    return sum(int(q) for q in lire(session).values())


def par_boutique(lignes_du_panier) -> list[dict]:
    """Regroupe pour l'affichage : l'acheteur doit voir de qui vient quoi.

    Ce n'est pas cosmétique. Deux marchands livrent séparément, acceptent
    séparément, et peuvent refuser l'un sans l'autre. Un panier présenté comme
    un bloc unique promettrait une commande indivisible qui n'existe pas.
    """
    groupes: dict = {}
    for ligne in lignes_du_panier:
        boutique = ligne["article"].boutique
        groupe = groupes.setdefault(
            boutique.pk, {"boutique": boutique, "lignes": [], "total": Decimal("0")}
        )
        groupe["lignes"].append(ligne)
        groupe["total"] += ligne["total"]
    return list(groupes.values())
