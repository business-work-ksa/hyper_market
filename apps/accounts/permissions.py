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
# Le cahier de crédit client (docs/22, §2.1). Deux droits et non un : consulter
# l'encours d'un client et encaisser sur son cahier ne sont pas le même geste, et
# le comptable a besoin du premier sans jamais toucher à l'argent.
CAHIER_VOIR = "cahier.voir"
CAHIER_ENCAISSER = "cahier.encaisser"

# --- Droits de plateforme ---------------------------------------------------
# Ils gouvernent l'exploitation de la place de marché, pas le commerce d'une
# boutique. La distinction n'est pas cosmétique : **aucun d'eux n'ouvre
# `MARGE_VOIR`, `COUT_VOIR` ni le cahier d'une boutique**, et c'est le résultat
# d'un inventaire, pas d'une précaution vague. Ce que l'exploitant fait
# réellement — valider une boutique, suspendre pour loyer impayé, ajuster une
# commission, vendre une tête de gondole, arbitrer un litige — n'exige à aucun
# moment de lire la marge ou la liste de clients d'un commerçant.
#
# Ils ne sont donc **pas** dans `TOUS` : `TOUS` est l'ensemble des droits
# *sur une boutique*, celui qu'un gérant possède chez lui. Un gérant n'exploite
# pas la place de marché, et un exploitant ne vend pas chez les autres.
#
# Voir ADR-012.
PLATEFORME_BOUTIQUES = "plateforme.boutiques"
PLATEFORME_COMMISSIONS = "plateforme.commissions"
PLATEFORME_EMPLACEMENTS = "plateforme.emplacements"
PLATEFORME_LITIGES = "plateforme.litiges"
PLATEFORME_APPORTEURS = "plateforme.apporteurs"

TOUS_PLATEFORME = frozenset(
    {
        PLATEFORME_BOUTIQUES,
        PLATEFORME_COMMISSIONS,
        PLATEFORME_EMPLACEMENTS,
        PLATEFORME_LITIGES,
        PLATEFORME_APPORTEURS,
    }
)

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
        CAHIER_VOIR,
        CAHIER_ENCAISSER,
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
    CAHIER_VOIR: "Consulter le cahier de crédit et les soldes clients",
    CAHIER_ENCAISSER: "Encaisser un paiement sur le cahier d'un client",
    PLATEFORME_BOUTIQUES: "Valider, suspendre et résilier les baux des boutiques",
    PLATEFORME_COMMISSIONS: "Fixer les taux de commission des rayons et les taux négociés",
    PLATEFORME_EMPLACEMENTS: "Vendre et attribuer les emplacements premium",
    PLATEFORME_LITIGES: "Accéder à une commande contestée, sur motif enregistré",
    PLATEFORME_APPORTEURS: "Administrer le réseau d'apporteurs et ses versements",
}

# --- Attribution par rôle ---------------------------------------------------
# La séparation qui compte : `COUT_VOIR` (ce que la marchandise a coûté) et
# `MARGE_VOIR` (ce qu'elle rapporte) ne sont pas le même droit. Le magasinier
# saisit des prix d'achat, il lui faut le premier ; il n'a aucune raison
# d'accéder au second.
DROITS_PAR_ROLE: dict[str, frozenset[str]] = {
    Role.GERANT: TOUS,
    Role.CAISSIER: frozenset(
        {CAISSE_ENCAISSER, VENTES_VOIR, STOCK_VOIR, CAHIER_VOIR, CAHIER_ENCAISSER}
    ),
    Role.VENDEUR: frozenset(
        {
            CAISSE_ENCAISSER,
            VENTES_VOIR,
            STOCK_VOIR,
            COMMANDES_TRAITER,
            CAHIER_VOIR,
            CAHIER_ENCAISSER,
        }
    ),
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
            # Le comptable voit l'encours — c'est une créance, elle est dans sa
            # balance — mais il n'encaisse pas : il ne tient pas la caisse.
            CAHIER_VOIR,
        }
    ),
    Role.RH: frozenset({BOUTIQUE_VOIR}),
    # Rôles plateforme : ils n'ouvrent toujours **aucun droit sur une boutique**
    # par simple portée — un exploitant ne vend pas chez les autres. Ce qu'ils
    # ouvrent désormais, ce sont les droits d'exploitation de la place de marché,
    # et rien d'autre (ADR-012). L'accès aux données propres d'une boutique passe
    # par `acces_plateforme()`, qui exige un motif et laisse une trace.
    Role.RESP_RAYON: frozenset({PLATEFORME_COMMISSIONS, PLATEFORME_EMPLACEMENTS}),
    Role.ADMIN_MARCHE: TOUS_PLATEFORME,
    Role.CABINET: frozenset(
        {VENTES_VOIR, COMPTABILITE_VOIR, COUT_VOIR, EXPORTER, CAHIER_VOIR}
    ),
}


def droits_du_role(code_role: str) -> frozenset[str]:
    return DROITS_PAR_ROLE.get(code_role, frozenset())


def droits_de(utilisateur, boutique) -> frozenset[str]:
    """Droits d'un utilisateur **sur une boutique donnée**.

    Un utilisateur peut être gérant ici et caissier ailleurs : le calcul est
    toujours relatif à la boutique courante, jamais global au compte. Les rôles
    cumulés s'additionnent — un comptable également gérant garde ses deux
    casquettes.

    **`is_superuser` n'ouvre plus rien ici** (ADR-012). Ce court-circuit donnait
    tous les droits sur toutes les boutiques à partir d'un booléen — dont
    `MARGE_VOIR` et `COUT_VOIR`, les deux que ce fichier protège avec le plus de
    soin. L'exploitant de la place de marché n'est pas commerçant chez les autres :
    ses droits d'exploitation sont `droits_plateforme_de()`, et lire les données
    propres d'une boutique passe par `acces_plateforme()`, avec un motif et une
    trace.

    Le superutilisateur garde `/admin/` : c'est Django, c'est le dernier recours
    d'exploitation, et le lui retirer laisserait l'application sans issue de
    secours. Mais `/admin/` laisse une trace dans le journal d'administration de
    Django, ce que ce court-circuit ne faisait pas.

    Le résultat est intersecté avec `TOUS` : un rôle de plateforme mal rattaché ne
    peut donc pas ouvrir un droit de boutique par accident.
    """
    if utilisateur is None or not utilisateur.is_authenticated or boutique is None:
        return frozenset()

    codes = utilisateur.appartenances.filter(
        actif=True, boutique_id=getattr(boutique, "pk", boutique)
    ).values_list("role_id", flat=True)

    acquis: set[str] = set()
    for code in codes:
        acquis |= droits_du_role(code)
    return frozenset(acquis) & TOUS


def droits_plateforme_de(utilisateur) -> frozenset[str]:
    """Droits d'exploitation de la place de marché (ADR-012).

    Ils ne dépendent d'aucune boutique — c'est ce qui les distingue. Et ils
    n'ouvrent jamais un droit de boutique : le résultat est intersecté avec
    `TOUS_PLATEFORME`, de sorte qu'une erreur dans la matrice ne puisse pas
    transformer un exploitant en gérant de toutes les boutiques.
    """
    if utilisateur is None or not utilisateur.is_authenticated:
        return frozenset()

    codes = utilisateur.roles_plateforme.filter(actif=True).values_list("role_id", flat=True)

    acquis: set[str] = set()
    for code in codes:
        acquis |= droits_du_role(code)
    return frozenset(acquis) & TOUS_PLATEFORME
