# 17 — Démarrer sans capital

> **Ce document remplace le plan de financement du [business plan](03-business-plan.md) pour la
> phase de démarrage.** Ce n'est pas une version réduite du plan à 400 M FCFA : c'est une autre
> stratégie, avec un autre ordre de construction et d'autres jalons.

---

## 1. La vérité d'abord

Le plan du document 03 suppose une équipe de 14 personnes financée par un amorçage de 400 M FCFA.
**Sans capital, ce plan n'est pas exécutable, et aucun aménagement ne le rendra exécutable.** Le
prétendre coûterait 18 mois.

Trois choses restent vraies, et elles suffisent à démarrer :

1. **Le marché ne bouge pas.** Le diagnostic du [document 02](02-etude-de-marche.md) — case vide,
   Mobile Money mature, fiscalité 2026 protectrice — vaut pour une entreprise d'une personne
   comme pour une entreprise de cent.
2. **Le socle logiciel existe déjà.** L'isolation multi-tenant, le moteur de stock en CMP, la
   caisse et le noyau comptable sont écrits et testés. C'est plusieurs mois de développement
   spécialisé qui n'ont pas à être financés. **C'est votre apport en capital, et il est réel.**
3. **La brique unique identifiée par le conseil d'experts** — stock + caisse — se vend seule, sans
   marketplace, sans logistique, sans paiement en ligne. Elle est déjà construite.

La question à se poser n'est donc pas « combien me faut-il pour construire la plateforme ? » mais
**« combien me faut-il pour tenir jusqu'au premier client payant ? »**. La réponse est un ordre de
grandeur plus petite.

---

## 2. Les trois montants à ne pas confondre

| Question | Montant | Commentaire |
|---|---|---|
| Combien pour **exister légalement** ? | ~200 000 F la première année | Dont 100 000 F de capital social, qui reste votre argent |
| Combien pour **atteindre le premier client payant** ? | **~450 000 F sur 6 mois** | Le chiffre qui compte au démarrage |
| Combien pour **ne plus perdre d'argent** ? | 0 F de plus — **3 clients payants** | Le seuil réel : un nombre de clients, pas une somme |

> **La bonne unité de mesure n'est pas le franc, c'est le client.** Trois clients payants et le
> projet s'autofinance. Huit et vous vous payez un salaire. C'est ce chiffre-là qu'il faut avoir
> en tête, pas le montant d'une levée.

### 2.1 — Budget minimal, 6 mois, sans se payer

| Poste | Montant | Note |
|---|---:|---|
| Capital social SARLU | 100 000 F | Minimum légal — **reste votre argent**, il est à l'actif |
| Formalités CFCE, timbres, publication | ~100 000 F | **[À CONFIRMER auprès du CFCE]** — l'acte notarié est facultatif pour une SARL unipersonnelle ou de capital ≤ 1 M F |
| Nom de domaine `.cm` (1 an) | 15 000 F | |
| Hébergement (VPS 4 Go, 6 mois) | 90 000 F | Un seul serveur suffit largement jusqu'à 50 boutiques |
| Crédit SMS / OTP initial | 30 000 F | |
| Forfait data mobile (6 mois) | 90 000 F | |
| Transport terrain (6 mois) | 180 000 F | Le poste le plus utile du budget |
| Impressions : contrats, cartes, fiches produit | 40 000 F | |
| **Total** | **645 000 F** | dont 100 000 F récupérables |
| **Dépense réelle** | **~545 000 F** | ≈ 830 EUR |
| **Si la société est créée au palier 2** *(voir §4)* | **~450 000 F** | ≈ 690 EUR |

**Différé volontairement :** le dépôt de marque à l'OAPI (~250 000 à 400 000 F). Le
[document 08](08-conformite-juridique-et-fiscale.md) le recommandait au mois 1 ; sans capital, on
le repousse au premier revenu. **La contrepartie est une discipline stricte : aucune dépense de
marque, aucun logo coûteux, aucune campagne au nom du produit tant que le dépôt n'est pas fait.**
On ne risque que le nom, pas un investissement de marque.

### 2.2 — Charges mensuelles récurrentes, une fois lancé

| Poste | Montant/mois |
|---|---:|
| Hébergement | 15 000 F |
| Data et SMS | 20 000 F |
| Transport terrain | 30 000 F |
| Divers | 5 000 F |
| **Sous-total sans salaire** | **70 000 F** |
| Salaire fondateur minimal | 150 000 F |
| **Total avec salaire** | **220 000 F** |

**Point mort, à 30 000 F d'abonnement mensuel net :**

| Objectif | Clients payants nécessaires |
|---|---|
| Le projet ne coûte plus rien | **3** |
| Vous vous payez 150 000 F/mois | **8** |
| Vous vous payez 300 000 F/mois | **13** |

---

## 3. La stratégie : inverser complètement l'ordre

Le plan financé construit la plateforme, puis cherche des clients. **Sans capital, on fait
l'inverse : on trouve les clients, on les sert à la main, et on automatise ce qu'on fait déjà.**

### 3.1 — Le premier produit n'est pas la marketplace

C'est **la reprise de stock et la tenue de caisse**. Un service, pas un logiciel. Vous arrivez
chez le commerçant, vous comptez son stock avec lui, vous le saisissez, vous lui installez la
caisse sur son téléphone, vous formez son vendeur, vous revenez chaque semaine.

Trois raisons de commencer par là :

- **Ça se vend sans rien démontrer.** Un commerçant qui ne sait pas ce qu'il a en stock comprend
  la proposition en trente secondes. Une marketplace sans acheteurs ne se vend pas.
- **Ça ne touche pas à l'argent.** Pas de collecte, pas de séquestre, pas de reversement — donc
  **aucun compte de cantonnement, aucun agrégateur de paiement, aucun des points réglementaires
  J3 et J7** du document 08. C'est l'économie la plus importante du plan de démarrage : la
  complexité réglementaire coûte plus cher que le développement.
- **Ça vous apprend le produit.** Ce que vous faites péniblement à la main pendant trois mois vous
  dit exactement quoi automatiser. Aucune spécification ne remplace ça.

### 3.2 — Ce qui est coupé, et qui ne revient pas avant longtemps

| Coupé | Pourquoi |
|---|---|
| **La logistique** | C'est le poste qui brûle le cash le plus vite, et le risque O1 coté 20 au registre. Zéro livraison, zéro transporteur, zéro entrepôt. |
| **Le paiement en ligne et le séquestre** | Complexité réglementaire hors de portée, et inutile tant qu'on ne vend pas en ligne. |
| **La commission sur GMV** | On ne facture qu'un abonnement. Plus simple à vendre, plus prévisible, et ça évite d'avoir à manipuler l'argent d'autrui. |
| **La marketplace publique** | Elle n'a de valeur qu'avec du trafic, et le trafic coûte cher. |
| **Le module paie** | Conditionné au partenariat cabinet (arbitrage A6), qui n'a pas à être payé comptant — voir §5.3. |
| **Le retail media, le fulfilment, le financement de stock** | Lots 4 et 5. Sans objet. |

### 3.3 — Ce qui n'est jamais sacrifié

Quatre choses coûtent **zéro franc aujourd'hui** et sont irrattrapables plus tard. Les couper
serait la seule erreur vraiment irréversible de ce plan.

1. **L'isolation multi-tenant.** Déjà écrite, déjà testée. Une fuite entre boutiques dans un
   module comptable tue le produit commercialement, quelle que soit sa taille.
2. **L'immuabilité du journal comptable.** Déjà écrite. Un journal falsifiable ne se rattrape pas
   rétroactivement : les données passées sont définitivement sans valeur probante.
3. **La réversibilité des données du marchand.** Export intégral, gratuit, à tout moment. C'est
   votre meilleur argument de vente face à un commerçant méfiant, et ça ne coûte rien.
4. **La séparation stricte de votre argent et de celui des autres.** Tant que vous ne collectez
   pas, la question ne se pose pas. Le jour où elle se posera, ne pas improviser.

---

## 4. Les cinq paliers, chacun financé par le précédent

### Palier 0 — Valider, sans dépenser (semaines 1 à 6) · **0 F**

Le [document 15](15-plan-de-validation-terrain.md) chiffre l'étude terrain à 12 M FCFA parce qu'il
suppose une équipe. **Vous n'avez besoin d'aucune société ni d'aucun budget pour parler à
30 commerçants.** Vous avez besoin de vos jambes et de six semaines.

Gardez du document 15 : le guide d'entretien en 21 questions, la règle de ne jamais montrer le
produit avant la question 16, le classement forcé des 8 cartes, et surtout l'avertissement sur le
biais de complaisance. Supprimez : les enquêteurs, le panel de 400 acheteurs, le pilote
logistique, l'achat mystère. Réduisez le dédommagement à un geste symbolique ou à rien — vous
n'êtes pas un cabinet d'études, vous êtes un fondateur qui vient voir, et cela s'entend très bien.

**Sortie :** 30 entretiens faits vous-même, et **3 commerçants qui ont dit oui à un pilote payant**.
Pas « ça m'intéresse ». Oui, à un prix, à une date.

### Palier 1 — Le service à la main (mois 2 à 4) · **~250 000 F**

Trois boutiques. Vous faites tout vous-même : inventaire physique, saisie du stock, installation
de la caisse, formation, passage hebdomadaire.

**L'offre de démarrage :**

| Ligne | Prix | Rôle |
|---|---:|---|
| Installation et reprise de stock | **150 000 F**, une fois | Le service manuel est cher parce qu'il coûte votre temps. Ne le bradez pas. |
| Abonnement mensuel | **30 000 F/mois** | |
| Ou abonnement annuel prépayé | **288 000 F** (−20 %) | **Le meilleur financement qui existe** |
| Commission sur ventes | **0 %** | On ne touche pas à l'argent |

> **Un seul client en annuel prépayé rapporte 438 000 F immédiatement — soit la totalité du budget
> de démarrage.** C'est le point le plus important de ce document : votre premier financement,
> c'est votre premier client, et il vous finance en étant engagé, pas en vous diluant.

**Sortie :** 3 clients qui paient et qui utilisent la caisse chaque semaine. Si à la fin du mois 4
ils ne l'utilisent pas, le problème n'est pas l'argent — c'est le produit, et il faut revenir au
palier 0.

### Palier 2 — Formaliser et atteindre le point mort (mois 5 à 9) · **autofinancé**

C'est **maintenant** qu'on crée la société, pas avant. Une SARL unipersonnelle : capital minimum
de 100 000 F, acte notarié facultatif à ce niveau de capital, dossier unique au CFCE — 72 heures
en théorie, trois à quinze jours en pratique.

Pourquoi ni plus tôt, ni plus tard :

- **Pas plus tôt** : une société qui ne facture rien coûte des formalités et des obligations
  déclaratives pour rien.
- **Pas plus tard** : une PME structurée — votre cible — veut une facture avec un NIU et un RCCM.
  Sans société, vous plafonnez sur ce segment.

**Régime fiscal :** en dessous de 50 M F de chiffre d'affaires, vous relevez de l'**IGS**, forfait
par classe **libératoire de la patente, de la TVA et de l'IRPP** sur les bénéfices. Concrètement :
pas de déclaration de TVA, obligations comptables réduites à un livre de recettes et dépenses. À
ce stade, la fiscalité n'est pas un sujet — profitez-en, cela ne durera pas.

**Sortie :** 10 clients payants, 300 000 F de revenu récurrent mensuel. Vous vous payez.

### Palier 3 — Automatiser et densifier (mois 10 à 18) · **autofinancé**

Vous connaissez maintenant précisément ce qui vous prend du temps. Vous l'automatisez. La reprise
de stock passe de deux jours à deux heures, l'installation devient un parcours guidé.

C'est là qu'on recrute — **une personne, sur le terrain, pas en développement.** Vous êtes le
développeur ; ce qui manque, ce sont des jambes pour installer et former.

C'est là aussi qu'on ouvre le **canal des cabinets comptables et des CGA** : un cabinet qui gère
40 PME vous en apporte plus en un mois que trois mois de prospection. Payé au succès (voir §5.3).

**Sortie :** 40 à 60 boutiques payantes, 1,5 à 2 M F de revenu mensuel, une personne recrutée.

### Palier 4 — Lever, ou ne pas lever (mois 18+)

Avec 50 clients payants, 12 mois d'historique de rétention et un produit utilisé quotidiennement,
vous n'êtes plus dans la même conversation. Une levée d'amorçage se négocie alors sur des faits,
pas sur des projections — et la valorisation n'a rien à voir avec celle qu'on obtient sur des
diapositives.

**Vous pouvez aussi ne pas lever.** 200 boutiques à 45 000 F, c'est 108 M F de revenu annuel pour
une équipe de six. C'est une entreprise saine, qui appartient à ses fondateurs, et qui n'a pas
besoin de devenir une licorne pour être un succès. La marketplace, la logistique et le financement
de stock du business plan initial redeviennent alors des options — à ouvrir avec l'argent des
clients, ou avec celui d'un investisseur, mais en position de force.

---

## 5. Financer sans lever : par ordre d'efficacité réelle

### 5.1 — Le client qui prépaie *(le meilleur, et de loin)*

20 % de remise contre 12 mois payés d'avance. Cinq clients en annuel prépayé, c'est
**1,44 M FCFA de trésorerie immédiate**, sans dilution, sans intérêts, sans dossier. Et un client
qui a payé un an d'avance est un client engagé : il utilisera le produit, il vous fera des retours,
il vous recommandera.

C'est la première chose à mettre en place, avant toute autre source.

### 5.2 — La prestation de services *(le plus sûr)*

Vous êtes développeur. Deux ou trois missions à 500 000 – 1 500 000 F financent six à douze mois
de projet. C'est lent, cela retarde le produit, et **cela ne dilue rien**.

**La règle à ne pas enfreindre :** jamais de développement sur mesure pour un client du produit.
C'est le chemin par lequel une jeune société de logiciel devient une société de services et n'en
ressort pas. Les missions de prestation doivent être **sans rapport** avec HyperMarché.

### 5.3 — Les partenaires payés au succès

Ni le cabinet comptable ni les apporteurs d'affaires n'ont besoin d'être payés comptant.

Le [document 16](16-partenariat-cabinet-comptable.md) chiffre le cabinet de référence à 8,7 M F
sur 24 mois. **Sans capital, on renverse le montage :** on propose au cabinet une commission
d'apport sur les clients qu'il amène et une part des honoraires de révision, en échange de son
appui technique. Un cabinet qui bascule 40 clients y gagne davantage qu'avec un forfait — et il
prend un vrai risque avec vous, ce qui vaut mieux qu'une caution achetée.

**Ce qui ne change pas :** le module paie n'ouvre toujours pas sans procès-verbal de recette
signé sur les 50 bulletins. Ce n'est pas une question d'argent, c'est une question de risque
partagé — et cela repousse simplement le module paie au palier 4.

### 5.4 — Les subventions et concours *(un bonus, jamais un plan)*

| Dispositif | Montant | Remarque |
|---|---|---|
| **Tony Elumelu Foundation** | 5 000 USD (≈ 3,3 M F) non remboursables + formation et réseau | Candidatures du 1ᵉʳ janvier au 1ᵉʳ mars, cohorte de 3 200 entrepreneurs africains. Le meilleur rapport effort/montant |
| **FNE** — Fonds national de l'emploi | jusqu'à 5 M F | Programme public |
| **PAJER-U, PIAASI, PIFMAS** | 500 000 à 5 M F | Programmes jeunesse, dossiers longs |
| **Digital Africa / Choose Africa** (AFD) | 10 000 à 300 000 EUR | Pour projets **déjà matures** — pertinent au palier 3, pas avant |
| **Incubateurs** (ActivSpaces, Orange Fab, CIPMEN) | Accompagnement, bureaux, réseau | Souvent plus utile que l'argent au démarrage |

**L'avertissement compte autant que la liste.** Les délais sont longs, les taux de sélection
faibles, et le temps passé à monter des dossiers est du temps volé à la prospection. **Un
entrepreneur qui court après les subventions au lieu des clients construit une association, pas
une entreprise.** Traitez-les comme un bonus : une candidature par trimestre, maximum, et jamais
au détriment d'un rendez-vous client.

### 5.5 — Tontine et love money

Culturellement pertinent et souvent le financement le plus rapide disponible. Deux règles :
**formaliser par écrit** (montant, échéance, contrepartie — prêt ou capital, décidé clairement),
et **ne jamais engager l'argent dont un proche a besoin**. Une brouille familiale coûte plus cher
qu'un refus de banque.

---

## 6. Les sept erreurs qui tuent un démarrage sans capital

1. **Construire six mois de plus avant de vendre.** Le socle existe. Il est suffisant pour servir
   trois boutiques dès la semaine prochaine. Chaque semaine de développement supplémentaire avant
   le premier client est une semaine de trésorerie perdue et d'apprentissage retardé.
2. **Vendre trop bas.** 10 000 F/mois ne finance rien, n'engage pas le client, et attire
   précisément les commerçants qui n'utiliseront pas le produit. Un prix bas n'est pas un argument
   commercial, c'est un aveu.
3. **Créer la société trop tôt.** Des charges et des obligations déclaratives avant le premier
   franc encaissé.
4. **Prendre un associé contre du travail, sans période d'acquisition progressive des parts.** Un
   associé qui part au bout de quatre mois avec 30 % du capital rend l'entreprise infinançable.
   Vesting sur 4 ans avec 1 an de seuil, dès le premier jour, sans exception — y compris entre
   amis. Surtout entre amis.
5. **Accepter du développement sur mesure.** Voir §5.2.
6. **Courir après les subventions.** Voir §5.4.
7. **Ne rien se payer pendant dix-huit mois.** C'est la cause d'abandon la plus fréquente, et elle
   n'a rien d'héroïque. Fixez-vous un salaire minimal dès 8 clients, et tenez-le.

---

## 7. Le seuil de renoncement

Défini maintenant, à froid.

| Échéance | Condition | Si elle n'est pas remplie |
|---|---|---|
| **Mois 2** | 3 commerçants ont dit oui à un pilote payant, avec un prix | Le problème est la proposition de valeur. Retour au palier 0, autre segment ou autre angle. |
| **Mois 4** | 3 clients paient, et utilisent la caisse chaque semaine | S'ils paient sans utiliser, vous vendez un service, pas un logiciel — et ça ne s'automatisera jamais. |
| **Mois 9** | 8 clients payants, aucun départ | **Point de décision franc.** Avec 8 clients en 9 mois sans dépenser, le modèle fonctionne. Sans eux, aucun financement ne répare : c'est le produit ou le marché. |
| **Mois 18** | 40 clients, rétention > 80 % | En dessous, ne pas recruter, ne pas lever. Consolider ou arrêter. |

> **Un échec à 500 000 F et neuf mois est une information payée au juste prix.** Un échec à
> 400 M F et trois ans est une autre affaire. C'est le seul avantage réel de démarrer sans
> capital, et il est considérable : **vous pouvez vous tromper.**

---

## 8. Les quatre prochaines actions

Dans cet ordre, et sans en sauter une.

1. **Cette semaine — cinq visites.** Cinq commerçants, guide d'entretien du document 15 en poche,
   aucun écran. Vous cherchez la phrase qui revient, pas l'approbation.
2. **Semaine 3 — la première installation gratuite.** Le commerçant le plus précis dans la
   description de ses problèmes, pas le plus enthousiaste. Vous faites son inventaire avec lui.
   Vous ne facturez rien. Vous observez tout.
3. **Semaine 6 — le premier prix demandé.** « À partir du mois prochain, c'est 30 000 F par mois,
   ou 288 000 F pour l'année. » La réponse à cette phrase vaut tous les documents de ce dépôt.
4. **Dès le premier oui — la société.** SARLU, capital 100 000 F, CFCE. Vous facturez proprement,
   et vous êtes crédible auprès des suivants.

Le reste — marketplace, logistique, affiliation, comptabilité complète, paie — est déjà spécifié
dans ce dépôt et attendra son financement. **Ce qui n'attend pas, c'est le premier client.**
