"""Second passage sur le code Python : les textes portés par une clé ou un argument lisible.

    python outils/i18n/envelopper_cles.py apps/plateforme/vues_tableau.py [...]

`envelopper_py.py` a traité les messages, les libellés de formulaire et les choix des modèles.
Restaient les textes que les vues composent pour l'écran : `{"titre": "…", "aide": "…"}`,
`Fiche(titre="…", resume="…")`, les `placeholder`, les messages d'erreur de champ
(`error_messages={"required": "…"}`), les erreurs renvoyées en JSON à la caisse (`"erreur"`) et
les listes de choix des formulaires de filtre (`[("seuil", "Sous le seuil d'alerte"), …]`).

Une ligne marquée `# i18n: non` est laissée telle quelle : un libellé enregistré en base à la
création (« Magasin principal »), un nom propre d'exemple.

Ne sont pas touchés, volontairement : `motif`, `commentaire`, `message`, `mention`, `ecran` — ces
textes sont **enregistrés** (journal, mouvements) et doivent rester ceux du jour de l'écriture,
quelle que soit la langue de la personne qui agit.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from envelopper_py import _imports, _remplacement, _texte  # noqa: E402

CLES = {
    "placeholder", "libelle", "titre", "aide", "detail", "texte", "bouton", "erreur", "required",
    "invalid", "min_length", "max_length", "max_value", "min_value", "invalid_choice",
    "periode_texte", "aide_ingredients", "sous_titre", "suffixe", "vide", "manque", "quoi",
}
ARGUMENTS = {
    "libelle", "titre", "resume", "manque", "help", "vide", "quoi", "description", "verbose_name",
    "verbose_name_plural", "libelle_identifiant_fiscal", "aide", "detail", "sous_titre",
}


class Collecteur(ast.NodeVisitor):
    def __init__(self, lignes):
        self.lignes = lignes  # une ligne marquée « # i18n: non » est laissée telle quelle
        self.cibles = []
        self.profondeur = 0

    def visit_FunctionDef(self, node):
        self.profondeur += 1
        self.generic_visit(node)
        self.profondeur -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def _ajouter(self, node):
        if node is not None and _texte(node) and "# i18n: non" not in self.lignes[node.lineno - 1]:
            if isinstance(node, ast.Constant) and "/" in node.value and " " not in node.value:
                return  # un chemin, pas une phrase
            self.cibles.append((node, self.profondeur > 0))

    def visit_Dict(self, node):
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value in CLES:
                self._ajouter(v)
        self.generic_visit(node)

    def visit_Call(self, node):
        nom = getattr(node.func, "id", getattr(node.func, "attr", ""))
        if nom in ("_", "gettext", "gettext_lazy", "ngettext", "pgettext", "gettext_noop"):
            return
        for kw in node.keywords:
            if kw.arg in ARGUMENTS:
                self._ajouter(kw.value)
        for kw in node.keywords:
            if kw.arg == "choices" and isinstance(kw.value, (ast.List, ast.Tuple)):
                self._choix(kw.value)
        if nom == "ValidationError" and node.args and isinstance(node.args[0], ast.Dict):
            for v in node.args[0].values:
                self._ajouter(v)
        self.generic_visit(node)

    def _choix(self, liste):
        for el in liste.elts:
            if isinstance(el, ast.Tuple) and len(el.elts) == 2 and isinstance(el.elts[0], ast.Constant) \
                    and isinstance(el.elts[1], ast.Constant) and isinstance(el.elts[1].value, str):
                self._ajouter(el.elts[1])

    def visit_Assign(self, node):
        # Listes de choix : [("code", "Libellé"), …] — dans un formulaire, un filtre, une vue.
        if isinstance(node.value, (ast.List, ast.Tuple)):
            for el in node.value.elts:
                if isinstance(el, ast.Tuple) and len(el.elts) == 2 and isinstance(el.elts[0], ast.Constant) \
                        and isinstance(el.elts[1], ast.Constant) and isinstance(el.elts[1].value, str):
                    self._ajouter(el.elts[1])
        self.generic_visit(node)


def traiter(chemin: Path) -> int:
    import re
    source = chemin.read_text()
    collecteur = Collecteur(source.splitlines())
    collecteur.visit(ast.parse(source))
    octets = source.encode()
    offsets, total = [], 0
    for ligne in source.splitlines(keepends=True):
        offsets.append(total)
        total += len(ligne.encode())
    remplacements, besoin, vus = [], {"_": False, "gettext_lazy": False}, set()
    for node, dans_fonction in collecteur.cibles:
        debut = offsets[node.lineno - 1] + node.col_offset
        fin = offsets[node.end_lineno - 1] + node.end_col_offset
        if debut in vus:
            continue
        vus.add(debut)
        avant = octets[:debut].decode(errors="ignore").rstrip()
        if re.search(r"(\b_|gettext|gettext_lazy|ngettext|pgettext|gettext_noop)\($", avant):
            continue
        fonction = "_" if dans_fonction else "gettext_lazy"
        besoin[fonction] = True
        remplacements.append((debut, fin, _remplacement(node, source, fonction)))
    if not remplacements:
        return 0
    for debut, fin, texte in sorted(remplacements, reverse=True):
        octets = octets[:debut] + texte.encode() + octets[fin:]
    resultat = _imports(octets.decode(), besoin)
    ast.parse(resultat)
    chemin.write_text(resultat)
    return len(remplacements)


if __name__ == "__main__":
    total = 0
    for a in sys.argv[1:]:
        n = traiter(Path(a))
        if n:
            print(f"{a} : {n}")
        total += n
    print(f"total : {total}")
