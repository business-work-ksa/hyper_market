"""Remplace les accords faits par `|pluralize` dans `{% blocktranslate with … %}` par un vrai pluriel.

    python outils/i18n/pluriels.py templates/**/*.html

`{% blocktranslate with n=x n2=x|pluralize %}{{ n }} article{{ n2 }}{% endblocktranslate %}` ne se
traduit pas : l'anglais n'accorde pas les adjectifs, et le catalogue exige que la traduction reprenne
chaque variable. Devient `{% blocktranslate count n=x %}{{ n }} article{% plural %}{{ n }}
articles{% endblocktranslate %}` — le traducteur voit les deux formes, et chaque langue applique sa
propre règle de pluriel. Un bloc dont les accords portent sur deux nombres différents est laissé tel
quel et signalé : il se réécrit à la main.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BLOC = re.compile(r"\{% blocktranslate (?P<options>[^%]*?) %\}(?P<corps>.*?)\{% endblocktranslate %\}", re.S)
AFFECTATION = re.compile(r'(\w+)=((?:"[^"]*"|\'[^\']*\'|[^\s"\'])+)')


def _formes(argument: str | None) -> tuple[str, str]:
    if argument is None:
        return "", "s"
    argument = argument.strip("\"'")
    if "," in argument:
        singulier, pluriel = argument.split(",", 1)
        return singulier, pluriel
    return "", argument


def convertir(source: str, chemin: str = "") -> str:
    def remplacer(m):
        options = m.group("options")
        if "count " in options or "|pluralize" not in options:
            return m.group(0)
        trimmed = " trimmed" if re.search(r"\btrimmed\b", options) else ""
        affectations = AFFECTATION.findall(options.replace("with ", "", 1))
        accords, autres = {}, []
        for nom, expr in affectations:
            pm = re.fullmatch(r'(.+?)\|pluralize(?::("[^"]*"|\'[^\']*\'))?', expr)
            if pm:
                accords[nom] = (pm.group(1), _formes(pm.group(2)))
            else:
                autres.append((nom, expr))
        bases = {base for base, _ in accords.values()}
        if len(bases) != 1:
            print(f"{chemin} : accords sur plusieurs nombres, à reprendre à la main :\n  {m.group(0)[:160]}")
            return m.group(0)
        base = bases.pop()
        compteur = next((nom for nom, expr in autres if expr == base), None)
        if compteur:
            autres = [(n, e) for n, e in autres if n != compteur]
        else:
            compteur = "compte"
        corps = m.group("corps")
        singulier, pluriel = corps, corps
        for nom, (_, (s, p)) in accords.items():
            motif = re.compile(r"\{\{\s*" + nom + r"\s*\}\}")
            singulier = motif.sub(s, singulier)
            pluriel = motif.sub(p, pluriel)
        avec = (" with " + " ".join(f"{n}={e}" for n, e in autres)) if autres else ""
        return (
            f"{{% blocktranslate count {compteur}={base}{avec}{trimmed} %}}{singulier}"
            f"{{% plural %}}{pluriel}{{% endblocktranslate %}}"
        )

    return BLOC.sub(remplacer, source)


if __name__ == "__main__":
    for a in sys.argv[1:]:
        p = Path(a)
        avant = p.read_text()
        apres = convertir(avant, a)
        if apres != avant:
            p.write_text(apres)
            print(f"{a} : {apres.count('{% plural %}') - avant.count('{% plural %}')} pluriels")
