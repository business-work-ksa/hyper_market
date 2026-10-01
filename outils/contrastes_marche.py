"""Vérifie les contrastes WCAG 2.1 des rôles de couleur du marché (static/src/marche.css).

    python outils/contrastes_marche.py

Échoue (code 1) si une paire passe sous son seuil : 4,5:1 pour du texte, 3:1 pour un bord de
composant ou un indicateur de focus (critères 1.4.3 et 1.4.11).
"""

import re
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "static" / "src" / "marche.css"

PAIRES = [
    # (premier plan, fond, seuil, usage)
    ("encre", "fond", 4.5, "texte courant sur la page"),
    ("encre", "surface", 4.5, "texte courant sur une carte"),
    ("encre-muette", "fond", 4.5, "texte secondaire sur la page"),
    ("encre-muette", "surface", 4.5, "texte secondaire sur une carte"),
    ("encre-muette", "surface-creuse", 4.5, "texte secondaire sur un fond creux"),
    ("sur-marque", "marque", 4.5, "libellé d'un bouton principal"),
    ("sur-marque", "marque-survol", 4.5, "bouton principal survolé"),
    ("marque-encre", "marque-douce", 4.5, "bouton secondaire, badge de marque"),
    ("sur-accent", "accent", 4.5, "bouton d'achat (or)"),
    ("accent-encre", "accent-doux", 4.5, "badge or"),
    ("succes-encre", "succes-doux", 4.5, "badge succès"),
    ("alerte-encre", "alerte-doux", 4.5, "badge alerte"),
    ("erreur-encre", "erreur-doux", 4.5, "badge erreur"),
    ("erreur-encre", "surface", 4.5, "message d'erreur sous un champ"),
    ("marque", "surface", 3.0, "lien, icône de marque"),
    ("filet-fort", "surface", 3.0, "bord d'un champ"),
    ("focus", "fond", 3.0, "anneau de focus"),
    ("focus", "surface", 3.0, "anneau de focus sur une carte"),
]


def luminance(rvb):
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, v, b = (canal(c) for c in rvb)
    return 0.2126 * r + 0.7152 * v + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def roles(bloc: str) -> dict:
    return {
        nom: tuple(int(x) for x in valeur.split())
        for nom, valeur in re.findall(r"--hm-([a-z-]+):\s*(\d+ \d+ \d+);", bloc)
    }


def main() -> int:
    css = SOURCE.read_text()
    clair = roles(css.split("@media (prefers-color-scheme: dark)")[0])
    sombre = roles(css.split(':root[data-theme="dark"] {', 1)[1].split("}", 1)[0])
    echecs = 0
    for mode, valeurs in (("clair", clair), ("sombre", sombre)):
        print(f"\n— Mode {mode}")
        for avant, fond, seuil, usage in PAIRES:
            ratio = contraste(valeurs[avant], valeurs[fond])
            ok = ratio >= seuil
            echecs += not ok
            print(f"  {'OK ' if ok else 'NON'} {ratio:5.2f}:1 ≥ {seuil}  {avant} / {fond} — {usage}")
    print(f"\n{echecs} paire(s) sous le seuil.")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
