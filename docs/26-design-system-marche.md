# 26 — Design system du marché

Référence vivante : **`/marche/design-system/`** (chaque composant, dans tous ses états, rendu par la
feuille et les partials de production). Ce document en donne les règles et les raisons.

Périmètre : la vitrine publique (`/marche/`). Le back-office garde son propre système
(docs/19) : les deux évoluent séparément, seul le sprite d'icônes est partagé.

## 1. Contraintes de départ

| Contrainte | Conséquence |
|---|---|
| Android d'entrée de gamme, 3G intermittente, data payante | une police auto-hébergée (27 Ko, `font-display: swap`), une feuille de **9 Ko gzip**, aucune image décorative, animations limitées à `opacity`/`transform` |
| Lecture en plein soleil | contrastes AA vérifiés par script, jamais une information portée par la couleur seule |
| Une main, debout | cibles tactiles ≥ 44 px (`btn-md`, `input`), actions d'achat en bas de carte |
| Cameroun bilingue | marché en français et en anglais (§6) |

## 2. Outillage

- **Tailwind CSS 3.4**, configuration des jetons dans `tailwind.config.js`, source dans
  `static/src/marche.css`, sortie **minifiée et purgée** dans `static/css/marche.css`.
- `npm run css` reconstruit la feuille ; `npm run css:veille` la reconstruit à chaque modification.
- La sortie est **versionnée** : la construction de production (Vercel, Python) n'a pas Node.
  Toute modification d'un gabarit du marché qui ajoute une classe exige `npm run css` avant commit
  — le test `test_la_feuille_compilee_contient_les_composants` attrape l'oubli le plus courant.
- `python outils/contrastes_marche.py` vérifie les contrastes de tous les rôles, dans les deux
  thèmes ; il est exécuté par la suite de tests.

## 3. Jetons

**Typographie** — échelle modulaire de rapport **1,25** (tierce majeure), base 16 px :
`2xs` 10,24 · `xs` 12,8 · `base` 16 · `lg` 20 · `xl` 25 · `2xl` 31,25 · `3xl` 39 · `4xl` 48,8 ·
`5xl` 61 px. Une seule exception documentée : `sm` 14 px pour l'interface dense. Police :
Plus Jakarta Sans (OFL), variable 200–800.

**Espacement** — base 4 px, en `rem` (suit le zoom) : 1 = 4 px … 64 = 256 px. `11` = 44 px, la
cible tactile minimale.

**Rayons** — `sm` 4 · `md` 8 · `lg` 12 · `xl` 16 · `2xl` 24 px · `full`.

**Ombres** — `xs` à `xl`, teinte chaude en clair, noire en sombre (variable `--hm-ombre`).

**Couleurs** — deux étages :

1. **Palettes** fixes, de 50 à 950 : `primary` (vert du marché, #00806A en 600), `secondary`
   (or), `success`, `warning`, `error`, `neutral` (pierre chaude).
2. **Rôles**, variables CSS qui changent en mode sombre : `bg`, `surface` (`raised`, `sunken`),
   `ink` (`muted`, `inverse`), `line` (`strong`), `brand` (`hover`, `soft`, `ink`, `on`), `accent`,
   `success/warning/error` (`soft`, `ink`), `focus`.

Les composants n'emploient **que les rôles** : c'est ce qui rend le mode sombre complet sans écrire
`dark:` sur chaque classe. Le mode sombre suit `prefers-color-scheme`, et le bouton de thème de
l'en-tête force clair ou sombre (`data-theme` sur `<html>`, choix gardé dans le navigateur et
restauré avant le premier rendu).

| Paire vérifiée (extrait) | Clair | Sombre |
|---|---|---|
| texte secondaire / fond | 6,08:1 | 7,70:1 |
| libellé / bouton principal | 4,89:1 | 7,46:1 |
| bord de champ / surface (1.4.11) | 4,35:1 | 4,02:1 |
| anneau de focus / fond | 4,52:1 | 10,43:1 |

## 4. Composants

Chaque composant est une classe (contrat CSS) et, quand il porte de la structure, un partial
Django isolé et documenté dans `templates/marche/composants/`. L'en-tête de chaque partial dit ses
paramètres, quand l'utiliser, quand ne pas l'utiliser et ce qu'il faut vérifier en accessibilité.

| § | Composant | Classe / partial |
|---|---|---|
| 4.1 | Bouton — 4 variantes (`primary`, `secondary`, `outline`, `ghost`) × 3 tailles (`sm` 36, `md` 44, `lg` 56 px), + `accent` pour l'achat | `.btn .btn-{variante} .btn-{taille}` · `bouton.html` |
| 4.2 | Champ — libellé, aide, erreur, tailles `input-sm/input/input-lg`, choix en carte, quantité | `.champ .input .choix .quantite` · `champ.html` |
| 4.3 | Badge — `neutre`, `marque`, `accent`, `succes`, `alerte`, `erreur` | `.badge .badge-{ton}` |
| 4.4 | Carte — simple, interactive, carte d'article | `.carte .carte-interactive` · `carte_article.html` |
| 4.5 | Modale — `<dialog>` natif | `.modale` · `modale.html` |
| 4.6 | Squelette | `.squelette` · `squelette_carte.html`, `squelette_grille.html` |
| 4.7 | État vide | `.vide` · `etat_vide.html` |
| 4.8 | Faits de confiance | `confiance.html` |

États couverts par chaque bouton : par défaut, survol, focus visible, appui, désactivé
(`disabled` / `aria-disabled`), occupé (`aria-busy`, posé automatiquement à l'envoi d'un formulaire
— sur 3G, sans retour visible, on clique deux fois).

## 5. Comportements (`static/js/marche.js`)

Amélioration progressive sans exception : chaque page fonctionne sans le script.

- **Entrées en scène** — `[data-apparition]`, déclenchées par IntersectionObserver, en cascade via
  `--delai`. Invisibles au départ seulement si le script tourne (classe `js` posée en tête), et
  jamais avec `prefers-reduced-motion`.
- **Grille du catalogue** — rayon et recherche rechargent la seule grille (en-tête `X-Fragment`,
  partial `vitrine/partials/resultats.html`, `Vary: X-Fragment`) ; squelettes pendant l'attente ;
  `aria-busy` sur la région ; le nombre de résultats est annoncé (`aria-live`) ; l'adresse change et
  le retour arrière fonctionne.
- **Thème**, **modales**, **sélecteur de quantité**, **bouton occupé**.

Points de rupture : < 640 (mobile) · `sm` 640 (tablette) · `md` 768 · `lg` 1024 (bureau).

## 6. Langues

Toute l'application se lit en **français** et en **anglais** : le marché, le back-office des
commerçants, la page de connexion et la console de la plateforme. Chacun porte un sélecteur FR/EN
dans son en-tête (`templates/partials/choix_langue.html` hors du marché). Seules les adresses
techniques restent en français, quoi qu'envoie l'appelant : l'API (`/api/`), les notifications des
opérateurs (`/paiements/notifications/`) et la tâche quotidienne (`/taches/`) — leurs messages sont
journalisés et relus en français (`apps/vitrine/langue.py`).

Ordre de décision : choix de la personne (cookie `hm_langue`, posé par `/i18n/setlang/`), puis
langue du navigateur, puis français. Réponses marquées `Content-Language` et `Vary: Accept-Language`.

Un seul catalogue : `config/locale/en/LC_MESSAGES/django.po`, compilé en `.mo` **versionné** (la
construction sans serveur n'a pas gettext ; `config/` est embarqué par `vercel.json`). Les libellés
définis hors des gabarits (paliers, états de commande, motifs de réclamation) sont marqués dans
`apps/vitrine/chaines.py` ; les messages des vues et services passent par `gettext`, les libellés
de modèles et de formulaires par `gettext_lazy`.

Les pluriels s'écrivent avec `{% blocktranslate count n=… %}…{% plural %}…{% endblocktranslate %}`
(ou `ngettext` en Python), jamais avec `|pluralize` dans une phrase traduite : l'anglais n'accorde
pas les adjectifs, et une variable d'accord ne peut pas disparaître de la traduction.
`outils/i18n/pluriels.py` convertit les anciens accords ; `outils/i18n/envelopper.py` et
`envelopper_py.py` ont enveloppé les textes existants (outils de migration, à relire après usage).

Régénérer après modification d'un texte :

```bash
python manage.py makemessages -l en --no-obsolete \
  -i .venv -i node_modules -i static -i staticfiles -i docs -i tests -i scripts -i outils \
  -i infrastructure -i captures -i media -i sortie_vide -i "*/migrations/*" -i apps/api -i config
# traduire les nouvelles entrées (et retirer la marque « fuzzy » des rapprochements), puis :
python manage.py compilemessages -l en --ignore=.venv --ignore=node_modules
```

Les contenus saisis par les commerçants (noms d'articles, descriptions, rayons) restent dans la
langue où ils ont été écrits.

## 7. Accessibilité — ce que les tests vérifient

`tests/test_marche_design.py` : pour chaque page du marché, `lang` sur `<html>`, lien « Aller au
contenu », `<main id="contenu">`, un seul `h1`, aucun bouton sans nom accessible ; contrastes AA ;
cohérence des palettes ; langue et repli du back-office ; fragment du catalogue.

À vérifier à la main avant une mise en production majeure : navigation complète au clavier,
lecteur d'écran (TalkBack sur Android, la cible réelle), zoom 200 %, mode sombre, réseau 3G lent
(DevTools), et — c'est la règle de docs/19 — un téléphone d'entrée de gamme en plein soleil.
