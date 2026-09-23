# HyperMarché — la place de marché qui gère aussi la boutique

> **Nom de code : `hyper_market`.** Plateforme d'hypermarché en ligne pour la zone CEMAC :
> des commerçants louent un **emplacement numérique**, y vendent en ligne, et la plateforme
> pilote pour eux **stock, comptabilité SYSCOHADA, personnel, paie, trésorerie et marketing**.
> Un réseau de **comptes marketing et revendeurs** (liens de filiation, commissions) alimente
> le trafic et les ventes.

---

## L'idée en une phrase

Là où les places de marché africaines s'arrêtent à la vitrine, HyperMarché descend jusqu'au
back-office : **le commerçant ne loue pas une page, il loue une boutique qui tourne toute
seule.** C'est ce back-office (compta, stock, paie) qui crée la rétention qu'aucune marketplace
pure ne réussit à obtenir.

## Positionnement retenu

| Axe | Choix |
|---|---|
| Marché de lancement | **CEMAC**, en commençant par le **Cameroun** (Douala / Yaoundé) |
| Devise | **XAF (FCFA)** |
| Cible marchand | **PME et boutiques structurées** (RCCM, NIU, salariés déclarés) |
| Référentiel comptable | **SYSCOHADA révisé** |
| Encaissement | **Mobile Money** (MTN MoMo, Orange Money) + carte + paiement à la livraison |
| Stack technique | **Django 5 / DRF / PostgreSQL** (monolithe modulaire) |

## Dossier projet

Le dossier complet est dans [`docs/`](docs/). Ordre de lecture conseillé :

| # | Document | À quoi ça sert |
|---|---|---|
| 01 | [Vision & enrichissement produit](docs/01-vision-et-enrichissement-produit.md) | Le problème, la proposition de valeur, les 12 briques ajoutées à l'idée initiale |
| 02 | [Étude de marché](docs/02-etude-de-marche.md) | Taille du marché, TAM/SAM/SOM, concurrence, PESTEL, Porter, personas |
| 03 | [Business plan](docs/03-business-plan.md) | Modèle de revenus, pricing, unit economics, prévisionnel 5 ans, financement |
| 04 | [Conseil d'experts (LLM Council)](docs/04-conseil-llm.md) | 7 avis contradictoires sur le projet + arbitrages rendus |
| 05 | [Périmètre fonctionnel](docs/05-perimetre-fonctionnel.md) | Les 14 modules, epics, user stories, priorisation MoSCoW |
| 06 | [Affiliation, marketing & revendeurs](docs/06-affiliation-marketing-revendeurs.md) | Liens de filiation, commissions, garde-fous anti-pyramidal |
| 07 | [Comptabilité & paie SYSCOHADA](docs/07-comptabilite-paie-syscohada.md) | Partie double, plan comptable, bulletin de paie camerounais |
| 08 | [Conformité juridique & fiscale](docs/08-conformite-juridique-et-fiscale.md) | OHADA, TVA 19,25 %, loi 2024/017 données personnelles, statut d'intermédiaire |
| 09 | [Architecture technique](docs/09-architecture-technique.md) | Monolithe modulaire Django, multi-tenant, sécurité, infrastructure |
| 10 | [Modèle de données](docs/10-modele-de-donnees.md) | Entités, relations, règles d'intégrité |
| 11 | [Roadmap, budget & équipe](docs/11-roadmap-budget-equipe.md) | 5 lots de livraison, staffing, budget par phase |
| 12 | [Risques & KPI](docs/12-risques-et-kpi.md) | Registre des risques cotés, tableau de bord de pilotage |
| 13 | [Sources](docs/13-sources.md) | Toutes les références chiffrées utilisées |
| 14 | [Guide du développeur](docs/14-guide-developpeur.md) | Mise en route du code, règles à ne pas enfreindre |
| 15 | [Plan de validation terrain](docs/15-plan-de-validation-terrain.md) | Protocole des 10 semaines de phase 0, guides d'entretien, seuils du jalon G0 |
| 16 | [Partenariat cabinet comptable](docs/16-partenariat-cabinet-comptable.md) | Sélection, frontière de responsabilité, recette des barèmes de paie |
| 17 | [Démarrer sans capital](docs/17-demarrage-sans-capital.md) | **Le plan effectivement applicable aujourd'hui** : 450 000 F, 5 paliers autofinancés |
| 18 | [Produit du palier 1](docs/18-produit-palier-1.md) | Le plan raffiné : les écrans et leurs critères, l'installation en 90 minutes, le mode hors ligne |
| 19 | [Système de design](docs/19-systeme-de-design.md) | Jetons validés, règles de visualisation, pièges rencontrés |
| 20 | [Déploiement](docs/20-deploiement.md) | Mise en ligne sur une machine, variables qui décident, ce que le démarrage refuse |
| 21 | [Manuel d'utilisation](docs/21-manuel-utilisation.md) | **Pour le commerçant et son équipe** : la journée d'un caissier, d'un magasinier, d'un gérant ; ce que le logiciel refuse de faire et pourquoi |

> **Deux conditions bloquantes** avant d'engager les 400 M FCFA d'amorçage et d'ouvrir les modules
> réglementés : la [validation terrain](docs/15-plan-de-validation-terrain.md) (jalon G0) et le
> [partenariat cabinet](docs/16-partenariat-cabinet-comptable.md) (arbitrages A5 et A6).
>
> **Sans capital de départ**, le plan de financement du document 03 n'est pas exécutable. Le
> [document 17](docs/17-demarrage-sans-capital.md) le remplace pour la phase de démarrage : les
> deux conditions ci-dessus y sont remplies **avec du temps plutôt qu'avec de l'argent**.

## Mise en route du code

```bash
make installer                  # environnement virtuel + dépendances
cp .env.example .env            # DEBUG=True, sinon le CSS n'est pas servi
docker compose up -d db redis   # PostgreSQL 16 + Redis
make migrer
make demo                       # référentiels + 6 boutiques, 20 jours de ventes
make servir                     # http://localhost:8000/
make tester                     # 652 tests
```

## Mettre en ligne

**Une adresse publique, gratuitement.** `render.yaml` décrit une instance de démonstration :
Render crée la base PostgreSQL et le service, fabrique les secrets, et charge les six boutiques
au premier démarrage. Aucun terminal. Depuis Render : **New → Blueprint**, choisir ce dépôt,
branche `claude/online-marketplace-platform-97d5tr`, **Apply**.

Ce que l'offre gratuite coûte : l'instance **s'endort** après quinze minutes (≈ 50 s de réveil),
la base **expire au bout de trente jours**, et les identifiants de démonstration sont **publics** —
qui a le lien peut modifier le stock. Aucune donnée réelle n'a sa place là.

**Sur une machine à soi** — image de production, pile `docker compose`, sauvegardes :

```bash
cp .env.production.example .env.production   # puis remplir
make deployer
```

Le détail de chaque choix est dans le [document 20](docs/20-deploiement.md).

Comptes de démonstration (mot de passe `demo1234`) — les rôles diffèrent, et les écrans avec :

| Téléphone | Rôle | Ce qu'il voit |
|---|---|---|
| `+237699110011` | Gérant, Quincaillerie Ateba | Tout |
| `+237699110022` | Caissière, Quincaillerie Ateba | Caisse, ventes, stock — **ni coût, ni marge** |
| `+237699110033` | Magasinier, Quincaillerie Ateba | Stock et coûts d'achat — **pas la marge** |
| `+237677220022` | Gérante, Bella Cosmétiques | Tout |
| `+237677220033` | Comptable, Bella Cosmétiques | Comptabilité, marge, export — pas le stock |
| `+237655330011` | Gérante, Pharmacie du Wouri | Tout — **lots, péremptions, ordonnancier et DCI** |
| `+237691440011` | Gérante, Boulangerie Bonapriso | Tout — **fiches techniques et production du jour** |
| `+237677550011` | Gérant, Auto Pièces Ndokoti | Tout — **recherche par véhicule et références croisées** |
| `+237698660011` | Gérant, Nkolo Électronique | Tout — **numéros de série, garantie et atelier** |

Détails dans le [guide du développeur](docs/14-guide-developpeur.md).

## Agir là où la donnée se lit

Chaque liste du back-office porte sa barre d'outils : **créer**, **modifier**,
**supprimer**, **filtrer**. Sélectionnez une ligne et la barre dit ce qu'elle fera
d'elle, nommément. On ne modifie qu'une ligne à la fois — deux lignes n'ont pas la
même correction à apporter, et le bouton se grise **en le disant** plutôt que de
laisser croire à une panne. La suppression, elle, porte sur autant de lignes qu'on
veut : faire le ménage est exactement le geste qui en concerne plusieurs.

Une règle gouverne tous ces écrans : **on supprime ce qui n'a pas d'histoire, on
retire ce qui en a une.** Une référence créée par erreur il y a trois minutes
disparaît vraiment ; un article vendu l'an dernier est retiré de la vente, parce
qu'effacer son libellé rendrait muets des tickets imprimés et des écritures
validées. Le logiciel tranche ligne par ligne, l'annonce avant, et dit après
lequel des deux il a fait. Les journaux en ajout seul — ventes, écritures,
mouvements — n'offrent rien d'autre que les filtres, et disent pourquoi.

Les filtres vivent **dans l'adresse de la page** : elle se partage, se met en
favori, et survit à un retour arrière. Deux personnes qui ouvrent le même lien
voient la même liste.

## Dix métiers, dix logiciels

Une boutique déclare **ce qu'elle vend**, et l'interface s'adapte : commerce général, pharmacie,
quincaillerie, cosmétique, restauration, boulangerie, mode, électronique, pièces auto, produits
frais. Référentiel dans [`apps/marketplace/metiers.py`](apps/marketplace/metiers.py).

Le métier change trois choses, et aucune n'est de l'habillage : **le vocabulaire** (un pharmacien
lit « médicament », un restaurateur « plat »), **les valeurs par défaut** — une officine est
exonérée de TVA, un poissonnier vend au kilo — et **les champs du formulaire**, la date de
péremption n'apparaissant que là où elle a un sens.

Pour les quatre métiers qui périment, le stock est suivi **lot par lot** : les sorties consomment
le plus proche de périmer, et un écran dédié sépare ce qui est déjà perdu de ce qu'on peut encore
écouler. Un lot ne porte pas de coût — la valorisation reste au coût moyen pondéré, le lot ne
répond qu'à « quoi périme quand ».

Pour les deux métiers qui **fabriquent** — restauration, boulangerie — une fiche technique dit ce
qu'il faut pour faire un plat ou une fournée, et la production sort réellement les ingrédients du
stock. Le produit fini entre à **exactement** ce que les ingrédients ont coûté : fabriquer ne crée
pas de valeur et n'en détruit pas. Le coût de revient n'est jamais figé sur la fiche — il est
recalculé sur les coûts du jour, parce qu'un boulanger qui fixe son prix sur le prix de la farine
du mois dernier vend à perte sans le voir. Et un invendu sort en **perte**, jamais en écart de
comptage : c'est la seule manière de savoir en fin de mois ce que la fabrication a jeté.

En **officine**, un médicament peut être marqué « délivré sur ordonnance ». Il disparaît alors de
la vente en ligne — le pharmacien doit voir l'ordonnance, et un panier ne la montre pas — et la
caisse réclame le prescripteur, réseau ou pas. Une vente qui arrive sans mention n'est pourtant
**pas refusée** : la boîte est partie avec le client, et la refuser n'effacerait que la trace.
L'ordonnancier remonte ce qui reste à consigner.

Toujours en officine, un client demande du **Doliprane** et la pharmacie n'a que de l'Efferalgan —
même molécule, même dosage. Renseigner la dénomination commune internationale d'une boîte la
rattache d'un coup à toutes celles qui la portent, et à celles qui arriveront ensuite : **aucune
paire n'est déclarée à la main**. Le nom commercial, lui, sert à retrouver la boîte, jamais à en
proposer une autre — substituer un article par lui-même n'est pas une substitution.

Chez un vendeur de **pièces détachées**, c'est le même mécanisme sous un autre mot : le client pose
un filtre marqué « W 68/3 » sur le comptoir, la boutique le tient sous la référence Toyota, et la
recherche les rapproche. On y cherche aussi par la voiture du client : marque, modèle,
année. Une compatibilité déclarée sans modèle couvre toute la marque, une borne d'année absente ne
borne rien — parce qu'un vendeur ne sait presque jamais quand une pièce a changé, et qu'un client
sait rarement l'année exacte de sa voiture. Le risque assumé est de montrer une pièce de trop
plutôt que d'en cacher une : au comptoir, on écarte en trois secondes une pièce qui ne convient
pas ; on ne peut rien contre une pièce qu'on ne nous a jamais montrée.

En **électronique**, un appareil se suit exemplaire par exemplaire : numéro de série ou IMEI relevé
à la réception, réclamé à la caisse, et retrouvé plus tard en le scannant. L'écran dit alors d'où il
vient, à qui il a été vendu, si la garantie court encore et combien de fois il est passé à
l'atelier. L'échéance est **figée le jour de la vente** — ramener la garantie du catalogue de douze
à six mois vaut pour les ventes futures, pas pour les engagements déjà pris. La quantité, elle,
reste la source de vérité : une livraison saisie sans les numéros n'est pas refusée, elle produit un
écart que l'écran chiffre et qui se rattrape depuis la fiche de l'article.

Ce que chaque métier prévoit **sans l'avoir encore** est affiché comme tel : lister une fonction
non écrite au milieu des autres donnerait l'impression d'un suivi qu'on n'a pas.

## Chaque boutique chez elle

Le commerçant loue un emplacement : son back-office et sa vitrine portent **son logo, ses couleurs
et son caractère typographique**, et son adresse publique lui appartient
(`/marche/boutique/<son-nom>/`). Il crée autant de **liens marketing courts** que de supports —
flyer, statut WhatsApp, enseigne — chacun compté séparément, sous `/l/<code>/`.

Les couleurs ne sont pas prises telles quelles.
[`apps/marketplace/charte.py`](apps/marketplace/charte.py) leur applique **les règles que le
produit s'applique à lui-même** : plancher de chroma, contraste minimal, version sombre éclaircie
et jamais inversée. Ce qui est corrigé est **affiché** — une couleur changée sans explication passe
pour un bogue — et la teinte, elle, n'est jamais touchée : c'est la seule chose que le commerçant
reconnaît dans son logo.

Aucune police n'est téléchargée : sur une connexion facturée au mégaoctet, un fichier de 90 Ko est
un coût que le commerçant paie sans le savoir, à chaque visiteur.

## La vitrine publique

`/marche/` — le catalogue de tout le marché, sans compte : recherche, fiche produit, vitrine par
commerçant, panier, tunnel de commande. Chaque article nomme le commerçant qui le vend et qui le
livrera.

C'est le **seul endroit du produit qui lit en contexte plateforme**, et
[`apps/vitrine/catalogue.py`](apps/vitrine/catalogue.py) en est la seule porte : elle ne rend que
des articles actifs de boutiques en état de vendre, et **jamais le stock ni le coût d'achat**. Une
boutique suspendue disparaît de la vitrine tout en gardant son back-office — on ne coupe pas sa
comptabilité à un marchand en retard de loyer.

Un panier traverse les boutiques et s'éclate en une sous-commande par commerçant, chacun acceptant,
préparant et livrant sa part séparément. On ne demande son identité à l'acheteur qu'au moment de
livrer, et passer commande **n'ouvre aucune session** : un numéro non vérifié ne donne pas accès à
l'historique de son propriétaire.

La vitrine n'encaisse pas encore — même frontière que les appels d'opérateur.

## Le back-office marchand

Seize écrans, en français, mode clair et sombre, du bureau au téléphone d'entrée de gamme.
Captures dans [`captures/`](captures/) — régénérables par `node scripts/captures.js`.

| Écran | Ce qu'il fait |
|---|---|
| **Tableau de bord** | Ventes du jour, **marge réelle au coût moyen pondéré**, valeur du stock, alertes, graphe sur 14 jours — composé selon le rôle |
| **Caisse** ★ | Grille tactile, recherche et code-barres, ticket, 3 moyens de paiement, encaissement idempotent |
| **Stock** | Liste, filtres, filtre par dépôt, valeur au CMP, historique des mouvements par article |
| **Ventes** | Journal des tickets clôturés, HT / TVA / TTC |
| **Commandes** | Files de traitement des commandes en ligne : accepter, préparer, expédier, livrer |
| **Commande** | Articles à servir, commission de place figée, refus avant expédition, retour après |
| **Comptabilité** | Balance SYSCOHADA, dernières écritures, marge brute — en lecture seule |
| **Ma boutique** | Identité, bail, équipe, dépôts, **droits de chaque rôle**, export intégral en CSV |
| **Équipe** | Embaucher, changer un rôle, retirer un accès, régénérer un mot de passe |
| **Nouvel article** | Produit, prix, coût, quantité et seuil en un seul formulaire |
| **Inventaire** | Comptage physique, théorique masqué, écarts régularisés par ajustement |
| **Entrée de stock** | Réception fournisseur, CMP recalculé, **mise en file si le réseau manque** |
| **Transfert** | Déplacement entre dépôts : ni création ni destruction de valeur |
| **Nouveau dépôt** | Ouverture d'une réserve, dans la limite du quota de l'emplacement loué |
| **Session de caisse** | Ouverture sur fonds déclaré, fermeture sur comptage, écart calculé |
| **Ticket** | Bande 80 mm, mentions légales, **impression thermique Bluetooth**, ou partage WhatsApp |

Un encaissement produit d'un seul geste **le ticket, la sortie de stock au coût moyen et les trois
écritures comptables** — c'est la promesse « zéro double saisie », et elle est testée de bout en
bout.

### Rôles et droits

Un rattachement à une boutique n'est pas un droit sur tout ce qu'elle contient. Douze droits
élémentaires, attribués par rôle dans [`apps/accounts/permissions.py`](apps/accounts/permissions.py),
séparent notamment **le coût d'achat** (que le magasinier saisit) de **la marge** (qui ne regarde
que le gérant et le comptable).

Un droit refusé ne masque pas une valeur en CSS : **elle n'est pas calculée**. Un `display:none`
voyage quand même sur le réseau.

### Isolation entre boutiques

Trois barrières indépendantes, dont aucune ne suffit seule : le contexte de requête, le
gestionnaire filtrant, et des **politiques PostgreSQL au niveau ligne** sur les 32 tables scopées.
La troisième protège de ce que les deux premières ne voient pas — une requête brute, un script,
un gestionnaire non filtré. Réglage de session absent : rien n'est visible.

```bash
make securite   # la barrière 3 est-elle réellement active ?
```

Elle a une condition d'existence facile à manquer : **le rôle applicatif ne doit être ni
`SUPERUSER` ni `BYPASSRLS`**, faute de quoi les politiques sont ignorées sans la moindre erreur.
La commande ci-dessus et un test dédié le vérifient.

### Mode hors ligne

L'application s'installe sur l'écran d'accueil et **la caisse fonctionne sans réseau**. Une vente
encaissée ou une réception saisie hors ligne est mise en file dans IndexedDB, survit au
rechargement, et part seule au retour du réseau — sans jamais se dédoubler, parce que le serveur est
idempotent. Le catalogue est rangé à chaque passage en ligne, et ressorti daté quand le réseau
manque.

```bash
node scripts/verifier-hors-ligne.js   # coupe vraiment le réseau et vérifie les 15 points
```

### API REST

`/api/v1/` — catalogue, stock, ventes, balance, encaissement et réception. Elle ne réimplémente
aucune règle : elle appelle les services du back-office.

```bash
python manage.py creer_jeton_api +237699110011 --libelle "Tablette du comptoir 2"
curl -H "Authorization: Bearer hm_…" http://localhost:8000/api/v1/moi/
```

**Le jeton porte la boutique** ([ADR-010](docs/adr/010-jeton-d-api-porteur-de-la-boutique.md)) :
un client n'a aucun moyen d'en désigner une autre, et la base ne conserve du jeton qu'une
empreinte. Les droits sont les mêmes qu'à l'écran, avec la même conséquence — le coût d'achat
est **absent** de la réponse faite à une caissière, pas mis à `null`. Détails en
[docs/14](docs/14-guide-developpeur.md), §6.

## Décisions d'architecture

Onze fiches dans [`docs/adr/`](docs/adr/), chacune nommant l'endroit du dépôt où la décision est
**tenue par un test** — une fiche que rien ne vérifie décrit une intention, pas une architecture.
Dix sont actées ; [l'ADR-008](docs/adr/008-localisation-de-l-hebergement.md), sur la localisation
de l'hébergement, reste ouverte parce qu'il lui manque un fait juridique et non une analyse.

## État du projet

- [x] Cadrage marché et positionnement
- [x] Étude de marché et business plan
- [x] Dossier de conception fonctionnelle et technique
- [x] **Lot 0** — Socle Django : multi-tenant, rôles, emplacements, isolation prouvée par les tests
- [x] **Interface du palier 1** — 13 écrans, système de design, captures de recette
- [x] **Reprise de stock, inventaire, session de caisse, ticket, export intégral**
- [x] **Mode hors ligne** — application installable, file IndexedDB, catalogue de secours, rejeu idempotent
- [x] **Rôles et droits** — le coût et la marge fermés à qui n'a pas à les voir, refus explicites
- [x] **Multi-dépôts** — dépôt d'exploitation, transferts, quota d'emplacement
- [x] **Impression thermique** — pilote ESC/POS sur Bluetooth basse consommation
- [x] **Isolation au niveau ligne** — la base refuse ce que le code aurait pu laisser passer
- [x] **Gestion de l'équipe** — embauche, rôles et retraits d'accès, sans passer par l'administration
- [x] **Socle de paiement** — routage par opérateur, disjoncteur, idempotence, prestataire simulé
  *(les appels réseau MTN / Orange / Camtel attendent un bac à sable : ils ne seront pas écrits à l'aveugle)*
- [x] **API REST** — jeton porteur de la boutique, mêmes droits qu'à l'écran, écritures idempotentes
- [x] **Décisions d'architecture** — onze fiches, chacune rattachée au test qui la tient
- [x] **Commandes en ligne** — éclatement d'un panier multi-boutiques, commission figée, chaque
  effet à son étape, écran de traitement pour le marchand
- [x] **Vitrine publique** — catalogue de tout le marché sans compte, panier, tunnel de commande,
  lien de parrainage *(l'encaissement en ligne attend le même bac à sable d'opérateur)*
- [x] **Dix métiers** — vocabulaire, valeurs par défaut et formulaires adaptés ; suivi par lot et
  péremptions, fiches techniques et production, compatibilité véhicule, ordonnancier, suivi à
  l'unité et garantie, désignations et équivalents — chacun réservé aux métiers qui en ont besoin
- [x] **Espace personnalisé** — logo, charte graphique validée, adresse publique et liens
  marketing courts, par boutique
- [x] **Mise en ligne** — image de production, pile `docker compose`, intégration continue sur
  PostgreSQL 16 ; le démarrage **refuse de servir** si l'isolation au niveau ligne n'est pas en
  place *(l'hébergeur reste à choisir — [ADR-008](docs/adr/008-localisation-de-l-hebergement.md))*
- [x] **Durcissement** — essais de mot de passe freinés par compte, téléversement d'image borné,
  réponses comprimées ; chaque défaut reproduit avant correction et tenu par un test
  *(le détail chiffré est en [docs/20](docs/20-deploiement.md), §8)*
- [ ] **Lot 1** — MVP marchand : catalogue, **stock, caisse**, commandes, paiement, affiliation
  *(reste la couche HTTP des opérateurs Mobile Money — voir
  [docs/18](docs/18-produit-palier-1.md), §9)*
- [ ] **Lot 2** — Opérations : logistique, séquestre, WhatsApp, B2B
- [ ] **Lot 3** — Comptabilité SYSCOHADA
- [ ] **Lot 4** — RH & paie
- [ ] **Lot 5** — Affiliation complète, retail media, financement de stock

> L'ordre stock/caisse avant comptabilité résulte de l'arbitrage **A1** du
> [conseil d'experts](docs/04-conseil-llm.md) : le stock crée l'usage quotidien, la comptabilité
> crée la rétention — mais on ne retient pas un client qu'on n'a pas encore acquis.

## Avertissement

Les chiffres réglementaires (taux de TVA, barèmes CNPS et IRPP, seuils de régimes fiscaux) sont
donnés à titre de cadrage et sourcés dans [`docs/13-sources.md`](docs/13-sources.md). Ils doivent
être **validés par un conseil fiscal et un expert-comptable agréé OHADA** avant toute mise en
production des modules comptabilité et paie.
