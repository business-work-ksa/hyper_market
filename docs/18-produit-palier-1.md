# 18 — Le produit du palier 1, écran par écran

Ce document raffine le plan du [démarrage sans capital](17-demarrage-sans-capital.md) : il dit
exactement ce qu'on installe chez les trois premiers clients, et à quoi on reconnaît que c'est
fini. Il remplace, pour cette phase, le périmètre du lot 1 du
[document 05](05-perimetre-fonctionnel.md), qui suppose une équipe financée.

---

## 1. Le produit n'est pas un logiciel, c'est une installation

Le palier 1 se vend 150 000 F d'installation puis 30 000 F par mois. **Ce que le commerçant achète
d'abord, c'est la journée où quelqu'un vient compter son stock avec lui.** Le logiciel est ce qui
reste quand cette personne repart.

Le parcours d'installation est donc le produit, et il tient en 90 minutes :

| Étape | Durée | Ce qui se passe | Ce que ça produit |
|---|---|---|---|
| 1. Compte | 5 min | Création du compte au numéro du gérant, création de la boutique | Une boutique active, un bail signé |
| 2. Catalogue | 25 min | Saisie des 20 à 60 références qui font 80 % du chiffre d'affaires — **pas tout le stock** | Produits, variantes, prix TTC |
| 3. Comptage | 35 min | Comptage physique avec le gérant, article par article, coût d'achat renseigné | Stock initial valorisé au coût réel |
| 4. Seuils | 10 min | « En dessous de combien tu recommandes ? » pour chaque référence | Alertes de réapprovisionnement |
| 5. Première vente | 10 min | Le vendeur encaisse une vraie vente, seul, pendant qu'on regarde | Un ticket, un mouvement, trois écritures |
| 6. Remise | 5 min | On montre le tableau de bord : « voilà ce que tu as gagné aujourd'hui » | L'adhésion |

> **L'étape 6 est celle qui vend l'abonnement.** Un commerçant qui voit sa marge réelle du jour
> pour la première fois ne discute plus le prix. Tout le reste du produit existe pour rendre cette
> minute possible.

**Règle de l'étape 2 :** on ne saisit jamais tout le stock à l'installation. 40 références bien
tenues valent mieux que 400 abandonnées au bout d'une semaine. Le reste se saisit au fil de l'eau.

---

## 2. Les écrans du quotidien, et rien d'autre

### 2.1 — Connexion

Identification par **numéro de téléphone**, pas par adresse électronique : c'est l'identifiant
réel d'un commerçant camerounais.

| Critère d'acceptation |
|---|
| Un gérant se connecte avec son numéro et arrive sur sa boutique sans choisir quoi que ce soit |
| Un compte sans boutique active est refusé avec un message explicite, pas une page blanche |
| La promesse produit et la mention « votre expert-comptable révise et atteste » sont visibles |

### 2.2 — Tableau de bord

Quatre indicateurs, un graphe, deux listes. **Pas douze tuiles** : un tableau de bord qui dit tout
ne dit rien.

| Bloc | Contenu | Pourquoi celui-là |
|---|---|---|
| Ventes du jour | Total TTC encaissé + écart avec la veille | La question que le gérant se pose en fermant |
| **Marge du jour** | Ventes − coût des marchandises **au CMP réel** | **L'information qu'il n'a jamais eue** |
| Valeur du stock | Somme quantité × CMP | Ce que vaut son magasin, chiffré |
| À réapprovisionner | Ruptures + sous le seuil | Le déclencheur d'action |
| Graphe 14 jours | Chiffre d'affaires quotidien, une seule série | Voir la saisonnalité de sa semaine |
| Santé du stock | Piste composite + trois articles à commander | Transformer un constat en course à faire |
| Meilleures ventes | Classement sur 14 jours | Savoir sur quoi il gagne vraiment |

| Critère d'acceptation |
|---|
| La marge affichée est lue sur les mouvements de stock réels, jamais sur un prix d'achat théorique |
| Le graphe est lisible sans JavaScript (géométrie calculée côté serveur) |
| Aucune tuile n'affiche « — » sur une boutique fraîchement installée : l'état initial est prévu |

### 2.3 — Caisse ★

**L'écran qui décide de l'adoption.** Contrainte imposée par le conseil d'experts : une ligne
saisie en moins de 4 secondes.

- grille d'articles à cibles tactiles larges, prix en évidence, stock visible ;
- recherche par libellé ou référence ; **la touche Entrée ajoute l'article s'il ne reste qu'un
  résultat visible** — c'est le comportement d'une douchette de code-barres ;
- ticket à droite (en bas sur mobile), quantité modifiable au pas-à-pas ;
- totaux HT / TVA / à payer **calculés depuis le TTC**, parce que c'est le prix affiché qui fait foi ;
- trois moyens de paiement : espèces, Mobile Money, carte ;
- **clé d'idempotence générée côté client** : une retransmission après coupure ne crée pas deux ventes.

| Critère d'acceptation |
|---|
| Un encaissement produit, en une transaction : le ticket, la sortie de stock au CMP, les écritures comptables |
| Un même `operation_id` renvoyé deux fois ne dédouble ni le ticket, ni le stock, ni les écritures |
| Un règlement incomplet est refusé avec le montant manquant |
| L'état du réseau est visible en permanence, pas découvert au moment de l'échec |

### 2.4 — Stock

Liste, recherche, trois filtres (tous / sous le seuil / rupture), valeur totale au CMP.
Chaque ligne porte son état sous forme de **puce icône + libellé** — jamais la couleur seule.

| Critère d'acceptation |
|---|
| Un stock négatif s'affiche comme une anomalie à régulariser, pas comme une erreur bloquante |
| La fiche article montre l'historique complet des mouvements, avec CMP après chaque ligne |

### 2.5 — Ventes

Journal des tickets clôturés, avec HT, TVA et total. C'est l'écran que le gérant ouvre quand il
doute d'un caissier.

### 2.6 — Comptabilité (lecture seule)

Balance générale SYSCOHADA, dernières écritures, et quatre agrégats : chiffre d'affaires, coût des
ventes, marge brute, TVA collectée.

> **Aucune saisie comptable au palier 1.** On montre ce que le système a produit tout seul. C'est
> une démonstration, pas un module de tenue — et l'écran porte la mention imposée par l'arbitrage
> A5 : *« la plateforme prépare, votre expert-comptable révise et atteste. »*

| Critère d'acceptation |
|---|
| La balance est équilibrée, et le déséquilibre serait affiché s'il survenait |
| Chaque écriture affiche son journal, sa pièce et son état — validée signifie immuable |
| Une boutique au régime **IGS** ne voit pas de TVA à déclarer |

---

## 3. Ce qui est explicitement dehors

| Hors périmètre | Quand |
|---|---|
| Vitrine publique, catalogue en ligne, panier acheteur | Palier 3 au plus tôt |
| Livraison, transporteurs, zones, preuve de livraison | Après la preuve du coût unitaire (arbitrage A7) |
| Encaissement en ligne, séquestre, portefeuille marchand | Quand on acceptera de manipuler l'argent d'autrui |
| Commission sur GMV | Le palier 1 ne facture qu'un abonnement |
| Affiliation, revendeurs, retail media | Palier 5 |
| Paie, bulletins, déclarations sociales | Bloqué par l'arbitrage A6 |
| Commandes fournisseurs et encours | Palier 2 — l'entrée de stock manuelle suffit d'abord |

**Le code du dépôt va plus loin que cette liste** : les modèles de commandes, de paiement et
d'affiliation existent et sont testés. Ils ne sont simplement pas exposés dans l'interface. C'est
délibéré : on ne montre pas au client une fonction qu'on ne sait pas encore opérer.

---

## 4. Ce que la construction de l'interface a changé au plan

Trois enseignements de la mise en œuvre, qui modifient les documents antérieurs.

### 4.1 — La marge du jour est le vrai produit d'appel, pas le stock

Le document 04 disait « le stock crée l'usage quotidien ». Vrai. Mais en construisant le tableau
de bord, l'écran qui frappe n'est pas la liste de stock : c'est **la tuile de marge**. Le stock est
ce qu'on installe ; la marge est ce qu'on vend.

**Conséquence sur l'argumentaire commercial :** la première phrase du commercial devient
*« vous savez ce que vous avez vendu hier ; savez-vous ce que vous avez gagné ? »*, et la
démonstration commence par le tableau de bord, pas par la caisse.

### 4.2 — Le régime IGS n'est pas un cas limite, c'est le cas courant

Le [document 07](07-comptabilite-paie-syscohada.md) a été corrigé : l'IGS couvre tout le chiffre
d'affaires jusqu'à 50 M F et dispense de TVA. **Une bonne part des premiers clients ne facturera
donc pas de TVA du tout.** L'interface doit le refléter (elle le fait déjà sur l'écran
comptabilité) et le moteur de facturation devra traiter ce cas dès le palier 2, pas comme une
exception tardive.

### 4.3 — L'offre « Étal » à 15 000 F n'a pas de sens au palier 1

La grille du [business plan](03-business-plan.md) prévoit trois offres. Au palier 1, il n'y en a
qu'une : **30 000 F/mois, tout compris**. Trois offres à vendre quand on est seul, c'est trois
conversations au lieu d'une, et un client qui choisit le moins cher pour de mauvaises raisons.
La segmentation revient au palier 3, quand il y aura quelqu'un pour la porter.

---

## 5. Ce qu'on mesure chez les trois premiers clients

L'hypothèse H2 — l'adoption réelle du back-office — se teste ici, pas dans un questionnaire.

| Indicateur | Seuil | Lu où |
|---|---|---|
| Tickets encaissés par semaine et par boutique | **≥ 20** | Journal des ventes |
| Jours d'écart entre le stock théorique et le dernier inventaire | ≤ 7 | Mouvements d'ajustement |
| Part des ventes saisies à la caisse vs déclarées oralement | ≥ 80 % | Comparaison au relevé Mobile Money du gérant |
| Temps de saisie d'une ligne | < 4 s | Chronométré sur place, à l'œil |
| Connexions par semaine par le gérant lui-même | ≥ 3 | Journal d'audit |

**Si le gérant ne se connecte jamais et laisse le caissier faire, l'abonnement ne sera pas
renouvelé.** C'est le signal d'alerte le plus fiable, et il apparaît dès le deuxième mois.

---

## 6. Les cinq chantiers de l'installation, livrés

Les cinq manques identifiés à la livraison de l'interface sont comblés. Chacun touche au
journal du stock ou à celui de la caisse : **aucun n'écrit un compteur en direct.**

### 6.1 — Reprise de stock

Deux écrans, pour deux moments différents.

**Nouvel article** (`/stock/nouvel-article/`) est l'écran de l'installation : un seul formulaire
produit le produit, la variante, le seuil d'alerte et l'entrée de stock valorisée. Le bouton
« Enregistrer et ajouter le suivant » existe parce qu'on saisit vingt références d'affilée, debout
dans une réserve, pas une par session.

Deux garde-fous : la référence est normalisée en majuscules et refusée si elle existe déjà ; un
coût d'achat supérieur au prix de vente est **signalé** — vendre à perte se décide, ça ne doit pas
se découvrir au bilan.

**Entrée de stock** (`/stock/<article>/entree/`) sert au réapprovisionnement. Le formulaire propose
le coût moyen courant comme valeur de départ, et le moteur recalcule le CMP.

### 6.2 — Inventaire physique

`/stock/inventaire/` liste le dépôt et n'attend qu'une chose : les quantités comptées.

**Le stock théorique est masqué par défaut.** C'est le point qui a demandé une correction après
coup : le premier écran affichait le théorique à côté du champ de saisie, ce qui annulait le
contrôle — un compteur qui connaît le chiffre attendu ne compte plus, il confirme. Un bouton le
révèle quand le gérant veut vérifier une ligne douteuse.

Les lignes vides sont ignorées : un article non compté n'est pas régularisé. Les écarts passent
par des mouvements d'ajustement horodatés et motivés. La virgule décimale française est acceptée.

### 6.3 — Session de caisse

`/caisse/session/` ouvre la caisse sur un fonds déclaré et la ferme sur un comptage. L'écart est
calculé et annoncé — manquant ou excédent. Sans cet écran, il n'y a pas d'écart de caisse, donc
aucun contrôle du caissier.

L'écran de fermeture rappelle de compter **avant** de consulter le théorique, pour la même raison
qu'à l'inventaire.

### 6.4 — Ticket imprimable

`/ventes/<ticket>/ticket/` rend le ticket au format bande 80 mm, en monospace pour que les
colonnes s'alignent sans tableau. Il porte les mentions légales du vendeur — raison sociale, RCCM,
NIU — le détail des lignes, les totaux et le moyen de paiement.

Une feuille d'impression dédiée retire toute l'interface. À défaut d'imprimante, le bouton
**Partager** utilise le partage natif du téléphone : le ticket part par WhatsApp, qui est le canal
réel du commerce ici. Le bouton n'apparaît que si l'appareil sait le faire.

Une boutique au régime **IGS** n'affiche ni ligne de TVA ni total hors taxes, mais la mention
« TVA non applicable ».

### 6.5 — Export intégral

`/boutique/export/` produit une archive ZIP de six fichiers CSV — articles, stock, mouvements,
tickets, lignes de ticket, écritures comptables — plus une notice. Séparateur point-virgule,
UTF-8 **avec BOM** : sans lui, Excel en français ouvre les accents en mojibake.

C'était une promesse écrite dans l'interface et dans le contrat de bail. Elle est maintenant vraie,
et testée — y compris sur le fait qu'elle ne franchit pas la frontière d'une autre boutique.

---

## 7. Le mode hors ligne

C'est la contrainte d'architecture ADR-004, et la seule pièce que les tests Django ne pouvaient
pas prouver seuls.

### 7.1 — Ce qui a été posé

| Pièce | Rôle |
|---|---|
| `manifest.webmanifest` | L'application s'installe sur l'écran d'accueil, démarre sur la caisse |
| `service-worker.js` | Coquille en cache : la caisse s'ouvre sans réseau |
| `hors-ligne.js` | File d'attente **IndexedDB** des opérations non transmises, rejeu automatique, catalogue de secours |
| `imprimante.js` | Pilote ESC/POS sur Bluetooth basse consommation |

Le service worker est servi **depuis la racine** : sa portée est celle de son URL, et depuis
`/static/js/` il n'aurait intercepté que `/static/js/`.

**Deux stratégies de cache, choisies selon ce que coûte une donnée périmée.** Le statique est
servi depuis le cache d'abord — il est versionné, et servir l'ancien une seconde économise de la
data. Les pages sont servies depuis le réseau d'abord — un stock périmé affiché comme frais serait
pire qu'une page lente.

**Ce que le service worker ne met jamais en cache : l'encaissement.** Une vente n'est pas une
ressource, c'est une écriture.

### 7.2 — Les quatre règles de la file

1. **Une opération enregistrée n'est jamais perdue.** Elle part, ou elle attend. Le panier est vidé
   dès la mise en file, pas à la confirmation du serveur : le client a payé, il attend son ticket,
   la vente ne peut plus être reprise. C'est au serveur de rattraper le réseau, pas au vendeur.
2. **Le rejeu est séquentiel.** La numérotation des tickets doit rester déterministe ; deux ventes
   envoyées en parallèle se disputeraient le même numéro.
3. **Une erreur métier sort de la file.** Réessayer indéfiniment une opération que le serveur refuse
   ne la fera jamais passer, et bloquerait toutes les suivantes derrière elle.
4. **Une erreur réseau reste dans la file.** C'est exactement le cas pour lequel elle existe.

Le nombre d'opérations en attente est affiché en permanence dans le bandeau. L'état du réseau ne se
découvre pas au moment de l'échec.

La file ne transporte plus seulement des ventes : chaque entrée porte son URL, et le vidage ne
connaît rien du métier qu'il achemine. C'est ce qui a permis d'y ajouter les réceptions de
marchandise sans toucher à la mécanique de rejeu.

### 7.3 — Ce qui a été prouvé, et comment

`scripts/verifier-hors-ligne.js` coupe réellement le réseau du navigateur et vérifie quinze points :

```
ok  une vente en ligne est transmise immédiatement
ok  la file est vide après une vente en ligne
ok  hors ligne, la vente est conservée
ok  la file contient la vente hors ligne
ok  une seconde vente hors ligne s'empile
ok  la file survit au rechargement de la page
ok  la file se vide au retour du réseau
ok  les trois ventes sont arrivées au serveur
ok  la même clé d'idempotence ne crée qu'un ticket
ok  la caisse affiche son catalogue sans réseau
ok  la fraîcheur du catalogue est annoncée
ok  hors ligne, la réception est conservée
ok  la file mélange ventes et mouvements de stock
ok  la réception part au retour du réseau
ok  le mouvement est bien inscrit au journal du stock
```

Le neuvième point est celui qui rend tout le reste possible : **c'est parce que le serveur est
idempotent que le rejeu est sûr.**

C'est aussi ce script qui a trouvé un défaut invisible autrement : `hors-ligne.js` est chargé en
`defer`, donc **après** les scripts en ligne des pages. Le compteur d'opérations en attente du
bandeau s'abonnait à un objet qui n'existait pas encore, et restait muet sans qu'aucune erreur ne
soit levée (docs/19, §7.6).

---

## 8. Les manques du palier 1, comblés

Les cinq points listés ici comme bloquants ont été traités, puis deux autres qui les suivaient de
près. Ce qu'ils ont chacun coûté, et ce que chacun a appris.

### 8.1 — Rôles et permissions dans les vues

C'était le plus urgent, et ce n'était pas une fonctionnalité : **tout utilisateur rattaché voyait
tout, la marge comprise.** Un coût d'achat affiché sur un écran ouvert au comptoir circule dans le
quartier avant la fin de la journée.

La matrice vit dans `apps/accounts/permissions.py`, en code. Onze droits élémentaires, dont deux
qu'il fallait absolument séparer :

- **`cout.voir`** — ce que la marchandise a coûté. Le magasinier en a besoin : il saisit des prix
  d'achat.
- **`marge.voir`** — ce qu'elle rapporte. Le magasinier n'a aucune raison d'y accéder.

| Rôle | Ce qu'il ouvre |
|---|---|
| Gérant | Tout |
| Caissier · Vendeur | Caisse, ventes, stock — **ni coût, ni marge** |
| Magasinier | Stock, mouvements, coûts d'achat — **pas la marge**, pas la caisse |
| Comptable | Comptabilité, marge, coûts, export — pas le stock, pas la caisse |
| RH | Fiche de la boutique |

Trois décisions de conception valent d'être notées :

1. **La source de vérité est en code, pas en base.** `Role.permissions` n'est qu'un miroir
   d'affichage. Une table modifiable à chaud n'a pas à pouvoir ouvrir la marge à un caissier.
2. **Le tableau de bord est composé, pas grisé.** Un magasinier n'a pas la version amputée du
   tableau du gérant : il a le sien — mouvements du jour, valeur du stock, réapprovisionnement.
   Et la marge n'est pas cachée en CSS, elle **n'est pas calculée** : un `display:none` voyage
   quand même sur le réseau.
3. **Le refus est explicite.** Un 403 qui nomme le rôle et le droit manquant, pas une redirection
   silencieuse — sinon l'utilisateur croit à une panne et appelle.

L'écran « Ma boutique » affiche la matrice appliquée à l'équipe réelle : un gérant qui confie sa
caisse doit pouvoir vérifier lui-même que la marge est fermée à sa caissière.

### 8.2 — Catalogue hors ligne

La caisse s'ouvrait sans réseau, mais sur la page en cache — **catalogue figé compris**. Un article
créé le matin restait invisible l'après-midi sur un poste hors ligne.

La grille est désormais reconstruite au chargement à partir de `/caisse/catalogue.json`, rangé dans
IndexedDB à chaque passage en ligne. Sans réseau, on ressort le dernier catalogue connu, **avec sa
date affichée en clair** : « catalogue du 12/03 à 17:41, les quantités peuvent avoir bougé ». Un
catalogue périmé présenté comme frais serait pire qu'un catalogue daté.

Le rendu serveur reste en place : la caisse fonctionne sans JavaScript.

### 8.3 — Mouvements de stock hors ligne

Seules les ventes étaient mises en file. Une réception saisie au moment où le réseau tombait était
perdue — et le camion, lui, était bien reparti : la marchandise était en réserve et absente du
système.

Deux changements :

- `POST /stock/<id>/entree.json` accepte une réception **idempotente**, avec la même clé
  d'opération qu'un ticket. Sans elle, un rejeu fausserait le coût moyen pondéré à chaque
  retransmission.
- `localStorage` a cédé la place à **IndexedDB**. Il était synchrone, plafonné à quelques
  mégaoctets et partagé avec tout le reste ; il tenait pour trente tickets, pas pour une file
  hétérogène plus un catalogue. Un repli sur `localStorage` subsiste pour les navigateurs qui
  refusent IndexedDB : mieux vaut une file dégradée qu'aucune.

Détail qui compte : la clé primaire de la file est **auto-incrémentée**, pas l'identifiant
d'opération. L'ordre des clés est l'ordre d'insertion, et c'est lui qui garantit le rejeu
séquentiel ; un UUID en clé primaire aurait donné un ordre aléatoire — et des numéros de tickets
dans le désordre.

### 8.4 — Multi-dépôts dans l'interface

Le modèle portait les dépôts depuis le premier jour ; les écrans supposaient le principal. Une
réserve et un comptoir ont pourtant des stocks différents, et un comptage fait dans la mauvaise
réserve produit des écarts inventés de toutes pièces.

- Un **dépôt d'exploitation** est choisi dans le bandeau — celui où l'on encaisse, où l'on reçoit,
  où l'on compte. Le sélecteur n'apparaît qu'à partir de deux dépôts.
- **Une session de caisse ouverte l'emporte sur ce choix.** Changer de dépôt en cours de journée ne
  déplace pas la caisse ; sinon une vente sortirait le stock d'une réserve pendant qu'on encaisse
  au comptoir.
- La liste de stock garde son **propre** filtre de dépôt : ici on consulte, là-bas on travaille.
- Un écran de **transfert** a été ajouté. Le dépôt source n'y est pas un champ : c'est le dépôt
  courant. On sort la marchandise du dépôt où l'on se trouve, pas d'un dépôt désigné de loin.
- L'ouverture d'un dépôt respecte le **quota de l'emplacement loué** — une contrainte commerciale
  (docs/03, §1.1), donc annoncée à l'écran autant qu'appliquée.

### 8.5 — Impression thermique directe

`window.print()` ouvre la boîte de dialogue du navigateur, qui ne sait pas parler à la bobine posée
sur le comptoir. Le pilote `imprimante.js` compose un ruban ESC/POS et l'envoie en Bluetooth basse
consommation.

Trois choix imposés par le terrain :

- **Les accents sont repliés sur l'ASCII.** Les imprimantes bon marché démarrent en CP437 et
  ignorent la commande qui change de table : un « é » y sort en caractère grec. Un ticket sans
  accents reste lisible ; un ticket en charabia, non.
- **La largeur est un réglage**, 32 ou 48 colonnes, mémorisé. Le parc est partagé entre bobines
  58 et 80 mm.
- **Le ruban est composé à partir des données du ticket**, pas en grattant le DOM : un changement
  de gabarit ne doit pas casser silencieusement l'impression.

**Ce que cela ne couvre pas, et il faut le dire :** iOS n'expose Web Bluetooth dans aucun
navigateur ; les imprimantes USB, Wi-Fi et Bluetooth « classique » (SPP) restent hors d'atteinte ;
et la page doit être servie en HTTPS. Là, l'impression navigateur et le partage WhatsApp restent
les chemins — et une application native reste nécessaire pour un pilotage complet.

### 8.6 — L'isolation au niveau ligne, et le piège qui la rendait décorative

La troisième barrière du multi-tenant existait sur le papier depuis le document 09 ; elle n'existait
pas en base. Elle y est désormais : une politique sur chacune des 24 tables scopées, pilotée par un
réglage de session que le contexte Python pose à chaque changement de boutique. Réglage absent :
rien n'est visible.

**Le premier essai n'a rien prouvé du tout.** Les 156 tests sont passés sans qu'une seule ligne ne
change de comportement — le rôle applicatif était superutilisateur, et un superutilisateur ignore
toutes les politiques *sans lever la moindre erreur*. Les tests d'isolation passaient
triomphalement en ne testant rien. C'est le piège le plus coûteux du dispositif, et le seul qui ne
laisse aucune trace : `manage.py verifier_rls` et un test dédié le détectent maintenant, et
`docker compose` retire l'attribut à l'initialisation de la base.

Une fois la barrière réellement active, elle a immédiatement attrapé deux fautes qui dormaient : un
test qui préparait un dépôt pour une seconde boutique sans changer de contexte, et un jeu de
démonstration qui antidatait des écritures validées — donc qui n'avait jamais tourné sur
PostgreSQL. Les deux étaient invisibles tant que la base ne disait rien.

Conséquence de sens, à retenir : `objects_all_tenants` ne contourne plus que le gestionnaire.
**Connaître son tenant ne suffit plus, il faut le déclarer.**

### 8.7 — La gestion de l'équipe

Les droits étaient appliqués et affichés, mais leur attribution passait par l'administration
Django : un gérant ne pouvait ni embaucher, ni changer un rôle, ni retirer un accès sans nous
appeler. Intenable pour un produit vendu à des commerçants — un départ se règle le jour même.

Un écran, et trois principes qui viennent du terrain :

1. **Un accès se retire, il ne se supprime jamais.** L'employé qui part a encaissé des ventes et
   signé des mouvements de stock. Effacer son compte effacerait la traçabilité de ce qu'il a fait —
   et c'est précisément ce qu'un gérant cherchera à faire un jour de colère.
2. **Le mot de passe se remet en main propre.** Il n'y a ni passerelle SMS ni courriel fiable à ce
   palier. Il est donc généré dans un alphabet qui se dicte sans ambiguïté — ni O/0 ni I/1, comme
   les codes d'apporteur — affiché une seule fois, en grand, et jamais stocké en clair. Le gérant
   peut en régénérer un : sans lui, un employé qui oublie le sien n'a aucun recours.
3. **On ne se ferme pas la porte de l'intérieur.** Un gérant ne retire pas son propre accès, et le
   dernier gérant d'une boutique ne peut ni se retirer ni se rétrograder.

Le numéro de téléphone reste l'identifiant : une personne qui a déjà un compte HyperMarché est
rattachée, jamais recréée. Un même numéro qui ouvrirait deux comptes scinderait l'historique d'un
employé en deux.

---

## 9. Ce qui reste avant d'ouvrir à un vrai client

| Sujet | Pourquoi ce n'est pas encore fait |
|---|---|
| **Adaptateurs Mobile Money** | L'interface est définie, les implémentations MTN / Orange / Camtel restent à écrire |
| **Impression hors Bluetooth LE** | Voir §8.5 : USB, Wi-Fi, SPP et iOS demandent une application native |

Aucun de ces deux points n'est une fuite de données ni une perte de saisie. C'est la différence
avec la liste précédente.
