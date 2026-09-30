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


@register.filter
def taux(valeur, decimales=2):
    """Affiche un **taux stocké en fraction** : 0.1925 → « 19,25 % ».

    `pourcent` attend un nombre déjà exprimé en pour-cent (la marge, l'écart).
    Un taux de TVA est rangé en base comme une fraction ; passé tel quel à
    `pourcent`, il s'affichait « 0,19 % » sur la fiche publique d'un article.
    Les zéros de fin sont retirés : 19,25 % mais 5,5 % et 0 %.
    """
    if valeur is None:
        return "—"
    try:
        nombre = (Decimal(valeur) * 100).quantize(Decimal(1).scaleb(-int(decimales)))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    texte = f"{nombre:f}"
    if "." in texte:
        texte = texte.rstrip("0").rstrip(".")
    return texte.replace(".", ",") + ESPACE_FINE + "%"


@register.filter
def teinte(texte):
    """Angle de teinte stable (0-359) tiré d'un texte — le nom d'un commerçant.

    Sert aux vignettes de la vitrine quand un article n'a pas de photo : chaque
    commerçant garde la même teinte d'une page à l'autre, et l'œil regroupe ses
    articles sans lire. Un FNV-1a plutôt que `hash()`, que Python randomise à
    chaque démarrage : la teinte doit survivre à un redéploiement.
    """
    total = 0x811C9DC5
    for octet in str(texte or "").encode("utf-8"):
        total = ((total ^ octet) * 0x01000193) & 0xFFFFFFFF
    # Huit teintes choisies plutôt que 360 tirées au hasard : deux commerçants
    # voisins ne tombent pas sur deux roses indiscernables, et aucune ne vire au
    # criard (sable, argile, olive, sauge, lagon, ciel, lavande, prune).
    return TEINTES_VIGNETTE[total % len(TEINTES_VIGNETTE)]


TEINTES_VIGNETTE = (32, 14, 70, 135, 178, 208, 250, 320)


@register.filter
def monogramme(texte):
    """Deux lettres pour la vignette d'un article sans photo : « Ba » pour
    « Baguette 250 g », « Ch » pour « Chargeur rapide ».

    Pas `initiales` : sur un libellé de produit, les initiales de deux mots
    donnent « B2 » ou « DÀ ». Les deux premières lettres du premier mot se
    lisent comme une abréviation, et restent distinctes d'un article à l'autre.
    """
    for mot in str(texte or "").split():
        lettres = "".join(c for c in mot if c.isalpha())
        if lettres:
            return (lettres[:1].upper() + lettres[1:2].lower())
    return "?"


@register.simple_tag
def nav(nom_url, icone, libelle, page_courante, pastille=None, court=None):
    """Entrée de navigation du rail, avec état actif et pastille d'alerte.

    `court` : forme brève du libellé pour la barre d'onglets mobile
    (« Accueil » pour « Tableau de bord »). Le libellé long reste dans la page,
    masqué à l'écran mais lu par un lecteur d'écran ; la forme courte, elle, est
    cachée aux technologies d'assistance pour ne pas être annoncée deux fois.
    """
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

    if court:
        texte = format_html(
            '<span class="lien__long">{}</span><span class="lien__court" aria-hidden="true">{}</span>',
            libelle,
            court,
        )
    else:
        texte = format_html("<span>{}</span>", libelle)

    return format_html(
        '<a class="{}" href="{}"{}><svg aria-hidden="true"><use href="#{}"></use></svg>'
        "{}{}</a>",
        classe,
        cible,
        mark_safe(aria),
        icone,
        texte,
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
