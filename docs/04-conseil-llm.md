# 04 — Conseil d'experts (« LLM Council »)

Le projet a été soumis à sept points de vue spécialisés, délibérément mis en tension. Chaque
membre défend son angle sans chercher le consensus. Les désaccords sont conservés tels quels ; les
arbitrages figurent au §8 et **font foi** pour la suite du dossier.

---

## 1. L'analyste marché Afrique subsaharienne

**Verdict : favorable, avec une réserve sur le timing.**

Le diagnostic de la case vide est correct. Le départ de Jumia du Cameroun en 2019 a laissé un
marché sans dominant, et la loi de finances 2026 — 3 % du chiffre d'affaires local pour les
plateformes étrangères sans présence physique — vient de créer une protection tarifaire de fait
pour un opérateur local. Le rail Mobile Money est mature : 71 % des transactions scripturales de
la CEMAC, 76,6 % de la valeur régionale au Cameroun. Ces conditions ne seront pas réunies
indéfiniment.

**Ma réserve porte sur Bolamba.** Une plateforme publique adossée à Campost, avec deux hubs
logistiques aux aéroports de Douala et Yaoundé, ne se bat pas sur le même terrain économique. Elle
peut opérer à perte pendant des années. Historiquement, ces initiatives publiques exécutent mal —
mais elles peuvent abîmer durablement les prix de marché avant d'échouer.

> **Recommandation :** ne pas se positionner en concurrent frontal de Bolamba sur le transport.
> Chercher au contraire un accord de distribution logistique. Un acteur privé qui apporte du
> volume à un opérateur postal public est un partenaire, pas une menace.

---

## 2. L'investisseur / directeur financier

**Verdict : réservé. Le plan est cohérent, la structure de risque ne l'est pas.**

Ce que j'approuve : la marge brute de 73 %, le point d'équilibre en année 3-4, un besoin avant
rentabilité de 620 M FCFA sécurisé à 1,6 Md. C'est de la discipline.

**Ce qui me pose problème : vous construisez deux entreprises en même temps.** Une place de marché
et un éditeur d'ERP sont deux métiers, deux cycles de vente, deux organisations. Les startups qui
tentent les deux simultanément échouent rarement par manque de marché — elles échouent par
dilution de l'exécution. Vous demandez 400 M FCFA d'amorçage pour livrer un MVP marketplace *et*
un socle de gestion. Sur 18 mois, avec 14 personnes, c'est tendu.

Deuxième point : **le financement de stock ne doit jamais toucher vos fonds propres.** Le document
03 le dit, je le répète parce que c'est l'erreur la plus fréquente : une fintech de prêt consomme
du capital linéairement avec sa croissance. Si vous financez le livre de crédit sur la levée, vous
détruisez le multiple de votre equity story. Partenariat bancaire ou véhicule dédié, sans
exception.

Troisième point : **le churn est votre seule vraie variable.** Le tableau de sensibilité le montre
mal parce qu'il traite le churn comme les autres. Ce n'est pas le cas : le churn est le seul
paramètre qui compose négativement dans le temps. À 32 % la première année, vous perdez un tiers
de votre base annuellement pendant que vous payez pour l'acquérir.

> **Recommandation :** amorçage à 400 M seulement si le périmètre du lot 1 est réduit à
> marketplace + stock + caisse. La comptabilité passe au seed, financée sur preuve de rétention,
> pas sur promesse.

---

## 3. Le directeur produit

**Verdict : favorable, mais l'ordre de construction proposé est le mauvais.**

Le document 01 dit « livrer le back-office avant la marketplace ». Je suis d'accord sur
l'intention et en désaccord sur la lecture : le back-office ne veut pas dire la comptabilité. Il
veut dire **le stock et la caisse**.

La séquence de valeur perçue par M. Ateba, gérant de quincaillerie, est la suivante :

1. « Je sais enfin ce que j'ai en stock. » → valeur immédiate, ressentie en 48 h
2. « Ma caisse enregistre mes ventes comptoir. » → valeur quotidienne, crée l'habitude
3. « Je vends aussi en ligne. » → valeur additionnelle
4. « Ma compta se fait toute seule. » → valeur annuelle, ressentie une fois par an
5. « Ma paie est conforme. » → valeur mensuelle, mais anxiogène

La comptabilité SYSCOHADA est le meilleur verrou de rétention **et le pire produit d'acquisition**.
Personne ne change d'outil pour une balance générale. On change d'outil parce qu'on s'est fait
voler du stock. Construire la compta en premier, c'est passer 8 mois sur une fonctionnalité que
le client ne ressentira qu'au moment du bilan.

**Mon inquiétude principale : l'adoption réelle du module de caisse.** L'hypothèse H2 du document
01 est la bonne, mais elle est sous-testée. Un commerçant qui doit saisir chaque vente comptoir
sur un téléphone abandonnera en trois semaines si le parcours dépasse 4 secondes par ligne. Le
critère de conception n'est pas la richesse fonctionnelle, c'est le **temps de saisie**.

> **Recommandation :** lot 1 = vitrine + commande + stock + caisse offline. Lot 2 = comptabilité.
> Et un budget de recherche utilisateur non négociable de 15 jours-homme par lot.

---

## 4. L'architecte technique

**Verdict : favorable. Django est le bon choix, à trois conditions.**

Le choix de Django se justifie ici mieux que dans la plupart des projets : l'administration
intégrée fait gagner 4 à 6 mois sur un back-office multi-boutiques, l'ORM et le système de
migrations sont fiables pour un domaine comptable, et l'écosystème Python facilite le recrutement
en Afrique francophone. Un monolithe modulaire, pas des microservices : à 14 personnes, les
microservices sont un impôt, pas une architecture.

**Condition 1 — Le multi-tenant doit être décidé maintenant et jamais rediscuté.** Schéma partagé
avec discriminant `boutique_id` sur chaque table métier, isolation garantie par un gestionnaire de
requêtes par défaut et une politique de sécurité au niveau ligne côté PostgreSQL. Une seule fuite
inter-boutiques dans un module comptable et le produit est mort commercialement.

**Condition 2 — L'offline-first n'est pas une fonctionnalité, c'est une contrainte
architecturale.** Elle impose des identifiants générés côté client (UUIDv7), un journal
d'opérations idempotent, et une stratégie de résolution de conflits sur le stock décidée avant la
première ligne de code. Ajouter l'offline après coup revient à réécrire l'application.

**Condition 3 — La comptabilité est un journal en ajout seul.** Aucune écriture validée n'est
modifiable ni supprimable ; on ne corrige que par contre-passation. C'est une exigence OHADA et
c'est aussi ce qui rend le système auditable. Toute conception qui permet un `UPDATE` sur une
écriture validée est à rejeter en revue de code.

> **Mon vrai souci n'est pas technique.** C'est qu'un projet de cette ampleur — 14 modules
> métier — attire naturellement la sur-ingénierie. Le risque est de passer 6 mois sur un moteur de
> règles comptables générique alors que le Cameroun a un seul plan comptable et un seul taux de
> TVA. Coder le cas simple, généraliser quand le Gabon arrivera.

---

## 5. L'expert-comptable OHADA / juriste

**Verdict : favorable sur le fond, alarmé sur deux points de conformité.**

Le référentiel est le **SYSCOHADA révisé**, applicable depuis 2018 dans les 17 États membres.
Produire une balance, un grand livre et des états financiers conformes est parfaitement faisable
en logiciel. C'est même un besoin criant : la majorité des PME camerounaises tient une comptabilité
de trésorerie inexploitable pour un banquier.

**Alarme 1 — Vous ne pouvez pas certifier.** Un logiciel ne signe pas des états financiers. Toute
communication laissant croire que la plateforme « fait la comptabilité » sans intervention d'un
professionnel agréé vous expose à l'ONECCA et détruira votre crédibilité auprès des cabinets, qui
sont par ailleurs votre meilleur canal d'acquisition. La formulation juste est : *« la plateforme
prépare, votre expert-comptable révise et atteste. »* Le réseau de cabinets partenaires du document
01 n'est pas une option commerciale, c'est une nécessité déontologique.

**Alarme 2 — La paie est un piège réglementaire.** Le bulletin camerounais combine CNPS part
salarié à 4,2 % plafonnée à 750 000 F, charges patronales (pension 4,2 %, allocations familiales
7 %, accident du travail de 1,75 % à 5 % selon le secteur), CFC 1 %, FNE 1 %, IRPP progressif à
quatre tranches, CAC à 10 % de l'IRPP, plus la taxe communale et la redevance audiovisuelle. Une
erreur de barème génère un redressement chez **tous** vos clients simultanément. Il vous faut un
moteur de paie versionné par période d'application, un jeu de tests de non-régression construit
sur des bulletins réels validés par un cabinet, et une revue annuelle après chaque loi de
finances.

Point positif que personne n'a relevé : **le dépôt de marque à l'OAPI couvre 17 pays en une seule
formalité.** À faire immédiatement, avant toute communication publique.

> **Recommandation :** ne pas ouvrir le module paie avant d'avoir un partenariat formalisé avec un
> cabinet agréé qui valide les barèmes et engage sa responsabilité sur le paramétrage.

---

## 6. Le directeur des opérations et de la logistique

**Verdict : le point de rupture du projet est ici, et il est sous-estimé.**

Tout le reste du dossier est de la construction de valeur. La logistique, elle, est de la
destruction de valeur si elle est mal calibrée. Trois réalités :

**a) L'adressage n'existe pas.** À Douala, une adresse est une description : « après le carrefour
Bonamoussadi, la maison bleue derrière la pharmacie ». Cela signifie un appel téléphonique par
livraison, des tentatives multiples, et un coût réel très supérieur au coût affiché. Il faut
capturer un point GPS + un repère textuel + un contact, dès la commande, sans exception.

**b) Le paiement à la livraison génère 15 à 30 % d'annulation.** C'est le chiffre qui tue les
places de marché africaines. Un colis annulé coûte deux trajets et zéro revenu. L'escrow Mobile
Money proposé au document 01 est la bonne réponse, mais il faut le rendre attractif : réduction
sur les frais de livraison en cas de prépaiement, garantie de remboursement en 24 h affichée
partout. **Convertir 20 points de paiement à la livraison vers le prépaiement vaut plus que
n'importe quelle optimisation de coût de transport.**

**c) « Un panier, une livraison » est une promesse coûteuse.** Grouper des articles de cinq
boutiques différentes suppose un point de consolidation, donc l'entrepôt — c'est-à-dire du capital
et des frais fixes dès l'année 2. Sans entrepôt, on livre cinq colis, et l'économie s'effondre.

> **Recommandation ferme :** ne pas ouvrir le catalogue au-delà de 200 boutiques avant d'avoir
> prouvé le coût unitaire de livraison sur 200 livraisons réelles. Et ouvrir en priorité les rayons
> à forte valeur au kilo (cosmétique, mode, petit électronique), pas l'alimentaire, dont l'économie
> de livraison est structurellement négative à cette échelle.

---

## 7. L'avocat du diable

**Verdict : trois raisons sérieuses de ne pas faire ce projet.**

**a) La cible ne veut peut-être pas être formalisée.** Le dossier suppose qu'une PME camerounaise
veut une comptabilité propre et une paie conforme. Une partie non négligeable de ces entreprises
optimise activement sa visibilité fiscale et sociale. Leur vendre un système qui trace chaque
vente, chaque salarié et chaque marge, c'est leur vendre un risque. **Le meilleur argument produit
du dossier est peut-être son principal obstacle commercial.** Cela ne condamne pas le projet, mais
cela impose de tester la volonté de traçabilité, pas seulement la volonté de payer.

**b) Le concurrent réel n'est pas Glotelho, c'est WhatsApp.** Gratuit, universel, déjà installé,
socialement confiant. Le produit doit être 10 fois meilleur sur un axe précis, pas 20 % meilleur
sur dix axes. Si la réponse à « pourquoi quitter WhatsApp ? » n'est pas formulable en une phrase
par un commercial de terrain, le projet n'a pas de proposition de valeur.

**c) Le périmètre est celui d'un éditeur de 200 personnes.** Marketplace, POS, stock, compta, paie,
RH, affiliation, retail media, logistique, crédit. Chacune de ces briques est une entreprise. En
faire dix à quatorze personnes suppose de n'en faire aucune très bien. Le risque n'est pas
l'échec : c'est la médiocrité sur tous les fronts, qui ne se voit qu'au bout de trois ans.

> **Ma question au comité :** quelle est la seule brique que vous accepteriez de livrer si vous
> n'aviez droit qu'à une ? Si la réponse n'est pas immédiate et unanime, le projet n'est pas prêt.

---

## 8. Arbitrages rendus

Ces décisions tranchent les désaccords ci-dessus et **s'imposent au reste du dossier**.

| # | Question | Décision | Motif |
|---|---|---|---|
| **A1** | Ordre de construction : compta d'abord ou stock/caisse d'abord ? | **Stock + caisse au lot 1. Comptabilité au lot 3.** | Le directeur produit l'emporte sur le document 01. Le stock crée l'usage quotidien ; la compta crée la rétention, mais on ne retient pas un client qu'on n'a pas encore acquis. |
| **A2** | Périmètre de l'amorçage à 400 M FCFA | **Réduit à : vitrine, commande, paiement, stock, caisse offline, affiliation minimale.** Compta et paie repoussées au seed. | Le directeur financier a raison sur le risque d'exécution. Le montant reste inchangé, le périmètre se resserre. |
| **A3** | Financement du livre de crédit | **Interdiction formelle d'utiliser les fonds propres.** Partenariat bancaire ou véhicule dédié obligatoire, sinon la ligne n'ouvre pas. | Unanimité entre le DAF et le juriste. |
| **A4** | Positionnement face à Bolamba | **Partenariat logistique recherché en priorité, affrontement en dernier recours.** | Analyste marché + directeur des opérations. Un hub aéroportuaire public est un actif à louer, pas à concurrencer. |
| **A5** | Communication sur la comptabilité | **Formulation imposée : « la plateforme prépare, votre expert-comptable révise et atteste. »** Aucune mention de « comptabilité certifiée » n'est autorisée. | Exigence déontologique de l'expert-comptable. Contrainte rédactionnelle sur tout le marketing. |
| **A6** | Ouverture du module paie | **Conditionnée à un partenariat cabinet agréé signé et à une base de tests de bulletins réels.** | Le risque de redressement en masse est inacceptable. |
| **A7** | Ouverture du catalogue | **Plafonnée à 200 boutiques tant que l'économie du dernier kilomètre n'est pas prouvée sur 200 livraisons réelles.** | Directeur des opérations. C'est le garde-fou anti-mort-par-logistique. |
| **A8** | Rayons prioritaires | **Cosmétique, mode, petit électronique, pièces détachées, quincaillerie. L'alimentaire frais est exclu jusqu'au lot 4.** | Marge marchand > 30 % et valeur au kilo élevée : les deux conditions d'une logistique rentable. |
| **A9** | Réponse à « pourquoi quitter WhatsApp ? » | **Phrase officielle : « WhatsApp vous fait vendre. HyperMarché vous dit combien vous avez gagné, ce qu'il vous reste en stock, et vous encaisse sans que vous couriez après l'argent. »** | Réponse exigée par l'avocat du diable. Elle devient l'argumentaire commercial de référence. |
| **A10** | Test de l'hypothèse de formalisation | **Ajout d'un volet dédié à l'étude terrain : mesurer l'appétence à la traçabilité, pas seulement au prix.** | Objection (a) de l'avocat du diable, retenue. |
| **A11** | Profondeur de la filiation | **2 niveaux maximum, commission assise exclusivement sur du chiffre d'affaires encaissé et non annulé.** | Juriste. Non négociable, codé en dur. |
| **A12** | Architecture | **Monolithe modulaire Django, schéma partagé + `boutique_id`, offline-first natif, journal comptable en ajout seul.** | Architecte technique, sans opposition. |

## 9. La brique unique

Question de l'avocat du diable : *si vous n'aviez droit qu'à une seule brique, laquelle ?*

**Réponse du comité : la gestion de stock avec caisse intégrée, connectée au Mobile Money.**

C'est la seule brique qui, prise isolément, résout une douleur quotidienne, se démontre en cinq
minutes sur un téléphone, ne demande aucune expertise réglementaire, et produit dès le premier
jour la donnée qui rendra possible tout le reste : la comptabilité, le scoring de crédit, et la
mesure de la performance du réseau d'affiliation.

**Tout le reste du produit est un enrichissement de cette brique. Si elle échoue, rien d'autre ne
tient.**
