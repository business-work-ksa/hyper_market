"""Les données en base, en français et en anglais.

L'interface se traduit par le catalogue (`config/locale/`). Les **données** — le nom d'un rayon,
d'une catégorie, d'un article, sa description — ne sont pas dans le catalogue : elles sont saisies
par la plateforme ou par le commerçant. Chacune porte donc un second champ, en anglais :
`libelle` et `libelle_en`, `description` et `description_en`.

Règles :

* **le français est la langue de référence** : `libelle` est obligatoire, `libelle_en`
  facultatif. Un champ anglais vide n'est jamais une erreur ;
* **à l'affichage, l'anglais s'il existe, sinon le français** (`traduit()`). Une page anglaise
  qui montre un nom d'article en français vaut mieux qu'une page qui ne montre rien ;
* **ce qui est enregistré pour mémoire ne se traduit pas** : un ticket, une écriture, une ligne
  de commande recopient le libellé du jour de la vente, dans la langue de référence.

Une autre langue s'ajoute par un champ `_xx` de plus et une entrée dans `settings.LANGUAGES` ;
rien ici ne suppose qu'il n'y en a que deux.
"""

from __future__ import annotations

from django.utils.translation import get_language

LANGUE_DE_REFERENCE = "fr"


def langue_courante() -> str:
    return (get_language() or LANGUE_DE_REFERENCE)[:2]


def nom_du_champ(champ: str, langue: str | None = None) -> str:
    """`libelle` en français, `libelle_en` en anglais : le nom de la colonne à lire."""
    langue = langue or langue_courante()
    return champ if langue == LANGUE_DE_REFERENCE else f"{champ}_{langue}"


def traduit(objet, champ: str = "libelle") -> str:
    """La valeur dans la langue de la page, ou en français si elle n'a pas été saisie."""
    if objet is None:
        return ""
    if isinstance(objet, dict):
        lire = objet.get
    else:
        def lire(nom, defaut=""):
            return getattr(objet, nom, defaut)
    langue = langue_courante()
    if langue != LANGUE_DE_REFERENCE:
        valeur = lire(nom_du_champ(champ, langue), "")
        if valeur:
            return valeur
    return lire(champ, "") or ""


class Bilingue:
    """Mixin de modèle : `libelle_affiche` et `description_affiche`, lus dans la langue de la page.

    Le modèle déclare lui-même ses champs `libelle_en` (et `description_en`) ; le mixin ne fait
    que les lire.
    """

    @property
    def libelle_affiche(self) -> str:
        return traduit(self, "libelle")

    @property
    def description_affiche(self) -> str:
        return traduit(self, "description")
