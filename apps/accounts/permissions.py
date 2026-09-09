"""Droits d'accès du back-office marchand.

Un rattachement à une boutique n'est pas un droit sur tout ce qu'elle contient.
Le caissier encaisse, il ne consulte pas la marge ; le magasinier reçoit la
marchandise, il ne lit pas la balance. C'est un **problème d'exposition de
données avant d'être une fonctionnalité** : le coût d'achat d'un article, sur un
écran ouvert au comptoir, est une information qui circule dans le quartier avant
la fin de la journée.

Deux choses en découlent :

1. **La source de vérité est ici, en code, pas en base.** `Role.permissions` est
   un miroir écrit par `initialiser_referentiels` pour que l'administration
   affiche les droits ; il n'est jamais lu pour décider. Une table modifiable à
   chaud n'a pas à pouvoir ouvrir la marge à un caissier.
2. **Un droit absent ferme, il ne dégrade pas.** `droits_de()` d'un utilisateur
   sans appartenance active renvoie l'ensemble vide — jamais l'ensemble complet.
"""

from apps.accounts.models import Role

# --- Droits élémentaires ----------------------------------------------------
# Nommés par ce qu'ils ouvrent, pas par l'écran qui les consomme : un même droit
# gouverne souvent plusieurs endroits (la marge apparaît au tableau de bord et
# en comptabilité).
TABLEAU_DE_BORD = "tableau_de_bord"
CAISSE_ENCAISSER = "caisse.encaisser"
STOCK_VOIR = "stock.voir"
STOCK_MOUVEMENTER = "stock.mouvementer"
VENTES_VOIR = "ventes.voir"
COMMANDES_TRAITER = "commandes.traiter"
COMPTABILITE_VOIR = "comptabilite.voir"
COUT_VOIR = "cout.voir"
MARGE_VOIR = "marge.voir"
BOUTIQUE_VOIR = "boutique.voir"
BOUTIQUE_ADMINISTRER = "boutique.administrer"
EXPORTER = "exporter"

TOUS = frozenset(
    {
        TABLEAU_DE_BORD,
        CAISSE_ENCAISSER,
        STOCK_VOIR,
        STOCK_MOUVEMENTER,
        VENTES_VOIR,
        COMMANDES_TRAITER,
        COMPTABILITE_VOIR,
        COUT_VOIR,
        MARGE_VOIR,
        BOUTIQUE_VOIR,
        BOUTIQUE_ADMINISTRER,
        EXPORTER,
    }
)

LIBELLES = {
    TABLEAU_DE_BORD: "Consulter le tableau de bord",
    CAISSE_ENCAISSER: "Encaisser au comptoir",
    STOCK_VOIR: "Consulter le stock",
    STOCK_MOUVEMENTER: "Entrer, inventorier et transférer du stock",
    VENTES_VOIR: "Consulter le journal des ventes",
    COMMANDES_TRAITER: "Accepter, préparer et expédier les commandes en ligne",
    COMPTABILITE_VOIR: "Consulter la comptabilité",
    COUT_VOIR: "Voir les coûts d'achat et la valeur du stock",
    MARGE_VOIR: "Voir la marge",
    BOUTIQUE_VOIR: "Consulter la fiche de la boutique",
    BOUTIQUE_ADMINISTRER: "Modifier les dépôts et l'organisation",
    EXPORTER: "Exporter les données de la boutique",
}

# --- Attribution par rôle ---------------------------------------------------
# La séparation qui compte : `COUT_VOIR` (ce que la marchandise a coûté) et
# `MARGE_VOIR` (ce qu'elle rapporte) ne sont pas le même droit. Le magasinier
# saisit des prix d'achat, il lui faut le premier ; il n'a aucune raison
# d'accéder au second.
DROITS_PAR_ROLE: dict[str, frozenset[str]] = {
    Role.GERANT: TOUS,
    Role.CAISSIER: frozenset({CAISSE_ENCAISSER, VENTES_VOIR, STOCK_VOIR}),
    Role.VENDEUR: frozenset({CAISSE_ENCAISSER, VENTES_VOIR, STOCK_VOIR, COMMANDES_TRAITER}),
    Role.MAGASINIER: frozenset(
        {TABLEAU_DE_BORD, STOCK_VOIR, STOCK_MOUVEMENTER, COUT_VOIR, COMMANDES_TRAITER}
    ),
    Role.COMPTABLE: frozenset(
        {
            TABLEAU_DE_BORD,
            VENTES_VOIR,
            COMPTABILITE_VOIR,
            COUT_VOIR,
            MARGE_VOIR,
            BOUTIQUE_VOIR,
            EXPORTER,
        }
    ),
    Role.RH: frozenset({BOUTIQUE_VOIR}),
    # Rôles plateforme : ils n'ouvrent aucun droit sur une boutique par simple
    # portée. L'accès transverse passe par `contexte_plateforme()`, journalisé.
    Role.RESP_RAYON: frozenset(),
    Role.ADMIN_MARCHE: frozenset(),
    Role.CABINET: frozenset({VENTES_VOIR, COMPTABILITE_VOIR, COUT_VOIR, EXPORTER}),
}


def droits_du_role(code_role: str) -> frozenset[str]:
    return DROITS_PAR_ROLE.get(code_role, frozenset())


def droits_de(utilisateur, boutique) -> frozenset[str]:
    """Droits d'un utilisateur **sur une boutique donnée**.

    Un utilisateur peut être gérant ici et caissier ailleurs : le calcul est
    toujours relatif à la boutique courante, jamais global au compte. Les rôles
    cumulés s'additionnent — un comptable également gérant garde ses deux
    casquettes.
    """
    if utilisateur is None or not utilisateur.is_authenticated or boutique is None:
        return frozenset()

    if utilisateur.is_superuser:
        return TOUS

    codes = utilisateur.appartenances.filter(
        actif=True, boutique_id=getattr(boutique, "pk", boutique)
    ).values_list("role_id", flat=True)

    acquis: set[str] = set()
    for code in codes:
        acquis |= droits_du_role(code)
    return frozenset(acquis)
