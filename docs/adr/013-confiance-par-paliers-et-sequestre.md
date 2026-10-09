# ADR-013 — La confiance se gagne par paliers, l'argent attend la livraison confirmée, et aucun contrôle ne suffit seul

**Statut :** Actée — socle posé, chantiers en cours · **Détail :** `apps/marketplace/confiance.py` (ce que chaque palier permet) ; `apps/marketplace/models.py` (`Boutique.palier_confiance`, `CompteVersement`) ; `apps/orders/models.py` (`SousCommande.livraison_confirmee_le`, `mode_paiement`, `Litige`) ; `apps/payments/models.py` (`Sequestre`, `Versement`) ; `apps/accounts/models.py` (`DossierKyc`) ; `apps/confiance/` (`paliers.py`, `verification.py`, `signaux.py`) ; [docs/23](../23-confiance-et-lutte-contre-la-fraude.md)

---

## Contexte

Une place de marché qui encaisse à l'avance l'argent des acheteurs devient la cible d'un geste
simple : ouvrir une boutique, encaisser des commandes prépayées, disparaître avant les livraisons.
Au Cameroun, ce geste a un public tout prêt — l'acheteuse urbaine paie à la livraison **par
méfiance** (docs/02, §4) — et le faire échouer est la condition de la thèse économique du projet :
convertir le paiement à la livraison en prépaiement sous séquestre.

Trois faits de terrain ont fixé la forme de la réponse.

**Un contrôle à l'entrée ne distingue pas le fraudeur.** Une CNI se prête, une copie s'achète sur
WhatsApp, un RCCM de société en sommeil se loue. Et une boutique neuve honnête ressemble trait pour
trait à une fausse : pas d'historique, pas d'avis, un gérant jeune. Un filtre d'entrée assez strict
pour arrêter l'une refuse l'autre.

**L'argent part par le compte de versement.** Changer le numéro Mobile Money de versement la
veille d'un gros versement suffit à tout emporter — et le geste est à la portée d'un employé du
commerçant, d'un agent terrain qui « aide » à l'inscription, ou d'un attaquant qui a fait
dupliquer la SIM du gérant. Si nos contrôles ont cédé, la créance du marchand n'est pas éteinte :
la plateforme paie deux fois.

**Les signaux sont bruyants.** Un téléphone pour toute une famille, un seul appareil pour toute la
boutique, des milliers d'abonnés derrière la même adresse IP d'opérateur : ce qui trahit un
fraudeur ailleurs est banal ici.

S'y ajoute une contrainte réglementaire : recevoir et garder l'argent d'autrui relève, dans la
CEMAC, d'activités réservées à des établissements agréés (docs/08, §5 ; docs/23, §4.2). La
plateforme n'en est pas un et ne cherche pas à le devenir.

## Décision

**La confiance se gagne par paliers, l'argent reste en séquestre jusqu'à la livraison confirmée
par l'acheteur, et aucun contrôle unique n'est tenu pour suffisant.**

Cinq points, indissociables.

### 1. Le séquestre ne cède qu'à l'acheteur

Le séquestre est tenu **par part de sous-commande** : un panier traverse les boutiques, et chacune
a son palier, son délai, ses litiges. Une part n'est libérée qu'après `livraison_confirmee_le` — le
code de remise saisi à la livraison, le geste de l'acheteur, ou la confirmation implicite sept
jours après l'expédition sans réclamation —, puis le délai de libération du palier, et seulement si
aucun litige n'est ouvert. `livree_le`, la livraison **déclarée** par le marchand, ne
libère jamais rien : c'est précisément ce que déclarerait une fausse boutique.

Le remboursement retourne **toujours** au numéro qui a payé. Cette règle, à elle seule, ferme le
blanchiment par remboursement et le détournement d'un remboursement par un employé.

Le séquestre est tenu **par un partenaire agréé**, sur un compte de cantonnement ; la plateforme
donne des instructions, elle ne détient pas les fonds.

### 2. Ce qu'on confie se gagne : un plafond, pas un refus

Quatre paliers (`confiance.py`). Chacun fixe un **plafond** d'encours en séquestre et un **délai**
de libération ; chacun s'atteint par des livraisons confirmées, de l'ancienneté et un taux de
litiges perdus bas. Au-delà du plafond, la vitrine ne refuse pas la vente : elle propose le
paiement à la livraison.

Le palier est **calculé**, jamais saisi : `apps/confiance/paliers.py` l'écrit chaque nuit dans
`Boutique.palier_confiance`, et les paiements le lisent sans importer le calcul. On monte d'un
palier à la fois, après la fenêtre de litige ; on redescend tout de suite. Un niveau inconnu
retombe au palier 0.

### 3. L'identité est vérifiée, l'argent passe par deux personnes

La vérification d'identité produit une **attestation** (`DossierKyc`) — ce que l'administrateur
a lu sur l'original vu en présentiel ou en visio : type, numéro, pays, expiration, nom, mode de
vérification, empreinte du document s'il en a reçu un, qui a déclaré et qui a validé — **pas une
copie** de la pièce. Une copie ne se garde que si un stockage persistant est désigné
explicitement.

Tout ce qui ouvre une boutique ou oriente de l'argent passe par **deux personnes distinctes** : la
validation d'une pièce (contrainte en base `kyc_quatre_yeux`), la vérification d'un compte de
versement, la levée d'un gel, une libération forcée, un litige au-dessus d'un seuil ou visant une
boutique de l'exploitant. Un compte de versement n'est utilisable qu'après une **carence de 48 h** ;
il n'y en a qu'un vérifié à la fois ; on le retire, on ne le supprime pas. La destination d'un
`Versement` est figée au moment où il est demandé.

### 4. L'automate réduit, l'humain retire

Les signaux (`apps/confiance/`) sont des **indices présentés dans la console**, pas des décisions.
L'automate a le droit de faire tout ce qui **réduit ce qu'on confie** — ne pas compter une livraison
pour le palier, prolonger un délai, masquer un numéro, retirer le paiement à la livraison à un
acheteur, redescendre un palier. Il n'a pas le droit de **retirer ce qu'on doit** : geler un
versement, suspendre une boutique, trancher un litige sont des gestes humains, nommés, motivés,
journalisés.

### 5. Chaque décision laisse une trace qu'on ne peut pas effacer

Vérifications, comptes de versement, gels, libérations forcées, litiges, signaux traités,
réponses aux réquisitions : au journal en ajout seul, protégé par le déclencheur de l'ADR-003 et de
l'ADR-012.

## Conséquences

**Ce que cela coûte au marchand honnête.** Une boutique neuve attend sept jours après chaque
livraison confirmée et voit ses prépaiements plafonnés à 150 000 F d'encours ; avec les hypothèses
du business plan, le plafond mord sur les nouvelles boutiques les plus actives (docs/23, §3.3). Un
changement de numéro de versement coûte 48 h sans versement. C'est le prix assumé ; il est mesuré
(indicateurs M1, M2, M10 du docs/23) et les seuils sont faits pour être recalibrés.

**Ce que cela coûte à l'équipe.** Des gestes à deux quand l'équipe compte deux personnes : ce qui
exige quatre yeux **attend** l'absent, sauf recours d'urgence marqué et revu (docs/23, §6.6). Une
console de signaux à trier chaque jour, et des litiges à instruire en 72 h.

**Ce que cela impose au code.**

* La libération, le remboursement et le litige se font **par part de sous-commande** ; le mode de
  paiement aussi, pour que le plafond d'une boutique ne refuse pas le prépaiement chez sa voisine.
* Les versements ne lisent que `CompteVersement` — jamais `PortefeuilleMarchand.numero_momo`.
* Le calcul du palier doit exiger des livraisons à des **acheteurs distincts** et sans lien avec la
  boutique — le nombre est déjà mesuré (`MesureConfiance.acheteurs_distincts`) ; sans cette
  condition, le palier s'achète par auto-commandes.
* Le message affiché à une boutique gelée est neutre et identique quel que soit le motif, pour ne
  pas contrevenir à l'interdiction d'informer en matière de blanchiment (docs/23, §4.3).

**Ce que cela ne résout pas.** Le paiement hors plateforme, par définition : l'argent ne passe pas
par nous. Il se traite par le masquage des coordonnées, le message permanent à l'acheteur et les
conditions générales — pas par le séquestre. Et l'escroquerie longue au palier sans plafond, qui
relève d'un signal de pic d'encours et d'un regard humain.

**Ce qui reste à valider.** La qualification du séquestre et du rôle d'instruction de la
plateforme (J3, J12), la qualité d'assujetti LBC/FT (J13), la non-conservation des copies face aux
exigences du partenaire (J14), la validité des clauses de retenue et de confirmation implicite
(J15) — docs/08, §9.

## Vérification

À écrire par les chantiers, une ligne par règle de cette fiche :

* un `Sequestre` ne se libère pas tant que `livraison_confirmee_le` est vide, même si `livree_le`
  est renseigné ; ni tant qu'un `Litige` est ouvert ;
* un remboursement ne peut viser qu'un numéro égal au numéro payeur ;
* `palier()` d'un niveau inconnu renvoie le palier 0 (`confiance.py`) ;
* un `CompteVersement` ne peut être vérifié par celui qui l'a déclaré, n'est pas utilisable avant
  `utilisable_le`, et deux comptes vérifiés pour une même boutique sont refusés par la base (déjà
  tenu par la contrainte `un_compte_de_versement_verifie_par_boutique`) ; une pièce ne peut être
  validée par celui qui l'a attestée (contrainte `kyc_quatre_yeux`) ;
* aucune boutique ne passe à `active` sans les contrôles de `verification.exiger_activable` ;
* pour une part de séquestre tranchée, `montant_libere + montant_rembourse == montant` ;
* aucun code de `apps/confiance/` ne modifie `Boutique.etat` : un test qui lit le module, sur le
  modèle de celui de l'ADR-012.

## Ce qui a été écarté

**Refuser les nouveaux marchands tant qu'ils n'ont pas fait leurs preuves.** Refuser, c'est
empêcher de faire ses preuves : il n'y a pas d'historique sans ventes. Et le refus ne choisit pas
entre le fraudeur et l'honnête — il les écarte tous les deux, alors que notre cible est faite de
commerces jeunes. Le plafond obtient ce que voulait le refus — borner ce qu'un inconnu peut
emporter — sans empêcher de vendre : au-delà, la vente continue au paiement à la livraison.

**Conserver les copies des pièces d'identité.** La finalité — identifier notre cocontractant,
détecter une pièce qui sert deux fois, pouvoir agir en justice — est remplie par le nom, le numéro
chiffré et une empreinte ; l'image n'ajoute qu'un visage, une signature et une date de naissance,
ce que la minimisation de la loi 2024/017 interdit de garder sans besoin. Surtout, une base de
scans de CNI est la matière première de l'usurpation d'identité : la perdre ferait de nous un
fournisseur de la fraude qu'on combat. La preuve de l'identité existe ailleurs — l'opérateur
Mobile Money a identifié le titulaire du compte de versement. Et la production tourne sans disque
durable (ADR-008) : une copie écrite par défaut s'évaporerait au prochain redémarrage, preuve qu'on
croirait avoir. Si le partenaire de paiement exige des copies, elles vont chez lui ou dans un
stockage désigné explicitement (J14).

**Suspendre automatiquement une boutique sur signal.** Les faux positifs sont structurels ici ; une
suspension est publique, coûte une vente et une réputation, et le marchand honnête qui la subit le
raconte. Elle renseigne aussi le fraudeur sur ce que nous détectons et, en matière de blanchiment,
peut valoir divulgation interdite. Attendre un humain est sans danger parce que le plafond et le
séquestre tiennent pendant ce temps : c'est ce qui rend la règle « l'automate réduit, l'humain
retire » praticable.

**Tenir le séquestre sur un compte propre de la plateforme.** Plus simple à ouvrir, plus souple à
opérer — et c'est tout le problème. Recevoir et garder l'argent du public pour le compte de tiers
relève d'activités réservées dans la CEMAC ; les fonds des acheteurs seraient mêlés au patrimoine
de la plateforme et exposés à ses créanciers ; et le partenaire de paiement, qui porte l'agrément,
ne l'accepterait pas. Un compte de cantonnement chez un établissement agréé sépare les fonds par
construction, et laisse à la plateforme ce qu'elle sait faire : décider **quand** l'argent peut
partir.
