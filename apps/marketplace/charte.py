"""Charte graphique d'une boutique : du logo à une palette utilisable.

Un commerçant téléverse son logo. Il en attend que « son » logiciel prenne ses
couleurs. Le problème est qu'**une couleur de logo n'est presque jamais une
couleur d'interface** : elle a été choisie pour être imprimée sur une enseigne,
pas pour porter du texte, un bouton et une barre de graphique sur deux fonds.

Le document 19 raconte l'erreur exacte que ce module existe pour éviter : le
premier teal du produit, `#0F6F5C`, a été rejeté par le validateur de palette
avec un chroma de 0,088, sous le plancher de 0,1. À l'œil il paraissait bon ; sur
une barre de graphique, il « lisait gris ». C'est le genre de faute qu'on ne voit
pas et qu'un commerçant ne saura pas diagnostiquer.

Ce que fait ce module
---------------------

Il applique au logo du commerçant **exactement les règles que le produit
s'applique à lui-même** :

1. **plancher de chroma** — en dessous, la couleur lit gris ;
2. **contraste ≥ 3:1** sur la surface de fond, en clair comme en sombre ;
3. **une variante sombre choisie, pas inversée** — un teal foncé sur fond noir
   disparaît ; il faut l'éclaircir, pas le retourner.

Et quand la couleur ne passe pas, il ne la refuse pas : **il l'ajuste et le
dit.** Refuser le logo d'un commerçant parce que son bleu manque de chroma est
une réponse de logiciel ; lui montrer la couleur retenue et pourquoi elle diffère
d'un cheveu est une réponse de fournisseur.

Pourquoi les calculs sont écrits ici plutôt qu'importés
------------------------------------------------------

La conversion sRGB → OKLab tient en trente lignes et n'a pas d'états d'âme. Une
dépendance de plus sur un chemin qui tourne à chaque téléversement de logo
coûterait plus cher que ces trente lignes — et le projet n'ajoute pas de
dépendance sans preuve (docs/09, §1).
"""

import math

__all__ = [
    "POLICES",
    "PALETTE_PAR_DEFAUT",
    "couleurs_du_logo",
    "chroma",
    "contraste",
    "ajuster",
    "variante_sombre",
    "teinte_claire",
    "charte_depuis_couleur",
]

# Plancher de chroma OKLCH : en dessous, une couleur porteuse de données lit
# gris sur une barre. Valeur du document 19, §2.1.
PLANCHER_CHROMA = 0.10

# Contraste minimal d'une couleur de marque sur le fond de page.
CONTRASTE_MINIMAL = 3.0

# Le mode sombre demande davantage, et ce n'est pas une prudence de principe :
# le produit lui-même y a atteint 6,5:1 avec son teal clair. Un seuil de 3:1
# laisserait passer des teintes foncées sur fond noir, conformes et illisibles.
CONTRASTE_SOMBRE = 4.5

# En dessous, la couleur est neutre : elle n'a pas de teinte à préserver, et
# lui en inventer une reviendrait à choisir la marque du commerçant à sa place.
SEUIL_NEUTRE = 0.02

# Au-delà, on ne lit pas le logo : on refuse de le développer en mémoire. Voir
# `couleurs_du_logo`. 25 mégapixels, c'est 5000 × 5000 — très au-delà de ce que
# demande un logo, et très en deçà de ce qui tue un processus.
PIXELS_MAX = 25_000_000

FOND_CLAIR = "#f4f3ee"
FOND_SOMBRE = "#0e110e"

PALETTE_PAR_DEFAUT = {
    "marque": "#00806a",
    "marque_sombre": "#2fa98e",
}

# Piles système uniquement : aucun fichier de police n'est téléchargé. Sur une
# connexion facturée au mégaoctet, une police de titrage à 90 Ko est un coût que
# le commerçant paie sans le savoir, à chaque visiteur. Le choix porte donc sur
# le caractère de la pile, pas sur une fonderie.
POLICES = [
    (
        "systeme",
        "Système (recommandée)",
        'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    ),
    (
        "humaniste",
        "Humaniste — chaleureuse, lisible en petit",
        '"Segoe UI", Candara, "Trebuchet MS", "Gill Sans", system-ui, sans-serif',
    ),
    (
        "geometrique",
        "Géométrique — nette, moderne",
        'Futura, "Century Gothic", "Avenir Next", "Nimbus Sans", system-ui, sans-serif',
    ),
    (
        "serif",
        "Serif — traditionnelle, artisanale",
        'Georgia, "Times New Roman", "Liberation Serif", serif',
    ),
    (
        "condensee",
        "Condensée — beaucoup de texte, peu de place",
        '"Roboto Condensed", "Liberation Sans Narrow", "Arial Narrow", system-ui, sans-serif',
    ),
]

CHOIX_POLICES = [(code, libelle) for code, libelle, _ in POLICES]
PILES_POLICES = {code: pile for code, _, pile in POLICES}


# ---------------------------------------------------------------------------
# Conversions de couleur
# ---------------------------------------------------------------------------
def _vers_rvb(hexa: str) -> tuple[float, float, float]:
    hexa = (hexa or "").strip().lstrip("#")
    if len(hexa) == 3:
        hexa = "".join(c * 2 for c in hexa)
    if len(hexa) != 6:
        raise ValueError(f"Couleur illisible : « {hexa} ».")
    return tuple(int(hexa[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _vers_hexa(rvb) -> str:
    """Notation `#rrggbb`, **en minuscules**.

    Ce n'est pas une préférence de style : la spécification HTML exige d'un
    `<input type="color">` une « couleur simple valide », c'est-à-dire six
    chiffres hexadécimaux **minuscules**. En majuscules, le sélecteur ignore la
    valeur et repart du noir — le commerçant rouvre sa charte et ne retrouve pas
    sa couleur.
    """
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rvb)


def _lineaire(canal: float) -> float:
    return canal / 12.92 if canal <= 0.04045 else ((canal + 0.055) / 1.055) ** 2.4


def _compresse(canal: float) -> float:
    return canal * 12.92 if canal <= 0.0031308 else 1.055 * canal ** (1 / 2.4) - 0.055


def _vers_oklab(hexa: str) -> tuple[float, float, float]:
    r, v, b = (_lineaire(c) for c in _vers_rvb(hexa))
    l = math.cbrt(0.4122214708 * r + 0.5363325363 * v + 0.0514459929 * b)
    m = math.cbrt(0.2119034982 * r + 0.6806995451 * v + 0.1073969566 * b)
    s = math.cbrt(0.0883024619 * r + 0.2817188376 * v + 0.6299787005 * b)
    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def _rvb_brut(L: float, a: float, b: float) -> tuple[float, float, float]:
    """Canaux sRGB **non écrêtés** — ils peuvent sortir de [0, 1]."""
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        _compresse(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
        _compresse(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
        _compresse(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
    )


def _depuis_oklab(L: float, a: float, b: float) -> str:
    return _vers_hexa(_rvb_brut(L, a, b))


def _oklch(hexa: str) -> tuple[float, float, float]:
    L, a, b = _vers_oklab(hexa)
    return L, math.hypot(a, b), math.atan2(b, a)


def _depuis_oklch(L: float, C: float, h: float) -> str:
    """Ramène (L, C, h) dans le gamut sRGB **en réduisant le chroma**.

    Le réflexe est d'écrêter les trois canaux dans [0, 1]. C'est faux, et ça se
    voit : sur un or `#FFD700` assombri, l'écrêtage indépendant des canaux
    déplaçait la teinte de sept degrés — un jaune qui vire à l'olive. Le
    commerçant ne reconnaissait plus sa couleur, ce qui est exactement ce que ce
    module promet de ne jamais faire.

    La réduction de chroma, elle, conserve la teinte **et** la clarté : elle
    désature jusqu'à ce que la couleur existe sur un écran, et pas au-delà. Le
    prix est une couleur un peu moins vive à l'extrême du gamut ; c'est le bon
    prix — l'autre était une couleur différente.
    """
    if _dans_le_gamut(L, C, h):
        return _depuis_oklab(L, C * math.cos(h), C * math.sin(h))

    bas, haut = 0.0, C
    for _ in range(24):
        milieu = (bas + haut) / 2
        if _dans_le_gamut(L, milieu, h):
            bas = milieu
        else:
            haut = milieu
    return _depuis_oklab(L, bas * math.cos(h), bas * math.sin(h))


def _dans_le_gamut(L: float, C: float, h: float) -> bool:
    canaux = _rvb_brut(L, C * math.cos(h), C * math.sin(h))
    # Une demi-valeur de quantification de tolérance : au-delà, la couleur
    # n'existe pas sur un écran sRGB.
    return all(-0.002 <= canal <= 1.002 for canal in canaux)


def chroma(hexa: str) -> float:
    """Chroma OKLCH. En dessous de 0,10, la couleur lit gris sur une barre."""
    return _oklch(hexa)[1]


def _luminance(hexa: str) -> float:
    r, v, b = (_lineaire(c) for c in _vers_rvb(hexa))
    return 0.2126 * r + 0.7152 * v + 0.0722 * b


def contraste(premier: str, second: str) -> float:
    """Rapport de contraste WCAG entre deux couleurs."""
    a, b = _luminance(premier), _luminance(second)
    clair, sombre = max(a, b), min(a, b)
    return (clair + 0.05) / (sombre + 0.05)


# ---------------------------------------------------------------------------
# Ajustement
# ---------------------------------------------------------------------------
def _corriger(hexa: str, *, fond: str, minimum: float) -> tuple[str, list[str]]:
    """Rend la couleur lisible sur `fond`, sans jamais toucher à sa teinte.

    La teinte est la seule chose que le commerçant reconnaît dans son logo. Une
    marque dont on décale le bleu vers le violet n'est plus sa marque : on ne
    joue donc que sur la clarté et la saturation.

    **Les deux corrections se combattent au bord du gamut sRGB**, et c'est un
    défaut trouvé en vérifiant le module sur ses propres exemples : remonter le
    chroma puis assombrir reprend une partie de ce qu'on venait de donner, parce
    qu'une teinte très saturée n'existe pas à toutes les clartés. On itère donc,
    et si les deux règles restent inconciliables, **on le dit** au lieu de rendre
    une couleur qui a l'air validée.
    """
    L, C, h = _oklch(hexa)
    C = max(C, PLANCHER_CHROMA)
    vers_le_clair = _luminance(fond) < 0.2
    motifs = []

    couleur = _depuis_oklch(L, C, h)
    for _ in range(80):
        if contraste(couleur, fond) >= minimum:
            break
        L = min(1.0, L + 0.01) if vers_le_clair else max(0.0, L - 0.01)
        couleur = _depuis_oklch(L, C, h)

    if _oklch(hexa)[1] < PLANCHER_CHROMA:
        motifs.append("saturation remontée : trop pâle, elle aurait lu gris sur un graphe")
    if abs(L - _oklch(hexa)[0]) > 0.005:
        motifs.append(
            "éclaircie pour le fond sombre" if vers_le_clair
            else "assombrie : le texte blanc dessus n'aurait pas été lisible"
        )
    if chroma(couleur) < PLANCHER_CHROMA - 0.005:
        # Le gamut a repris ce que la remontée avait donné : c'est une limite de
        # l'écran, pas une erreur de saisie, et l'annoncer vaut mieux que de
        # laisser croire que la règle est tenue.
        motifs.append(
            "poussée à la limite de ce qu'un écran peut afficher dans cette teinte"
        )
    return couleur, motifs


def ajuster(hexa: str, *, fond: str = FOND_CLAIR) -> tuple[str, str]:
    """Couleur utilisable en mode clair, et ce qui a été corrigé."""
    couleur, motifs = _corriger(hexa, fond=fond, minimum=CONTRASTE_MINIMAL)
    return couleur, " ; ".join(motifs)


def variante_sombre(hexa: str) -> str:
    """Version pour fond sombre — éclaircie, **jamais inversée**.

    Inverser une couleur de marque produit une autre couleur. Ce qu'il faut,
    c'est la même teinte remontée en clarté jusqu'à se détacher du fond : c'est
    la règle que le produit s'applique à lui-même (docs/19, §2.1), et le seuil
    retenu est celui qu'il a lui-même atteint — son teal sombre `#2FA98E` tient
    6,5:1, bien au-delà des 3:1 qui suffisent en mode clair. Un seuil bas
    produirait ici des teals foncés sur fond noir, techniquement conformes et
    illisibles en boutique.
    """
    couleur, _ = _corriger(hexa, fond=FOND_SOMBRE, minimum=CONTRASTE_SOMBRE)
    return couleur


def teinte_claire(hexa: str, *, sombre: bool = False) -> str:
    """Fond de puce : la même teinte, très désaturée et très claire (ou très foncée)."""
    _, C, h = _oklch(hexa)
    return _depuis_oklch(0.18 if sombre else 0.94, min(C, 0.06), h)


def charte_depuis_couleur(hexa: str) -> dict:
    """Palette complète et utilisable, à partir d'une seule couleur de marque.

    Une couleur **neutre** — un logo noir et blanc, un gris — est refusée plutôt
    qu'inventée. Lui donner une teinte reviendrait à tirer une marque au sort
    dans le bruit d'arrondi : le commerçant garde la palette du produit, et on
    lui dit pourquoi.
    """
    if chroma(hexa) < SEUIL_NEUTRE:
        return {
            **PALETTE_PAR_DEFAUT,
            "teinte": "#e2f0ec",
            "teinte_sombre": "#14251f",
            "motif": (
                "cette couleur est neutre : lui inventer une teinte reviendrait à "
                "choisir votre marque à votre place. La palette HyperMarché est "
                "conservée."
            ),
            "ajustee": True,
            "refusee": True,
        }

    marque, motif = ajuster(hexa)
    return {
        "marque": marque,
        "marque_sombre": variante_sombre(marque),
        "teinte": teinte_claire(marque),
        "teinte_sombre": teinte_claire(marque, sombre=True),
        "motif": motif,
        "ajustee": bool(motif),
        "refusee": False,
    }


# ---------------------------------------------------------------------------
# Lecture du logo
# ---------------------------------------------------------------------------
def couleurs_du_logo(fichier, *, combien: int = 5) -> list[str]:
    """Couleurs dominantes d'un logo, les plus utilisables d'abord.

    Les gris et les quasi-blancs sont écartés : un logo est majoritairement fait
    de fond et de contour noir, et proposer « noir » comme couleur de marque à un
    commerçant serait une lecture correcte et un conseil inutile.

    Le tri final privilégie le chroma, pas la surface occupée. La couleur qui
    fait la marque est rarement celle qui couvre le plus de pixels — c'est celle
    qui saute aux yeux.
    """
    from PIL import Image

    try:
        image = Image.open(fichier)

        # Deuxième verrou, après celui du formulaire (`CharteForm.clean_logo`).
        # Il n'est pas redondant : cette fonction est aussi appelée sur des logos
        # **déjà en base**, téléversés avant que la borne existe ou par un autre
        # chemin. Et le coût d'un oubli n'est pas une image de travers, c'est un
        # processus tué par le noyau — `convert("RGBA")` sur douze mille pixels
        # de côté demande plus d'un gigaoctet.
        #
        # Pillow, lui, se contente d'un avertissement au-delà de 89 mégapixels,
        # puis développe l'image quand même.
        largeur, hauteur = image.size
        if largeur * hauteur > PIXELS_MAX:
            return []

        # Réduit **avant** la conversion : `draft` demande au décodeur JPEG de
        # sortir directement une image plus petite, et `thumbnail` travaille par
        # bandes. Convertir d'abord reviendrait à payer le plein format en
        # mémoire, ce que tout ce verrou cherche à éviter.
        image.draft("RGB", (320, 320))
        image.thumbnail((160, 160))
        image = image.convert("RGBA")
    except Exception:
        return []

    # Sur fond blanc : un logo transparent doit être lu comme il sera vu.
    fond = Image.new("RGBA", image.size, (255, 255, 255, 255))
    image = Image.alpha_composite(fond, image).convert("RGB")

    reduite = image.quantize(colors=16, method=Image.Quantize.MEDIANCUT).convert("RGB")
    candidats = []
    for compte, couleur in sorted(reduite.getcolors(4096) or [], reverse=True):
        hexa = _vers_hexa(tuple(c / 255 for c in couleur))
        try:
            L, C, _ = _oklch(hexa)
        except ValueError:  # pragma: no cover — une couleur sortie de Pillow est valide
            continue
        if C < 0.04 or L > 0.93 or L < 0.08:
            continue  # gris, blanc cassé, noir : lisibles mais sans identité
        candidats.append((C, compte, hexa))

    candidats.sort(reverse=True)
    return [hexa for _, _, hexa in candidats[:combien]]
