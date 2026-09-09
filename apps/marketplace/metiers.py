"""Les métiers du marché : ce qu'un commerce fait, et ce que le logiciel en déduit.

Un `Rayon` dit **où** une boutique est rangée dans le marché, et porte le taux de
commission. Un `TypeEmplacement` dit **ce qu'elle loue**. Ni l'un ni l'autre ne
dit **ce qu'elle vend**, et c'est pourtant ce qui change l'interface.

Un pharmacien ne saisit pas un « article » : il saisit un médicament, avec son
lot et sa date de péremption, et il ne facture pas de TVA dessus. Un vendeur de
pièces détachées cherche par référence constructeur. Un boucher vend au poids.
Leur donner à tous le même écran, c'est leur donner à tous un écran approximatif.

Pourquoi ce référentiel est en code
-----------------------------------

Comme la matrice des droits (`apps/accounts/permissions.py`), et pour la même
raison : ce que déclare un métier **gouverne le comportement du logiciel**, pas
seulement son affichage. Une table modifiable à chaud n'a pas à pouvoir activer
la traçabilité par lot dans une pharmacie, ni à la désactiver. `Boutique.metier`
ne stocke qu'un code ; tout ce qui en découle se lit ici.

Ce qui est câblé, et ce qui ne l'est pas
---------------------------------------

Les fonctions déclarées ci-dessous sont **celles qui agissent réellement**. Une
fonction qui ne ferait qu'apparaître dans une liste donnerait au commerçant
l'impression d'un suivi qu'il n'a pas — c'est exactement le genre de promesse
qu'une pharmacie paie cher.

Restent à écrire, et volontairement non déclarées : numéros de série et garantie
(électronique), fiches techniques et production du jour (restauration,
boulangerie), compatibilité véhicule (pièces auto), mention d'ordonnance
(pharmacie). Le métier les prévoit dans son `a_venir`, qui sert à l'afficher au
commerçant sans le lui promettre.

Une limite à connaître sur les lots : le stock est suivi **lot par lot**, ce qui
répond à « qu'est-ce qui périme quand » et « combien me reste-t-il de ce lot ».
Il ne répond pas à « quel lot est parti chez quel client » — cela demande une
affectation ligne à ligne à la vente, et c'est un autre chantier. Le rappel de
lot au sens pharmacovigilance n'est donc pas couvert, et le libellé de la
fonction ne le prétend pas.
"""

from dataclasses import dataclass, field

__all__ = [
    "Metier",
    "METIERS",
    "CHOIX_METIER",
    "METIER_DEFAUT",
    "metier_de",
    "PEREMPTION",
    "LOT",
    "POIDS_VARIABLE",
    "DECLINAISONS",
]

# --- Fonctions réellement câblées -------------------------------------------
PEREMPTION = "peremption"
LOT = "lot"
POIDS_VARIABLE = "poids_variable"
DECLINAISONS = "declinaisons"

LIBELLES_FONCTIONS = {
    PEREMPTION: "Suivi des dates de péremption, et alerte avant qu'il ne soit trop tard",
    LOT: "Numéro de lot à la réception, et stock suivi lot par lot",
    POIDS_VARIABLE: "Vente au poids ou à la longueur, quantités décimales",
    DECLINAISONS: "Déclinaisons d'un même modèle : taille, couleur, contenance",
}


@dataclass(frozen=True)
class Metier:
    """Ce qu'un commerce vend, et les conséquences pour le logiciel.

    Le vocabulaire n'est pas une coquetterie. Un pharmacien à qui l'écran parle
    d'« articles » se demande s'il est au bon endroit ; celui à qui il parle de
    « médicaments » sait qu'on a compris son métier. C'est la différence entre un
    logiciel générique reconfiguré et un logiciel fait pour lui.
    """

    code: str
    libelle: str
    resume: str

    # Vocabulaire de l'interface
    article: str
    articles: str
    reception: str = "Réception fournisseur"

    # Valeurs par défaut à la création d'un article
    unite_defaut: str = "U"
    regime_tva_defaut: str = "normal"

    # Fonctions actives, et ce qui reste à écrire
    fonctions: frozenset[str] = field(default_factory=frozenset)
    a_venir: tuple[str, ...] = ()

    # Aide à la saisie : ce qu'on montre en exemple dans les formulaires
    exemples: tuple[str, ...] = ()

    def a(self, fonction: str) -> bool:
        return fonction in self.fonctions

    @property
    def libelles_fonctions(self) -> list[str]:
        return [LIBELLES_FONCTIONS[f] for f in sorted(self.fonctions)]


# ---------------------------------------------------------------------------
# Les dix métiers
# ---------------------------------------------------------------------------
# Choisis sur le commerce camerounais réel, pas sur une taxonomie générique :
# ce sont les enseignes qu'on croise en descendant une rue de Douala.
METIERS: dict[str, Metier] = {
    "COMMERCE_GENERAL": Metier(
        code="COMMERCE_GENERAL",
        libelle="Commerce général & alimentation",
        resume="Boutique de quartier, épicerie, alimentation générale.",
        article="article",
        articles="articles",
        exemples=("Riz parfumé 5 kg", "Huile de palme 1 L", "Savon de Marseille"),
    ),
    "PHARMACIE": Metier(
        code="PHARMACIE",
        libelle="Pharmacie & parapharmacie",
        resume="Officine, dépôt pharmaceutique, parapharmacie.",
        article="médicament",
        articles="médicaments",
        reception="Réception grossiste",
        # Les médicaments essentiels sont exonérés de TVA au Cameroun. Le défaut
        # est donc « exonéré » : c'est le cas le plus fréquent en officine, et
        # un défaut qui oblige à corriger chaque ligne finit par être ignoré.
        regime_tva_defaut="exonere",
        fonctions=frozenset({PEREMPTION, LOT}),
        a_venir=(
            "Mention d'ordonnance à la délivrance",
            "Dénomination commune internationale et équivalences",
        ),
        exemples=("Paracétamol 500 mg — boîte de 20", "Amoxicilline 1 g", "Sérum physiologique"),
    ),
    "QUINCAILLERIE": Metier(
        code="QUINCAILLERIE",
        libelle="Quincaillerie & matériaux",
        resume="Fer, ciment, outillage, plomberie, électricité.",
        article="article",
        articles="articles",
        fonctions=frozenset({POIDS_VARIABLE}),
        exemples=("Ciment CIMENCAM 50 kg", "Fer à béton 12 mm", "Tuyau PVC 100 mm"),
    ),
    "COSMETIQUE": Metier(
        code="COSMETIQUE",
        libelle="Cosmétique & beauté",
        resume="Soins, parfums, produits capillaires, salon.",
        article="produit",
        articles="produits",
        fonctions=frozenset({PEREMPTION, LOT, DECLINAISONS}),
        exemples=("Beurre de karité 500 g", "Huile d'argan 100 ml", "Masque à l'argile"),
    ),
    "RESTAURATION": Metier(
        code="RESTAURATION",
        libelle="Restauration & snack",
        resume="Restaurant, snack, bar, traiteur.",
        article="plat",
        articles="plats",
        reception="Réception des denrées",
        fonctions=frozenset({PEREMPTION}),
        a_venir=(
            "Fiches techniques : un plat consomme ses ingrédients",
            "Service à table et commandes en cours",
        ),
        exemples=("Poulet DG", "Ndolé aux crevettes", "Jus de bissap 50 cl"),
    ),
    "BOULANGERIE": Metier(
        code="BOULANGERIE",
        libelle="Boulangerie & pâtisserie",
        resume="Pain, viennoiserie, pâtisserie, production quotidienne.",
        article="produit",
        articles="produits",
        reception="Réception des matières premières",
        fonctions=frozenset({PEREMPTION, POIDS_VARIABLE}),
        a_venir=("Production du jour et invendus", "Recettes et coût de revient au gramme"),
        exemples=("Baguette 250 g", "Croissant au beurre", "Gâteau d'anniversaire 1 kg"),
    ),
    "MODE": Metier(
        code="MODE",
        libelle="Mode & prêt-à-porter",
        resume="Vêtements, chaussures, maroquinerie, friperie.",
        article="article",
        articles="articles",
        fonctions=frozenset({DECLINAISONS}),
        exemples=("Chemise en wax — homme", "Sandales cuir", "Sac à main"),
    ),
    "ELECTRONIQUE": Metier(
        code="ELECTRONIQUE",
        libelle="Électronique & téléphonie",
        resume="Téléphones, accessoires, informatique, réparation.",
        article="appareil",
        articles="appareils",
        fonctions=frozenset({DECLINAISONS}),
        a_venir=(
            "Numéro de série et IMEI suivis à l'unité",
            "Garantie : durée, échéance, retour atelier",
        ),
        exemples=("Téléphone 64 Go", "Chargeur rapide 25 W", "Écouteurs sans fil"),
    ),
    "PIECES_AUTO": Metier(
        code="PIECES_AUTO",
        libelle="Pièces détachées auto & moto",
        resume="Pièces neuves et d'occasion, lubrifiants, pneumatiques.",
        article="pièce",
        articles="pièces",
        fonctions=frozenset(),
        a_venir=(
            "Compatibilité véhicule : marque, modèle, années",
            "Références constructeur et équivalences",
        ),
        exemples=("Filtre à huile — Toyota Corolla", "Plaquettes de frein avant", "Huile 15W40 5 L"),
    ),
    "PRODUITS_FRAIS": Metier(
        code="PRODUITS_FRAIS",
        libelle="Produits frais",
        resume="Primeur, boucherie, poissonnerie, crémerie.",
        article="produit",
        articles="produits",
        reception="Arrivage",
        unite_defaut="KG",
        fonctions=frozenset({PEREMPTION, POIDS_VARIABLE}),
        exemples=("Filet de bœuf", "Bar frais", "Tomates fraîches"),
    ),
}

METIER_DEFAUT = "COMMERCE_GENERAL"

CHOIX_METIER = [(code, m.libelle) for code, m in METIERS.items()]


def metier_de(boutique_ou_code) -> Metier:
    """Métier d'une boutique, avec repli sur le commerce général.

    Le repli n'est pas une commodité : une boutique créée avant l'existence des
    métiers, ou dont le code a été retiré du référentiel, doit continuer de
    fonctionner. Le commerce général est le seul métier qui n'active aucune
    fonction — c'est le plus petit dénominateur, et donc le repli sûr.
    """
    code = getattr(boutique_ou_code, "metier", boutique_ou_code)
    return METIERS.get(code or "", METIERS[METIER_DEFAUT])
