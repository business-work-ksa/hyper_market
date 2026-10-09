# 23 — Confiance et lutte contre la fraude

> ⚠️ Cadrage de conception écrit pour l'équipe produit, pas un avis juridique. Toute référence
> marquée **[À VÉRIFIER]** n'a pas pu être contrôlée sur le texte officiel au moment de la
> rédaction : elle doit l'être par un avocat inscrit au barreau du pays concerné avant d'être citée
> dans les conditions générales, dans un écran ou dans un courrier. Les points à trancher sont
> reportés au registre du [document 08](08-conformite-juridique-et-fiscale.md), §9.
>
> Décision d'architecture associée : [ADR-013](adr/013-confiance-par-paliers-et-sequestre.md).

**En une phrase :** on ne cherche pas à reconnaître le fraudeur à l'entrée — on s'arrange pour
qu'il n'ait rien à emporter tant qu'il n'a pas prouvé, par des livraisons réelles, qu'il n'en est
pas un.

Trois principes, auxquels chaque règle de ce document se rattache :

1. **L'argent de l'acheteur ne quitte le séquestre qu'après une livraison confirmée par
   l'acheteur**, puis un délai de réclamation. Une livraison *déclarée* par le marchand ne libère
   rien : c'est exactement ce que déclarerait une fausse boutique.
2. **Ce qu'on confie se gagne.** Le plafond de séquestre et le délai de libération dépendent d'un
   palier, lui-même gagné par des livraisons confirmées, de l'ancienneté et peu de litiges perdus.
3. **Aucun contrôle unique n'est tenu pour suffisant.** Et une règle de partage entre la machine et
   l'humain : **l'automate peut réduire ce qu'on confie, jamais retirer ce qu'on doit.** Il
   plafonne, retarde, masque, signale. Geler un versement, suspendre une boutique, trancher un
   litige : c'est un humain, nommé, avec un motif, dans le journal.

---

## 1. Les menaces, classées par coût

Le classement suit le **coût attendu pour HyperMarché** : fréquence probable × montant par
incident × atteinte à la confiance. Ce dernier terme n'est pas décoratif : le séquestre est le
levier qui fait passer l'acheteuse du paiement à la livraison au prépaiement (docs/02, §4 —
« convertir Sandrine »), et une seule histoire d'arnaque qui circule sur WhatsApp coûte plus que
son montant.

| # | Menace | Qui perd l'argent | Fréquence attendue | Montant par incident | Pourquoi ce rang |
|---|---|---|---|---|---|
| 1 | Détournement du compte de versement | Le marchand honnête, **puis la plateforme** | Rare | Tout ce qui est dû à la boutique | La plateforme a payé la mauvaise personne et **doit toujours** la somme au marchand : elle paie deux fois |
| 2 | Paiement Mobile Money hors plateforme | L'acheteur | **Très fréquente** | Un panier (10 000 à 300 000 F) | Aucune protection possible, et chaque victime raconte « on m'a volé sur HyperMarché » |
| 3 | Fausse boutique qui encaisse et disparaît | Les acheteurs, puis la plateforme si le séquestre a cédé | Occasionnelle, par vagues (rentrée, fêtes) | Plafond du palier × nombre de boutiques du même fraudeur | Sans séquestre, c'est la menace n° 1 ; avec, elle ne réussit que si une autre couche a cédé |
| 4 | Abus de confiance interne (employé, administrateur, livreur) | Le marchand, l'acheteur ou la plateforme | Occasionnelle | Très variable ; illimité pour un administrateur | Rare, mais celui qui connaît les règles sait les contourner |
| 5 | Fraude au code de remise, SIM swap | L'acheteur ou la plateforme | Occasionnelle | Un panier ; un solde entier si le SIM swap vise un gérant (→ 1) | Le code de remise est la clé qui libère le séquestre |
| 6 | Faux acheteurs, commandes fictives | Le marchand (frais de livraison), la plateforme (confiance faussée) | Fréquente | 1 800 F par livraison refusée (docs/12, §7.4) ; un palier indû | Bon marché pour le fraudeur, et c'est le moyen d'**acheter** un palier |
| 7 | Usurpation d'identité (pièces prêtées ou achetées) | — directement ; elle rend possibles 3 et 8 | Fréquente | — | C'est un vecteur, pas une perte : elle rend la plainte inutile |
| 8 | Blanchiment par des ventes fictives | Presque personne, directement | Rare | Élevé | **Dernier en argent, premier en risque existentiel** : un partenaire de paiement qui résilie, c'est la fin du prépaiement |

### 1.1 — Détournement du compte de versement

Changer le numéro de versement la veille d'un gros versement suffit à tout emporter. Quatre
chemins, tous observés sur les places de marché africaines :

- un **employé** du commerçant qui a accès au back-office remplace le numéro Mobile Money par le
  sien, un vendredi soir ;
- une **prise de contrôle du compte du gérant**, par un mot de passe partagé à toute la boutique
  ou par un **SIM swap** qui détourne ses codes SMS ;
- un **agent terrain ou un administrateur** de la plateforme qui « aide » le commerçant à
  s'inscrire et saisit un numéro qui n'est pas le sien ;
- un **ancien associé** qui a gardé ses accès.

Ce qui rend cette menace la plus chère : si la faute vient de nos contrôles, la créance du
marchand sur la plateforme n'est pas éteinte. Nous lui devons toujours son argent.

### 1.2 — Le paiement Mobile Money en dehors de la plateforme

C'est **l'arnaque la plus répandue**, et elle contourne toutes les défenses d'argent par
construction : l'argent ne passe jamais par nous. Les formes courantes :

- dans une fiche produit ou un message : « contactez-moi au 6XX XX XX XX », « payez par OM pour
  réserver », « 10 % de remise si vous payez directement », « le paiement du site ne marche pas » ;
- un faux « service client HyperMarché » qui appelle l'acheteur après sa commande et lui demande
  de « valider » par un dépôt ;
- côté marchand, la même mécanique à l'envers : **faux SMS de confirmation** imitant ceux de
  l'opérateur (« Vous avez reçu 45 000 FCFA de… ») pour obtenir une remise de marchandise, ou le
  « transfert envoyé par erreur, renvoyez-le-moi ».

Tous les marchands qui demandent un paiement direct ne sont pas des escrocs : beaucoup veulent
simplement éviter la commission. Le produit doit donc traiter le **contournement** comme une faute
contractuelle graduée, et l'**escroquerie** comme ce qu'elle est — mais les deux avec la même
réponse d'interface : l'acheteur est prévenu, la coordonnée est masquée, et la protection ne vaut
que sur la plateforme.

### 1.3 — La fausse boutique qui encaisse et disparaît

Des prix attractifs sur des produits qui se vendent vite (téléphones, téléviseurs, groupes
électrogènes, fournitures à la rentrée), des commandes prépayées, des livraisons déclarées, puis
plus personne. Sans séquestre, le gain est total. Avec séquestre, elle ne gagne que si elle obtient
des **confirmations de livraison** (collusion avec un livreur, codes arrachés à l'acheteur) ou si
l'argent est libéré avant que les acheteurs ne réclament.

Variante à ne pas oublier, **l'escroquerie longue** : une boutique vend honnêtement pendant six
mois, atteint le palier sans plafond, puis lance une « grande promotion » prépayée et disparaît.
C'est le cas que les paliers seuls n'arrêtent pas (§2.5, signal de pic d'encours).

### 1.4 — L'abus de confiance interne

Trois populations, trois gestes :

| Qui | Geste typique | Couche qui le borne |
|---|---|---|
| **Employé du commerçant** | Remboursement vers son propre numéro ; annulation après encaissement à la livraison ; changement du compte de versement | Remboursement vers l'origine (§2.1), compte de versement (§2.4), droits du back-office |
| **Administrateur de la plateforme** | Valider une boutique qu'il contrôle ; forcer une libération ; trancher un litige pour un complice ; lire des données (ADR-012) | Quatre yeux (§2.3), journal en ajout seul (§2.6), revue croisée (§6.6) |
| **Livreur** | Garder l'espèce du paiement à la livraison ; substituer la marchandise ; obtenir le code avant la remise ; « client absent » puis revente | Code de remise (§2.1), litige (§6.1), rapprochement des encaissements à la livraison |

### 1.5 — Fraude au code de remise et SIM swap

Le code de remise (docs/05, M06 : « code OTP remis par l'acheteur au livreur ») est la clé qui
confirme la livraison, donc qui libère l'argent. Attaques connues :

- le livreur appelle avant d'arriver : « donnez-moi le code pour que je valide la sortie » ;
- l'acheteur donne le code, reçoit le colis, puis ouvre un litige « non reçu » ;
- un SIM swap sur l'acheteur pour recevoir le code (rentable seulement sur de gros paniers) ;
- un SIM swap sur le **gérant**, qui ramène au §1.1.

### 1.6 — Faux acheteurs et commandes fictives

Trois mobiles : **acheter un palier** (la boutique se passe dix commandes à elle-même et monte au
palier 1 — pour 5 % de commission sur de petits paniers, c'est le moyen le moins cher d'obtenir
notre confiance) ; **nuire à un concurrent** (commandes à la livraison jamais retirées) ;
**frauder l'affiliation** (docs/06, §6). Le premier est créé par notre propre système de paliers :
c'est à nous de le verrouiller (§2.2, §3.2).

### 1.7 — Usurpation d'identité avec des pièces prêtées ou achetées

La CNI d'un parent, des copies de pièces qui circulent sur WhatsApp, un prête-nom payé quelques
milliers de francs, le RCCM d'une société en sommeil. Notre vérification **ne peut pas prouver**
que la personne de la pièce est celle qui exploite la boutique. Elle peut prouver la cohérence (le
visage devant la caméra est celui de la pièce), l'unicité (cette pièce ne sert pas déjà ailleurs)
et le lien avec l'argent (le titulaire du compte de versement est la personne de la pièce).

### 1.8 — Le blanchiment par des ventes fictives

Une boutique « vend » à des acheteurs qui sont les mules du blanchisseur : l'argent entre par de
nombreux numéros Mobile Money, ressort en versements qui ressemblent à du chiffre d'affaires. Ou
un remboursement demandé vers un autre numéro que celui qui a payé : un transfert déguisé. Le
préjudice direct est faible ; le risque est que le partenaire de paiement, lui-même assujetti,
nous coupe, et que la responsabilité pénale des dirigeants soit recherchée.

---

## 2. Les défenses en couches

Chaque couche est décrite par ce qu'elle arrête, ce qu'elle **n'arrête pas**, et l'endroit du code
où elle vit. La colonne « n'arrête pas » est la plus importante : c'est elle qui justifie la
couche suivante.

**Qui arrête quoi** (● arrêt principal, ◐ partiel, — rien) :

| Menace | Séquestre | Paliers | Quatre yeux | Compte de versement | Signaux | Journal | Confiance publique |
|---|---|---|---|---|---|---|---|
| 1. Détournement du versement | — | — | ● | ● | ◐ | ◐ | — |
| 2. Paiement hors plateforme | — | — | — | — | ● | — | ● |
| 3. Fausse boutique | ● | ● | ◐ | ◐ | ◐ | — | ◐ |
| 4. Abus interne | ◐ | — | ● | ● | ◐ | ● | — |
| 5. Code de remise, SIM swap | ◐ | ◐ | — | ◐ | ◐ | — | — |
| 6. Commandes fictives | ◐ | ◐ | — | — | ● | — | — |
| 7. Usurpation d'identité | — | ● | ◐ | ● | ◐ | — | — |
| 8. Blanchiment | ◐ | ◐ | — | ● | ● | ● | — |

Aucune ligne ne tient sur une seule colonne. C'est la décision de l'ADR-013.

### 2.1 — Le séquestre jusqu'à la livraison confirmée par l'acheteur

**Le mécanisme.** Le paiement prépayé arrive chez le partenaire agréé, sur le compte de
cantonnement (docs/08, §5.2). Pour **chaque sous-commande** — donc chaque boutique d'un panier —
un `Sequestre` constate la part cantonnée et garde la trace des ordres donnés au partenaire ; il ne
*détient* rien. Le mode de paiement se choisit aussi par sous-commande
(`SousCommande.mode_paiement`) : le plafond d'une boutique nouvelle peut refuser le prépaiement
chez elle sans le refuser chez sa voisine. La part n'est libérée au portefeuille du marchand que si
**trois conditions** sont réunies :

1. la livraison est **confirmée** (`SousCommande.livraison_confirmee_le`) — par le code de remise
   à six chiffres saisi à la livraison (seule son empreinte est stockée, les essais ratés sont
   comptés et le code se verrouille), par le geste de l'acheteur sur sa page de commande, ou par
   confirmation implicite (ci-dessous) ;
2. le **délai de libération du palier** est écoulé depuis cette confirmation (la fenêtre pendant
   laquelle l'acheteur peut encore ouvrir un litige) ;
3. aucun `Litige` n'est ouvert sur la sous-commande.

Ensuite seulement, le portefeuille (compte de suivi, pas un dépôt) est crédité, et le versement
part vers le `CompteVersement` vérifié et utilisable.

**Deux règles qui vont avec :**

- **Le remboursement retourne toujours au numéro qui a payé.** Jamais « sur mon autre numéro »,
  jamais en espèces. Cette seule règle ferme le blanchiment par remboursement (§1.8) et l'arnaque
  de l'employé qui rembourse vers lui-même (§1.4).
- **Confirmation implicite, bornée.** Un acheteur qui ne confirme jamais bloquerait indéfiniment
  un marchand honnête. Le chantier séquestre a retenu : sans confirmation ni litige **sept jours
  après l'expédition déclarée** (`SousCommande.expediee_le`), la livraison est réputée confirmée
  (`Sequestre.IMPLICITE`). C'est le point faible assumé du dispositif — une fausse boutique qui
  déclare des expéditions à des acheteurs inattentifs — d'où deux exigences : **relancer
  l'acheteur** avant l'échéance (à J+3 et J+6, par les canaux disponibles), et faire figurer la
  règle dans les conditions générales acheteur (J15). Le signal de pic de prépaiement (§2.5)
  couvre le cas où une boutique neuve accumule des expéditions sans aucune confirmation.

**Arrête :** la fausse boutique sur toutes les commandes prépayées (§1.3) ; l'essentiel du « non
reçu » de mauvaise foi, puisque l'argent est encore là quand le litige s'ouvre ; le blanchiment par
remboursement.

**N'arrête pas :** le paiement hors plateforme (§1.2), par définition ; le paiement à la livraison,
où l'argent n'entre jamais en séquestre (la fraude y porte sur la marchandise et sur le livreur) ;
une confirmation obtenue par collusion ou par un code arraché (§1.5) ; une disparition *après*
libération.

**Où il vit :** `apps/payments/models.py` (`Sequestre`, une part par sous-commande, avec
l'invariant `montant_libere + montant_rembourse == montant` ; `Versement`) ;
`apps/orders/models.py` (`SousCommande.livraison_confirmee_le`, distinct de `livree_le`,
`expediee_le`, `mode_paiement`, et `Litige` qui gèle la part contestée) ; le service de libération
(chantier séquestre).

**Points d'attention pour le chantier séquestre :**

- `livree_le` ne libère **jamais** rien. Un test doit le dire.
- Le remboursement vers le numéro payeur doit être tenu par le code, pas seulement par l'écran.
- `PortefeuilleMarchand.numero_momo` ne doit **jamais** servir de destination de versement : seule
  la table `CompteVersement` le peut. Sinon, les règles du §2.4 ont une porte de service.

**Pourquoi un séquestre tenu par un tiers et non sur un compte de la plateforme :** voir §4.2 et
l'ADR-013. En une ligne : recevoir et garder l'argent d'autrui est une activité réglementée, et un
compte à notre nom confondrait les fonds des acheteurs avec nos créanciers.

### 2.2 — Les paliers de confiance : un plafond plutôt qu'un refus

**Le mécanisme.** Chaque boutique a un palier (`Boutique.palier_confiance`, de 0 à 3) qui fixe
deux choses : le **plafond** de ce qu'elle peut avoir en séquestre à la fois, et le **délai** entre
la livraison confirmée et la libération. Au-delà du plafond, la vitrine ne refuse pas la vente :
elle **propose le paiement à la livraison** au lieu du prépaiement. Les valeurs sont au §3.1.

**Pourquoi un plafond plutôt qu'un refus des nouveaux marchands :**

- À l'entrée, une fausse boutique ressemble trait pour trait à une vraie boutique neuve. Un filtre
  assez strict pour arrêter la première refuse la seconde — et notre cible, ce sont précisément des
  commerces jeunes (42 % des PME créées en 2025 portées par des moins de 35 ans, docs/02).
- Le plafond rend la perte **connue d'avance** : au palier 0, une fausse boutique qui aurait
  franchi toutes les autres couches emporte au plus 150 000 F.
- Il oblige le fraudeur à **investir des semaines de ventes honnêtes** pour un gain plafonné.
- Le repli sur le paiement à la livraison laisse vendre le marchand honnête : il perd un confort,
  pas une vente.

**On monte lentement, on descend tout de suite.** Le palier est recalculé chaque nuit par
`apps/confiance/paliers.py` : seules les livraisons **confirmées** comptent, on ne monte que d'un
palier à la fois et pas avant la fin de la fenêtre de litige du palier courant ; on redescend dès
que le taux de litiges perdus dépasse le plafond. Descendre ne fait que réduire ce qu'on confie :
c'est dans le rôle de l'automate (principe 3). Chaque changement est journalisé en ajout seul
(`ChangementPalier`) avec ses raisons, pour répondre au marchand qui demande pourquoi ses fonds
sont retenus.

**Arrête :** la rentabilité de la fausse boutique (§1.3) ; le volume d'un prête-nom (§1.7) ou d'un
blanchisseur (§1.8) tant qu'il n'a pas d'historique.

**N'arrête pas :** l'escroquerie longue au palier 3, sans plafond (→ signal de pic d'encours,
§2.5) ; l'achat d'un palier par des auto-commandes (→ le nombre d'**acheteurs distincts** est déjà
mesuré, `MesureConfiance.acheteurs_distincts` ; il reste à en faire une condition de montée,
§3.2) ; plusieurs boutiques ouvertes par la même personne (→ identités partagées, §2.5).

**Où il vit :** `apps/marketplace/confiance.py` dit ce que chaque palier permet ;
`apps/confiance/paliers.py` le calcule et l'écrit (`MesureConfiance`, `ChangementPalier`) ; les
paiements lisent le champ sans importer le calcul. Un niveau inconnu retombe au palier 0
(`palier()`), jamais au plus large.

### 2.3 — La vérification d'identité à quatre yeux, sans copie conservée

**Ce qu'on vérifie :**

- une **pièce** de la liste du pays (`cemac.py` : CNI, passeport, carte consulaire, titre de
  séjour), en cours de validité ;
- une **preuve de présence** : l'original vu en présentiel ou en visio (le mode est consigné) —
  une simple photo de pièce reçue par message prouve seulement qu'on possède une photo ;
- le **téléphone** du gérant, par un appel de l'administration attesté (il n'existe pas encore de
  passerelle SMS, et rien ne prétend en envoyer) ;
- l'**existence commerciale** : RCCM pour une société ou un commerçant, **ou déclaration
  d'entreprenant** (§4.1) — refuser l'entreprenant, c'est refuser une grande part de notre cible ;
  et c'est bien le RCCM **de la fiche** : un RCCM modifié depuis sa vérification redevient un manque ;
- l'**identifiant fiscal** du pays (NIU au Cameroun et au Congo, NIF ailleurs) ;
- la **cohérence des noms** : titulaire du compte de versement = nom lu sur la pièce, ou raison
  sociale.

Aucune boutique ne devient `active` sans ces contrôles (`exiger_activable`), et seulement dans un
pays ouvert (`cemac.PAYS_OUVERTS`).

**Ce qu'on garde — une attestation, pas une copie** (`DossierKyc`, `apps/accounts/models.py`) :

| Conservé | Non conservé (par défaut) |
|---|---|
| Type de pièce, pays émetteur, date d'expiration | Image recto verso de la pièce |
| Nom tel qu'il figure sur la pièce | Photo, vidéo de l'appel |
| Numéro de pièce, **masqué** partout sauf dans le dossier | Date et lieu de naissance, filiation, adresse, signature |
| Mode de vérification (présentiel, visio, document reçu puis supprimé, appel) | |
| **Empreinte SHA-256** du document reçu, s'il y en a eu un : la preuve qu'on a vu *celui-là* | |
| Qui a déclaré, qui a validé, quand, décision, motif | |

Une copie ne s'enregistre que si un stockage persistant et privé est désigné explicitement
(`KYC_STOCKAGE_COPIES`) — la porte existe pour le cas où le partenaire l'exigerait (J14), elle est
fermée par défaut.

**Recommandation :** chiffrer le numéro de pièce au repos. Il est aujourd'hui en clair en base
(masqué à l'affichage) parce que la détection des identités partagées le compare entre boutiques ;
une empreinte à clé secrète (HMAC) permettrait la même comparaison sans garder le numéro lisible
dans une sauvegarde (§7, Q8).

**Pourquoi on ne garde pas les copies :**

- **Minimisation** (loi 2024/017, docs/08 §4.2) : les finalités sont d'identifier notre
  cocontractant, de détecter la réutilisation d'une pièce et de pouvoir agir en justice. Le nom, le
  numéro et l'attestation y suffisent. L'image ajoute un visage, une signature, une date de
  naissance — rien dont ces finalités aient besoin.
- **Fiabilité** : la production tourne sans disque durable (ADR-008) ; une copie écrite sans
  stockage désigné disparaîtrait au prochain redémarrage — une preuve qu'on croit avoir et qu'on n'a
  plus.
- **Sécurité** : une base de scans de CNI est la matière première exacte de l'usurpation
  d'identité (§1.7). La perdre ferait de nous un fournisseur de la fraude qu'on combat.
- **La preuve existe ailleurs** : l'opérateur Mobile Money a identifié le titulaire du compte de
  versement, et une réquisition judiciaire l'obtient de lui (§4.4).

**Réserve :** le partenaire de paiement, lui-même assujetti à la LBC/FT, peut exiger que les
copies soient conservées. Dans ce cas, de préférence, c'est **lui** qui les conserve — l'image lui
est transmise directement ; à défaut, le stockage désigné par `KYC_STOCKAGE_COPIES`. Point J14 du
registre ; la ligne « chiffrement au repos des pièces d'identité » du docs/08 §4.2 est à lire à la
lumière de ce paragraphe.

**Les quatre yeux.** Celui qui valide n'est ni celui qui a déclaré, ni celui qui a ouvert la
boutique dans la console, ni un membre de son équipe (`refus_quatre_yeux`) ; la base le refuse
aussi pour les pièces (contrainte `kyc_quatre_yeux`). Rejeter reste ouvert au déclarant : un refus
n'ouvre rien.

| Geste | Deux personnes distinctes ? | Où c'est tenu |
|---|---|---|
| Valider une pièce d'identité, un RCCM, un identifiant fiscal | **Toujours** | `verification.py` + contrainte en base |
| Vérifier un compte de versement | **Toujours** | `verification.py` (`verifier_compte`) |
| Lever un gel, forcer une libération, rembourser hors règle | **Oui** | Procédure §6.3 ; à coder avec les écrans de versement |
| Trancher un litige au-dessus d'un seuil, ou visant une boutique de l'exploitant (ADR-012, §5) | **Oui** | Procédure §6.1 |

**Arrête :** les faux grossiers ; l'administrateur ou l'agent terrain qui valide seul sa propre
fausse boutique ; la même pièce ou le même compte sur plusieurs boutiques (avec le signal
d'identités partagées).

**N'arrête pas :** une pièce authentique prêtée par une personne consentante ; un faux de bonne
qualité (nous n'avons pas accès au fichier national des titres d'identité **[À VÉRIFIER : existence
d'un service de vérification ouvert aux entreprises]**).

**Où il vit :** `apps/confiance/verification.py` (les règles) ; `apps/accounts/models.py`
(`DossierKyc`, la preuve) ; `Boutique.clean()` pour l'administration Django ; écrans
`/plateforme/verifications/` et `/boutique/verification/`.

### 2.4 — Le compte de versement : vérifié, unique, avec 48 h de carence

**Le mécanisme** (`CompteVersement`, `apps/marketplace/models.py`) :

- le **titulaire** déclaré chez l'opérateur doit être la personne dont la pièce a été vérifiée ;
  si l'agrégateur offre une consultation du nom du titulaire, on la compare automatiquement
  **[À VÉRIFIER auprès du partenaire]** ;
- **un seul compte vérifié** à la fois (contrainte d'unicité) : quand le nouveau est vérifié,
  l'ancien est retiré dans la même transaction ;
- **carence de 48 h** après vérification (`utilisable_le`) : aucun versement ne part pendant ce
  temps, **ni vers l'ancien ni vers le nouveau**. Attendre est sûr dans les deux sens : l'ancien
  est peut-être la SIM perdue, le nouveau est peut-être l'attaquant ;
- **notification sur tous les canaux disponibles** à la déclaration et à la vérification —
  bandeau du back-office, courriel, et SMS à l'ancien numéro dès qu'une passerelle existera
  (aujourd'hui il n'y en a pas) — avec, à terme, un bouton « Ce n'est pas moi » qui gèle
  immédiatement les versements. Ce gel-là peut être automatique : il ne fait qu'arrêter une sortie
  d'argent, et il est demandé par le titulaire. Tant qu'il n'existe pas de SMS, l'appel de
  l'administration au gérant (déjà utilisé pour vérifier son téléphone) tient lieu de canal
  indépendant pour les changements de compte d'une boutique active ;
- **la destination d'un versement est figée à la demande** (`Versement` recopie opérateur, numéro
  et titulaire) : changer de compte après coup ne détourne pas un versement déjà demandé ;
  l'exécution exige la référence de l'opérateur, unique ;
- on ne supprime jamais un compte ni un versement : on le **retire** ou on l'**annule**, avec un
  motif. Dans un an, il faut pouvoir dire où est parti chaque franc.

**Pourquoi 48 h :**

- **24 h ne suffisent pas.** Une attaque un samedi à 20 h passe avant que le gérant, qui coupe ses
  données le soir et passe son dimanche au marché, ait vu la moindre notification. La connectivité
  est intermittente (coût de la data, délestages — docs/02, PESTEL).
- **72 h et plus coûtent trop à l'honnête.** Le marchand qui change de numéro a déjà attendu le délai
  de libération ; trois jours de plus sans versement, c'est un fournisseur qu'il ne paie pas.
- 48 h couvrent **deux cycles jour-nuit** : deux occasions de voir l'alerte.

**Question ouverte :** 48 h *calendaires* laissent passer l'attaque du vendredi 18 h, utilisable le
dimanche 18 h. Option à trancher sur les premières données : reporter la fin de carence au
prochain jour ouvré à 8 h (§3.2).

**Arrête :** l'employé, l'ancien associé et l'agent terrain (§1.1, §1.4) ; la plupart des SIM swap
sur le gérant, à condition que la notification passe par un canal que la SIM détournée ne contrôle
pas (courriel, bandeau, appel).

**N'arrête pas :** le gérant lui-même quand c'est lui le fraudeur ; un gérant qui ne lit aucune
notification.

**Où il vit :** `apps/marketplace/models.py` (`CompteVersement`) ; `apps/confiance/verification.py`
(`DELAI_DE_CARENCE`, `verifier_compte`, `compte_de_versement_utilisable`) ;
`apps/payments/models.py` (`Versement`). Les versements ne lisent que `CompteVersement` —
**jamais** `PortefeuilleMarchand.numero_momo`, champ antérieur qui ferait sinon une porte de
service.

### 2.5 — Les signaux de risque : des indices, pas des preuves

`apps/confiance/signaux.py` cherche les signaux chaque nuit et les écrit dans `SignalRisque` ; la
console (`/plateforme/signaux/`) les présente avec une **preuve lisible** (« même téléphone que
telle boutique, suspendue le… », pas « score 83 »). Un administrateur **écarte ou confirme**, avec
un motif, au journal ; confirmer ne suspend rien — suspendre est un second geste, délibéré.
**Aucun signal ne suspend une boutique.** Les seules réactions automatiques permises sont celles
qui réduisent l'exposition sans rien retirer à personne.

**Détecteurs déjà codés** (seuils en tête de `signaux.py`) :

| Signal | Ce qu'il suggère |
|---|---|
| Identités partagées : même téléphone, RCCM, identifiant fiscal, pièce ou compte de versement entre deux boutiques — grave si l'autre est suspendue ou résiliée | Une personne, plusieurs vitrines ; réouverture après suspension (§1.3, §1.7) |
| Prix d'appât : une boutique récente vend une part notable de ses articles à moins de la moitié du prix médian du marché | Fausse boutique qui attire des prépaiements (§1.3) |
| Pic de prépaiement : boutique jeune dont les prépaiements des 7 derniers jours dépassent 3 fois son historique | Le moment de la sortie (§1.3) |
| Litiges ou annulations sur 30 jours nettement au-dessus du marché | Boutique qui ne livre pas (§1.3, §1.6) |
| Compte de versement changé puis versement demandé dans les 7 jours — gravité critique d'emblée | Détournement, fraude interne (§1.1, §1.4) |
| Boutique active à laquelle il manque une vérification | Contournement, ou simple retard (§2.3) |

**Détecteurs proposés**, avec la réaction automatique qu'ils peuvent déclencher :

| Signal | Ce qu'il suggère | Réaction automatique permise |
|---|---|---|
| Numéro de téléphone, « OM », « MoMo », « dépôt », code USSD (*126#, #150#) dans une fiche ou un message | Paiement hors plateforme (§1.2) | Masquer la coordonnée, avertir l'acheteur, signal |
| Acheteur et boutique partagent un appareil, un numéro payeur, une adresse de livraison | Auto-commande, achat de palier (§1.6) | La livraison **ne compte pas** pour le palier |
| Plus de la moitié des livraisons confirmées d'une boutique viennent de moins de trois acheteurs | Idem | Idem |
| Livraison confirmée quelques minutes après l'expédition, ou livreur géolocalisé loin de l'adresse | Code arraché, collusion (§1.5) | Délai de libération prolongé pour cette commande |
| Encours en séquestre d'une boutique **établie** supérieur à 3 fois sa moyenne des 30 derniers jours | Escroquerie longue au palier sans plafond (§1.3) — le pic codé ne vise que les boutiques jeunes | Aucune — revue humaine prioritaire |
| Nouvel appareil du gérant puis changement de compte de versement dans l'heure | Prise de contrôle (§1.1) | Carence prolongée à 72 h |
| Boutique neuve, nombreux numéros payeurs distincts, gros paniers, zéro litige, versement réclamé aussitôt | Blanchiment (§1.8) | Aucune — revue humaine, déclaration possible (§6.2) |
| Taux d'annulation élevé des commandes à la livraison d'un acheteur | Faux acheteur (§1.6) | Paiement à la livraison retiré à cet acheteur |
| Litiges « non reçu » répétés d'un même acheteur malgré code saisi | Acheteur de mauvaise foi | Aucune — pièce versée aux litiges suivants |

**Pourquoi pas de suspension automatique sur signal :**

- **Les faux positifs sont structurels ici.** Un téléphone pour toute la famille, un seul appareil
  pour toute la boutique, des milliers d'abonnés derrière la même adresse IP de l'opérateur : ce
  qui est suspect ailleurs est banal à Douala.
- **Une suspension est publique et immédiate.** Elle coûte une vente, une réputation, parfois un
  gagne-pain — et le marchand honnête qui la subit le raconte.
- **Elle renseigne le fraudeur** sur ce que nous détectons. Et en matière de blanchiment, elle peut
  constituer une divulgation interdite (§4.3).
- Le coût d'attendre un humain est borné, justement parce que le plafond et le séquestre tiennent
  pendant ce temps.

Ce principe s'applique aussi à l'affiliation : la « mise en quarantaine automatique des gains » et
la « suspension » du docs/06 §6 se lisent comme une **retenue** automatique (permise) suivie d'une
**décision humaine** de suspension.

### 2.6 — Le journal en ajout seul

**Ce qui y entre :** chaque décision de vérification (pièce, compte de versement), chaque gel et
levée de gel, chaque libération forcée, chaque décision de litige, chaque traitement de signal,
chaque réponse à une réquisition — avec qui, quand, et le motif.

**Le mécanisme :** le même déclencheur que le journal comptable (ADR-003) et que `AccesPlateforme`
(ADR-012) : `UPDATE` et `DELETE` rejetés par la base, y compris en SQL brut.

**Arrête :** l'effacement des traces par un interne ; il fournit la chronologie d'une plainte et
d'un litige avec un marchand ; il dissuade.

**N'arrête pas :** l'acte lui-même. Un journal que personne ne lit ne protège de rien — d'où la
revue croisée hebdomadaire (§6.6).

### 2.7 — La confiance publique

La vitrine montre, pour chaque boutique : le **libellé du palier** (« Nouvelle boutique »,
« Boutique confirmée »…), le **nombre de livraisons confirmées**, l'**ancienneté**, la mention
« identité vérifiée ». Au paiement prépayé : « Paiement protégé par HyperMarché », et partout où
un acheteur peut échanger avec un marchand : **« HyperMarché ne vous demandera jamais de payer sur
un numéro personnel. »**

On n'affiche que des faits positifs et vérifiables ; les faits négatifs agissent à travers le
palier. Afficher un taux de litiges exposerait à une contestation pour dénigrement sur de petits
nombres **[À VÉRIFIER]**.

**Arrête :** donne à l'acheteur une raison de préférer une boutique établie ; rend visible la
promesse du séquestre ; éduque contre le paiement hors plateforme.

**N'arrête pas :** l'acheteur qui choisit de sortir. Et le badge devient une cible : c'est
pourquoi le décompte des livraisons est protégé (§2.2, §3.2).

---

## 3. Paramètres à calibrer

Les seuils sont des **paramètres commerciaux**, écrits en code parce que ce sont des règles
(`apps/marketplace/confiance.py`). Ils sont posés à dire d'expert, sans données : leur valeur
initiale est un pari, et ce paragraphe dit comment le corriger.

### 3.1 — Les paliers tels qu'ils sont codés

| Palier | Délai de libération | Plafond en séquestre | Pour l'atteindre : livraisons | ancienneté | litiges perdus max |
|---|---|---|---|---|---|
| 0 — Nouvelle boutique | 7 jours | 150 000 F | 0 | 0 | — |
| 1 — Boutique confirmée | 5 jours | 750 000 F | 10 | 30 jours | 10 % |
| 2 — Boutique reconnue | 3 jours | 3 000 000 F | 50 | 90 jours | 5 % |
| 3 — Boutique établie | 2 jours | Aucun | 200 | 180 jours | 3 % |

**Deux remarques pour les développeurs :**

- La description du palier 3 dit que « le délai minimal couvre la médiation de 72 h ». Deux jours
  ne couvrent pas 72 heures. En réalité le délai de libération n'a pas à couvrir la médiation — un
  litige ouvert gèle l'argent quel que soit le délai — mais la **fenêtre pour ouvrir** un litige.
  Il faut soit corriger la phrase, soit porter le délai à 3 jours si l'intention était bien de
  couvrir 72 h. À trancher par le chantier séquestre.
- Le taux de litiges perdus est calculé sur les sous-commandes **abouties depuis l'ouverture**
  (`paliers.py`) : c'est juste — un litige perdu sur deux cents n'est pas « 100 % ». Deux effets à
  surveiller : sur de petits nombres il est instable (au palier 1, un seul litige perdu sur dix
  livraisons fait déjà 10 %) ; et, cumulé, il dilue la dégradation récente d'une boutique ancienne.
  Le second est couvert par le signal « litiges sur 30 jours » (§2.5) ; une fenêtre glissante
  reste une option de calibrage (§3.2).

### 3.2 — Les autres paramètres

| Paramètre | Valeur proposée | Où | Statut |
|---|---|---|---|
| Carence d'un nouveau compte de versement | 48 h | `verification.py` (`DELAI_DE_CARENCE`) | Codé ; « ouvrées ou calendaires » et 72 h si nouvel appareil : ouverts |
| Instruction d'un litige | 72 h | docs/08, §8 | Décidé |
| Confirmation implicite de livraison | 7 jours après l'expédition déclarée | Service séquestre | Codé ; relances acheteur et clause CG à ajouter (J15) |
| Acheteurs distincts parmi les livraisons qui comptent | P1 : 7 sur 10 · P2 : 30 · P3 : 100 | `paliers.py` (déjà mesuré, pas encore exigé) | **À décider** |
| Fenêtre du taux de litiges perdus | Cumulé depuis l'ouverture ; option : 90 jours glissants | `paliers.py` | Codé cumulé ; à revoir sur données |
| Seuils des détecteurs (prix d'appât, pic, litiges, changement de compte) | Voir la tête du module | `signaux.py` | Codés ; à calibrer par M7 |
| Seuil de litige tranché à quatre yeux | 200 000 F | Procédure §6.1 | **À décider** |
| Durée maximale d'un gel conservatoire | 7 jours, renouvelable une fois | Procédure §6.3 | **À décider** (J15) |
| Gains d'apporteur sans KYC renforcé ; retrait après création | 500 000 F/mois ; 72 h | docs/06, §6 | Décidé |

### 3.3 — Ordre de grandeur : le plafond du palier 0 mord-il ?

Avec les hypothèses du business plan (12,9 M F de GMV par boutique et par an, docs/03), une
boutique moyenne fait environ **35 000 F par jour**. Son encours en séquestre est ce qu'elle a
vendu en prépayé entre le paiement et la libération : environ 2 jours de livraison (cible docs/12)
+ 7 jours de délai = 9 jours.

| Part prépayée | Encours d'une boutique moyenne au palier 0 | Le plafond de 150 000 F… |
|---|---|---|
| 30 % (démarrage) | ≈ 95 000 F | ne mord pas |
| 65 % (cible A3, docs/12) | ≈ 205 000 F | **mord** : le surplus passe au paiement à la livraison |

Au palier 1 (5 + 2 jours, 65 %), l'encours moyen est d'environ 160 000 F pour un plafond de
750 000 F : large marge. Conclusion : le plafond du palier 0 est **calibré pour mordre sur les
nouvelles boutiques les plus actives** — c'est voulu, et c'est la première métrique à surveiller.

Côté fraudeur, soyons lucides : 750 000 F au palier 1, c'est plus d'un an de SMIG (60 000 F,
docs/08 §7). Un fraudeur patient trouvera encore l'escroquerie rentable. **Le plafond ne rend pas
la fraude impossible, il borne la perte quand une autre couche a cédé.** Ce qui la rend
impossible, c'est la confirmation par l'acheteur.

### 3.4 — Comment calibrer sur les six premiers mois

Revue mensuelle, par cohorte d'inscription, avec les indicateurs suivants :

| # | Indicateur | Ce qu'il dit | S'il est trop haut |
|---|---|---|---|
| M1 | Part des commandes basculées au paiement à la livraison par le plafond, par palier | Le coût du plafond pour les honnêtes | Relever le plafond du palier concerné |
| M2 | Délai médian (et 3ᵉ quartile) pour atteindre P1 et P2 ; part des boutiques actives restées à P0 après 60 jours | La marche est-elle franchissable ? | Baisser les livraisons ou l'ancienneté requises |
| M3 | Entonnoir de vérification : abandon par étape, délai médian candidature → vérifiée | Le coût de l'entrée | Simplifier l'étape qui perd le plus |
| M4 | Litiges ouverts et perdus pour 1 000 livraisons, par palier (cible docs/12 : < 12 ouverts) | La qualité réelle par palier | Durcir le palier où il dérive |
| M5 | Réclamations reçues **après** libération | Délai de libération trop court | Allonger le délai du palier concerné |
| M6 | Pertes nettes absorbées par la plateforme, en F et en % du GMV prépayé, par palier | **Le coût de la fraude** | Durcir ; tolérance à fixer (proposition de départ : < 0,2 %) |
| M7 | Part des signaux suivis d'une mesure | Précision des signaux | Sous 10 % : le signal est du bruit, le revoir |
| M8 | Délai de traitement des signaux et des litiges | Charge humaine | Au-delà de 72 h : recruter ou automatiser le tri |
| M9 | Changements de compte de versement ; contestés pendant la carence ; fraudes avérées | L'utilité de la carence | Aucune contestation en six mois : la carence peut-être raccourcie |
| M10 | Attrition à 90 jours des nouveaux marchands, comparée à celle des P1 et plus ; plaintes sur les délais de versement | Le découragement des honnêtes | Assouplir délai ou plafond de P0 |
| M11 | Part du GMV prépayé (cible docs/12 : > 65 % en A3) | La thèse du séquestre | Chercher ce qui freine : plafond, délai, confiance |
| M12 | Signalements d'acheteurs pour paiement hors plateforme | L'ampleur de §1.2 | Renforcer masquage et message |

**Règles de modification :** un seul seuil à la fois ; pas d'assouplissement dans les trois
premiers mois sauf si M1 ou M3 montrent un coût net pour les honnêtes **et** M6 reste proche de
zéro ; chaque changement dans un commit qui cite les chiffres qui le justifient.

### 3.5 — Trop strict ou trop lâche : ce que chaque erreur coûte

| Paramètre | Trop strict | Trop lâche |
|---|---|---|
| Plafond P0 | Les nouvelles boutiques actives basculent au paiement à la livraison ; M11 recule ; le marchand conclut « HyperMarché ne me paie pas » | Une fausse boutique emporte davantage avant d'être repérée |
| Délai de libération | Trésorerie du marchand tendue ; il retourne vers WhatsApp, où l'argent arrive tout de suite | L'argent part avant que l'acheteur n'ait déballé ; M5 monte |
| Conditions de montée | Les honnêtes restent au P0 ; le palier ne signifie plus rien pour l'acheteur | Le palier s'achète par auto-commandes |
| Carence du compte de versement | Un marchand qui a perdu sa SIM attend ; il appelle le support | L'attaque du samedi soir passe |
| Signaux | Console saturée, les vrais cas noyés, l'équipe cesse de lire | La fraude n'est vue qu'aux litiges, trop tard |
| Vérification d'identité | Abandon à l'inscription (M3) ; on perd les entreprenants | Prête-noms et pièces achetées sans friction |

---

## 4. Le cadre juridique CEMAC, OHADA et national

**Mode d'emploi.** Pour chaque texte : ce qu'il implique pour le produit. Aucune référence n'a pu
être vérifiée sur un texte officiel pendant la rédaction (pas d'accès à Internet). Les numéros et
dates donnés sans marque sont ceux dont l'auteur est sûr ; **tous les autres sont [À VÉRIFIER]**,
et aucun numéro d'article ne doit passer dans les conditions générales sans contrôle.

### 4.1 — Le droit OHADA (commun aux six pays)

| Texte | Ce qu'il implique pour le produit |
|---|---|
| **Acte uniforme relatif au droit commercial général** (révisé à Lomé le 15 décembre 2010) | Définit le **commerçant** et crée le statut d'**entreprenant**, qui se déclare au RCCM sans s'y immatriculer comme une société. La vérification doit accepter trois cas : société (extrait RCCM), commerçant personne physique (immatriculation), entreprenant (déclaration). Le format du numéro RCCM varie selon les greffes et l'époque : valider avec tolérance **[À VÉRIFIER : format actuel]**. |
| Idem, régime des **intermédiaires de commerce** (commissionnaire, courtier, agent commercial) | Le commissionnaire agit **en son nom** pour le compte d'autrui : s'il était la qualification retenue, la plateforme deviendrait la venderesse aux yeux de l'acheteur, et le choix d'intermédiaire transparent (docs/08, §1) tomberait. Les CG doivent faire agir la plateforme **au nom du marchand**, comme mandataire d'encaissement **[À VÉRIFIER : qualification exacte]**. |
| **Acte uniforme relatif au droit des sociétés commerciales et du GIE** (révisé en 2014) | Vérifier que la personne qui signe est bien le **représentant légal** (gérant de SARL, directeur général de SA) : l'extrait RCCM le mentionne. |
| **Acte uniforme portant organisation des procédures simplifiées de recouvrement et des voies d'exécution** | Un créancier du marchand peut pratiquer une **saisie-attribution** entre nos mains sur les sommes que nous lui devons : nous sommes alors **tiers saisi**, tenus de déclarer immédiatement l'étendue de nos obligations, sous peine d'être condamnés à payer à sa place **[À VÉRIFIER : articles et délais]**. Il faut pouvoir bloquer le versement d'une boutique sur ordre (§6.5). |
| **Acte uniforme relatif au droit comptable et à l'information financière** (2017) | Durée de conservation des pièces justificatives, **dix ans** selon notre compréhension **[À VÉRIFIER]** ; elle fixe le plancher de conservation des preuves de transaction. |
| **Acte uniforme relatif à la médiation** (2017) **[À VÉRIFIER : date]** | Notre « médiation » de litige est en réalité une **décision contractuelle sur le sort du séquestre**. Ne pas l'appeler « arbitrage » (terme réservé à l'Acte uniforme relatif au droit de l'arbitrage), et rappeler que les parties gardent l'accès au juge. La formule « décision opposable » du docs/08 §8 est à faire valider. |

### 4.2 — Services de paiement et monnaie électronique (BEAC, COBAC)

**Les textes :** le règlement CEMAC relatif aux services de paiement **[référence à vérifier —
probablement n° 04/18/CEMAC/UMAC/COBAC du 21 décembre 2018]**, qui encadre notamment l'émission de
monnaie électronique et les établissements de paiement ; la réglementation bancaire COBAC, qui
réserve aux établissements agréés la **réception de fonds du public** ; le règlement relatif aux
systèmes, moyens et incidents de paiement **[référence à vérifier]**.

**Ce qu'ils impliquent pour un séquestre :**

- **Garder l'argent d'autrui en attendant une condition** ressemble à un service de paiement, voire
  à une réception de fonds du public. D'où le montage de docs/08 §5.2 : les fonds sont chez un
  **partenaire agréé**, sur un compte de cantonnement, et la plateforme ne fait que **donner des
  instructions** (libérer, rembourser). La question décisive est de savoir si ce rôle
  d'instruction exige lui-même un statut (agent, mandataire du partenaire) — J3 et J12.
- **Au nom de qui est le compte de cantonnement ?** S'il est au nom de HyperMarché, même chez une
  banque, le risque de requalification demeure, et les fonds des acheteurs sont exposés aux
  créanciers de la plateforme en cas de difficulté. C'est la raison pour laquelle l'ADR-013 écarte
  le séquestre sur un compte propre.
- **Le portefeuille est une créance, pas un solde.** Conséquences produit, non négociables sans
  avis contraire : pas de rechargement, pas de transfert entre portefeuilles, pas de paiement d'un
  achat avec le solde, versement automatique selon un calendrier fixe plutôt qu'un solde qu'on
  laisse dormir.
- **Défaillance du partenaire** : ce qui arrive aux fonds cantonnés, et qui porte le risque, doit
  être écrit au contrat.
- **Interopérabilité régionale** : les versements d'un pays de la CEMAC à l'autre passent par les
  opérateurs et, le cas échéant, par le dispositif d'interopérabilité du GIMAC **[À VÉRIFIER]**.
  Une carte bancaire émise hors zone (diaspora) relève de la réglementation des changes CEMAC
  **[référence à vérifier]**.

### 4.3 — Lutte contre le blanchiment et le financement du terrorisme

**Les textes :** le règlement CEMAC relatif à la prévention et à la répression du blanchiment des
capitaux et du financement du terrorisme **[référence à vérifier — probablement n° 01/16/CEMAC/
UMAC/CM du 11 avril 2016]** ; le GABAC comme organe régional ; dans chaque État, une **cellule de
renseignement financier**, l'**ANIF** (Agence nationale d'investigation financière) au Cameroun, et
selon notre compréhension une ANIF dans chacun des cinq autres pays **[À VÉRIFIER]**.

**Ce qu'ils impliquent :**

- **Sommes-nous assujettis ?** Une place de marché ne figure pas, à notre connaissance, dans la
  liste des professions assujetties ; le partenaire de paiement, lui, l'est certainement, et nous
  imposera contractuellement une partie de ses obligations sur nos marchands. **La réponse change
  le produit** (conservation des copies, J14 ; qui déclare, J23) — J13.
- **Déclaration de soupçon** : si nous sommes assujettis, c'est nous qui déclarons à l'ANIF ;
  sinon, nous transmettons au partenaire. La procédure §6.2 prévoit les deux.
- **Interdiction d'informer** : une personne qui fait l'objet d'une déclaration ne doit pas en être
  avertie. Conséquence d'interface : le message affiché à une boutique dont les versements sont
  gelés est **neutre et identique quel que soit le motif** (« vérification en cours »), et le
  support n'en dit pas plus.
- **Listes de sanctions** (gel des avoirs) : qui filtre les noms, nous ou le partenaire ? J13.
- **Conservation** : durée imposée aux assujettis, qui fixera celle du constat de vérification et
  des traces de transaction **[À VÉRIFIER : durée]**.

### 4.4 — Au Cameroun

| Texte | Ce qu'il implique pour le produit |
|---|---|
| **Loi n° 2010/021 du 21 décembre 2010 régissant le commerce électronique au Cameroun** | Obligations d'information du vendeur en ligne (identité, coordonnées, prix, conditions) : la page de chaque boutique affiche raison sociale, NIU, RCCM et un contact. Régime de responsabilité des intermédiaires techniques à confirmer **[À VÉRIFIER]**, avec son décret d'application **[référence à vérifier]**. |
| **Loi n° 2010/012 du 21 décembre 2010 relative à la cybersécurité et à la cybercriminalité** | Incrimine l'accès frauduleux, l'atteinte aux systèmes et l'usurpation en ligne : base de plainte pour une prise de contrôle de compte. Impose aux fournisseurs de services la **conservation de certaines données de connexion** et la coopération avec les autorités **[À VÉRIFIER : périmètre et durée ; si nous y sommes soumis]**. Rôle de l'ANTIC. |
| Identification des abonnés au téléphone (loi sur les communications électroniques et décret sur l'identification des abonnés) **[références à vérifier]** | Une SIM, donc un compte Mobile Money, est rattachée à une identité : c'est le fondement de la comparaison titulaire ↔ pièce (§2.4) et de la réquisition à l'opérateur (§6.5). |
| **Loi-cadre n° 2011/012 du 6 mai 2011 portant protection du consommateur** **[À VÉRIFIER : date]** | Information, clauses abusives, garanties. Nos clauses de retenue et de suspension doivent être **proportionnées, limitées dans le temps et motivées**, sinon elles risquent d'être jugées abusives à l'égard de l'acheteur. |
| **Loi n° 2024/017 du 23 décembre 2024** relative à la protection des données (docs/08, §4), pleinement applicable depuis le 23 juin 2026 | Minimisation (pas de copie de pièce, §2.3), finalité (le constat ne sert qu'à la vérification et à la preuve), sécurité (chiffrement, empreinte à clé), information de la personne au moment de la vérification, durées de conservation. Encadrement éventuel des décisions automatisées **[À VÉRIFIER]** : ne pas suspendre automatiquement (§2.5) nous en tient à l'écart. Le masquage des numéros dans les messages est un traitement du contenu des échanges : base légale à confirmer (J21). |
| **Loi n° 2016/007 du 12 juillet 2016 portant Code pénal** — escroquerie et abus de confiance (article 318 selon notre compréhension **[À VÉRIFIER]**), faux et usage de faux **[articles à vérifier]** | Sert à **nommer les comportements** dans les CG (sans promettre de peine), à fonder le dépôt de plainte (§6.4), et à rappeler au prête-nom qu'il engage sa propre responsabilité. |
| Loi régissant l'activité commerciale **[référence à vérifier — probablement n° 2015/018 du 21 décembre 2015]** | Pratiques commerciales et obligations d'information : à confronter avec la vitrine et le programme d'affiliation (J6). |

### 4.5 — Les cinq autres pays : ce qui change

Commun aux six : XAF, BEAC, COBAC, OHADA, règlement CEMAC LBC/FT. Ce qui change est dans
`apps/marketplace/cemac.py`, **ligne par ligne à valider avant l'ouverture du pays** (§6.7).

| Pays | Identifiant fiscal | Mobile Money (référentiel) | Protection des données | Ce qui change pour le produit |
|---|---|---|---|---|
| **Cameroun** (ouvert) | NIU | MTN MoMo, Orange Money | Loi n° 2024/017 | Camtel (Blue Money) est actif (docs/02) mais absent du référentiel : l'ajouter demande une migration |
| **Gabon** | NIF | Airtel Money, Moov Money | Loi n° 001/2011 du 25 septembre 2011, autorité CNPDCP **[À VÉRIFIER]** | Longueur des numéros mobiles à confirmer (8 ou 9 chiffres) |
| **Congo** | NIU | MTN MoMo, Airtel Money | Loi n° 29-2019 du 10 octobre 2019 **[À VÉRIFIER]** | Même opérateur dominant qu'au Cameroun : premier candidat naturel |
| **Tchad** | NIF | Airtel Money, Moov Money | Loi n° 007/PR/2015 **[À VÉRIFIER]** | Commerce frontalier avec Kousséri ; pièces d'identité très variées |
| **RCA** | NIF | Orange Money, Moov Money | Pas de loi générale connue de l'auteur **[À VÉRIFIER]** | Opérateurs à confirmer ; sécurité des livraisons |
| **Guinée équatoriale** | NIF | Virement bancaire seulement | Loi n° 1/2016 **[À VÉRIFIER]** | Écrans en espagnol ; pas de Mobile Money, donc pas de prépaiement Mobile Money |

Ailleurs qu'au Cameroun, les textes nationaux équivalents (commerce électronique, cybersécurité,
consommation, Code pénal) existent à des degrés divers et sont à inventorier par l'avocat local
avant l'ouverture.

### 4.6 — Les questions à poser

**À un avocat camerounais (droit des affaires et données) :**

1. Qualifier la plateforme au regard des intermédiaires de commerce de l'AUDCG : courtier,
   mandataire d'encaissement, commissionnaire ? Quelle rédaction évite la qualification de
   commissionnaire ?
2. Le paiement de l'acheteur sur le compte de cantonnement est-il **libératoire** à l'égard du
   marchand (l'acheteur est-il quitte) ? Quelle clause de mandat d'encaissement le garantit ?
3. Les clauses de retenue, de gel conservatoire, de compensation et de confirmation implicite de
   livraison (§5) sont-elles valables, et à quelles conditions de durée et de motivation, envers un
   marchand professionnel et envers un acheteur consommateur ?
4. Notre décision sur un litige : quel statut, quelle rédaction, et comment préserver l'accès au
   juge sans vider la décision de son effet sur le séquestre ?
5. Ne conserver qu'un constat de vérification (nom, numéro chiffré, empreinte) et non la copie de
   la pièce : est-ce suffisant pour agir en justice et conforme à la loi 2024/017 ? Quelles durées
   de conservation ?
6. Le masquage automatique des numéros de téléphone dans les messages entre acheteurs et marchands
   est-il licite, et sur quelle base légale ?
7. Sommes-nous soumis à la conservation des données de connexion au titre de la loi 2010/012 ?
   Pour quelle durée ?
8. Obligations exactes du tiers saisi (AUPSRVE) et forme des réquisitions auxquelles nous devons
   répondre ; qui, chez nous, peut y répondre ?
9. Articles du Code pénal à viser pour une plainte contre une fausse boutique, un prête-nom, un
   employé qui détourne un versement, une prise de contrôle de compte.
10. Faut-il un avocat par pays avant chaque ouverture, ou un cabinet régional peut-il couvrir les
    six ?

**À la COBAC, par l'intermédiaire du partenaire de paiement ou de son conseil :**

1. Le montage « fonds chez un établissement agréé, instructions données par la plateforme »
   exige-t-il de la plateforme un statut propre (agent, mandataire) ? Lequel ?
2. Le compte de cantonnement doit-il être au nom du partenaire, ou peut-il être au nom de la
   plateforme ? Quelle protection des fonds en cas de défaillance de l'un ou de l'autre ?
3. Un délai de séquestre maximal est-il imposé ou attendu ?
4. Le portefeuille marchand tel que décrit (créance, pas de rechargement ni de transfert) échappe-t-il
   bien à la qualification de monnaie électronique ?

**Au partenaire de paiement (agrégateur) :**

1. Quelles obligations de connaissance des sous-marchands nous impose-t-il ? Exige-t-il la
   conservation des copies de pièces, et par qui ?
2. Offre-t-il la consultation du **nom du titulaire** d'un compte Mobile Money avant versement ?
3. Qui filtre les listes de sanctions ? Qui déclare à l'ANIF, et comment nous transmettons un
   soupçon ?
4. Remboursement vers le numéro payeur : est-il techniquement garanti, y compris après expiration
   d'une transaction ?
5. Délais et forme de ses réponses aux réquisitions, et coordination avec les nôtres.
6. Couverture des cinq autres pays : opérateurs, agréments, compte de cantonnement par pays ?

---

## 5. Ce que disent les conditions générales

Clauses à **rédiger par l'avocat** ; la liste dit ce que le produit a besoin qu'elles disent, et
pourquoi.

| Clause | Ce qu'elle doit dire | Menace ou défense servie | Côté |
|---|---|---|---|
| **Statut d'intermédiaire et mandat d'encaissement** | Le marchand vend ; la plateforme encaisse en son nom, par un partenaire agréé ; le paiement de l'acheteur est libératoire | Socle juridique du séquestre (§4.1, §4.2) | Les deux |
| **Séquestre et délai de libération** | Fonds bloqués jusqu'à la livraison confirmée, puis délai selon le palier ; paliers publics et leurs critères | §2.1, §2.2 | Marchand |
| **Confirmation de livraison** | Le code de remise ne se donne qu'à la réception en main propre ; réputée confirmée sept jours après l'expédition sans confirmation ni litige, après relances | §1.5, §2.1 | Acheteur |
| **Compte de suivi ≠ dépôt** | Le portefeuille retrace une créance ; ni intérêts, ni rechargement, ni transfert ; versement selon calendrier | §4.2 | Marchand |
| **Compte de versement** | Titulaire = personne vérifiée ; carence ; notification ; responsabilité du marchand pour les accès qu'il donne à ses employés | §1.1, §2.4 | Marchand |
| **Droit de retenue et de suspension** | En cas de litige ou de signal : retenue des sommes concernées, gel conservatoire limité dans le temps et motivé, décision humaine, voie de contestation | §2.5, §6.3 | Marchand |
| **Compensation** | Un remboursement décidé au profit d'un acheteur s'impute sur les sommes dues au marchand, puis sur les suivantes | §6.1 | Marchand |
| **Interdiction du paiement hors plateforme** | Interdiction de solliciter ou d'accepter un paiement direct pour une commande née sur la plateforme ; sanctions graduées jusqu'à la résiliation ; **la protection ne s'applique qu'aux paiements sur la plateforme** | §1.2 | Les deux |
| **Masquage des coordonnées** | Les numéros et moyens de paiement sont masqués dans les échanges et les fiches | §2.5 | Les deux |
| **Vérification d'identité et données** | Ce qui est vérifié, ce qui est conservé (constat, pas de copie), combien de temps, pour quoi | §2.3, loi 2024/017 | Marchand |
| **Prête-nom et exactitude** | Le titulaire de la vérification répond de la boutique ; obligation de mise à jour ; fausse déclaration = résiliation et plainte | §1.7 | Marchand |
| **Conservation des preuves** | Commandes, messages, codes de remise, décisions et journaux conservés pour la durée légale ; ils font foi entre les parties | §2.6 | Les deux |
| **Litiges** | Délai d'ouverture, pièces attendues, instruction sous 72 h, décision motivée sur le sort du séquestre, sans préjudice de l'accès au juge | §6.1, §4.1 | Les deux |
| **Coopération avec les autorités** | Réponse aux réquisitions et saisies ; transmission aux autorités compétentes ; sans information préalable lorsque la loi l'interdit | §4.3, §6.5 | Les deux |
| **Sommes non réclamées** | Sort des sommes dues à une boutique injoignable ou disparue | §1.3 | Marchand |
| **Réversibilité** | Rappel du principe du docs/08 §8, y compris en cas de résiliation pour fraude — sous réserve des gels ordonnés | docs/08 | Marchand |

---

## 6. Les procédures humaines

Ce que le code ne fait pas. Chaque procédure laisse une trace au journal (§2.6).

### 6.1 — Instruire un litige en 72 heures

| Moment | Qui | Quoi |
|---|---|---|
| H0 | Le code | L'acheteur ouvre le litige ; la part du séquestre est **gelée** ; accusé de réception aux deux parties |
| H0 → H24 | Instructeur | Réunir les pièces : preuve de remise (code, géolocalisation, photo du livreur), photos de l'acheteur, fiche produit **telle qu'elle était au moment de l'achat**, échanges ; demander sa version au marchand |
| H24 → H48 | Instructeur | Appliquer la grille ci-dessous ; appeler les parties si les pièces se contredisent |
| H48 → H72 | Instructeur (et second si §2.3) | Décision écrite et motivée : faveur de l'acheteur, du marchand, ou partage ; notification ; exécution par le code |
| Au-delà | Responsable | Prévenir les deux parties du retard et de la nouvelle échéance ; le retard est un indicateur (M8) |

**Grille de preuve, par motif :**

- **Non reçue** — Code de remise saisi : présomption de livraison ; l'acheteur doit expliquer
  (code donné avant la remise ? appel du livreur ?). Pas de code : la preuve de la remise incombe
  au marchand et au livreur.
- **Non conforme** — Comparer à la fiche produit figée au moment de l'achat ; retour de l'article
  avant remboursement, sauf article dangereux ou illicite.
- **Incomplète** — Bon de préparation et poids déclaré au transporteur contre photos.

**Recours :** une seule révision interne, par l'autre administrateur ; ensuite, le juge. Une
décision en faveur de l'acheteur, totale ou partielle, compte comme **litige perdu** dans le palier.

### 6.2 — Traiter un signal

1. **Trier sous 24 h** selon la colonne « réaction » du §2.5 : les signaux « revue humaine
   prioritaire » d'abord.
2. **Regarder avant d'agir** : historique de la boutique, journal, liens avec d'autres boutiques
   (empreinte de pièce, numéro payeur, appareil).
3. **Choisir une issue, et l'écrire** : *classé* (faux positif, avec la raison — c'est ce qui
   améliore M7) ; *surveillé* (échéance de revue) ; *mesure conservatoire* (§6.3) ; *contact du
   marchand* (seulement si aucun soupçon de blanchiment) ; *escalade* (plainte §6.4, ou
   déclaration).
4. **Soupçon de blanchiment** : ne pas contacter le marchand sur ce motif. Rédiger un exposé
   factuel (flux, dates, numéros) et le transmettre selon la réponse à J13/J23 — à l'ANIF si nous
   sommes assujettis, au partenaire sinon. Le gel éventuel porte le message neutre du §4.3.

### 6.3 — Le gel conservatoire

- **Portée minimale** : d'abord les versements de la boutique ; la vitrine n'est suspendue que si
  la poursuite des ventes expose des acheteurs (fausse boutique probable).
- **Gel à un, maintien à deux** : un administrateur peut geler seul, en urgence ; un second doit
  confirmer sous 24 h, sinon le gel se lève de lui-même. Lever un gel exige toujours deux personnes
  (§2.3).
- **Durée bornée** : 7 jours, renouvelable une fois par décision motivée ; au-delà, il faut une
  décision de fond (résiliation, plainte, restitution) ou une mesure d'une autorité.
- **Message neutre** au marchand, identique quel que soit le motif.
- Les sommes gelées restent chez le partenaire ; rien n'est « confisqué ». Si la fraude est
  établie, elles servent d'abord à rembourser les acheteurs lésés.

### 6.4 — Déposer plainte

**Quand :** fraude établie et préjudice pour la plateforme ; ou pour appuyer des acheteurs
victimes, qui peuvent porter plainte eux-mêmes.

**Le dossier :** chronologie extraite du journal ; transactions et références du partenaire ;
constat de vérification (nom, numéro de pièce) ; numéros Mobile Money et comptes de versement
utilisés ; captures des fiches et des échanges ; liste des victimes et montants.

**Où :** commissariat ou brigade de gendarmerie du lieu des faits, ou plainte écrite au procureur
de la République ; plainte avec constitution de partie civile devant le juge d'instruction si le
parquet n'agit pas **[À VÉRIFIER : juridictions et unités spécialisées en cybercriminalité]**.

**Qui :** le représentant légal de HyperMarché, ou une personne munie d'un pouvoir. Pour un
acheteur victime, la plateforme fournit une **attestation** des faits et des montants.

### 6.5 — Répondre à une réquisition, à une saisie, à l'ANIF

1. **Authentifier** : rappeler le service par un numéro trouvé indépendamment, jamais celui du
   courrier. Une fausse réquisition est un moyen classique d'obtenir des données.
2. **Vérifier la portée** : qui requiert, sur quel fondement, quelles données, quelle période.
   Répondre à ce qui est demandé, pas davantage.
3. **Tracer** : motif « réquisition » au journal, copie de la demande et de la réponse.
4. **Ne pas informer** la personne visée lorsque la demande l'interdit.
5. **Saisie-attribution** (huissier) : bloquer immédiatement les sommes dues à la boutique et
   déclarer l'étendue de nos obligations dans le délai légal **[À VÉRIFIER]** ; prévenir le
   partenaire qui détient les fonds.
6. **Droit de communication de l'ANIF** : même procédure, même confidentialité.

Une seule personne désignée répond ; l'autre relit avant envoi.

### 6.6 — La séparation des tâches quand l'équipe compte deux personnes

Au démarrage, l'administration du marché, c'est deux personnes, A et B — dont l'une est peut-être
aussi l'exploitant-commerçant (ADR-012, §5).

- **Personne ne valide son propre geste.** Ce que A déclare ou saisit, B le vérifie, et
  inversement. Le code l'impose là où il le peut (`verifie_par` ≠ `declare_par`).
- **L'exploitant-commerçant ne touche jamais aux dossiers de ses propres boutiques** : compte de
  versement, litiges, signaux passent par l'autre.
- **Revue croisée hebdomadaire, 30 minutes** : chacun relit dans le journal ce que l'autre a fait
  — changements de compte de versement, libérations forcées, litiges tranchés, signaux classés sans
  suite, gels levés.
- **Absence de l'un** : les gestes à quatre yeux **attendent**. Un seul recours d'urgence, par le
  superadministrateur, marqué « urgence » et revu par l'absent à son retour, sous 7 jours.
- **Troisième regard mensuel** : un tiers de confiance sans droit d'agir (le cabinet comptable
  partenaire, docs/16) reçoit la synthèse mensuelle — volumes gelés, litiges, pertes (M6).
- **Dès la troisième recrue**, la vérification et la décision de versement passent à deux
  personnes qui ne sont pas les fondateurs.

### 6.7 — Ouvrir un nouveau pays

`apps/marketplace/cemac.py` dit ce qui existe dans chaque pays ; aucune ligne n'y est tenue pour
vraie avant cette procédure.

1. Faire valider par un avocat local chaque donnée de la ligne du pays : indicatif et **longueur
   des numéros**, nom et **format** de l'identifiant fiscal, opérateurs Mobile Money actifs,
   pièces d'identité admises, loi de protection des données et autorité compétente, CRF.
2. Obtenir du partenaire de paiement la couverture du pays (opérateurs, compte de cantonnement,
   KYC exigé) — sans cela, pas de prépaiement dans ce pays.
3. Répondre pour ce pays aux questions du §4.6.
4. Corriger `cemac.py` (données seulement), puis passer `ouvert=True` dans un commit qui cite
   l'avis obtenu.
5. Adapter les conditions générales et, pour la Guinée équatoriale, les écrans en espagnol.

---

## 7. Questions ouvertes pour les chantiers

| # | Question | Chantier | Proposition |
|---|---|---|---|
| Q1 | ~~`Sequestre` un par commande~~ — **réglé** : une part par sous-commande | Séquestre | — |
| Q2 | Confirmation implicite à 7 jours de l'expédition : l'acheteur inattentif perd sa protection | Séquestre | Relancer l'acheteur à J+3 et J+6 ; clause CG (J15) |
| Q3 | Délai de 2 jours au palier 3 contre « couvre la médiation de 72 h » | Séquestre | Corriger la phrase, ou passer à 3 jours (§3.1) |
| Q4 | Carence de 48 h calendaires ou ouvrées | Vérification | Calendaires, fin reportée au prochain jour ouvré à 8 h |
| Q5 | Acheteurs distincts dans le décompte des paliers | Signaux / paliers | §3.2 |
| Q6 | `PortefeuilleMarchand.numero_momo` concurrent de `CompteVersement` | Séquestre | Ne jamais l'utiliser pour verser ; à terme, le retirer |
| Q7 | Camtel absent du référentiel des opérateurs | Vérification | Ajouter le code et la migration quand le partenaire le couvre |
| Q8 | Numéro de pièce en clair en base (masqué à l'affichage) | Vérification | Chiffrer au repos ; comparer par empreinte à clé (HMAC) (§2.3) |
| Q9 | Aucune passerelle SMS : comment prévenir le gérant d'un changement de compte ? | Vérification | Bandeau + courriel + appel de l'administration ; SMS dès que possible (§2.4) |
| Q10 | Pic d'encours d'une boutique **établie** (escroquerie longue) non couvert | Signaux | Étendre le détecteur de pic au-delà des boutiques jeunes (§2.5) |

Les points juridiques sont au registre du [document 08](08-conformite-juridique-et-fiscale.md),
§9 : J3, J7 et J12 à J23.
