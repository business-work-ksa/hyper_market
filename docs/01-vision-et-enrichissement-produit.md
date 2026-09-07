# 01 — Vision & enrichissement du produit

## 1. L'idée de départ

> « Construire un hypermarché en ligne où des personnes louent un emplacement comme sur un
> marché. La plateforme gère leur comptabilité, leur stock, le personnel, la paie et tous les
> aspects d'une boutique. Gérer aussi le marché globalement, et créer des comptes marketing et
> revendeur avec liens de filiation. »

L'intuition est juste et elle est rare. La plupart des projets de place de marché s'arrêtent à
la vitrine : ils mettent en relation un acheteur et un vendeur, prennent une commission, et
laissent le commerçant se débrouiller avec son cahier, son stock et ses employés. Ici, l'objet
loué n'est pas une page produit, c'est **une boutique qui fonctionne**.

## 2. Le problème réel, côté CEMAC

Trois constats structurent le produit.

**a) Le commerçant camerounais structuré est mal outillé.** Le pays compte plus de 472 000 PME
actives et 569 000 unités économiques formelles, très majoritairement dans le tertiaire, et la
grande majorité fonctionne encore sur Excel, sur cahier, ou sur des outils disparates. Les ERP
disponibles (Sage 100, Odoo, Dynamics) sont vendus par des intégrateurs, coûtent cher à
déployer, et ne sont pas pensés pour un commerce de détail qui vend aussi par WhatsApp.

**b) L'infrastructure de paiement, elle, est déjà là.** Le Mobile Money représente 71 % des
transactions scripturales en zone CEMAC, avec 52,4 millions de comptes actifs et environ
23 800 milliards FCFA de volume annuel. Le Cameroun concentre à lui seul plus de 76 % de la
valeur des opérations de la zone. Le rail d'encaissement n'est plus le verrou : la gestion l'est.

**c) La place est ouverte côté marketplace.** Jumia a quitté le Cameroun en 2019, Afrimarket et
Cdiscount aussi. Le leader local, Glotelho, occupe le terrain mais reste un e-commerçant
classique. Le e-commerce camerounais est estimé autour de **490 milliards FCFA** avec une
croissance du chiffre d'affaires des plateformes de **+18 % en 2024**. C'est un marché en
croissance, sans acteur dominant, et désormais protégé de facto par la fiscalité 2026 qui
impose 3 % du chiffre d'affaires local aux plateformes étrangères sans présence physique.

**La conclusion : le verrou n'est ni le paiement, ni la demande. C'est l'outillage de gestion du
commerçant. C'est exactement là que se place HyperMarché.**

## 3. Proposition de valeur

### Pour le commerçant (locataire d'emplacement)
> « Louez un emplacement, on vous donne le magasin, la caisse, le comptable et le gestionnaire
> de paie avec. »

Un abonnement mensuel unique donne accès à une vitrine dans l'hypermarché en ligne, une gestion
de stock multi-dépôts, une caisse, une comptabilité SYSCOHADA tenue automatiquement à partir des
opérations réelles, la gestion du personnel et l'édition des bulletins de paie conformes au droit
camerounais, et un tableau de bord de trésorerie. Zéro double saisie : **une vente en ligne
génère automatiquement le mouvement de stock, l'écriture comptable et la ligne de TVA.**

### Pour l'acheteur
Un seul catalogue, un seul panier, un seul paiement Mobile Money, une seule livraison — même
quand la commande touche cinq boutiques différentes. C'est la promesse d'un hypermarché, pas
celle d'une galerie de boutiques indépendantes.

### Pour l'exploitant de la plateforme
Un revenu à trois étages : le **loyer** (abonnement, récurrent et prévisible), la **commission**
(variable, indexée sur le succès du commerçant), et les **services** (publicité interne,
logistique, avance de trésorerie). Et surtout : une donnée transactionnelle et comptable
propriétaire, qui rend le scoring de crédit possible là où les banques ne savent pas prêter.

## 4. Enrichissement de l'idée : les 12 briques à ajouter

L'idée initiale couvre la marketplace et l'ERP. Voici ce qui la transforme en entreprise
défendable.

### 4.1 — Le bail numérique, pas l'abonnement SaaS
Ne pas vendre « un logiciel ». Vendre **un emplacement**, avec un vocabulaire de marché réel :
un contrat de location à durée déterminée, un loyer mensuel, un dépôt de garantie, un état des
lieux (audit d'onboarding), un règlement intérieur, un préavis, et une **résiliation pour
manquement** (taux d'annulation trop élevé, contrefaçon, litiges non traités). Ce cadre est
juridiquement plus solide qu'un CGU de marketplace et culturellement immédiatement compris par
un commerçant de Douala.

### 4.2 — L'organisation en rayons et allées
Un hypermarché n'est pas une liste de boutiques : c'est un plan. On structure la plateforme en
**rayons** (alimentaire, électroménager, mode, cosmétique, quincaillerie, pharmacie parapharma,
services), chaque rayon ayant un **responsable de rayon** (category manager) côté plateforme, une
grille de commission propre, des règles d'assortiment et des standards qualité. Les emplacements
premium — tête de gondole, page d'accueil, bandeau de rayon — se louent plus cher. C'est du
merchandising, et c'est un produit vendable.

### 4.3 — Le commerce omnicanal, pas seulement en ligne
La majorité du chiffre d'affaires du commerçant cible se fait **en boutique physique**. Si la
plateforme ne voit que les ventes en ligne, sa comptabilité est fausse et son intérêt s'effondre.
Il faut donc une **caisse (POS) intégrée**, utilisable sur téléphone Android, qui capte les ventes
comptoir dans le même stock et le même journal comptable. C'est ce qui fait passer la plateforme
de « canal de vente accessoire » à « système d'information de l'entreprise ».

### 4.4 — Le mode dégradé et l'offline-first
La connectivité est intermittente et les coupures de courant fréquentes. La caisse et la prise
de commande doivent fonctionner **hors ligne** avec synchronisation différée et résolution de
conflits. Une commande passée hors ligne ne doit jamais être perdue, et le stock doit se
réconcilier proprement au retour du réseau. C'est un critère d'architecture, pas une option.

### 4.5 — La commande par WhatsApp et USSD
Le canal d'achat réel au Cameroun, c'est WhatsApp. On expose un **catalogue WhatsApp Business**
par boutique, une prise de commande conversationnelle, et un fallback **USSD** pour les acheteurs
sans smartphone. Chaque commande, quel que soit le canal, retombe dans le même back-office.

### 4.6 — L'entrepôt mutualisé et le fulfilment
Un vrai hypermarché a des réserves. On propose un **service de fulfilment optionnel** : le
commerçant dépose son stock dans l'entrepôt de la plateforme (Douala, puis Yaoundé), et la
plateforme prépare, emballe et livre. Cela résout la promesse « un panier, une livraison » et
crée un second point d'ancrage physique très difficile à répliquer.

### 4.7 — L'escrow et la confiance
Le paiement à la livraison domine parce que la confiance manque. On installe un **séquestre
(escrow)** : l'argent Mobile Money de l'acheteur est bloqué à la commande, libéré au commerçant
après confirmation de livraison ou expiration du délai de rétractation. Cela permet de faire
reculer le paiement à la livraison — donc les taux d'annulation, qui sont le poison économique
du e-commerce africain.

### 4.8 — L'avance de trésorerie sur historique de ventes
Une fois qu'on tient la comptabilité et le flux de ventes d'un commerçant pendant 6 mois, on sait
ce qu'aucune banque locale ne sait : sa saisonnalité, sa marge réelle, sa régularité. On peut
alors financer son réapprovisionnement (avance remboursée par prélèvement sur les encaissements
futurs). **C'est le produit le plus rentable de la plateforme, et il n'est possible que grâce à
l'ERP.** C'est la justification stratégique de tout le module comptabilité.

### 4.9 — Le retail media
Quand le trafic existe, les emplacements publicitaires internes (produits sponsorisés, bannières
de rayon, mise en avant à la recherche) se vendent à marge quasi nulle en coût variable. Chez les
places de marché matures, cette ligne représente 1 à 3 % du GMV et une part majeure du résultat.
À prévoir dès l'architecture (slots, enchères, attribution), à commercialiser au lot 5.

### 4.10 — Le réseau de revendeurs comme force de vente
Le « compte revendeur » de l'idée initiale est bien plus qu'un affilié : c'est un **commerce
social**. Un revendeur prend le catalogue des boutiques, le pousse dans son quartier, sur son
WhatsApp, dans son église ou son tontine, encaisse, et touche une marge. Il ne porte pas de stock.
C'est le canal d'acquisition d'acheteurs le moins cher qui existe dans ce contexte, et c'est
aussi une réponse à la faible pénétration de la carte bancaire.

### 4.11 — La filiation à deux niveaux, et pas plus
Le « lien de filiation » demandé est un levier viral puissant et un risque juridique réel : au-delà
de deux niveaux et si la rémunération dépend du recrutement plutôt que de la vente, on bascule
vers la vente pyramidale, prohibée. La règle produit : **maximum 2 niveaux (N1 direct, N2
indirect), commission exclusivement assise sur du chiffre d'affaires réellement encaissé et non
annulé, aucun droit d'entrée, aucun achat obligatoire.** Détail dans le document 06.

### 4.12 — L'assistance comptable humaine
Un commerçant ne fera pas confiance à un bilan produit par un logiciel qu'il ne comprend pas. On
adosse au produit un **réseau de cabinets partenaires** : la plateforme produit la balance, le
grand livre et les états financiers SYSCOHADA, un expert-comptable agréé les révise et les signe.
Le logiciel fait 90 % du travail, l'humain apporte les 10 % de crédibilité. C'est aussi un canal
d'acquisition : les cabinets amènent leurs clients.

## 5. Ce qu'on ne fait pas (au moins jusqu'au lot 5)

Cadrer par la négative évite la dispersion :

- **Pas de vendeurs informels au lancement.** Le ciblage est PME structurée. L'informel viendra
  plus tard, par un produit dégradé, une fois la machine rodée.
- **Pas de flotte de livraison en propre.** On agrège des transporteurs partenaires ; la logistique
  capitalistique se décide au lot 4, pas avant.
- **Pas d'établissement de paiement.** On s'appuie sur des agrégateurs Mobile Money agréés. Devenir
  soi-même émetteur de monnaie électronique est un projet réglementaire BEAC de plusieurs années.
- **Pas de multi-pays au lancement.** Cameroun d'abord, jusqu'à preuve du modèle. Gabon et Congo
  en année 3.
- **Pas de marketplace transfrontalière.** Les frictions douanières intra-CEMAC tueraient
  l'expérience avant qu'elle n'existe.

## 6. Les trois hypothèses qui décident du sort du projet

Tout le reste est de l'exécution. Ces trois hypothèses doivent être testées en priorité :

1. **H1 — Volonté de payer.** Une PME camerounaise du commerce accepte de payer 25 000 à
   50 000 FCFA/mois pour un outil de gestion + un canal de vente.
   *Test : 30 entretiens de découverte et 10 lettres d'intention signées avant la première ligne
   de code métier.*
2. **H2 — Adoption du back-office.** Le commerçant utilise réellement le module stock/caisse au
   quotidien, et pas seulement la vitrine.
   *Test : au lot 2, mesurer le taux de boutiques avec ≥ 20 opérations de caisse par semaine.*
3. **H3 — Économie unitaire de la livraison.** Le coût de livraison du dernier kilomètre à Douala,
   avec un taux d'annulation réaliste, laisse une marge positive.
   *Test : 200 livraisons pilotes en conditions réelles avant d'ouvrir le catalogue.*

Si H1 échoue, le modèle bascule vers du gratuit financé par la commission. Si H2 échoue, le
projet redevient une marketplace classique et perd son avantage. Si H3 échoue, il faut restreindre
l'assortiment aux produits à forte valeur ou passer en retrait en point relais.
