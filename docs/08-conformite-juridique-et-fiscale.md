# 08 — Conformité juridique, fiscale et réglementaire

> ⚠️ Ce document est un cadrage de conception, pas un avis juridique. Chaque point marqué
> **[À VALIDER]** doit être confirmé par un conseil local avant mise en production.

---

## 1. Statut de la plateforme : intermédiaire, pas commerçant

La qualification juridique de l'exploitant détermine tout le reste : sa responsabilité produit,
son assiette de TVA, ses obligations de paiement.

| Modèle | Qui vend ? | TVA collectée sur | Responsabilité produit |
|---|---|---|---|
| **Retailer** (Glotelho) | La plateforme | Le prix de vente complet | La plateforme |
| **Intermédiaire transparent** — *choix retenu* | Le marchand | La commission et le loyer uniquement | Le marchand |

**Conséquences du choix d'intermédiaire transparent :**

- Le marchand est le vendeur ; la facture au client final porte **son** NIU et **son** RCCM.
- La plateforme facture au marchand une prestation de service (loyer + commission), soumise à TVA
  à 19,25 %.
- La plateforme n'est pas responsable de la conformité des produits, mais elle est responsable de
  la **diligence** : vérification KYC des marchands, retrait des offres illicites signalées,
  traçabilité.
- Cette qualification doit être **explicite dans les conditions générales, sur chaque fiche
  produit et sur chaque facture**. Une ambiguïté sur ce point fait basculer la responsabilité et
  l'assiette de TVA. **[À VALIDER]**

---

## 2. Constitution et formalités

| Formalité | Échéance | Note |
|---|---|---|
| Constitution SARL (puis SA) de droit camerounais, OHADA | M0 | Siège à Douala |
| Immatriculation au RCCM | M0 | |
| Obtention du NIU auprès de la DGI | M0 | |
| Dépôt de marque à l'**OAPI** | **M1, avant toute communication publique** | **Un seul dépôt couvre les 17 États membres** — avantage majeur, à ne pas manquer |
| Déclaration au registre des traitements de données | Avant le 23 juin 2026 | Loi 2024/017 |
| Enregistrement du nom de domaine `.cm` | M0 | |
| Contrats d'agrégation Mobile Money (MTN, Orange, Camtel) | M2 | Via agrégateur agréé |
| Adhésion à un cabinet d'expertise comptable agréé ONECCA | M1 | Prérequis des arbitrages A5 et A6 |

---

## 3. Fiscalité applicable à la plateforme

| Impôt | Taux | Base |
|---|---|---|
| **TVA** | 19,25 % (17,5 % + 10 % de centimes additionnels communaux) | Loyers, commissions, services |
| **Impôt sur les sociétés** | 27,5 % effectif au régime simplifié ; **33 %** au réel normal | Résultat fiscal |
| **Acompte mensuel (régime simplifié)** | 2,2 % du chiffre d'affaires | Imputable sur l'IS |
| **Patente** | Barème local | Selon commune |
| **Retenues à la source** | Selon nature | Prestataires, loyers |

### 3.1 — La loi de finances 2026 : un avantage compétitif

Depuis le 1ᵉʳ janvier 2026, les plateformes étrangères opérant au Cameroun **sans présence
physique** sont assujetties à un impôt sur les sociétés équivalent à **3 % de leur chiffre
d'affaires local**, via la notion d'« établissement stable numérique ». Les acteurs visés incluent
Amazon, Temu, Shein, TikTok et Netflix.

**Lecture stratégique :** un opérateur constitué localement, qui supporte des charges
d'implantation physique, n'est plus désavantagé face aux géants transfrontaliers. C'est une
protection tarifaire de fait dont il faut profiter maintenant — et un argument d'investissement
à mettre en avant.

### 3.2 — Obligations de facturation

Toute facture émise par un marchand via la plateforme doit comporter :

- raison sociale, adresse, **NIU** et **RCCM** du vendeur
- identification de l'acheteur (NIU si professionnel)
- numérotation séquentielle continue, sans rupture ni doublon
- date, désignation, quantité, prix unitaire HT
- taux et montant de TVA, total HT, total TTC
- mention du régime d'imposition **[À VALIDER : format exact des mentions obligatoires]**

Le moteur de facturation garantit la **séquence continue par boutique et par exercice**, avec
impossibilité technique de supprimer une facture émise (annulation par avoir uniquement).

---

## 4. Protection des données personnelles — loi n° 2024/017

### 4.1 — Le cadre

Le Cameroun a adopté la **loi n° 2024/017 du 23 décembre 2024** relative à la protection des
données à caractère personnel. Elle devient **pleinement applicable le 23 juin 2026** — soit
**avant le lancement du produit**. Une autorité de contrôle (APDP) est instituée, dotée d'un
pouvoir de sanction.

Principes imposés : tout traitement doit être **licite, loyal et non frauduleux**, respecter la vie
privée et être subordonné — sauf exemption légale — à un **consentement éclairé, spécifique et non
équivoque**.

### 4.2 — Ce que cela impose au produit

| Obligation | Traduction technique |
|---|---|
| Consentement explicite et spécifique | Registre des consentements horodaté, granulaire, révocable en un clic. Objet de première classe du modèle de données, jamais une simple case à cocher |
| Finalité déterminée | Registre des traitements documenté et tenu à jour |
| Minimisation | Ne collecter que le nécessaire ; pas de collecte « au cas où » |
| Droit d'accès et de portabilité | Export complet des données d'un utilisateur, à la demande, en format lisible |
| Droit à l'effacement | Anonymisation en cascade, avec conservation des données comptables obligatoires |
| Sécurité | Chiffrement au repos des pièces d'identité, journal d'accès, gestion des habilitations |
| Notification de violation | Procédure documentée, délai de notification à l'APDP **[À VALIDER]** |
| Encadrement des transferts hors du Cameroun | **Impacte le choix d'hébergement — voir §4.3** |

> **Pièces d'identité :** par défaut, la plateforme n'en conserve **pas** de copie ; elle garde une
> attestation de ce qui a été vu. Le raisonnement et ses réserves sont au
> [document 23](23-confiance-et-lutte-contre-la-fraude.md), §2.3, et à l'ADR-013 (point J14).

### 4.3 — Conflit entre effacement et obligation comptable

Un client demande la suppression de ses données. Ses factures doivent être conservées pour des
raisons fiscales et comptables. **Résolution retenue :**

- Les données d'identité sont **anonymisées** (nom, téléphone, adresse remplacés par un
  pseudonyme irréversible).
- Les données **comptables et fiscales sont conservées** pendant la durée légale de conservation,
  rattachées au pseudonyme.
- L'anonymisation est journalisée et opposable.

### 4.4 — Hébergement et souveraineté

Le transfert de données personnelles hors du Cameroun est encadré. **[À VALIDER : conditions
exactes de transfert et exigence éventuelle de localisation.]** Deux options d'architecture :

| Option | Avantages | Inconvénients |
|---|---|---|
| **Hébergement local** (datacenter camerounais) | Conformité maximale, latence faible, argument commercial et souverain | Coût, disponibilité, qualité de service variable |
| **Cloud régional** (Afrique du Sud, Europe) avec clauses de transfert | Fiabilité, élasticité, outillage | Risque réglementaire, latence, dépendance |

**Décision retenue :** architecture conçue pour être **portable** — pas d'adhérence à des services
propriétaires non substituables — afin que la localisation puisse changer sans réécriture. Voir
[document 09](09-architecture-technique.md).

---

## 5. Paiement et monnaie électronique

### 5.1 — Ce qu'on ne fait pas

La plateforme **n'est pas et ne cherche pas à devenir un établissement de monnaie électronique**.
L'agrément BEAC est un projet réglementaire de plusieurs années, incompatible avec le calendrier.

### 5.2 — Montage retenu

- Encaissement via des **agrégateurs de paiement agréés**, eux-mêmes interfacés avec MTN MoMo,
  Orange Money et Camtel.
- Les fonds en séquestre transitent par un **compte de cantonnement** ouvert chez un partenaire
  agréé, juridiquement distinct des fonds propres de la plateforme. **[À VALIDER : qualification
  du séquestre et régime applicable au compte de cantonnement.]**
- Le **portefeuille marchand** affiché dans le produit est un **compte de suivi**, pas un dépôt :
  il retrace une créance du marchand sur la plateforme, non un solde de monnaie électronique.
  Cette distinction doit être explicite dans les conditions générales.

> Conditions de libération du séquestre, paliers de confiance, compte de versement et ce que le
> montage implique pour le produit : [document 23](23-confiance-et-lutte-contre-la-fraude.md), §2 et
> §4.2.

### 5.3 — Lutte anti-blanchiment

Le dispositif LBC/FT s'applique. Mesures intégrées au produit :

- **KYC marchand obligatoire** : RCCM, NIU, pièce d'identité du gérant, vérification du compte
  Mobile Money de reversement.
- **KYC allégé affilié**, renforcé au-delà de 500 000 F de gains mensuels cumulés
  ([document 06](06-affiliation-marketing-revendeurs.md), §6).
- Surveillance des schémas atypiques : volumes sans logique commerciale, retraits immédiats,
  circularité entre comptes liés.
- Conservation des justificatifs et traçabilité des flux. **[À VALIDER : seuils de déclaration
  auprès de l'ANIF.]**

> Menaces, signaux de risque, textes CEMAC LBC/FT et procédure de soupçon :
> [document 23](23-confiance-et-lutte-contre-la-fraude.md), §1.8, §2.5, §4.3 et §6.2.

---

## 6. Le programme d'affiliation

Le risque de requalification en **vente pyramidale** est traité en détail au
[document 06](06-affiliation-marketing-revendeurs.md), §2.3. Rappel des six garde-fous, codés en
dur et non paramétrables :

1. Deux niveaux de filiation maximum
2. Rémunération assise exclusivement sur du chiffre d'affaires encaissé et non annulé
3. Aucun droit d'entrée, aucun achat obligatoire
4. Aucun stock imposé au revendeur
5. Aucun rang, titre ou bonus de volume d'équipe
6. Aucune promesse de gain dans la communication

**[À VALIDER : qualification du programme au regard du droit de la consommation camerounais et
des textes CEMAC sur les pratiques commerciales.]**

---

## 7. Droit du travail des marchands

La plateforme outille la paie de ses clients ; elle n'est pas leur employeur. Deux précautions :

- **Le module paie n'est pas un conseil juridique.** Les conditions d'utilisation excluent
  expressément toute garantie sur la conformité d'un bulletin, la responsabilité restant au
  marchand et à son cabinet.
- **Alertes de conformité intégrées** : fin de période d'essai, échéance de CDD, dépassement du
  contingent d'heures supplémentaires, salaire inférieur au SMIG (60 000 F). Ces alertes sont un
  service, pas une garantie.

Le Code du travail camerounais et les conventions collectives de branche s'appliquent aux
marchands. Le paramétrage des taux d'accident du travail (1,75 % à 5 %) dépend du groupe de risque
sectoriel de chaque employeur. **[À VALIDER : table complète des groupes de risque.]**

---

## 8. Litiges et médiation

| Type de litige | Traitement |
|---|---|
| Acheteur ↔ Marchand | Médiation par la plateforme sous 72 h, séquestre bloqué pendant l'instruction, décision motivée et opposable |
| Marchand ↔ Plateforme | Clause de conciliation préalable, puis juridiction compétente de Douala |
| Non-paiement du loyer | Mise en demeure, suspension de la vitrine à J+15, résiliation à J+45, restitution des données garantie |
| Contrefaçon ou produit illicite | Retrait immédiat sur signalement, notification au marchand, sanction graduée jusqu'à la résiliation |

> Instruction d'un litige en 72 h, gel conservatoire, plainte et réquisitions :
> [document 23](23-confiance-et-lutte-contre-la-fraude.md), §6. La portée juridique de la
> « décision opposable » est à valider (J17).

**Principe de réversibilité :** en toute circonstance, y compris en cas de résiliation pour faute,
le marchand récupère l'intégralité de ses données (catalogue, stock, clients, écritures
comptables, bulletins de paie) dans un format exploitable et **sans frais**. C'est une obligation
morale, un argument commercial, et une protection contre le grief d'abus de position.

---

## 9. Registre des points à valider

| # | Point | Interlocuteur | Échéance |
|---|---|---|---|
| J1 | Qualification d'intermédiaire transparent et assiette de TVA | Conseil fiscal | Avant lot 1 |
| J2 | Format exact des mentions obligatoires de facturation | Conseil fiscal / DGI | Avant lot 1 |
| J3 | Régime du compte de cantonnement et du séquestre | Conseil bancaire | Avant lot 1 |
| J4 | Conditions de transfert de données hors Cameroun | Conseil données / APDP | Avant lot 1 |
| J5 | Délai de notification de violation de données | Conseil données | Avant lot 1 |
| J6 | Qualification du programme d'affiliation | Conseil consommation | Avant lot 1 |
| J7 | Seuils de déclaration LBC/FT (ANIF) | Conseil conformité | Avant lot 2 |
| J8 | Rattachement comptable de la monnaie électronique | Cabinet ONECCA | Avant lot 3 |
| J9 | Table des groupes de risque accidents du travail | Cabinet ONECCA / CNPS | Avant lot 4 |
| J10 | Barèmes TDL et RAV en vigueur | Cabinet ONECCA | Avant lot 4 |
| J11 | Convention de partenariat cabinet (arbitrages A5, A6) | Cabinet ONECCA | Avant lot 3 |
| J12 | Rôle d'instruction de la plateforme sur le séquestre (libérer, rembourser) : statut exigé (agent, mandataire) ; titulaire du compte de cantonnement ; sort des fonds en cas de défaillance — complète J3 ([doc. 23](23-confiance-et-lutte-contre-la-fraude.md), §4.2) | COBAC via partenaire / conseil bancaire | Avant lot 1 |
| J13 | Qualité d'assujetti LBC/FT de la plateforme, ou obligations transférées par contrat du partenaire ; filtrage des listes de sanctions (doc. 23, §4.3) | Conseil conformité / partenaire | Avant lot 1 |
| J14 | Non-conservation des copies de pièces d'identité : compatible avec les exigences du partenaire et du règlement LBC/FT ? Sinon, qui conserve (doc. 23, §2.3) | Conseil données / partenaire | Avant lot 1 |
| J15 | Validité des clauses : retenue, gel conservatoire (durée), compensation, délai de libération, confirmation implicite de livraison à 7 jours — envers le marchand et envers l'acheteur consommateur (doc. 23, §5) | Conseil consommation / affaires | Avant lot 1 |
| J16 | Obligations de tiers saisi (AUPSRVE) sur les sommes dues aux marchands ; forme et authentification des réquisitions (doc. 23, §6.5) | Avocat | Avant lot 1 |
| J17 | Statut de la décision de litige de la plateforme (décision contractuelle, médiation au sens de l'Acte uniforme de 2017, jamais « arbitrage ») (doc. 23, §4.1) | Avocat | Avant lot 1 |
| J18 | Acceptation de l'entreprenant OHADA sans immatriculation de société ; pièces exigibles ; format du numéro RCCM (doc. 23, §2.3, §4.1) | Avocat | Avant lot 1 |
| J19 | Durées de conservation : attestations de vérification, preuves de transaction, journaux, données de connexion (LBC/FT, loi 2010/012, loi 2024/017, AUDCIF) | Conseil données / conformité | Avant lot 1 |
| J20 | Obligations d'information du vendeur en ligne (loi 2010/021) sur la page boutique et la fiche produit ; responsabilité de la plateforme en tant qu'intermédiaire | Avocat | Avant lot 1 |
| J21 | Licéité et base légale du masquage automatique des coordonnées dans les messages acheteur–marchand (loi 2024/017) | Conseil données | Avant lot 2 |
| J22 | Données pays de `apps/marketplace/cemac.py` (numérotation, identifiant fiscal, opérateurs, loi et autorité de protection des données, CRF) | Avocat local de chaque pays | Avant ouverture du pays |
| J23 | Procédure de déclaration de soupçon (qui déclare, par quel canal) et interdiction d'informer : texte du message affiché à une boutique gelée | Conseil conformité / ANIF / partenaire | Avant lot 2 |
