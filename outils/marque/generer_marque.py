"""Génère les fichiers de la marque HyperMarché (docs/27-identite-graphique.md).

    python outils/marque/generer_marque.py

Produit, dans `static/marque/` :
  symbole*.svg, logo*.svg, logo-vertical*.svg, icone-app.svg, favicon.svg, motif-feston.svg
et `static/fonts/bricolage-grotesque-800-latin.woff2` (titrage du marché).

Le logotype est **vectorisé** : ses lettres sont des tracés extraits de Bricolage Grotesque (OFL),
graisse 800, taille optique 96. Le logo ne dépend donc d'aucune police installée — il s'affiche à
l'identique sur une enseigne peinte, un ticket thermique ou un téléphone de 2016.

Outils de développement seulement (absents de la production) : fonttools, brotli, uharfbuzz, et la
police source fournie par `npm install` (@fontsource-variable/bricolage-grotesque).
"""

from __future__ import annotations

import io
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "node_modules/@fontsource-variable/bricolage-grotesque/files/bricolage-grotesque-latin-standard-normal.woff2"
SORTIE = RACINE / "static" / "marque"

# --- Couleurs de la marque (docs/27, §4) ------------------------------------------------------
VERT = "#00806A"        # Vert Wouri
VERT_CLAIR = "#36B49B"  # Vert Wouri, version sur fond sombre
OR = "#E3A72E"          # Or Mboppi
EBENE = "#1C1C18"       # Ébène
IVOIRE = "#F7F6F1"      # Ivoire

# --- Symbole : l'étal (grille de 64) ---------------------------------------------------------
# Un auvent rayé à trois lés festonnés, et sous lui l'étal : deux poteaux et le comptoir, qui
# dessinent le H d'HyperMarché. Les festons sont des demi-disques de rayon 9 — le même rayon que les
# coins de l'icône d'application : une seule courbe dans toute la marque.
G = 64
AUVENT_X, AUVENT_Y, AUVENT_H, LE = 5, 8, 14, 18  # 3 lés de 18 → 54 de large
FESTON = LE / 2
COIN = 6


def auvent(couleurs: list[str], ecart: float = 0) -> str:
    """Trois lés ; `ecart` > 0 les sépare d'un filet (version monochrome)."""
    morceaux = []
    for i, couleur in enumerate(couleurs):
        x0 = AUVENT_X + i * LE + (ecart / 2 if i > 0 else 0)
        x1 = AUVENT_X + (i + 1) * LE - (ecart / 2 if i < 2 else 0)
        y0, y1 = AUVENT_Y, AUVENT_Y + AUVENT_H
        cx = AUVENT_X + i * LE + FESTON
        r = FESTON - (ecart / 2 if ecart else 0)
        haut_g = COIN if i == 0 else 0
        haut_d = COIN if i == 2 else 0
        d = (
            f"M{x0} {y0 + haut_g}"
            + (f"Q{x0} {y0} {x0 + haut_g} {y0}" if haut_g else "")
            + f"H{x1 - haut_d}"
            + (f"Q{x1} {y0} {x1} {y0 + haut_d}" if haut_d else "")
            + f"V{y1}"
            + f"H{cx + r}A{r} {r} 0 0 1 {cx - r} {y1}"
            + f"H{x0}Z"
        )
        morceaux.append(f'<path fill="{couleur}" d="{d}"/>')
    return "".join(morceaux)


def etal(couleur: str) -> str:
    """Les deux poteaux et le comptoir : le H."""
    return (
        f'<path fill="{couleur}" d="M12 35h9v23a2 2 0 0 1-2 2h-5a2 2 0 0 1-2-2zM43 35h9v23a2 2 0 0 1-2 2h-5a2 2 0 0 1-2-2zM21 43h22v7H21z"/>'
    )


def symbole(auvent_couleurs, etal_couleur, ecart=0) -> str:
    return auvent(auvent_couleurs, ecart) + etal(etal_couleur)


# --- Logotype --------------------------------------------------------------------------------
def police_instance() -> TTFont:
    police = TTFont(SOURCE)
    instantiateVariableFont(police, {"wght": 800, "opsz": 96, "wdth": 100}, inplace=True)
    return police


def mot(police: TTFont, texte: str, x: float, ligne: float, echelle: float, couleur: str, accent: str | None = None):
    """Tracés d'un mot, mis en forme par HarfBuzz (crénage compris). Renvoie (svg, largeur)."""
    tampon = io.BytesIO()
    saveur, police.flavor = police.flavor, None  # HarfBuzz lit du TrueType, pas du WOFF2
    police.save(tampon)
    police.flavor = saveur
    face = hb.Face(tampon.getvalue())
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(texte)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    glyphes = police.getGlyphSet()
    ordre = police.getGlyphOrder()
    glyf = police["glyf"]
    curseur = 0
    traces = {couleur: [], accent or couleur: []}
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        nom = ordre[info.codepoint]
        ox = x + (curseur + pos.x_offset) * echelle
        oy = ligne - pos.y_offset * echelle
        glyphe = glyf[nom]
        if accent and glyphe.isComposite():
            # « é » : la lettre dans la couleur du mot, l'accent dans l'or de la marque.
            for i, composant in enumerate(glyphe.components):
                stylo = SVGPathPen(glyphes)
                glyphes[composant.glyphName].draw(TransformPen(stylo, (echelle, 0, 0, -echelle, ox + composant.x * echelle, oy - composant.y * echelle)))
                traces[couleur if i == 0 else accent].append(stylo.getCommands())
        else:
            stylo = SVGPathPen(glyphes)
            glyphes[nom].draw(TransformPen(stylo, (echelle, 0, 0, -echelle, ox, oy)))
            traces[couleur].append(stylo.getCommands())
        curseur += pos.x_advance
    svg = "".join(f'<path fill="{c}" d="{"".join(d)}"/>' for c, d in traces.items() if d)
    return svg, curseur * echelle


def logotype(police, x, ligne, taille, hyper, marche, accent):
    upm = police["head"].unitsPerEm
    echelle = taille / upm
    svg1, l1 = mot(police, "Hyper", x, ligne, echelle, hyper)
    svg2, l2 = mot(police, "Marché", x + l1, ligne, echelle, marche, accent)
    return svg1 + svg2, l1 + l2


def ecrire(nom: str, largeur: float, hauteur: float, corps: str, titre: str) -> None:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largeur:.2f} {hauteur:.2f}" '
        f'width="{largeur:.0f}" height="{hauteur:.0f}" role="img" aria-label="{titre}">'
        f"<title>{titre}</title>{corps}</svg>\n"
    )
    (SORTIE / nom).write_text(svg)


def generer() -> None:
    SORTIE.mkdir(parents=True, exist_ok=True)
    police = police_instance()

    # Symbole seul.
    ecrire("symbole.svg", G, G, symbole([VERT, OR, VERT], VERT), "HyperMarché")
    ecrire("symbole-negatif.svg", G, G, symbole([VERT_CLAIR, OR, VERT_CLAIR], VERT_CLAIR), "HyperMarché")
    ecrire("symbole-ebene.svg", G, G, symbole([EBENE] * 3, EBENE, ecart=2), "HyperMarché")
    ecrire("symbole-blanc.svg", G, G, symbole(["#FFFFFF"] * 3, "#FFFFFF", ecart=2), "HyperMarché")

    # Logo horizontal : symbole à gauche, logotype aligné sur la ligne de base des poteaux.
    taille = 46
    ligne = 58  # pied des poteaux = ligne de base
    x_texte = G + 10
    for nom, couleurs, hyper, marche, accent in (
        ("logo.svg", ([VERT, OR, VERT], VERT), EBENE, VERT, OR),
        ("logo-negatif.svg", ([VERT_CLAIR, OR, VERT_CLAIR], VERT_CLAIR), "#FFFFFF", VERT_CLAIR, OR),
        ("logo-ebene.svg", ([EBENE] * 3, EBENE), EBENE, EBENE, EBENE),
        ("logo-blanc.svg", (["#FFFFFF"] * 3, "#FFFFFF"), "#FFFFFF", "#FFFFFF", "#FFFFFF"),
    ):
        ecart = 2 if nom in ("logo-ebene.svg", "logo-blanc.svg") else 0
        texte, largeur_texte = logotype(police, x_texte, ligne, taille, hyper, marche, accent)
        ecrire(nom, x_texte + largeur_texte + 4, G + 4, symbole(*couleurs, ecart=ecart) + texte, "HyperMarché")

    # Logo vertical : symbole centré au-dessus du logotype.
    taille_v = 40
    texte, largeur_texte = logotype(police, 0, 0, taille_v, EBENE, VERT, OR)
    largeur = max(largeur_texte, G) + 16
    x_symbole = (largeur - 64 * 1.4) / 2
    texte_v, _ = logotype(police, (largeur - largeur_texte) / 2, 64 * 1.4 + 52, taille_v, EBENE, VERT, OR)
    corps = f'<g transform="translate({x_symbole:.2f} 0) scale(1.4)">{symbole([VERT, OR, VERT], VERT)}</g>{texte_v}'
    ecrire("logo-vertical.svg", largeur, 64 * 1.4 + 64, corps, "HyperMarché")

    # Icône d'application : le symbole ivoire et or sur le vert, dans la zone sûre des icônes
    # adaptatives (80 % centraux) — Android peut la découper en cercle sans entamer l'étal.
    icone = (
        f'<rect width="512" height="512" fill="{VERT}"/>'
        f'<g transform="translate(96 92) scale(5)">{symbole([IVOIRE, OR, IVOIRE], IVOIRE)}</g>'
    )
    ecrire("icone-app.svg", 512, 512, icone, "HyperMarché")
    favicon = f'<rect width="64" height="64" rx="14" fill="{VERT}"/><g transform="translate(6 5) scale(0.82)">{symbole([IVOIRE, OR, IVOIRE], IVOIRE)}</g>'
    ecrire("favicon.svg", 64, 64, favicon, "HyperMarché")

    # Motif : la frise festonnée de l'auvent, en bande répétable (largeur 36 = deux festons).
    motif = (
        f'<path fill="{VERT}" d="M0 0H36V10H36A9 9 0 0 1 18 10A9 9 0 0 1 0 10Z"/>'
        f'<path fill="{OR}" d="M18 0H36V10A9 9 0 0 1 18 10Z" opacity="1"/>'
    )
    ecrire("motif-feston.svg", 36, 19, motif, "Frise festonnée HyperMarché")

    # Police de titrage du marché : instance statique 800, sous-ensemble latin.
    titrage = police_instance()
    options = Options()
    options.flavor = "woff2"
    options.layout_features = ["kern", "liga", "calt", "ss01"]
    sous = Subsetter(options)
    sous.populate(unicodes=list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)) + [0x152, 0x153, 0x2019, 0x201C, 0x201D, 0x2013, 0x2014, 0x2026, 0x20AC, 0xAB, 0xBB])
    sous.subset(titrage)
    titrage.flavor = "woff2"
    titrage.save(RACINE / "static" / "fonts" / "bricolage-grotesque-800-latin.woff2")


if __name__ == "__main__":
    generer()
    for f in sorted(SORTIE.iterdir()):
        print(f"{f.stat().st_size:>7}  {f.relative_to(RACINE)}")
