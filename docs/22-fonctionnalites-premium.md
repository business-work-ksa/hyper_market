# 22 — Fonctionnalités premium

> **Ce que ce document couvre :** ce qu'on peut vendre au-delà du loyer, pourquoi, à quelle offre de
> la grille du [document 03](03-business-plan.md) §1.1, et dans quel ordre le construire. Le
> périmètre déjà livré est le [document 18](18-produit-palier-1.md) ; l'affiliation est le
> [document 06](06-affiliation-marketing-revendeurs.md).

---

## 1. La règle qui trie

Une fonctionnalité premium n'est pas une fonctionnalité en plus. C'est une fonctionnalité **qu'un
commerçant accepte de payer parce qu'elle lui fait gagner ou cesser de perdre de l'argent, et qu'il
peut le constater**. Tout le reste est du remplissage qui alourdit le produit et la maintenance.

D'où trois questions, dans cet ordre, pour chaque candidat :

1. **Quel franc CFA ?** Gagné, ou arrêté de fuir. Nommé, pas supposé.
2. **Le commerçant le voit-il ?** Une fonctionnalité qui travaille en silence ne se renouvelle pas.
3. **Qu'est-ce qui existe déjà et qu'elle réutilise ?** Une brique qui s'appuie sur le CMP, le
   journal comptable ou le numéro de téléphone coûte le tiers d'une brique nouvelle.

Ce document écarte volontairement ce qui échoue à la première question, même quand ça se vend bien
ailleurs — voir §6.

---

## 2. Ce qui manque et qui coûte le plus cher au commerçant

### 2.1 — Le cahier de crédit client

**C'est la proposition la plus importante de ce document.**

Dans le commerce de quartier camerounais, le cahier est universel : on note ce que le client habituel
emporte et paiera « à la fin du mois ». Il est en papier, il se perd, il se conteste, et **c'est là
que le commerçant perd réellement de l'argent** — pas sur sa marge, sur ses créances.

Ce qu'il faut : un solde par client, un plafond, un historique opposable, et un relevé qu'on peut
montrer. Rien de plus.

| | |
|---|---|
| Le franc | Les créances non recouvrées. Un commerçant qui récupère un mois de cahier perdu paie l'abonnement pour l'année. |
| Se voit | Oui, immédiatement : « voilà qui vous doit quoi ». |
| Réutilise | Le client existe déjà, le compte 411 du plan SYSCOHADA existe déjà (docs/07, §3.2), la créance est déjà distinguée de la trésorerie. |
| Offre | **Boutique** (45 000 F). C'est ce qui justifie le saut depuis Étal. |

**Le piège à ne pas franchir :** un cahier est une **facilité de paiement**, pas un prêt. Dès qu'on
facture un intérêt, un frais de retard ou qu'on prête de l'argent, on entre dans une activité
réglementée (agrément COBAC, microfinance). Le cahier reste gratuit pour le client final, et le
document 08 doit le dire avant la première ligne de code.

### 2.2 — Le rapport hebdomadaire au patron, par WhatsApp

Le propriétaire d'une boutique à Douala n'ouvre pas un tableau de bord. Il ouvre WhatsApp, quarante
fois par jour.

Un message, le lundi matin : chiffre d'affaires de la semaine, les cinq articles qui partent, les
ruptures, le total du cahier en cours, et la comparaison avec la semaine précédente. Six lignes.

| | |
|---|---|
| Le franc | Indirect mais décisif : c'est **la fonctionnalité de rétention**. Un outil qu'on n'ouvre pas se résilie ; un outil qui vient à vous chaque lundi se garde. |
| Se voit | C'est littéralement sa seule forme d'existence. |
| Réutilise | Les agrégats du tableau de bord sont déjà calculés, sans N+1 (mesuré, docs/20 §9). |
| Offre | **Toutes**, y compris Étal. C'est l'argument de renouvellement, il ne faut pas le réserver. |

**Coût réel à nommer :** WhatsApp Business facture à la conversation et impose des gabarits validés
par Meta. Un message hebdomadaire par boutique est négligeable ; « notifications illimitées » ne
l'est pas. Ce qui suit (§2.3) doit donc être vendu à l'usage, jamais en illimité.

**État (livré, première marche).** Le rapport existe dans le back-office, *Tableau de bord →
Rapport de la semaine* (`/rapport/semaine/`, droit `ventes.voir`) : le message tel qu'il partira,
et un bouton qui ouvre WhatsApp avec ce message déjà écrit (lien `wa.me`, aucune clé, aucun coût).
Le patron choisit à qui l'envoyer — à lui-même, à son associé. Le calcul est dans
`apps/backoffice/rapport_hebdo.py` : semaine du lundi au dimanche, **jamais la marge**, le cahier
seulement pour qui a `cahier.voir`, les ruptures seulement pour qui a `stock.voir`. Reste à faire :
l'envoi automatique du lundi par l'API WhatsApp Business, une fois un gabarit validé par Meta — le
texte est déjà celui que ce gabarit portera.

### 2.2 bis — Les commandes, envoyées sur WhatsApp à ceux qui les traitent

Le vendeur sert au comptoir ; il n'a pas le back-office ouvert. Une commande qui attend trois heures
son acceptation est une commande que l'acheteur annule. L'avis va donc sur le téléphone qu'il
regarde déjà (`apps/orders/avis.py`).

* **Qui** : les personnes de la boutique dont le rôle ouvre `commandes.traiter` (gérant, vendeur…),
  que le gérant n'a pas retirées — colonne « Commandes sur WhatsApp » de l'écran *Équipe*. Ni le
  caissier, ni la boutique voisine.
* **Quand** : une part payée à la livraison dès la commande ; une part prépayée seulement quand
  l'argent est constaté. Toujours **après** l'enregistrement de la transaction.
* **Quoi** : numéro, articles, total, mode de paiement, lien vers la commande. **Jamais le nom, le
  téléphone ni l'adresse de l'acheteur** : un message WhatsApp se transfère, ces données restent
  derrière la connexion du back-office (minimisation, loi n° 2024/017 — [À VÉRIFIER] par un juriste).
* **Comment** : sans clés, rien ne part tout seul, et la fiche de chaque commande propose un bouton
  par responsable qui ouvre WhatsApp, message déjà écrit (`wa.me`). Avec les clés de l'API WhatsApp
  Business, l'avis part seul ; un avis par personne et par part (contrainte d'unicité), et un avis
  qui échoue est noté sur la fiche sans jamais faire échouer la commande.

**Mettre en service l'envoi automatique** (à faire par l'exploitant, jamais dans le dépôt) :

1. Compte Meta Business vérifié, application avec le produit WhatsApp, numéro dédié.
2. Gabarit de catégorie *Utilitaire*, langue *français*, par exemple `nouvelle_commande` :
   « Nouvelle commande {{1}} pour {{2}} : {{3}}. Total {{4}} FCFA, {{5}}. À traiter ici : {{6}} »
   — six variables, dans cet ordre : numéro, boutique, articles, total, paiement, lien.
3. Dans Vercel, en variables **Sensitive** : `WHATSAPP_JETON` (jeton d'utilisateur système, pas le
   jeton temporaire de 24 h), `WHATSAPP_NUMERO_ID`, `WHATSAPP_GABARIT_COMMANDE`. Facultatives :
   `WHATSAPP_VERSION` (défaut `v21.0`), `WHATSAPP_LANGUE` (défaut `fr`). `URL_PUBLIQUE` doit être
   posée pour que le lien de l'avis soit absolu.

Coût : facturé par Meta à la conversation utilitaire — de l'ordre d'un avis par commande et par
responsable. Le gérant qui trouve la note trop haute retire des personnes de la liste.

### 2.3 — La relance du client dormant et du panier abandonné

Deux mécaniques, un seul canal.

Le panier abandonné est du revenu déjà à moitié gagné : le client a choisi, il n'a pas conclu. Le
client dormant — quarante-cinq jours sans achat alors qu'il venait chaque semaine — est un client
qu'on a **déjà** payé pour acquérir et qui est en train de partir chez le voisin.

| | |
|---|---|
| Le franc | Direct et mesurable : on sait combien de paniers relancés se concluent. C'est le seul endroit où l'on peut afficher un retour sur investissement honnête. |
| Se voit | Oui, à condition d'afficher le taux de conversion des relances, pas le nombre de messages envoyés. |
| Réutilise | Le panier existe, le téléphone est déjà l'identifiant du compte. |
| Offre | **Option à l'usage**, au message, au-dessus de Boutique. Pas en illimité — voir le coût ci-dessus. |

**La règle de décence, à coder et non à recommander :** un plafond dur de relances par client et par
mois, et un désabonnement en un mot. Un commerce de quartier vit de sa réputation dans le quartier ;
un outil qui le fait passer pour un spammeur lui coûte plus qu'il ne lui rapporte.

---

## 3. Ce qui fait vendre plus, à trafic constant

### 3.1 — Un moteur de promotions qui montre la marge avant d'activer

Aujourd'hui les remises se posent à la ligne, à la main. Ce qui manque n'est pas la remise, c'est la
**mécanique** : prix barré, lot (trois pour deux), pack, prix dégressif par quantité, heure creuse.

Le prix dégressif par quantité n'est pas un gadget ici : c'est ainsi que fonctionne le **demi-gros**,
qui est une part majeure du commerce camerounais.

**Ce qui en fait un produit premium et non une case à cocher :** le CMP est déjà calculé (ADR-005),
donc on peut afficher **la marge réelle de la promotion avant de l'activer**, et refuser en le disant
celle qui vend à perte. Un logiciel de caisse ordinaire laisse le commerçant découvrir après coup
qu'il a bradé. Celui-ci le lui dit avant.

| | |
|---|---|
| Le franc | La marge protégée sur chaque promotion mal calibrée qui n'a pas eu lieu. |
| Offre | **Boutique**, la visibilité de marge étant réservée à qui a le droit `MARGE_VOIR`. |

### 3.2 — Tarifs par client et par canal

« Tarifs B2B » figure déjà dans l'offre Grande surface. Ce qu'il faut derrière : des listes de prix
par segment, des paliers de quantité, et des prix négociés par client — parce qu'un grossiste de
Ndokoti n'a pas un prix, il en a un par client important.

| | |
|---|---|
| Le franc | Le chiffre d'affaires B2B qu'on ne peut pas traiter aujourd'hui sans sortir du logiciel. |
| Offre | **Grande surface** (120 000 F). C'est ce qui rend cette offre réelle plutôt qu'affichée. |

### 3.3 — La fidélité adossée au téléphone, sans carte

Pas de plastique : le numéro de téléphone **est déjà** l'identifiant du compte.

**Et un conseil de commerçant qui va contre l'intuition :** sur des marges fines, préférez la
**fréquence** au pourcentage. « Le dixième sac de riz offert » change le comportement bien davantage
que « 2 % de cashback », à coût identique — parce que le client compte ses achats, alors qu'il ne
calcule jamais 2 %.

Si cashback il y a, il se restitue en **avoir dans la boutique**, jamais en espèces : rendre de
l'argent est une activité de paiement, réglementée.

| | |
|---|---|
| Le franc | La fréquence d'achat, donc le panier annuel par client. |
| Offre | **Boutique**, avec le cahier — les deux parlent du même client fidèle. |

---

## 4. Ce que la plateforme se vend à elle-même

### 4.1 — Rendre comptable l'emplacement premium déjà vendu

`EmplacementPremium` existe : tête de gondole, bandeau de rayon, page d'accueil, avec tarif et
occupant. **Mais rien ne compte les impressions ni les clics.** Le commerçant paie 75 000 F la semaine
et ne voit jamais ce qu'il a acheté.

C'est le chantier premium le plus rentable de ce document, et le moins coûteux : la réservation est
déjà modélisée, il manque la mesure. Sans elle, l'emplacement ne se renouvelle qu'une fois — la
deuxième semaine, on demande « et ça a donné quoi ? », et il n'y a pas de réponse.

| | |
|---|---|
| Le franc | Direct pour la plateforme, et à la marge la plus élevée de tout le modèle. |
| Réutilise | Le modèle existe. Il faut un compteur et un écran. |

### 4.2 — Les avis clients adossés à un achat prouvé

Il n'y en a aucun aujourd'hui. Or l'étude de marché (docs/02) place la **défiance** comme premier
frein à l'achat en ligne dans la région : on ne paie pas d'avance quelqu'un qu'on ne connaît pas.

La condition qui fait toute la valeur : **seul un client dont la commande est livrée peut noter.** Un
système d'avis ouvert produit du faux avis, qui détruit la confiance qu'il devait créer — c'est pire
que pas d'avis du tout.

| | |
|---|---|
| Le franc | Le taux de conversion de la vitrine, pour toutes les boutiques à la fois. |
| Offre | **Bien commun de la plateforme**, gratuit. Facturer la confiance serait se tirer dans le pied. |

### 4.3 — La recherche par le mot du client

L'ADR-011 a déjà posé que l'équivalence entre articles se **déduit des désignations partagées**. Il
reste à en faire une recherche : personne ne cherche « cube de bouillon déshydraté », on cherche
« Maggi ». Personne ne cherche « pagne imprimé cire », on cherche « wax ».

C'est une barrière à l'entrée que les catalogues génériques ne franchiront pas, parce qu'elle demande
la connaissance du marché, pas de la technique.

---

## 5. Ce qui décide si tout le reste sert à quelque chose

### 5.1 — La caisse qui survit à la coupure

**Ce n'est pas une fonctionnalité premium, c'est la condition de toutes les autres.**

Les coupures de courant et les pertes de réseau sont la normalité, pas l'incident. Une caisse qui
s'arrête quand le réseau tombe est abandonnée dans la semaine — et un logiciel abandonné ne vend
aucune option.

**Et c'est une vraie décision d'architecture, pas une ligne de plus.** L'ADR-007 pose qu'il n'y a pas
d'application monopage, du JavaScript par page et rien d'autre. Une caisse hors ligne demande un
*service worker* et une file d'écritures à rejouer : c'est exactement ce que l'ADR-007 refuse. Il faut
donc soit un ADR qui l'autorise **pour la seule caisse** et dise pourquoi, soit renoncer. Ce qu'il ne
faut pas, c'est le faire sans le décider.

Deux questions à trancher avant d'écrire une ligne : que fait-on d'une vente encaissée hors ligne sur
un stock qui a bougé entre-temps (le stock négatif est déjà autorisé, ADR-005 — c'est une chance
ici) ; et comment le journal comptable en ajout-seul accepte des écritures arrivées dans le désordre.

---

## 6. Ce que je refuse de proposer, et pourquoi

Un document de propositions qui ne dit pas ce qu'il écarte n'aide pas à décider.

| Écarté | Pourquoi |
|---|---|
| **Cartes de fidélité physiques** | Coût d'impression et de distribution, pour une information que le téléphone porte déjà. |
| **Recommandations « intelligentes »** | Elles demandent un volume de données qui n'existe pas encore. Avant quelques milliers de commandes, elles recommandent du bruit — et brûlent la crédibilité de la fonctionnalité pour le jour où elle marcherait. |
| **Flotte de livraison en propre** | Immobilisation de capital incompatible avec le palier 1 (docs/17). Le fulfilment est déjà tarifé en option à 1,5 % du GMV : c'est la bonne façon de le vendre sans le posséder. |
| **Crédit avec intérêt, avance de trésorerie** | Activité réglementée. Le cahier (§2.1) est une facilité de paiement ; prêter est un autre métier, avec un agrément. |
| **Multi-devises** | Le franc CFA suffit à la zone CEMAC au palier 1. Le multi-devises ajoute une classe entière de bugs d'arrondi pour un besoin qui n'existe pas encore. |
| **Places de marché tierces (Jumia, etc.)** | Tant que le catalogue n'est pas stabilisé, synchroniser vers l'extérieur propage les erreurs plus vite qu'on ne les corrige. |

---

## 7. Dans quel ordre

Classement par (impact × facilité), pas par envie.

| Rang | Chantier | Offre | Pourquoi ce rang |
|---|---|---|---|
| **1** | Cahier de crédit client (§2.1) | Boutique | Le seul qui touche à de l'argent déjà perdu. Réutilise le plan comptable existant. |
| **2** | Rapport hebdomadaire WhatsApp (§2.2) | Toutes | Coût de construction le plus faible du document, effet de rétention le plus fort. Les agrégats existent. |
| **3** | Mesure des emplacements premium (§4.1) | Plateforme | Le modèle existe déjà ; il manque un compteur. Marge la plus élevée du modèle économique. |
| **4** | Moteur de promotions avec marge visible (§3.1) | Boutique | Différenciant réel grâce au CMP, mais demande un vrai moteur de règles. |
| **5** | Avis adossés à l'achat (§4.2) | Gratuit | Lève le premier frein du marché, profite à toutes les boutiques. |
| **6** | Fidélité par téléphone (§3.3) | Boutique | À faire après le cahier : même client, mêmes écrans. |
| **7** | Tarifs par client et paliers (§3.2) | Grande surface | Rend réelle l'offre haute, mais peu de comptes concernés au départ. |
| **8** | Relance dormants et paniers (§2.3) | Option | Dépend du canal WhatsApp construit en 2. |
| **—** | Caisse hors ligne (§5.1) | Condition | Hors classement : ce n'est pas une option à vendre, c'est ce qui décide si on garde les clients. À trancher par un ADR, pas par une priorisation produit. |

**Les chiffres de ce document sont des ordres de grandeur commerciaux, pas des engagements.** Les
montants de la grille tarifaire viennent du document 03 ; toute mention fiscale ou de crédit doit
passer par le document 08 et être validée par un conseil juridique avant mise en production.
