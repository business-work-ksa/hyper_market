"""Enveloppe les textes français d'un gabarit Django dans des balises de traduction.

    python outils/i18n/envelopper.py templates/stock.html [...]     # réécrit les fichiers
    python outils/i18n/envelopper.py --essai templates/stock.html   # montre sans écrire

Outil de migration, passé une fois sur chaque gabarit puis relu : le rendu français reste
identique (une chaîne littérale traduite garde son statut « sûre », rien n'est échappé de plus),
seule la langue anglaise change. Ce qu'il fait :

* un texte entre deux balises HTML → `{% translate "…" %}` ; s'il contient des variables
  (`{{ x }}`) ou plusieurs lignes → `{% blocktranslate [with …] trimmed %}…{% endblocktranslate %}` ;
* les attributs lus par un humain (`placeholder`, `title`, `aria-label`, `alt`, `data-libelle-*`)
  → valeur enveloppée ;
* `{% load i18n %}` ajouté si absent.

Ce qu'il ne touche pas : commentaires (`{# #}`, `{% comment %}`), `<script>`, `<style>`, ce qui
est déjà traduit, les textes sans mot (nombres, ponctuation, sigles seuls) et les noms propres de
la liste `INTACTS`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ATTRIBUTS = r"placeholder|title|aria-label|alt|data-libelle-[a-z-]+|data-chargement|label"
INTACTS = {
    "HyperMarché", "FCFA", "MTN", "MoMo", "MTN MoMo", "Orange Money", "OHADA", "SYSCOHADA", "CEMAC",
    "OAPI", "COBAC", "NIU", "RCCM", "SKU", "CNPS", "XAF", "KYC", "EAN", "HT", "TTC", "PDF", "CSV",
    "WhatsApp", "Douala", "Yaoundé", "OK", "FR", "EN", "N°", "Ctrl", "Alt", "Entrée", "Esc",
}
MOT = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿŒœ]{2,}")
VARIABLE = re.compile(r"\{\{\s*(.+?)\s*\}\}")


def _a_traduire(texte: str) -> bool:
    nu = VARIABLE.sub("", texte).strip()
    if not MOT.search(nu):
        return False
    if nu in INTACTS:
        return False
    mots = MOT.findall(nu)
    return not all(m in INTACTS or m.isupper() and len(m) <= 5 for m in mots)


def _litteral(texte: str) -> str:
    if '"' not in texte:
        return f'"{texte}"'
    if "'" not in texte:
        return f"'{texte}'"
    return '"' + texte.replace('"', '\\"') + '"'


def _alias(expression: str, pris: set) -> str:
    base = re.split(r"[|:]", expression)[0].strip()
    nom = re.sub(r"\W", "_", base.split(".")[-1]) or "valeur"
    if nom[0].isdigit():
        nom = "v" + nom
    candidat, i = nom, 2
    while candidat in pris:
        candidat = f"{nom}{i}"
        i += 1
    pris.add(candidat)
    return candidat


def _envelopper_texte(texte: str) -> str:
    """Un texte (avec ou sans variables) → balise de traduction, blancs extérieurs préservés."""
    debut = texte[: len(texte) - len(texte.lstrip())]
    fin = texte[len(texte.rstrip()):]
    coeur = texte.strip()
    variables = VARIABLE.findall(coeur)
    if not variables and "\n" not in coeur:
        return f"{debut}{{% translate {_litteral(coeur)} %}}{fin}"
    pris: set = set()
    alias = {}
    corps = coeur
    for expr in variables:
        if expr not in alias:
            alias[expr] = _alias(expr, pris)
    corps = VARIABLE.sub(lambda m: "{{ " + alias[m.group(1).strip()] + " }}", corps)
    avec = " with " + " ".join(f"{a}={e}" for e, a in alias.items()) if alias else ""
    return f"{debut}{{% blocktranslate{avec} trimmed %}}{corps}{{% endblocktranslate %}}{fin}"


JETON = re.compile(
    r"(\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}|<!--.*?-->|<(?:[A-Za-z!/][^<>]*?(?:\{[%{].*?[%}]\}[^<>]*?)*)>)",
    re.S,
)


def envelopper(source: str) -> str:
    morceaux = JETON.split(source)
    sortie = []
    texte_courant: list[str] = []
    profondeur_brute = None  # "comment", "script", "style", "blocktranslate", "verbatim"

    def vider():
        if not texte_courant:
            return
        bloc = "".join(texte_courant)
        texte_courant.clear()
        sortie.append(_envelopper_texte(bloc) if _a_traduire(bloc) else bloc)

    for i, m in enumerate(morceaux):
        est_jeton = i % 2 == 1
        if profondeur_brute:
            sortie.append(m)
            fin = {
                "comment": re.compile(r"\{%\s*endcomment\s*%\}"),
                "script": re.compile(r"</script\s*>", re.I),
                "style": re.compile(r"</style\s*>", re.I),
                "blocktranslate": re.compile(r"\{%\s*end(blocktranslate|blocktrans)\s*%\}"),
                "verbatim": re.compile(r"\{%\s*endverbatim\s*%\}"),
            }[profondeur_brute]
            if est_jeton and fin.match(m):
                profondeur_brute = None
            continue
        if not est_jeton:
            texte_courant.append(m)
            continue
        if m.startswith("{{"):
            texte_courant.append(m)
            continue
        vider()
        if m.startswith("{%"):
            nom = m[2:-2].strip().split(" ")[0]
            if nom in ("comment", "blocktranslate", "blocktrans", "verbatim"):
                profondeur_brute = {"blocktrans": "blocktranslate"}.get(nom, nom)
            sortie.append(m)
        elif m.startswith("{#") or m.startswith("<!--"):
            sortie.append(m)
        else:
            balise = m[1:].split()[0].lower().rstrip(">") if len(m) > 2 else ""
            if balise in ("script", "style"):
                profondeur_brute = balise
            sortie.append(_attributs(m))
    vider()
    resultat = "".join(sortie)
    if "{% load i18n" not in resultat and re.search(r"\{%\s*(block)?translate", resultat):
        resultat = _ajouter_load(resultat)
    return resultat


def _attributs(balise: str) -> str:
    def remplacer(m):
        nom, valeur = m.group(1), m.group(2)
        if "{" in valeur or not _a_traduire(valeur):
            return m.group(0)
        quote = "'" if "'" not in valeur else '"'
        if quote == '"':
            return m.group(0)  # valeur avec apostrophe dans un attribut entre guillemets : à la main
        return f'{nom}="{{% translate {quote}{valeur}{quote} %}}"'

    return re.sub(rf'\b({ATTRIBUTS})="([^"]*)"', remplacer, balise)


def _ajouter_load(texte: str) -> str:
    m = re.match(r"(\s*\{%\s*extends[^%]*%\}\s*\n?)", texte)
    if m:
        return texte[: m.end()] + "{% load i18n %}\n" + texte[m.end():]
    m = re.match(r"(\{%\s*load\s+)([^%]*)(%\})", texte)
    if m:
        return f"{m.group(1)}i18n {m.group(2)}{m.group(3)}" + texte[m.end():]
    return "{% load i18n %}" + texte


if __name__ == "__main__":
    essai = "--essai" in sys.argv
    for chemin in [a for a in sys.argv[1:] if not a.startswith("--")]:
        p = Path(chemin)
        avant = p.read_text()
        apres = envelopper(avant)
        if essai:
            print(apres)
        elif apres != avant:
            p.write_text(apres)
            print(f"{p} : {apres.count('translate') - avant.count('translate')} balises")
