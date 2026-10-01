"""Balises du marché : icônes et petits assemblages répétés dans les gabarits de la vitrine."""

from django import template
from django.utils.html import format_html

from apps.backoffice.templatetags.hm import ESPACE_FINE
from apps.backoffice.templatetags.hm import fcfa as fcfa_backoffice

register = template.Library()


@register.simple_tag
def icone(nom: str, classes: str = "size-5", libelle: str = ""):
    """Une icône du sprite (`partials/icones.html`, `marche/icones.html`).

    Sans `libelle`, l'icône est décorative et cachée aux lecteurs d'écran (`aria-hidden`) : le texte
    à côté porte le sens. Avec un `libelle`, elle devient une image nommée — à réserver aux icônes
    seules, sans texte, comme une coche « Identité vérifiée ».
    """
    if libelle:
        return format_html(
            '<svg class="{}" role="img" aria-label="{}"><title>{}</title><use href="#ic-{}"></use></svg>',
            classes,
            libelle,
            libelle,
            nom,
        )
    return format_html(
        '<svg class="{}" aria-hidden="true" focusable="false"><use href="#ic-{}"></use></svg>', classes, nom
    )


MOTS_VIDES = {"de", "du", "des", "la", "le", "les", "et", "a", "à", "en", "&", "and", "of", "the"}


@register.filter
def sigle(texte) -> str:
    """Deux lettres pour un rayon ou une enseigne : « Cosmétique & beauté » → « CB ».

    Les mots de liaison et les signes (« & », « de », « et ») sont sautés : « C& » ne dit rien.
    """
    mots = [m for m in str(texte or "").split() if m.lower() not in MOTS_VIDES and any(c.isalpha() for c in m)]
    if not mots:
        return "?"
    if len(mots) == 1:
        return mots[0][:2].upper()
    return (mots[0][0] + mots[1][0]).upper()


@register.filter
def fcfa(valeur, decimales=0):
    """Le montant du back-office, avec une espace insécable **ordinaire** entre les milliers.

    L'espace fine (U+202F) n'est pas dessinée par toutes les polices d'Android d'entrée de gamme, et
    les prix serrés de la vitrine (`tracking-tight`) l'écrasaient : « 34000 » au lieu de « 34 000 ».
    Chargée après `hm` (`{% load hm marche %}`), cette version remplace l'autre dans le marché.
    """
    return str(fcfa_backoffice(valeur, decimales)).replace(ESPACE_FINE, "\u00a0")


@register.filter
def delai(rang, pas: int = 60):
    """Retard d'apparition en cascade (`--delai`), plafonné : la douzième carte n'attend pas 720 ms."""
    try:
        return f"{min(int(rang), 8) * int(pas)}ms"
    except (TypeError, ValueError):
        return "0ms"
