"""Illustrations d'arrière-plan du marché (docs/27, §7).

    python outils/marque/generer_illustrations.py

Produit `static/marque/illustrations/` : `marche.svg` (scène de l'accueil) et `rayon-<code>.svg`
(une par rayon, plus `rayon-defaut.svg`). Vectorielles, quelques kilo-octets chacune : sur 3G, une
photo de héros coûte 200 Ko, ces scènes en coûtent 5.

Même grammaire que le logo : formes pleines, la courbe du feston, les couleurs de la marque et
leurs teintes. Pas de visage, pas de personnage : la place est aux étals et aux marchandises.
Elles ne remplacent pas les photos réelles des commerçants (docs/27, §7), elles habillent ce qui
n'en a pas encore.
"""

from __future__ import annotations

import random
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SORTIE = RACINE / "static" / "marque" / "illustrations"

VERT, VERT_F, VERT_C, VERT_P = "#00806A", "#006656", "#36B49B", "#D2F2E9"
OR, OR_F, OR_C, OR_P = "#E3A72E", "#A96D0E", "#F2D993", "#F9EDCB"
EBENE, PIERRE, PIERRE_C, IVOIRE, BLANC = "#1C1C18", "#7D796E", "#E7E5DD", "#F7F6F1", "#FFFFFF"
TERRE, TERRE_C = "#C2683C", "#F3D9C9"  # latérite : seulement dans les illustrations
BLEU, BLEU_C = "#2F6C8F", "#D5E6EF"     # wax, ciel du soir : seulement dans les illustrations


def svg(largeur, hauteur, corps, titre=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largeur} {hauteur}" '
        f'preserveAspectRatio="xMidYMid slice" role="img" aria-label="{titre}">{corps}</svg>\n'
    )


def festons(x, y, largeur, r, couleurs):
    """Bord d'auvent : une bande et ses demi-disques alternés."""
    morceaux = []
    n = max(1, round(largeur / (2 * r)))
    pas = largeur / n
    for i in range(n):
        c = couleurs[i % len(couleurs)]
        x0 = x + i * pas
        morceaux.append(
            f'<path fill="{c}" d="M{x0:.1f} {y}h{pas:.1f}v0a{pas / 2:.1f} {pas / 2:.1f} 0 0 1-{pas:.1f} 0z"/>'
        )
    return "".join(morceaux)


def auvent(x, y, largeur, hauteur, couleurs, r=None):
    """Auvent rayé (bandes verticales) et son bord festonné."""
    r = r or hauteur * 0.45
    n = max(2, round(largeur / (2 * r)))
    pas = largeur / n
    corps = []
    for i in range(n):
        corps.append(f'<rect x="{x + i * pas:.1f}" y="{y}" width="{pas + 0.5:.1f}" height="{hauteur}" fill="{couleurs[i % 2]}"/>')
    corps.append(festons(x, y + hauteur, largeur, pas / 2, couleurs))
    return "".join(corps)


def etal(x, sol, largeur, hauteur, couleurs, marchandises, poteau=EBENE):
    """Un étal : auvent, deux poteaux, comptoir, marchandises."""
    haut = sol - hauteur
    h_auvent = hauteur * 0.2
    comptoir_y = sol - hauteur * 0.36
    corps = [
        f'<rect x="{x + 6}" y="{haut + h_auvent}" width="7" height="{sol - haut - h_auvent}" fill="{poteau}" opacity=".85"/>',
        f'<rect x="{x + largeur - 13}" y="{haut + h_auvent}" width="7" height="{sol - haut - h_auvent}" fill="{poteau}" opacity=".85"/>',
        auvent(x - 8, haut, largeur + 16, h_auvent, couleurs),
        f'<rect x="{x}" y="{comptoir_y}" width="{largeur}" height="{sol - comptoir_y}" rx="4" fill="{PIERRE_C}"/>',
        f'<rect x="{x}" y="{comptoir_y}" width="{largeur}" height="9" rx="3" fill="{PIERRE}" opacity=".45"/>',
        marchandises(x + 12, comptoir_y, largeur - 24),
    ]
    return "".join(corps)


# --- Marchandises ------------------------------------------------------------------------------
def tas_de_fruits(x, y, largeur, couleurs=(TERRE, OR, VERT_C)):
    rnd = random.Random(int(x * 7 + y))
    corps = []
    r = 9
    rangs = 3
    for rang in range(rangs):
        n = int((largeur - rang * 2 * r) / (2 * r))
        for i in range(n):
            cx = x + r + rang * r + i * 2 * r
            cy = y - r - rang * r * 1.6
            corps.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{rnd.choice(couleurs)}"/>')
    return "".join(corps)


def cartons(x, y, largeur):
    corps = []
    l = largeur / 3
    for i, (h, c) in enumerate(((34, OR_C), (48, TERRE_C), (28, OR_C))):
        corps.append(f'<rect x="{x + i * l + 2:.1f}" y="{y - h}" width="{l - 4:.1f}" height="{h}" rx="2" fill="{c}"/>')
        corps.append(f'<rect x="{x + i * l + 2:.1f}" y="{y - h + h / 2 - 2:.1f}" width="{l - 4:.1f}" height="4" fill="{PIERRE}" opacity=".35"/>')
    return "".join(corps)


def flacons(x, y, largeur):
    corps = []
    n = int(largeur / 22)
    teintes = (VERT_C, OR, BLEU, TERRE, VERT)
    for i in range(n):
        h = 30 + (i * 13) % 22
        cx = x + i * 22 + 11
        c = teintes[i % len(teintes)]
        corps.append(f'<rect x="{cx - 7}" y="{y - h}" width="14" height="{h}" rx="5" fill="{c}"/>')
        corps.append(f'<rect x="{cx - 4}" y="{y - h - 8}" width="8" height="9" rx="2" fill="{EBENE}" opacity=".8"/>')
    return "".join(corps)


def pagnes(x, y, largeur, haut):
    """Tissus wax suspendus sous l'auvent."""
    corps = []
    n = int(largeur / 34)
    motifs = ((BLEU, OR), (TERRE, IVOIRE), (VERT, OR_C), (OR, VERT_F))
    for i in range(n):
        fond, motif = motifs[i % len(motifs)]
        x0 = x + i * 34
        h = 70 + (i % 3) * 14
        corps.append(f'<rect x="{x0}" y="{haut}" width="28" height="{h}" rx="2" fill="{fond}"/>')
        for k in range(int(h / 18)):
            corps.append(f'<circle cx="{x0 + 14}" cy="{haut + 12 + k * 18}" r="5" fill="{motif}"/>')
    return "".join(corps)


# --- Scène de l'accueil -----------------------------------------------------------------------
def scene_marche():
    L, H = 1600, 640
    sol = 560
    c = [
        f'<defs><linearGradient id="ciel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{OR_P}"/><stop offset=".7" stop-color="{IVOIRE}"/></linearGradient></defs>',
        f'<rect width="{L}" height="{H}" fill="url(#ciel)"/>',
        f'<circle cx="1270" cy="170" r="120" fill="{OR_C}" opacity=".55"/>',
    ]
    # Ville au loin : immeubles bas, tons pierre et vert pâle.
    rnd = random.Random(7)
    x = 520
    while x < L:
        l = rnd.choice((70, 90, 110, 130))
        h = rnd.choice((120, 160, 200, 240))
        teinte = rnd.choice((PIERRE_C, VERT_P, "#EFE7D6"))
        c.append(f'<rect x="{x}" y="{sol - 120 - h}" width="{l}" height="{h + 120}" fill="{teinte}"/>')
        for fy in range(sol - 100 - h, sol - 140, 28):
            for fx in range(x + 12, x + l - 16, 24):
                c.append(f'<rect x="{fx}" y="{fy}" width="10" height="12" fill="{BLANC}" opacity=".6"/>')
        x += l + rnd.choice((8, 14, 20))
    # Câbles et fanions.
    c.append(f'<path d="M520 230 Q1060 300 1600 220" stroke="{PIERRE}" stroke-width="2" fill="none" opacity=".5"/>')
    for i in range(18):
        t = i / 17
        px = 520 + t * 1080
        py = 230 + (1 - (2 * t - 1) ** 2) * 50 - t * 10
        couleur = (VERT, OR, TERRE, BLEU)[i % 4]
        c.append(f'<path d="M{px:.0f} {py:.0f}l10 0l-5 16z" fill="{couleur}"/>')
    # Rangée d'étals.
    rang = [
        (600, 230, 300, (VERT, IVOIRE), lambda x, y, l: tas_de_fruits(x, y, l)),
        (850, 210, 270, (OR, IVOIRE), lambda x, y, l: flacons(x, y, l)),
        (1080, 250, 320, (TERRE, IVOIRE), lambda x, y, l: cartons(x, y, l)),
        (1350, 230, 290, (BLEU, IVOIRE), lambda x, y, l: tas_de_fruits(x, y, l, (OR, VERT_C, OR_F))),
    ]
    for x, larg, haut, couleurs, marchandise in rang:
        c.append(etal(x, sol, larg, haut, couleurs, marchandise))
    c.append(pagnes(870, sol - 250 + 50, 170, sol - 250 + 50))
    # Sol et premier plan.
    c.append(f'<rect y="{sol}" width="{L}" height="{H - sol}" fill="{PIERRE_C}"/>')
    c.append(f'<rect y="{sol}" width="{L}" height="6" fill="{PIERRE}" opacity=".3"/>')
    # Parasol au premier plan, coupé par le bord : la profondeur sans personnage.
    c.append(f'<rect x="1530" y="300" width="8" height="{sol - 300 + 30}" fill="{EBENE}"/>')
    c.append(f'<path d="M1380 320 Q1534 170 1690 320 Z" fill="{VERT}"/>')
    c.append(festons(1380, 320, 310, 26, (VERT, OR)))
    # Paniers au sol.
    for bx, couleur in ((700, OR_F), (1240, TERRE)):
        c.append(f'<path d="M{bx} {sol + 4}h70l-8 40h-54z" fill="{couleur}"/>')
        c.append(tas_de_fruits(bx + 6, sol + 6, 58, (OR, VERT_C)))
    return svg(L, H, "".join(c), "Une rue de marché : étals sous des auvents rayés")


# --- Rayons -----------------------------------------------------------------------------------
def cadre_rayon(fond, rond, couleurs_auvent, objets, titre):
    L, H = 800, 500
    corps = [
        f'<rect width="{L}" height="{H}" fill="{fond}"/>',
        f'<circle cx="410" cy="290" r="220" fill="{rond}"/>',
        auvent(0, 0, L, 54, couleurs_auvent, r=25),
        f'<ellipse cx="410" cy="452" rx="250" ry="18" fill="{EBENE}" opacity=".08"/>',
        # Les objets sont dessinés autour de x = 560 ; centrés ici pour que la vignette se
        # recadre sans couper le sujet (cartes carrées, bandeaux larges).
        f'<g transform="translate(-150 0)">{objets}</g>',
    ]
    return svg(L, H, "".join(corps), titre)


def r_cosmetique():
    o = []
    for x, h, c, b in ((430, 190, VERT_C, EBENE), (510, 250, OR, EBENE), (600, 160, TERRE_C, VERT_F), (680, 210, BLEU_C, EBENE)):
        o.append(f'<rect x="{x}" y="{450 - h}" width="64" height="{h}" rx="22" fill="{c}"/>')
        o.append(f'<rect x="{x + 20}" y="{450 - h - 34}" width="24" height="36" rx="6" fill="{b}" opacity=".85"/>')
        o.append(f'<rect x="{x + 12}" y="{450 - h * .55}" width="40" height="34" rx="6" fill="{BLANC}" opacity=".7"/>')
    o.append(f'<rect x="760" y="380" width="70" height="70" rx="35" fill="{VERT}"/>')
    return cadre_rayon(OR_P, "#F6E3B8", (VERT, OR_P), "".join(o), "Cosmétiques sur un comptoir")


def r_mode():
    o = [f'<path d="M560 120 q0-26 22-26 q22 0 22 22 l-22 18" stroke="{EBENE}" stroke-width="7" fill="none"/>',
         f'<path d="M440 210 L582 148 L724 210 L700 236 L582 196 L464 236 Z" fill="{PIERRE}"/>',
         f'<path d="M480 226 L684 226 L716 450 L448 450 Z" fill="{BLEU}"/>']
    for k in range(5):
        for j in range(4):
            o.append(f'<circle cx="{500 + j * 56}" cy="{262 + k * 40}" r="11" fill="{OR}"/>')
    o.append(f'<path d="M330 330 h110 l14 120 h-138 z" fill="{TERRE}"/><path d="M360 330 q25-50 50 0" stroke="{EBENE}" stroke-width="7" fill="none"/>')
    return cadre_rayon(BLEU_C, "#C2DAE6", (BLEU, IVOIRE), "".join(o), "Vêtements en wax sur un cintre")


def r_quincaillerie():
    o = [f'<path d="M420 450 l20-150 h170 l20 150 z" fill="{PIERRE_C}"/><rect x="430" y="300" width="190" height="22" fill="{PIERRE}" opacity=".5"/>',
         f'<rect x="466" y="356" width="118" height="40" rx="4" fill="{VERT}"/>',
         f'<rect x="650" y="220" width="26" height="230" rx="6" fill="{TERRE}" transform="rotate(14 663 335)"/>',
         f'<rect x="604" y="196" width="120" height="44" rx="8" fill="{EBENE}" transform="rotate(14 663 335)"/>',
         f'<path d="M740 450 v-110 a40 40 0 0 1 80 0 v110" fill="none" stroke="{OR}" stroke-width="22"/>']
    return cadre_rayon(VERT_P, "#BCE9DC", (VERT, OR), "".join(o), "Sac de ciment, marteau et clé")


def r_pieces():
    o = [f'<circle cx="520" cy="330" r="120" fill="{EBENE}"/><circle cx="520" cy="330" r="70" fill="{PIERRE}"/><circle cx="520" cy="330" r="22" fill="{PIERRE_C}"/>']
    for k in range(10):
        import math
        a = k * math.pi / 5
        o.append(f'<rect x="{688 + 70 * math.cos(a) - 14:.1f}" y="{300 + 70 * math.sin(a) - 14:.1f}" width="28" height="28" rx="4" fill="{OR}" transform="rotate({k * 36} {688 + 70 * math.cos(a):.1f} {300 + 70 * math.sin(a):.1f})"/>')
    o.append(f'<circle cx="688" cy="300" r="62" fill="{OR}"/><circle cx="688" cy="300" r="24" fill="{OR_P}"/>')
    o.append(f'<rect x="740" y="380" width="22" height="70" rx="4" fill="{VERT}"/><rect x="733" y="360" width="36" height="26" rx="4" fill="{PIERRE_C}"/>')
    return cadre_rayon(PIERRE_C, "#D9D5C9", (EBENE, OR), "".join(o), "Pneu, engrenage et bougie")


def r_maison():
    o = [f'<path d="M430 450 q-20-120 70-130 q90 10 70 130z" fill="{VERT}"/><path d="M500 320 q-50-90 0-160 q50 70 0 160" fill="{VERT_C}"/><path d="M500 330 q-80-60-60-140 q60 40 60 140" fill="{VERT_F}"/>',
         f'<path d="M610 450 h220 v-80 a20 20 0 0 0-20-20 h-180 a20 20 0 0 0-20 20 z" fill="{TERRE}"/>',
         f'<rect x="640" y="300" width="70" height="60" rx="14" fill="{OR}"/><rect x="726" y="300" width="70" height="60" rx="14" fill="{BLEU_C}"/>',
         f'<path d="M750 120 h60 l18 70 h-96 z" fill="{OR_C}"/><rect x="777" y="190" width="6" height="110" fill="{EBENE}"/>']
    return cadre_rayon(TERRE_C, "#EDC7B2", (TERRE, IVOIRE), "".join(o), "Plante, canapé et lampe")


def r_electronique():
    o = [f'<rect x="440" y="160" width="150" height="290" rx="24" fill="{EBENE}"/><rect x="452" y="186" width="126" height="230" rx="10" fill="{VERT_C}"/>',
         f'<rect x="470" y="210" width="90" height="16" rx="8" fill="{BLANC}" opacity=".7"/><rect x="470" y="240" width="60" height="16" rx="8" fill="{BLANC}" opacity=".5"/>',
         f'<path d="M640 330 a90 90 0 0 1 180 0" fill="none" stroke="{TERRE}" stroke-width="20"/>',
         f'<rect x="626" y="320" width="40" height="80" rx="16" fill="{TERRE}"/><rect x="794" y="320" width="40" height="80" rx="16" fill="{TERRE}"/>',
         f'<rect x="660" y="420" width="140" height="30" rx="10" fill="{OR}"/>']
    return cadre_rayon(BLEU_C, "#C2DAE6", (BLEU, OR_P), "".join(o), "Téléphone et casque audio")


def r_electromenager():
    o = [f'<rect x="420" y="130" width="170" height="320" rx="16" fill="{BLANC}" stroke="{PIERRE_C}" stroke-width="4"/><rect x="420" y="240" width="170" height="6" fill="{PIERRE_C}"/>',
         f'<rect x="440" y="170" width="10" height="50" rx="5" fill="{PIERRE}"/><rect x="440" y="270" width="10" height="70" rx="5" fill="{PIERRE}"/>',
         f'<path d="M640 450 h110 l-12-40 h-86 z" fill="{EBENE}"/><path d="M656 410 l-10-180 h118 l-10 180 z" fill="{VERT_C}" opacity=".85"/><rect x="646" y="216" width="118" height="20" rx="6" fill="{EBENE}"/>',
         f'<circle cx="800" cy="250" r="56" fill="none" stroke="{OR}" stroke-width="10"/><path d="M800 250 l0-50 a50 50 0 0 1 43 25 z" fill="{OR}"/><rect x="795" y="306" width="10" height="144" fill="{EBENE}"/>']
    return cadre_rayon(VERT_P, "#BCE9DC", (VERT, IVOIRE), "".join(o), "Réfrigérateur, blender et ventilateur")


def r_alimentaire():
    o = [f'<path d="M410 330 h300 l-30 120 h-240 z" fill="{OR_F}"/>',
         f'<path d="M410 330 h300" stroke="{EBENE}" stroke-width="6" opacity=".4"/>']
    o.append(tas_de_fruits(430, 330, 260, (TERRE, "#D8452B", OR)))
    o.append(f'<path d="M560 240 q60-90 150-60 q-40 20-150 60" fill="{VERT}"/><path d="M590 250 q60-80 140-40 q-40 16-140 40" fill="{VERT_C}"/>')
    o.append(f'<path d="M740 450 v-130 q40-30 80 0 v130 z" fill="{IVOIRE}" stroke="{PIERRE}" stroke-width="3"/><rect x="752" y="360" width="56" height="30" fill="{TERRE}"/>')
    return cadre_rayon(OR_P, "#F6E3B8", (VERT, OR), "".join(o), "Panier de fruits, plantain et sac de riz")


def r_defaut():
    o = [etal(440, 450, 340, 300, (VERT, OR), lambda x, y, l: tas_de_fruits(x, y, l))]
    return cadre_rayon(IVOIRE, VERT_P, (VERT, OR), "".join(o), "Un étal du marché")


RAYONS = {
    "cosmetique-beaute": r_cosmetique,
    "mode-accessoires": r_mode,
    "quincaillerie": r_quincaillerie,
    "pieces-detachees": r_pieces,
    "maison-decoration": r_maison,
    "petit-electronique": r_electronique,
    "electromenager": r_electromenager,
    "alimentaire": r_alimentaire,
    "defaut": r_defaut,
}


def generer():
    SORTIE.mkdir(parents=True, exist_ok=True)
    (SORTIE / "marche.svg").write_text(scene_marche())
    for code, dessin in RAYONS.items():
        (SORTIE / f"rayon-{code}.svg").write_text(dessin())


if __name__ == "__main__":
    generer()
    for f in sorted(SORTIE.iterdir()):
        print(f"{f.stat().st_size:>7}  {f.relative_to(RACINE)}")
