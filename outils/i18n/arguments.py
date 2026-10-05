"""Enveloppe dans `_()` les textes passés en argument de balise de gabarit.

    python outils/i18n/arguments.py templates/**/*.html

`envelopper.py` traite le texte entre deux balises ; il laisse les arguments, qui ne sont pas
tous du texte (noms d'URL, classes, identifiants). Celui-ci ne touche qu'aux arguments qui se
lisent, par leur nom : `titre=`, `aide=`, `creer_libelle=`… d'un `{% include %}`, le libellé et la
forme courte d'un `{% nav %}`, et les valeurs de repli `|default:"…"` qui sont des mots.
`_("…")` y est compris par Django (traduit au rendu) et par `makemessages` (extrait).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CLES_LUES = {
    "a11y", "action_libelle", "aide", "aria", "avertissement_suppression", "creer_libelle",
    "indice", "innocent", "libelle", "libelle_confirmer", "modifier_libelle",
    "pas_quand", "quand", "responsive", "supprimer_libelle", "texte", "titre", "verifier", "vide",
    "court",
}
MOT = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


def _envelopper(valeur: str, guillemet: str) -> str:
    return f"_({guillemet}{valeur}{guillemet})"


def _arguments(contenu: str) -> str:
    def cle(m):
        nom, g, valeur = m.group(1), m.group(2), m.group(3)
        if nom not in CLES_LUES or not MOT.search(valeur):
            return m.group(0)
        return f"{nom}={_envelopper(valeur, g)}"

    return re.sub(r"(?<![\w(])(\w+)=(['\"])((?:(?!\2).)*)\2", cle, contenu)


def convertir(source: str) -> str:
    def include(m):
        return m.group(1) + _arguments(m.group(2)) + m.group(3)

    source = re.sub(r"(\{%\s*include\s+['\"][^'\"]+['\"]\s+with\s+)(.*?)(%\})", include, source, flags=re.S)

    def nav(m):
        args = m.group(2)
        # nav 'url' 'icone' 'Libellé' page …  : le troisième littéral est le libellé.
        litteraux = list(re.finditer(r"(?<![\w(=])(['\"])((?:(?!\1).)*)\1", args))
        if len(litteraux) >= 3:
            l3 = litteraux[2]
            args = args[: l3.start()] + _envelopper(l3.group(2), l3.group(1)) + args[l3.end():]
        return m.group(1) + _arguments(args) + m.group(3)

    source = re.sub(r"(\{%\s*nav\s+)(.*?)(%\})", nav, source, flags=re.S)

    def defaut(m):
        g, valeur = m.group(1), m.group(2)
        # Un mot en minuscules sans espace ni accent est un code (« primary », « md », « fr »).
        if not MOT.search(valeur) or valeur == "HyperMarché" or re.fullmatch(r"[a-z0-9_-]+", valeur):
            return m.group(0)
        return f"|default:{_envelopper(valeur, g)}"

    return re.sub(r"\|default:(['\"])((?:(?!\1).)*)\1", defaut, source)


if __name__ == "__main__":
    for a in sys.argv[1:]:
        p = Path(a)
        avant = p.read_text()
        apres = convertir(avant)
        if apres != avant:
            p.write_text(apres)
            print(f"{a} : {apres.count('_(') - avant.count('_(')} arguments")
