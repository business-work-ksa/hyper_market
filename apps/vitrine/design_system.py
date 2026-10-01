"""Les jetons du marché, tels que la référence vivante les affiche (/marche/design-system/).

La source de vérité est `tailwind.config.js` ; cette copie existe parce que la fonction en
production n'embarque pas le dépôt entier. Un test (`tests/test_marche_design.py`) vérifie que les
deux disent la même chose : une nuance changée d'un côté seulement fait échouer la suite.
"""

PALETTES = {
    "primary": ["#EDFAF6", "#D2F2E9", "#A7E4D4", "#6FD0BA", "#36B49B", "#129A81", "#00806A", "#006656", "#0A5146", "#0C433B", "#032722"],
    "secondary": ["#FDF8EC", "#F9EDCB", "#F2D993", "#EBC05A", "#E3A72E", "#CC8A14", "#A96D0E", "#8A5410", "#714414", "#5E3915", "#361D07"],
    "success": ["#EEFBEE", "#D6F5D6", "#AFE9AF", "#7AD77A", "#45BE45", "#16A316", "#0E870E", "#0B6B0E", "#0E5512", "#0D4612", "#032706"],
    "warning": ["#FFF9EB", "#FEEFC7", "#FDDD8A", "#FCC64D", "#FAB219", "#F4950B", "#D87006", "#B34F09", "#913D0E", "#77330F", "#451903"],
    "error": ["#FDF3F3", "#FBE4E4", "#F8CDCD", "#F2A8A8", "#E87676", "#DB4C4C", "#C73535", "#A72929", "#8A2626", "#742525", "#3F0F0F"],
    "neutral": ["#FAFAF7", "#F4F3EE", "#E7E5DD", "#D3D0C5", "#A8A498", "#7D796E", "#605D54", "#4A4841", "#2F2E29", "#1C1C18", "#0F0F0C"],
}
CRANS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]

ESPACEMENTS = [("1", 4), ("2", 8), ("3", 12), ("4", 16), ("5", 20), ("6", 24), ("8", 32), ("10", 40), ("12", 48), ("16", 64), ("20", 80), ("24", 96)]
RAYONS = [("rounded-sm", "4 px"), ("rounded-md", "8 px"), ("rounded-lg", "12 px"), ("rounded-xl", "16 px"), ("rounded-2xl", "24 px"), ("rounded-full", "∞")]
OMBRES = ["shadow-xs", "shadow-sm", "shadow-md", "shadow-lg", "shadow-xl"]
ROLES = [
    ("bg-bg", "bg", "Plan de page"),
    ("bg-surface", "surface", "Cartes, panneaux"),
    ("bg-surface-sunken", "surface-sunken", "Champs inertes, creux"),
    ("bg-ink", "ink", "Texte principal"),
    ("bg-ink-muted", "ink-muted", "Texte secondaire"),
    ("bg-line-strong", "line-strong", "Bord de champ"),
    ("bg-brand", "brand", "Action principale"),
    ("bg-brand-soft", "brand-soft", "Fond de marque doux"),
    ("bg-accent", "accent", "Achat (or du marché)"),
    ("bg-success-soft", "success-soft", "Fond de succès"),
    ("bg-warning-soft", "warning-soft", "Fond d'alerte"),
    ("bg-error-soft", "error-soft", "Fond d'erreur"),
]
VARIANTES_BOUTONS = ["primary", "secondary", "outline", "ghost", "accent"]
ETATS_BOUTONS = ["", "Par défaut", "Survol", "Focus", "Appui", "Désactivé", "Occupé"]


def contexte() -> dict:
    return {
        "palettes": [
            (nom, [(cran, hexa, "") for cran, hexa in zip(CRANS, nuances)])
            for nom, nuances in PALETTES.items()
        ],
        "espacements": ESPACEMENTS,
        "rayons_bordure": RAYONS,
        "ombres": OMBRES,
        "roles": ROLES,
        "variantes_boutons": VARIANTES_BOUTONS,
        "etats_boutons": ETATS_BOUTONS,
    }
