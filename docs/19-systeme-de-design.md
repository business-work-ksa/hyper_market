# 19 — Système de design

Implémenté dans `static/css/hypermarche.css`. Ce document explique **pourquoi** chaque valeur est
celle-là, et consigne les pièges rencontrés.

---

## 1. Le contexte décide de tout

| Contrainte réelle | Conséquence de conception |
|---|---|
| Android d'entrée de gamme, 3G intermittente, data payante | Aucun cadriciel front. CSS écrit à la main, JavaScript en clair, zéro dépendance CDN |
| Usage debout, une main, souvent en plein soleil | Cibles tactiles ≥ 44 px, contrastes tenus, traits d'icônes à 1,75 |
| Une ligne de caisse en moins de 4 secondes | La grille d'articles est l'écran, pas un menu. Aucun aller-retour réseau à la saisie |
| Le gérant regarde son téléphone, le caissier une tablette | Rail latéral sur bureau, barre d'onglets en bas sur mobile |
| Écran allumé toute la journée dans une boutique sombre | Mode sombre à valeurs choisies, pas une inversion |

> **« Premium » ne veut pas dire chargé.** Ici : hiérarchie nette, typographie tenue, couleur rare
> et intentionnelle, aucune latence. Une ombre portée coûte moins cher qu'une image, et une page
> qui s'affiche en 300 ms sur 3G impressionne plus qu'un dégradé.

---

## 2. Couleur

### 2.1 — La palette a été validée, pas choisie à l'œil

Le validateur de palette a été exécuté sur chaque couleur porteuse de données, contre les surfaces
réelles du produit.

| Rôle | Clair | Sombre | Vérification |
|---|---|---|---|
| Marque / série de données | `#00806A` | `#2FA98E` | Bande de clarté ✅ · plancher de chroma ✅ · contraste ≥ 3:1 ✅ dans les deux modes |
| Bon | `#0CA30C` | `#0CA30C` | Contraste ✅ |
| Alerte | `#FAB219` | `#FAB219` | **1,77:1 sur fond clair — sous le seuil, par construction** |
| Critique | `#D03B3B` | `#D03B3B` | Contraste ✅ |
| Or (chrome d'interface) | `#B07B10` | `#D9A441` | **Jamais utilisé comme marque de données** |

**Le premier teal essayé, `#0F6F5C`, a été rejeté** : chroma 0,088, sous le plancher de 0,1 — il
« lit gris » sur une barre. C'est exactement le genre d'erreur qu'on ne voit pas à l'œil et que le
validateur attrape.

### 2.2 — La règle qui découle du contraste de l'alerte

`--alerte` passe sous 3:1 sur fond clair. Ce n'est pas un défaut à corriger, c'est une propriété
de la couleur ambre. **La mitigation est obligatoire et systématique : tout statut porte une icône
et un mot, jamais la couleur seule.**

C'est codé dans la balise `{% puce_stock %}` (`apps/backoffice/templatetags/hm.py`) : impossible
d'afficher un état de stock sans son icône et son libellé.

### 2.3 — Ce que la couleur n'a pas le droit de faire

- Les couleurs de statut sont **réservées** : jamais réutilisées comme série de données.
- Le texte porte des jetons d'encre, jamais la couleur d'une série.
- Une seule série de données existe dans le produit (le chiffre d'affaires quotidien) : **pas de
  légende sur le graphe**, le titre de la carte nomme la mesure.

---

## 3. Typographie

Pile système (`system-ui, -apple-system, "Segoe UI", Roboto`). **Aucune police distante** : une
requête vers `fonts.googleapis.com` coûte de la data payante et un blocage de rendu sur 3G.

| Rôle | Taille | Graisse | Interlettrage |
|---|---|---|---|
| Héros / valeur de tuile | 26-30 px | 650-660 | -0,026 em |
| Titre de page | 21 px | 640 | -0,019 em |
| Titre de section | 15 px | 620 | -0,011 em |
| Corps | 14 px | 400 | 0 |
| Légende | 11,5-12,5 px | 400 | 0 |
| Sur-titre | 10,5 px | 650 | +0,075 em, capitales |

**Interlettrage négatif sur les grandes tailles, positif sur les capitales.** C'est ce qui sépare
une interface tenue d'une interface par défaut.

**Chiffres :** proportionnels par défaut sur les valeurs isolées ; `tabular-nums` (classe
`.chiffre`) uniquement dans les colonnes qui doivent s'aligner verticalement.

**Format monétaire :** le filtre `fcfa` sépare les milliers par une **espace fine insécable** et
n'affiche aucune décimale — le franc CFA n'a pas de subdivision en usage.

---

## 4. Rythme, surfaces, élévation

- **Rayons :** 6 / 8 / 11 / 16 px, et pilule pour les puces. Les cartes à 11 px, les contrôles à
  8 px : le contenant est toujours légèrement plus rond que le contenu.
- **Surfaces :** plan de page `#F4F3EE` (bone chaud, pas un gris neutre), cartes `#FCFBF8`,
  creux `#EEEDE6`. La chaleur du fond adoucit un écran regardé huit heures par jour.
- **Filets** plutôt que des ombres pour délimiter ; les ombres ne servent qu'à l'élévation réelle
  (info-bulle, barre d'onglets mobile).
- **Mouvement :** 110 ms pour un survol, 170 ms pour un changement d'état. Au-delà, ça traîne.
  `prefers-reduced-motion` neutralise tout.

---

## 5. Visualisation

Le graphe applique les règles du système de visualisation, sans exception :

| Règle | Application |
|---|---|
| Le travail des données choisit la forme | Grandeur dans le temps → barres verticales |
| Une seule série → pas de légende | Le titre de la carte nomme la mesure |
| Marques fines | Barres de 24 px maximum, écart bien supérieur aux 2 px requis |
| Extrémité haute arrondie à 4 px, pied carré sur la ligne de base | Tracé calculé dans `_chemin_barre()` |
| Grille et axes effacés | Filets à `--grille`, ligne de base à `--ligne-base` |
| Étiquettes directes sélectives | **Le seul maximum** est étiqueté, jamais chaque barre |
| Couche de survol par défaut | Info-bulle + atténuation des autres barres ; **désactivée sur écran tactile**, où il n'y a pas de survol |
| Cible plus grande que la marque | La zone de survol couvre tout le créneau, pas la barre |
| Vue tabulaire disponible | Le tableau des meilleures ventes porte les mêmes chiffres |

**La géométrie est calculée côté serveur.** La page est lisible sans JavaScript, et le premier
rendu n'attend rien — ce qui compte sur 3G plus que n'importe quelle animation.

La piste de santé du stock est un empilement à trois états avec un écart de 2 px entre
remplissages, et une légende à pastille + libellé + valeur.

---

## 6. Accessibilité

- Contraste : corps et titres au-dessus de 4,5:1 dans les deux modes ; les statuts sous 3:1
  compensés par icône + libellé.
- Focus visible partout (`:focus-visible`, anneau à la couleur de marque).
- Navigation au clavier : le rail est un `<nav>`, l'onglet actif porte `aria-current="page"`.
- Les moyens de paiement sont un `role="group"` avec `aria-pressed` — pas des `<div>` cliquables.
- Le graphe porte un `role="img"` et une description ; la piste de stock, un `aria-label` chiffré.
- Cibles tactiles : 44 px de haut sur les actions principales, 104 px pour une tuile d'article.

---

## 7. Quatre pièges rencontrés, et leur correctif

Consignés parce qu'ils se reproduiront.

### 7.1 — La locale française corrompt les attributs SVG et CSS

En `LANGUAGE_CODE = "fr-fr"`, Django rend un flottant `128.43` en **`128,43`**. Injecté dans
`x="…"` d'un SVG ou dans `width:…%`, le navigateur rejette la valeur **sans aucune erreur** : le
graphe se disloque et les barres de progression restent vides.

**Correctif :** `{% load l10n %}` et `{% localize off %}` autour de toute valeur machine. Un
nombre destiné à une géométrie n'est pas un nombre à afficher.

### 7.2 — Un sélecteur de classe bat l'attribut `hidden`

`.ticket__vide { display: flex }` l'emporte sur la règle `[hidden] { display: none }` du
navigateur. Le panier se remplissait, les totaux se mettaient à jour, et l'état vide restait
affiché par-dessus les lignes.

**Correctif :** `[hidden] { display: none !important; }` dans la réinitialisation. À poser une
fois, dès le premier jour.

### 7.3 — Le filtre `add` de Django ne fait pas d'arithmétique flottante

`{{ valeur|add:'3.5' }}` avec `valeur = 184.0` renvoie une **chaîne vide** : `int('3.5')` échoue,
puis `184.0 + '3.5'` échoue aussi. Toutes les étiquettes d'axe se sont retrouvées empilées à
`y=0`, hors cadre.

**Correctif :** aucune arithmétique dans un gabarit. La géométrie se calcule en Python et arrive
prête à écrire. La règle vaut au-delà de ce cas : un gabarit dispose, il ne calcule pas.

### 7.4 — Un écran peut annuler sa propre consigne

L'inventaire affichait « comptez d'abord, regardez le théorique ensuite » — et montrait le stock
théorique dans la colonne voisine du champ de saisie. La consigne était juste, l'écran la
contredisait. **Un compteur qui connaît le chiffre attendu ne compte plus, il confirme**, et tout
le contrôle disparaît.

**Correctif :** le théorique est masqué par défaut, révélable par un bouton. La règle générale :
quand une consigne demande de ne pas regarder quelque chose, l'interface ne doit pas le montrer.
Écrire la consigne ne suffit pas.

Ce défaut n'apparaît dans aucun test — l'écran fonctionnait parfaitement. Il s'est vu sur une
capture.

> **Et un piège d'outillage, tout aussi coûteux :** `runserver --noreload` garde le module Python
> en mémoire. Plusieurs corrections de `views.py` semblaient sans effet alors qu'elles étaient
> justes — le serveur servait l'ancien code. **Après toute modification Python, redémarrer avant
> de conclure quoi que ce soit d'une capture d'écran.**

---

## 8. Vérifier le rendu, pas seulement le code

Le validateur contrôle la couleur ; il ne voit ni les collisions d'étiquettes, ni les
débordements. `captures/` contient une capture de chaque écran, en clair et en sombre, plus deux
vues mobiles, produites par un script Playwright.

C'est en les regardant qu'ont été trouvés : les commentaires Django multilignes rendus en clair
dans la page, le débordement du bandeau à 390 px, la contradiction de l'écran d'inventaire, et les
pièges du §7. **Aucun de ces défauts n'était visible dans le code, et aucun ne faisait échouer un
test.**

Le mode hors ligne, lui, se vérifie autrement : `scripts/verifier-hors-ligne.js` coupe réellement
le réseau du navigateur et rejoue le parcours d'un caissier en panne de connexion.

Régénérer après toute modification d'interface :

```bash
python manage.py runserver 8000 --noreload   # redémarrer si le Python a changé
node scripts/captures.js
```
