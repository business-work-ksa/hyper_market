# 27 — Identité graphique

Version de référence publiée comme système de design (brand book avec aperçus vivants). Fichiers de la marque : `static/marque/` (logos, symboles, icône, frise, image de partage), `static/icones/` (PNG d'application), `static/fonts/` (polices). Régénération : `python outils/marque/generer_marque.py` (outils de développement : `pip install fonttools brotli uharfbuzz`, `npm install`).

HyperMarché est la place de marché des commerçants de Douala et Yaoundé, et l'outil de gestion (caisse, stock, comptabilité) qui les fait tourner. Cette charte dit comment la marque se montre — à l'écran, sur un ticket thermique, sur une enseigne peinte à Mboppi — et pourquoi.

## 1. Plateforme de marque

**Mission.** Mettre le commerce de quartier en ligne sans lui faire perdre ce qui fait sa force : le commerçant qu'on connaît, le prix qu'on voit, la livraison par celui qui vend.

**Promesse.** *Le marché, livré chez vous.* — en anglais : *The market, delivered to you.*

**Ce que la marque doit faire sentir, dans cet ordre :**

1. **Confiance.** L'argent payé d'avance reste en séquestre chez un partenaire agréé jusqu'à la confirmation de réception. Chaque élément visuel lié au paiement est sobre, stable, lisible.
2. **Proximité.** Ce sont des commerçants nommés, pas un entrepôt anonyme. La marque s'efface derrière leur enseigne sur leur propre page.
3. **Vitalité.** Un marché camerounais est coloré, bruyant, vivant. La marque en garde une rayure et une couleur, pas le vacarme.

**Personnalité :** franche, chaleureuse, débrouillarde, jamais clinquante. Elle parle comme un commerçant sérieux qui connaît ses clients — pas comme une banque, pas comme une start-up de la Silicon Valley.

## 2. Le logo

### Le concept : l'étal

Le symbole est un **étal de marché vu de face** : un auvent rayé à trois lés festonnés, et dessous les deux poteaux et le comptoir — qui forment le **H** d'HyperMarché. On le lit d'un coup d'œil comme « boutique », on le relit comme une initiale.

- **L'auvent** est l'image la plus partagée des marchés de la CEMAC, de Mokolo à Marché Central : l'ombre qui accueille. Ses trois lés alternent **Vert Wouri – Or Mboppi – Vert Wouri**.
- **Les festons** sont des demi-disques de rayon 9 (sur une grille de 64). C'est la seule courbe de la marque : elle revient dans la frise, dans les coins de l'icône d'application et dans les rayons d'interface.
- **Le logotype** est dessiné en Bricolage Grotesque, graisse 800, vectorisé : il ne dépend d'aucune police installée. « Hyper » est en Ébène, « Marché » en Vert Wouri, et **l'accent de « é » est en Or** — le seul point d'or du logotype, qui fait écho au lé central de l'auvent.

### Versions

| Fichier (groupe Logos) | Quand l'employer |
|---|---|
| `logo.svg` | Version de référence, sur Ivoire, blanc ou tout fond clair. |
| `logo-negatif.svg` | Sur Ébène ou fond sombre (le vert passe en `primary-400`, l'or reste). |
| `logo-ebene.svg` | Une seule encre noire : ticket thermique, fax, tampon, gravure, presse. |
| `logo-blanc.svg` | Une seule encre blanche : sur Vert Wouri, sur photo assombrie, en sérigraphie. |
| `logo-vertical.svg` | Formats carrés ou hauts : affiche, autocollant, profil de réseau social. |
| `symbole.svg` et déclinaisons | Quand le nom est déjà écrit ailleurs ou que la place manque (en-tête mobile, avatar). |
| `icone-app.svg`, `favicon.svg` | Écran d'accueil, onglet du navigateur. Ne pas employer ailleurs. |

### Zone de protection

Autour du logo, laisser vide une marge égale à **la hauteur d'un feston** (X = 9/64 de la hauteur du symbole, soit environ 14 %). Rien n'y entre : ni texte, ni bord de page, ni autre logo. Pour un logo partenaire (MTN MoMo, Orange Money), doubler la marge : `2X`.

### Tailles minimales

| Version | Écran | Imprimé |
|---|---|---|
| Logo horizontal | 96 px de large | 25 mm |
| Logo vertical | 64 px de large | 18 mm |
| Symbole | 16 px | 5 mm |

Sous ces tailles, employer le symbole seul. Sur un ticket thermique de 58 mm, le logo horizontal se pose à 40 mm de large, en `logo-ebene.svg`.

### Interdits

- Ne pas recolorer le logo hors des quatre versions livrées, ni changer l'ordre des couleurs de l'auvent.
- Ne pas déformer, incliner, ombrer, contourner ou poser sur un dégradé.
- Ne pas recomposer le logotype dans une police, même Bricolage Grotesque : la version vectorisée a un crénage et un accent or qui ne se retrouvent pas en texte.
- Ne pas séparer l'accent or du « é », ni le mettre ailleurs dans le mot.
- Ne pas poser le logo couleur sur une photo chargée : passer en `logo-blanc.svg` sur photo assombrie.
- Ne pas employer le symbole comme puce, comme icône d'interface ou comme motif répété : il signe, il ne décore pas.

## 3. Couleurs

### Les quatre couleurs de marque

| Nom | HEX | RVB | CMJN (indicatif) | Rôle |
|---|---|---|---|---|
| **Vert Wouri** | `#00806A` | 0 128 106 | 100 0 17 50 | La marque, l'action principale, les liens. Le fleuve qui fait Douala. |
| **Or Mboppi** | `#E3A72E` | 227 167 46 | 0 26 80 11 | L'achat (Ajouter, Commander, Payer) et l'accent du « é ». Le marché qui fait vivre Douala. |
| **Ébène** | `#1C1C18` | 28 28 24 | 0 0 14 89 | Le texte, le logotype, les fonds sombres. |
| **Ivoire** | `#F7F6F1` | 247 246 241 | 0 0 2 3 | Le fond. Plus chaud que le blanc, moins fatigant en plein soleil. |

Les valeurs CMJN sont des conversions indicatives : valider un bon à tirer avec l'imprimeur, sur le papier réel, avant toute impression en série.

**Proportions** sur une composition : Ivoire 60 %, Vert Wouri 25 %, Ébène 10 %, Or 5 %. L'or est rare exprès : il désigne ce qu'on achète. Un écran où il apparaît trois fois ne dit plus où acheter.

### Dans l'interface

Les composants n'emploient que les **rôles** (jetons `fond`, `surface`, `encre`, `marque`, `accent`…), qui changent de valeur en mode sombre ; les palettes `primary`, `secondary`, `success`, `warning`, `error`, `neutral` (50 à 950) servent à composer et à documenter.

- Texte courant : `encre` sur `fond` ou `surface` (15,8:1). Texte secondaire : `encre-muette` (6,1:1 minimum).
- Bouton principal : `sur-marque` sur `marque` (4,9:1 clair, 7,5:1 sombre). Bouton d'achat : `sur-accent` (Ébène) sur `accent` — jamais de blanc sur l'or, illisible au soleil (2,1:1).
- Statuts : toujours un mot et une icône avec la couleur (`succes-*`, `alerte-*`, `erreur-*`). Une couleur seule ne dit rien à un daltonien ni sur un écran délavé.
- Anneau de focus : `focus`, 2 px, décalé de 2 px — au moins 3:1 sur toutes les surfaces, dans les deux thèmes.

## 4. Typographie

Deux familles, auto-hébergées, `font-display: swap` : le texte s'affiche tout de suite dans la police du téléphone, puis bascule.

| Famille | Rôle | Pourquoi |
|---|---|---|
| **Bricolage Grotesque** 800 (OFL) | Titrage : titres de page et de section, affiches, enseignes, logotype. | Une grotesque aux contreformes généreuses et aux pièges à encre visibles, qui garde quelque chose de la lettre peinte des enseignes de quartier. Instance unique 800, 17 Ko. |
| **Plus Jakarta Sans** 200–800 (OFL) | Tout le reste : texte, interface, prix, formulaires. | Lisible en petit sur un écran bas de gamme, chiffres tabulaires pour aligner les prix, 27 Ko pour toutes les graisses. |

**Échelle** modulaire de rapport 1,25 sur une base de 16 px : 10,24 · 12,8 · 16 · 20 · 25 · 31,25 · 39 · 48,8 · 61 px (styles `sur-titre`, `legende`, `corps`, `titre-carte`, `sous-titre`, `titre-3`, `titre-2`, `titre-1`, `affiche`). Seule exception : `interface` à 14 px pour l'interface dense.

Règles :

- Bricolage Grotesque seulement à 25 px et plus, jamais en texte courant, jamais en italique (il n'y en a pas).
- Pas plus de deux graisses de Plus Jakarta Sans par écran (400 et 600 ou 700).
- Les prix en chiffres tabulaires, le montant en 800, la devise « FCFA » en plus petit et en `encre-muette`, séparée par une espace insécable : **34 000** FCFA.
- Capitales réservées aux sur-titres (`sur-titre`, interlettrage 0,08 em).

## 5. La frise festonnée

Les festons de l'auvent, alternés vert et or, en bande répétable (`motif-feston.svg`, module de 36 × 19). C'est **la signature graphique** de la marque hors du logo :

- en tête des supports imprimés (ticket, facture, carte de visite, affiche) ;
- sur le ruban adhésif et les sacs de livraison ;
- en haut des visuels de partage et des publications.

Jamais derrière du texte, jamais en fond plein, jamais en vertical. Une frise par support.

## 6. Iconographie

Icônes au trait, grille de 24, trait de 1,75, bouts et jonctions arrondis, couleur héritée du texte (`currentColor`). Une icône accompagne un mot ; seule, elle porte un `aria-label`. Pas d'émoji dans l'interface ni dans les messages transactionnels : ils changent d'aspect d'un téléphone à l'autre et ne se lisent pas toujours.

## 7. Images

- **Les vrais commerçants, dans leurs vraies boutiques**, en lumière naturelle, avec leur accord écrit. Les produits photographiés sur l'étal ou le comptoir, pas détourés sur fond blanc d'entrepôt.
- Jamais de banque d'images (poignée de main, famille souriante devant un ordinateur), jamais de visage d'acheteur.
- Sans photo, un article prend son **monogramme** sur la teinte de son commerçant : c'est une partie de l'identité, pas un manque.

## 8. Voix et ton

On écrit comme on parle à un client qu'on respecte : vouvoiement, phrases courtes, mots concrets. En français et en anglais, avec le même sens et la même retenue.

| Dire | Ne pas dire |
|---|---|
| « Votre argent reste en séquestre chez notre partenaire agréé. » | « Nous gardons votre argent en sécurité. » (faux : la plateforme ne détient pas les fonds) |
| « Le commerçant vous appelle pour convenir de la livraison. » | « Livraison express garantie ! » |
| « Payer 24 350 FCFA » | « Valider », « OK » |
| « HyperMarché ne vous demandera jamais votre code secret. » | « Ne vous inquiétez pas. » |
| « Ce rayon est encore vide. » | « Oups ! » |

Pas de point d'exclamation dans l'interface, pas de majuscules pour crier, pas de promesse que le produit ne tient pas encore.

## 9. Applications

Les fiches du groupe **Applications** montrent la marque sur ses supports réels : icône d'application, enseigne de boutique partenaire, ticket de caisse thermique, carte de visite, autocollant de vitrine, visuel de partage WhatsApp. Chaque fiche dit les fichiers et les règles à employer.
