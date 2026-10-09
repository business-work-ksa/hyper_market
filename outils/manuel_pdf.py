"""Compose le manuel d'utilisation en PDF, prêt à imprimer.

    make manuel        →  docs/manuel-hypermarche.pdf

Pourquoi un script plutôt qu'un export fait une fois à la main : le manuel
bougera — un écran ajouté, un droit déplacé — et un PDF qu'il faut refabriquer
de mémoire finit par décrire une version que plus personne n'utilise. La source
reste `docs/21-manuel-utilisation.md` ; ceci n'en est qu'un rendu.

Le style reprend **les jetons du système de design** (docs/19), lus dans
`static/css/hypermarche.css` : un manuel qui ne ressemble pas au logiciel
qu'il décrit oblige le lecteur à faire la traduction lui-même.

Deux ajouts que le Markdown ne porte pas, parce qu'ils n'ont de sens qu'imprimé :

* une **page de garde** et une table des matières paginée ;
* des **fiches de poste**, une par rôle, à découper et punaiser près de la
  caisse. C'est le format qui sert réellement dans une boutique : personne ne
  feuillette vingt pages derrière un comptoir avec un client qui attend.
"""

from __future__ import annotations

import datetime
import pathlib
import re

import markdown
from weasyprint import HTML

RACINE = pathlib.Path(__file__).resolve().parent.parent
SOURCE = RACINE / "docs" / "21-manuel-utilisation.md"
SORTIE = RACINE / "docs" / "manuel-hypermarche.pdf"
FEUILLE = RACINE / "static" / "css" / "hypermarche.css"

MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def jetons() -> dict[str, str]:
    """Couleurs du système de design, lues à la source.

    Recopier les valeurs ici les ferait diverger au premier ajustement de la
    charte, et le manuel serait le dernier endroit où on penserait à regarder.

    **La lecture s'arrête au thème sombre**, et cette ligne est tout sauf un
    détail. La feuille redéfinit les mêmes jetons plus bas, pour le mode sombre ;
    lire le fichier entier et garder la dernière valeur de chaque nom donne donc
    la palette sombre — sur du papier blanc. Le premier tirage avait une page de
    garde au cartouche noir, et rien dans le code ne disait pourquoi.
    """
    css = FEUILLE.read_text(encoding="utf-8")
    clair = css.split("@media (prefers-color-scheme: dark)")[0]
    return dict(re.findall(r"^\s*--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{3,8});", clair, re.M))


# Les rôles tels que le manuel les décrit. La liste est ici et non déduite du
# code : une fiche de poste est un texte pour un humain, pas une projection de
# la matrice des droits — celle-ci est déjà dans le corps du manuel.
FICHES = [
    {
        "titre": "Caissier",
        "accroche": "Vous encaissez. Vous ne voyez ni les coûts d'achat, ni la marge.",
        "gestes": [
            ("Le matin", "Caisse › Ouvrir la session. Saisissez les espèces présentes dans le tiroir."),
            ("Une vente", "Cherchez l'article (nom, référence ou code-barres), ajoutez-le, choisissez le règlement : espèces, Mobile Money, carte, ou à crédit."),
            ("Sans réseau", "Continuez à encaisser. Les ventes attendent sur l'appareil et repartent seules. Ne fermez pas l'application tant que le bandeau annonce des ventes en attente."),
            ("Imprimer", "Bouton Imprimer, sur Android + Chrome + imprimante Bluetooth. Sur iPhone, passez par l'impression du navigateur ou WhatsApp."),
            ("Le soir", "Comptez les espèces du tiroir AVANT de regarder le montant théorique affiché à côté. Puis saisissez votre comptage."),
        ],
        "retenir": "Une vente enregistrée n'est jamais perdue. Elle part, ou elle attend.",
    },
    {
        "titre": "Magasinier",
        "accroche": "Vous recevez et comptez la marchandise. Vous voyez les coûts d'achat, pas la marge.",
        "gestes": [
            ("Réception", "Stock › l'article › Entrée de stock. Quantité reçue et coût d'achat unitaire."),
            ("Le coût compte", "Il recalcule le coût moyen pondéré, qui sert à valoriser tout le stock et à calculer la marge. Un coût de travers fausse la marge pendant des mois."),
            ("Inventaire", "Stock › Inventaire. Saisissez les quantités comptées ; les écarts sont chiffrés et écrits, jamais effacés."),
            ("Transfert", "Stock › l'article › Transférer, si la boutique a plusieurs dépôts. Le coût moyen d'origine suit la marchandise."),
            ("Sans réseau", "Une réception saisie pendant une coupure n'est pas perdue : elle attend et repart au retour du réseau."),
        ],
        "retenir": "Une quantité ne se retape pas : elle se corrige par un autre mouvement.",
    },
    {
        "titre": "Gérant",
        "accroche": "Vous voyez tout, et vous seul gérez l'équipe et les dépôts.",
        "gestes": [
            ("Chaque matin", "Tableau de bord : ventes et marge du jour, valeur du stock, ce qu'il faut commander en priorité."),
            ("Nouvel article", "Stock › Nouvel article. Le seuil d'alerte déclenche l'avertissement de réapprovisionnement — à zéro, vous ne serez jamais prévenu."),
            ("Équipe", "Ma boutique › Équipe : embaucher, changer un rôle, régénérer un mot de passe, retirer un accès."),
            ("Commandes", "En attente → acceptée → préparée → expédiée → livrée. Le stock sort à l'expédition."),
            ("Export", "Ma boutique › Exporter. Archive ZIP en CSV, intégrale et gratuite, à tout moment."),
        ],
        "retenir": "Retirer un accès ne supprime pas la personne : ses ventes restent à son nom.",
    },
    {
        "titre": "Comptable",
        "accroche": "Vous lisez les ventes, la comptabilité, les coûts et la marge. Pas le stock, pas l'équipe.",
        "gestes": [
            ("Comptabilité", "Les écritures SYSCOHADA sont générées à chaque vente. Il n'y a rien à saisir."),
            ("Balance", "L'écran montre la balance et les dernières écritures. Le détail complet part à l'export."),
            ("Export", "Ma boutique › Exporter : écritures en partie double, ventes, mouvements de stock, en CSV."),
            ("Corriger", "Une écriture ne se modifie pas : le journal est en ajout seul. On écrit l'écriture qui corrige, comme sur un livre papier."),
        ],
        "retenir": "La plateforme prépare la comptabilité. Un expert-comptable la révise et l'atteste.",
    },
]


def en_html(markdown_source: str) -> str:
    return markdown.markdown(
        markdown_source,
        extensions=["tables", "attr_list", "sane_lists"],
        output_format="html5",
    )


def decouper(texte: str) -> tuple[str, str]:
    """Sépare le bandeau d'en-tête (la citation initiale) du corps."""
    lignes = texte.split("\n")
    # Le titre de niveau 1 et le bloc de citation qui le suit forment le chapeau.
    fin = 0
    for i, ligne in enumerate(lignes):
        if ligne.strip() == "---" and i > 0:
            fin = i
            break
    return "\n".join(lignes[1:fin]), "\n".join(lignes[fin + 1 :])


def fiches_html() -> str:
    morceaux = []
    for fiche in FICHES:
        gestes = "\n".join(
            f"<tr><th scope='row'>{quand}</th><td>{quoi}</td></tr>"
            for quand, quoi in fiche["gestes"]
        )
        morceaux.append(
            f"""
<section class="fiche">
  <header>
    <span class="fiche__sur-titre">Fiche de poste — à afficher près du poste de travail</span>
    <h2>{fiche["titre"]}</h2>
    <p class="fiche__accroche">{fiche["accroche"]}</p>
  </header>
  <table class="fiche__gestes"><tbody>{gestes}</tbody></table>
  <p class="fiche__retenir"><strong>À retenir&nbsp;:</strong> {fiche["retenir"]}</p>
</section>"""
        )
    return "\n".join(morceaux)


def style(t: dict[str, str]) -> str:
    marque = t.get("marque", "#00806A")
    appui = t.get("marque-appui", "#006352")
    teinte = t.get("marque-teinte", "#E2F0EC")
    encre = t.get("encre", "#14140F")
    encre2 = t.get("encre-2", "#56564E")
    muette = t.get("encre-muette", "#86867C")
    filet = t.get("filet", "#E3E1D8")
    creuse = t.get("surface-creuse", "#EEEDE6")
    critique = t.get("critique", "#D03B3B")
    return f"""
@page {{
  size: A4;
  margin: 20mm 18mm 18mm 18mm;
  @bottom-center {{
    content: counter(page) " / " counter(pages);
    font-family: "DejaVu Sans", sans-serif; font-size: 8.5pt; color: {muette};
  }}
  @bottom-right {{
    content: "HyperMarché — manuel d'utilisation";
    font-family: "DejaVu Sans", sans-serif; font-size: 8pt; color: {muette};
  }}
}}
/* La page de garde et les fiches n'ont pas de pied de page : l'une est une
   couverture, les autres sont faites pour être découpées. */
@page garde {{ margin: 0; @bottom-center {{ content: none }} @bottom-right {{ content: none }} }}
@page fiche {{ @bottom-right {{ content: "À découper et afficher" }} }}

* {{ box-sizing: border-box; }}
body {{
  font-family: "DejaVu Sans", sans-serif;
  font-size: 9.6pt; line-height: 1.55; color: {encre};
  margin: 0; hyphens: auto;
}}

/* ---- page de garde ---- */
.garde {{
  page: garde; height: 297mm; padding: 34mm 24mm;
  background: {marque}; color: #fff;
  display: flex; flex-direction: column; justify-content: space-between;
  page-break-after: always;
}}
.garde__sceau {{
  display: inline-block; border: 2px solid rgba(255,255,255,.55);
  border-radius: 7px; padding: 4px 9px; font-weight: 700; letter-spacing: .06em;
}}
.garde h1 {{ font-size: 34pt; line-height: 1.1; margin: 0 0 6mm 0; font-weight: 700; }}
.garde__accroche {{ font-size: 13pt; opacity: .92; max-width: 105mm; line-height: 1.5; }}
.garde__chapeau {{ font-size: 10pt; opacity: .88; max-width: 118mm; }}
/* Le chapeau est un bloc de citation dans la source Markdown. Sur la couverture
   il n'a pas à porter le cadre des citations du corps : fond et filet sont
   retirés, pas seulement adoucis. */
.garde__chapeau blockquote {{
  margin: 0; border: 0; padding: 0; background: none; color: inherit;
}}

/* Un lien imprimé ne se clique pas, et les renvois de ce manuel pointent vers
   des fichiers du dépôt. Les laisser en bleu souligné promet une action qui
   n'existe pas sur papier ; ils gardent donc le style du texte, en gras. */
a {{ color: inherit; text-decoration: none; font-weight: 700; }}
.garde__pied {{ font-size: 9pt; opacity: .8; }}

/* ---- sommaire ---- */
.sommaire {{ page-break-after: always; }}
.sommaire h2 {{ border: 0; margin-top: 0; }}
.sommaire ol {{ list-style: none; padding: 0; margin: 6mm 0 0 0; counter-reset: s; }}
.sommaire li {{
  counter-increment: s; padding: 2.6mm 0; border-bottom: 1px solid {filet};
  font-size: 11pt;
}}
.sommaire li::before {{
  content: counter(s) "."; color: {marque}; font-weight: 700;
  display: inline-block; width: 9mm;
}}

/* ---- corps ---- */
h2 {{
  font-size: 15.5pt; color: {appui}; margin: 9mm 0 3mm 0; font-weight: 700;
  border-bottom: 2px solid {teinte}; padding-bottom: 1.6mm;
  page-break-after: avoid; page-break-inside: avoid;
}}
h3 {{
  font-size: 11.2pt; margin: 5.5mm 0 1.8mm 0; font-weight: 700; color: {encre};
  page-break-after: avoid;
}}
p {{ margin: 0 0 2.4mm 0; }}
strong {{ font-weight: 700; }}
ul, ol {{ margin: 0 0 2.8mm 0; padding-left: 5.5mm; }}
li {{ margin-bottom: 1.1mm; }}
code {{
  font-family: "DejaVu Sans Mono", monospace; font-size: 8.4pt;
  background: {creuse}; padding: .4mm 1.1mm; border-radius: 2px;
}}
em {{ color: {encre2}; }}

blockquote {{
  margin: 3mm 0; padding: 2.8mm 4mm; background: {teinte};
  border-left: 3px solid {marque}; border-radius: 0 4px 4px 0;
  font-size: 9.2pt; page-break-inside: avoid;
}}
blockquote p:last-child {{ margin-bottom: 0; }}

table {{
  width: 100%; border-collapse: collapse; margin: 3mm 0 4mm 0;
  font-size: 8.8pt; page-break-inside: avoid;
}}
th, td {{
  border-bottom: 1px solid {filet}; padding: 1.7mm 2mm;
  text-align: left; vertical-align: top;
}}
thead th {{
  background: {creuse}; color: {encre}; font-weight: 700;
  border-bottom: 1.5px solid {filet};
}}
tbody tr:nth-child(even) {{ background: #FBFAF6; }}
/* Colonnes de coches : centrées, et la coche en couleur de marque. */
td[align="center"], th[align="center"] {{ text-align: center; color: {marque}; font-weight: 700; }}

hr {{ border: 0; border-top: 1px solid {filet}; margin: 7mm 0; }}

/* ---- fiches de poste ---- */
.fiches-intro {{ page-break-before: always; }}
.fiche {{
  page: fiche; page-break-before: always; page-break-inside: avoid;
  border: 1.5px solid {marque}; border-radius: 5px; padding: 8mm;
}}
.fiche__sur-titre {{
  font-size: 7.6pt; letter-spacing: .09em; text-transform: uppercase;
  color: {muette};
}}
.fiche h2 {{ border: 0; margin: 1.5mm 0 1mm 0; font-size: 22pt; color: {marque}; }}
.fiche__accroche {{ font-size: 10.4pt; color: {encre2}; margin-bottom: 5mm; }}
.fiche__gestes {{ font-size: 10pt; }}
.fiche__gestes th {{
  width: 32mm; color: {appui}; font-weight: 700; background: none;
  border-bottom: 1px solid {filet};
}}
.fiche__gestes td {{ border-bottom: 1px solid {filet}; }}
.fiche__retenir {{
  margin-top: 6mm; padding: 3.4mm 4mm; background: {teinte};
  border-radius: 4px; font-size: 10pt;
}}
.avertissement {{ color: {critique}; }}
"""


def composer() -> pathlib.Path:
    texte = SOURCE.read_text(encoding="utf-8")
    chapeau, corps = decouper(texte)

    titres = re.findall(r"^## \d+\.\s*(.+)$", corps, re.M)
    sommaire = "".join(f"<li>{t}</li>" for t in titres)

    aujourdhui = datetime.date.today()
    date_fr = f"{aujourdhui.day} {MOIS[aujourdhui.month - 1]} {aujourdhui.year}"

    document = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>HyperMarché — Manuel d'utilisation</title>
<style>{style(jetons())}</style></head><body>

<section class="garde">
  <div><span class="garde__sceau">HM</span></div>
  <div>
    <h1>Manuel<br>d'utilisation</h1>
    <p class="garde__accroche">HyperMarché — la boutique qui tourne toute seule.</p>
    <div class="garde__chapeau">{en_html(chapeau)}</div>
  </div>
  <div class="garde__pied">Édition du {date_fr}</div>
</section>

<section class="sommaire">
  <h2>Ce que contient ce manuel</h2>
  <ol>{sommaire}</ol>
  <p style="margin-top:8mm">
    Les quatre dernières pages sont des <strong>fiches de poste</strong> : une par rôle,
    à découper et à afficher près du poste de travail.
  </p>
</section>

{en_html(corps)}

<section class="fiches-intro">
  <h2>Fiches de poste</h2>
  <p>
    Une page par rôle, à découper et punaiser près du poste concerné. Personne ne
    feuillette vingt pages derrière un comptoir avec un client qui attend.
  </p>
</section>
{fiches_html()}

</body></html>"""

    HTML(string=document, base_url=str(RACINE)).write_pdf(SORTIE)
    return SORTIE


if __name__ == "__main__":
    chemin = composer()
    print(f"{chemin.relative_to(RACINE)} — {chemin.stat().st_size // 1024} Ko")
