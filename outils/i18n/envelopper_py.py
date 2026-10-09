"""Enveloppe les textes français du code Python dans `gettext` (outil de migration, relu ensuite).

    python outils/i18n/envelopper_py.py apps/backoffice/views.py [...]

Cibles, et seulement elles (ce que l'utilisateur lit) :
* `messages.success|error|info|warning(request, "…")` ;
* les arguments `label=`, `help_text=`, `empty_label=` et les `ValidationError("…")`, `add_error(…, "…")` ;
* `raise QuelqueChoseRefuse|Impossible|Invalide|Indisponible|Erreur("…")` — ces messages
  remontent tels quels à l'écran ;
* dans un `models.py`, les libellés des listes de choix `[(CODE, "Libellé"), …]`.

Une f-chaîne devient `_("… %(nom)s …") % {"nom": …}` : le traducteur voit la phrase entière.
Dans une fonction : `gettext` (la langue de la requête) ; au niveau d'une classe ou du module :
`gettext_lazy` (nom complet : `makemessages` ne reconnaît pas d'alias ; évalué à l'affichage).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

EXCEPTIONS = re.compile(r"(Refuse|Refusee|Impossible|Invalide|Indisponible|Erreur|Interdit|Bloque)$")
KWARGS = {"label", "help_text", "empty_label"}


def _texte(node) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(re.search(r"[A-Za-zÀ-ÿ]{2,}", node.value))
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.Constant) and re.search(r"[A-Za-zÀ-ÿ]{2,}", v.value) for v in node.values)
    return False


def _nom(expr: ast.AST, pris: dict) -> str:
    if isinstance(expr, ast.Name):
        base = expr.id
    elif isinstance(expr, ast.Attribute):
        base = expr.attr
    elif isinstance(expr, ast.Call):
        f = expr.func
        base = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "valeur")
    elif isinstance(expr, ast.Subscript):
        base = "element"
    else:
        base = "valeur"
    base = base.strip("_") or "valeur"
    nom, i = base, 2
    while nom in pris:
        nom = f"{base}{i}"
        i += 1
    return nom


def _remplacement(node, source: str, fonction: str) -> str:
    if isinstance(node, ast.Constant):
        return f"{fonction}({ast.get_source_segment(source, node)})"
    morceaux, valeurs = [], {}
    for v in node.values:
        if isinstance(v, ast.Constant):
            morceaux.append(v.value.replace("%", "%%"))
        else:
            expr_src = ast.get_source_segment(source, v.value)
            if v.format_spec is not None or v.conversion != -1:
                spec = "".join(c.value for c in v.format_spec.values) if v.format_spec else ""
                conv = {115: "str", 114: "repr", 97: "ascii"}.get(v.conversion)
                expr_src = f"{conv}({expr_src})" if conv else expr_src
                expr_src = f'format({expr_src}, "{spec}")' if spec else expr_src
            existant = next((k for k, s in valeurs.items() if s == expr_src), None)
            cle = existant or _nom(v.value, valeurs)
            valeurs[cle] = expr_src
            morceaux.append(f"%({cle})s")
    gabarit = "".join(morceaux)
    litteral = repr(gabarit)
    dico = ", ".join(f'"{k}": {s}' for k, s in valeurs.items())
    return f"{fonction}({litteral}) % {{{dico}}}"


class Collecteur(ast.NodeVisitor):
    def __init__(self, est_modele: bool):
        self.cibles = []  # (node, dans_fonction)
        self.profondeur_fonction = 0
        self.est_modele = est_modele

    def visit_FunctionDef(self, node):
        self.profondeur_fonction += 1
        self.generic_visit(node)
        self.profondeur_fonction -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def _ajouter(self, node):
        if node is not None and _texte(node) and not _deja(node):
            self.cibles.append((node, self.profondeur_fonction > 0))

    def visit_Call(self, node):
        f = node.func
        nom = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "messages" \
                and nom in ("success", "error", "info", "warning", "debug") and len(node.args) >= 2:
            self._ajouter(node.args[1])
        if nom == "ValidationError" and node.args:
            self._ajouter(node.args[0])
        if nom == "add_error" and len(node.args) >= 2:
            self._ajouter(node.args[1])
        for kw in node.keywords:
            if kw.arg in KWARGS:
                self._ajouter(kw.value)
        self.generic_visit(node)

    def visit_Raise(self, node):
        exc = node.exc
        if isinstance(exc, ast.Call) and exc.args:
            f = exc.func
            nom = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if EXCEPTIONS.search(nom):
                self._ajouter(exc.args[0])
        self.generic_visit(node)

    def visit_Assign(self, node):
        if self.est_modele and self.profondeur_fonction == 0 and isinstance(node.value, (ast.List, ast.Tuple)):
            for el in node.value.elts:
                if isinstance(el, ast.Tuple) and len(el.elts) == 2 and isinstance(el.elts[1], ast.Constant) \
                        and isinstance(el.elts[1].value, str):
                    self._ajouter(el.elts[1])
        self.generic_visit(node)


def _deja(node) -> bool:
    return False


def _deja_enveloppe(source: str, node) -> bool:
    avant = source[: _decalage(source, node.lineno, node.col_offset)].rstrip()
    return bool(re.search(r"(_|_l|gettext|gettext_lazy|ngettext|pgettext)\($", avant))


def _decalage(source: str, ligne: int, col: int) -> int:
    lignes = source.splitlines(keepends=True)
    return sum(len(l) for l in lignes[: ligne - 1]) + len(lignes[ligne - 1][:col].encode()) - (
        len(lignes[ligne - 1][:col].encode()) - len(lignes[ligne - 1][:col])
    )


def _offset(source_bytes: bytes, ligne: int, col_octets: int, lignes_offsets) -> int:
    return lignes_offsets[ligne - 1] + col_octets


def traiter(chemin: Path) -> int:
    source = chemin.read_text()
    arbre = ast.parse(source)
    collecteur = Collecteur(est_modele=chemin.name == "models.py")
    collecteur.visit(arbre)
    if not collecteur.cibles:
        return 0
    # Les positions d'ast sont en octets UTF-8 : on travaille sur les octets.
    octets = source.encode()
    offsets, total = [], 0
    for l in source.splitlines(keepends=True):
        offsets.append(total)
        total += len(l.encode())
    remplacements = []
    besoin = {"_": False, "gettext_lazy": False}
    for node, dans_fonction in collecteur.cibles:
        debut = offsets[node.lineno - 1] + node.col_offset
        fin = offsets[node.end_lineno - 1] + node.end_col_offset
        avant = octets[:debut].decode(errors="ignore").rstrip()
        if re.search(r"(\b_|\b_l|gettext|gettext_lazy|ngettext|pgettext|gettext_noop)\($", avant):
            continue
        fonction = "_" if dans_fonction else "gettext_lazy"
        besoin[fonction] = True
        remplacements.append((debut, fin, _remplacement(node, source, fonction)))
    if not remplacements:
        return 0
    for debut, fin, texte in sorted(remplacements, reverse=True):
        octets = octets[:debut] + texte.encode() + octets[fin:]
    resultat = octets.decode()
    resultat = _imports(resultat, besoin)
    ast.parse(resultat)  # garde-fou : jamais un fichier cassé
    chemin.write_text(resultat)
    return len(remplacements)


def _imports(source: str, besoin: dict) -> str:
    lignes = []
    if besoin["_"] and not re.search(r"^from django\.utils\.translation import .*\bgettext as _\b", source, re.M):
        lignes.append("from django.utils.translation import gettext as _")
    if besoin["gettext_lazy"] and not re.search(r"^from django\.utils\.translation import .*\bgettext_lazy\b", source, re.M):
        lignes.append("from django.utils.translation import gettext_lazy")
    if not lignes:
        return source
    arbre = ast.parse(source)
    derniere = 0
    for n in arbre.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            derniere = n.end_lineno
        elif derniere:
            break
    tout = source.splitlines(keepends=True)
    if derniere == 0:
        # après la docstring et `from __future__`
        derniere = arbre.body[0].end_lineno if arbre.body and isinstance(arbre.body[0], ast.Expr) else 0
    insere = "".join(l + "\n" for l in lignes)
    return "".join(tout[:derniere]) + insere + "".join(tout[derniere:])


if __name__ == "__main__":
    total = 0
    for a in sys.argv[1:]:
        n = traiter(Path(a))
        if n:
            print(f"{a} : {n}")
        total += n
    print(f"total : {total}")
