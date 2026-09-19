"""Retrouver un article sous un autre nom, et lui trouver des équivalents.

La scène, en officine : quelqu'un demande du **Doliprane**, la pharmacie n'a que
de l'Efferalgan. La scène, en pièces détachées : un client pose un filtre marqué
**W 712/75** sur le comptoir, le vendeur n'a que la référence Toyota. Dans les
deux cas la même question — « c'est la même chose, ou non ? » — et dans les deux
cas, aujourd'hui, la même réponse perdue faute de savoir le dire.

Deux fonctions, et rien de plus :

  — `chercher` : trouver un article par n'importe laquelle de ses désignations ;
  — `equivalents_de` : les autres articles qui partagent une désignation.

**L'équivalence se déduit, elle ne se stocke pas.** Deux articles sont
équivalents parce qu'ils portent la même désignation, pas parce que quelqu'un a
déclaré la paire. Une table de paires aurait demandé N² déclarations et se serait
désynchronisée au premier article ajouté ; ici, saisir la DCI d'un médicament
suffit à le rattacher à tous ses confrères — y compris ceux qui arriveront
demain.

**Le nom commercial ne fait pas équivalence.** « Doliprane » est un autre nom du
*même* article, pas le nom d'un autre article : le poser en équivalence
proposerait au pharmacien de substituer une boîte par elle-même. Seuls la DCI et
la référence d'un autre fabricant rapprochent deux articles distincts.
"""

from django.db.models import Q

from apps.catalog.models import Designation, Variante

__all__ = ["TYPES_EQUIVALENTS", "chercher", "equivalents_de", "designations_de", "valeurs_connues"]

# Ce qui rapproche deux articles **différents**. Le nom commercial en est exclu :
# il désigne le même article autrement, il ne le relie à aucun autre.
TYPES_EQUIVALENTS = (Designation.DCI, Designation.REFERENCE)


def chercher(terme: str):
    """Variantes qui portent cette désignation, dans la boutique courante.

    La comparaison est faite sur la forme normalisée **et** en sous-chaîne : un
    vendeur tape ce qu'il lit, et ce qu'il lit est souvent partiel — « 712/75 »
    plutôt que « W 712/75 ». Exiger l'exactitude ferait échouer la recherche
    précisément dans le cas où elle sert.
    """
    propre = Designation.normaliser(terme)
    if not propre:
        return Variante.objects.none()

    portees = Designation.objects.filter(valeur__icontains=propre).values("variante_id")
    return (
        Variante.objects.filter(pk__in=portees)
        .select_related("produit")
        .order_by("produit__libelle")
    )


def equivalents_de(variante):
    """Les autres articles qui partagent au moins une désignation avec celui-ci.

    Renvoie des couples `(variante, désignations partagées)` : dire « le
    paracétamol 500 mg les rapproche » vaut mieux que de poser une liste
    d'articles sans expliquer pourquoi ils y sont. C'est aussi ce qui permet au
    pharmacien de vérifier le rapprochement avant de proposer la boîte.
    """
    siennes = list(
        Designation.objects.filter(variante=variante, type__in=TYPES_EQUIVALENTS)
    )
    if not siennes:
        return []

    correspond = Q()
    for designation in siennes:
        correspond |= Q(type=designation.type, valeur=designation.valeur)

    partagees: dict = {}
    autres = (
        Designation.objects.filter(correspond)
        .exclude(variante_id=variante.pk)
        .select_related("variante__produit")
    )
    for designation in autres:
        entree = partagees.setdefault(
            designation.variante_id, {"variante": designation.variante, "par": []}
        )
        entree["par"].append(designation)

    return sorted(partagees.values(), key=lambda e: str(e["variante"]))


def designations_de(variante):
    """Toutes les désignations d'un article, les plus structurantes d'abord."""
    return Designation.objects.filter(variante=variante)


def valeurs_connues(type_designation: str) -> list[str]:
    """Désignations déjà saisies dans la boutique, pour la saisie assistée.

    Même piège que les marques de véhicules : `order_by()` est vidé avant le
    `distinct()`, parce que l'ordre par défaut du modèle ajoute ses colonnes au
    `SELECT` et ferait ressortir « PARACÉTAMOL 500 MG » autant de fois qu'il y a
    de boîtes qui le portent.
    """
    return sorted(
        Designation.objects.filter(type=type_designation)
        .order_by()
        .values_list("valeur", flat=True)
        .distinct()
    )
