"""Les paliers de confiance d'une boutique : ce qu'on lui confie, selon ce qu'elle a prouvé.

Le principe : **ce qu'un fraudeur ne peut pas toucher, il ne peut pas le voler.** Une fausse boutique
vit d'un seul geste — encaisser des commandes prépayées, puis disparaître avant les livraisons.
Aucun contrôle à l'entrée ne l'arrête à coup sûr : une pièce d'identité se prête, un registre du
commerce s'achète. Ce qui l'arrête, c'est que l'argent des acheteurs reste en séquestre jusqu'à la
livraison confirmée, et que le montant qu'elle peut y accumuler soit **plafonné tant qu'elle n'a
rien prouvé**.

D'où des paliers. Une boutique qui vient d'être vérifiée entre au palier 0 : elle vend, mais son
séquestre en cours est plafonné et ses fonds ne se libèrent qu'une semaine après chaque livraison
confirmée. Chaque palier suivant se gagne par des **livraisons confirmées**, de l'**ancienneté** et un
**taux de litiges perdus** bas. Un fraudeur doit alors investir des semaines de ventes honnêtes pour
un gain plafonné : l'escroquerie cesse d'être rentable.

Ce fichier dit *ce que chaque palier permet*. Le calcul du palier d'une boutique vit dans
`apps/confiance/` (plus haut dans le graphe des dépendances, parce qu'il lit les commandes) et
l'écrit dans `Boutique.palier_confiance`. Les paiements lisent ce champ, jamais l'inverse.

Tous les seuils sont des **paramètres commerciaux à calibrer** sur les six premiers mois
(docs/23, §3). Ils sont écrits en code, comme la matrice des droits : ce sont des règles, pas des
données qu'on ajuste d'un clic dans un écran.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Palier:
    niveau: int
    code: str
    libelle: str
    # Délai entre la livraison confirmée et la libération des fonds au marchand : la fenêtre
    # pendant laquelle l'acheteur peut encore ouvrir un litige.
    delai_liberation_jours: int
    # Montant total TTC que la boutique peut avoir **en séquestre à la fois**. `None` : sans
    # plafond. Au-delà, la vitrine propose le paiement à la livraison au lieu du prépaiement.
    plafond_sequestre: Decimal | None
    # Conditions pour **atteindre** ce palier.
    livraisons_min: int
    anciennete_jours_min: int
    taux_litiges_perdus_max: Decimal  # fraction : 0.05 = 5 %
    # Des livraisons à des acheteurs **distincts** : sans cette condition, un palier s'achète par
    # des auto-commandes, passées depuis quelques numéros amis et « livrées » à soi-même.
    acheteurs_distincts_min: int
    description: str


PALIERS = (
    Palier(
        niveau=0,
        acheteurs_distincts_min=0,
        code="nouvelle",
        libelle="Nouvelle boutique",
        delai_liberation_jours=7,
        plafond_sequestre=Decimal("150000"),
        livraisons_min=0,
        anciennete_jours_min=0,
        taux_litiges_perdus_max=Decimal("1"),
        description="Identité vérifiée, aucun historique. Prépaiement plafonné, fonds retenus 7 jours.",
    ),
    Palier(
        niveau=1,
        acheteurs_distincts_min=8,
        code="confirmee",
        libelle="Boutique confirmée",
        delai_liberation_jours=5,
        plafond_sequestre=Decimal("750000"),
        livraisons_min=10,
        anciennete_jours_min=30,
        taux_litiges_perdus_max=Decimal("0.10"),
        description="Dix livraisons confirmées sur un mois, peu de litiges perdus.",
    ),
    Palier(
        niveau=2,
        acheteurs_distincts_min=35,
        code="reconnue",
        libelle="Boutique reconnue",
        delai_liberation_jours=3,
        plafond_sequestre=Decimal("3000000"),
        livraisons_min=50,
        anciennete_jours_min=90,
        taux_litiges_perdus_max=Decimal("0.05"),
        description="Cinquante livraisons confirmées sur un trimestre.",
    ),
    Palier(
        niveau=3,
        acheteurs_distincts_min=120,
        code="etablie",
        libelle="Boutique établie",
        delai_liberation_jours=3,
        plafond_sequestre=None,
        livraisons_min=200,
        anciennete_jours_min=180,
        taux_litiges_perdus_max=Decimal("0.03"),
        description="Deux cents livraisons confirmées sur six mois. Le délai minimal couvre la médiation de 72 h (docs/08, §8).",
    ),
)

PAR_NIVEAU = {p.niveau: p for p in PALIERS}
CHOIX_PALIERS = [(p.niveau, p.libelle) for p in PALIERS]


def palier(niveau: int) -> Palier:
    """Le palier d'un niveau ; un niveau inconnu retombe au plus prudent, jamais au plus large."""
    return PAR_NIVEAU.get(niveau, PALIERS[0])


def palier_de(boutique) -> Palier:
    return palier(getattr(boutique, "palier_confiance", 0) or 0)
