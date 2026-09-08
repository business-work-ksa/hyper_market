"""Filtres et balises d'affichage du back-office."""

from decimal import Decimal, InvalidOperation

from django import template
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

ESPACE_FINE = "\u202f"  # espace fine insécable : séparateur de milliers et signe %


@register.filter
def fcfa(valeur, decimales=0):
    """Formate un montant en francs CFA : 1 250 000 plutôt que 1250000.00.

    Le franc CFA n'a pas de subdivision en usage courant : on n'affiche donc pas
    de décimales, même si les calculs intermédiaires en conservent.
    """
    if valeur is None:
        return "—"
    try:
        montant = Decimal(valeur)
    except (InvalidOperation, TypeError, ValueError):
        return "—"

    signe = "-" if montant < 0 else ""
    montant = abs(montant)
    entier = int(montant)
    groupes = f"{entier:,}".replace(",", ESPACE_FINE)

    if decimales:
        reste = (montant - entier).quantize(Decimal("0.01"))
        return f"{signe}{groupes},{str(reste).split('.')[1]}"
    return f"{signe}{groupes}"


@register.filter
def quantite(valeur):
    """Affiche une quantité sans décimales inutiles : 12 et non 12.0000."""
    if valeur is None:
        return "—"
    try:
        nombre = Decimal(valeur).normalize()
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    entier = nombre.to_integral_value()
    if nombre == entier:
        return f"{int(entier):,}".replace(",", ESPACE_FINE)
    return f"{nombre:f}".rstrip("0").rstrip(".").replace(".", ",")


@register.filter
def pourcent(valeur, decimales=1):
    if valeur is None:
        return "—"
    try:
        # Typographie française : espace insécable avant le signe pour-cent.
        return f"{Decimal(valeur):.{decimales}f}".replace(".", ",") + ESPACE_FINE + "%"
    except (InvalidOperation, TypeError, ValueError):
        return "—"


@register.filter
def initiales(texte):
    if not texte:
        return "?"
    mots = [m for m in str(texte).split() if m]
    if len(mots) == 1:
        return mots[0][:2].upper()
    return (mots[0][0] + mots[1][0]).upper()


@register.simple_tag
def nav(nom_url, icone, libelle, page_courante, pastille=None):
    """Entrée de navigation du rail, avec état actif et pastille d'alerte."""
    try:
        cible = reverse(nom_url)
    except NoReverseMatch:
        cible = "#"

    classe = "lien lien--actif" if page_courante == nom_url else "lien"
    aria = ' aria-current="page"' if page_courante == nom_url else ""

    marqueur = ""
    if pastille:
        marqueur = format_html(
            '<span class="lien__pastille" aria-label="{} alerte(s)">{}</span>', pastille, pastille
        )

    return format_html(
        '<a class="{}" href="{}"{}><svg aria-hidden="true"><use href="#{}"></use></svg>'
        "<span>{}</span>{}</a>",
        classe,
        cible,
        mark_safe(aria),
        icone,
        libelle,
        marqueur,
    )


@register.simple_tag
def puce_stock(niveau):
    """Puce d'état de stock — **icône + libellé**, jamais la couleur seule.

    Règle imposée par le système de design : `--alerte` passe sous 3:1 sur fond
    clair, l'icône et le mot portent donc le sens (docs/19, §3).
    """
    if niveau.quantite <= 0:
        return format_html(
            '<span class="puce puce--critique"><svg aria-hidden="true"><use href="#ic-rupture">'
            "</use></svg>Rupture</span>"
        )
    if niveau.sous_le_seuil:
        return format_html(
            '<span class="puce puce--alerte"><svg aria-hidden="true"><use href="#ic-alerte">'
            "</use></svg>Sous le seuil</span>"
        )
    return format_html(
        '<span class="puce puce--bon"><svg aria-hidden="true"><use href="#ic-check">'
        "</use></svg>En stock</span>"
    )
