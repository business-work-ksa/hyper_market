"""`{{ rayon|traduit }}`, `{{ produit|traduit:"description" }}` : la donnée dans la langue de la page.

Chargé d'office dans tous les gabarits (`TEMPLATES[...]["OPTIONS"]["builtins"]`). Accepte un
objet ou un dictionnaire ; sans valeur anglaise, rend le français (`apps/core/bilingue.py`).
"""

from django import template

from apps.core.bilingue import traduit as _traduit

register = template.Library()


@register.filter
def traduit(objet, champ="libelle"):
    return _traduit(objet, champ)
