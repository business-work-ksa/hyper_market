# 07 — Comptabilité SYSCOHADA et paie camerounaise

> ⚠️ **Avertissement.** Les barèmes, taux et numéros de compte de ce document sont donnés à titre
> de cadrage de conception, sourcés en [document 13](13-sources.md). Ils doivent être **validés et
> contresignés par un expert-comptable agréé ONECCA et un conseil fiscal** avant toute mise en
> production. Conformément à l'arbitrage A5, la plateforme *prépare* la comptabilité ; elle ne la
> certifie pas.

---

## 1. Principes directeurs

### 1.1 — Le référentiel

Le **SYSCOHADA révisé** s'applique dans les 17 États membres de l'OHADA, dont l'ensemble de la
CEMAC. C'est un atout d'architecture majeur : **un seul plan comptable couvre tout le marché
régional visé.** Les différences entre pays portent sur la fiscalité (taux de TVA, impôt sur les
sociétés) et le droit du travail, pas sur le plan de comptes.

### 1.2 — Trois règles non négociables

**Règle 1 — Le journal est en ajout seul.**
Une écriture validée n'est jamais modifiée ni supprimée. Toute correction se fait par
**contre-passation** : une écriture inverse, datée du jour de la correction, référençant l'écriture
d'origine. Toute conception permettant un `UPDATE` ou un `DELETE` sur une écriture validée est
rejetée en revue de code (arbitrage A12).

**Règle 2 — Zéro double saisie.**
Le comptable ne saisit rien de ce que le système sait déjà. Une vente en caisse produit
automatiquement l'écriture de vente, l'écriture de TVA, la sortie de stock et l'encaissement. La
saisie manuelle existe, mais elle est l'exception (opérations diverses, régularisations).

**Règle 3 — Traçabilité bidirectionnelle.**
Depuis toute écriture on remonte à l'opération métier qui l'a produite ; depuis toute opération
métier on descend aux écritures générées. C'est ce qui rend le système auditable et ce qui permet
à un cabinet partenaire de réviser en confiance.

---

## 2. Plan comptable

### 2.1 — Les classes SYSCOHADA

| Classe | Intitulé | Usage principal dans le produit |
|---|---|---|
| **1** | Ressources durables | Capital, réserves, emprunts, dettes financières |
| **2** | Actif immobilisé | Matériel de boutique, aménagements, logiciels |
| **3** | Stocks | Marchandises, valorisation CMP |
| **4** | Tiers | Clients, fournisseurs, personnel, État, organismes sociaux |
| **5** | Trésorerie | Caisse, banque, **monnaie électronique (Mobile Money)** |
| **6** | Charges des activités ordinaires | Achats, services extérieurs, personnel, impôts |
| **7** | Produits des activités ordinaires | Ventes, prestations, produits accessoires |
| **8** | Autres charges et produits | Hors activités ordinaires (HAO) |
| **9** | Comptabilité analytique | Optionnel, par point de vente ou rayon |

### 2.2 — Comptes structurants du produit

| Compte | Intitulé | Rôle |
|---|---|---|
| `311` | Marchandises | Stock valorisé en CMP |
| `401` | Fournisseurs, dettes en compte | Achats |
| `411` | Clients | Ventes à crédit, encours |
| `422` | Personnel, rémunérations dues | Net à payer |
| `431` | Sécurité sociale (CNPS) | Cotisations salariales et patronales |
| `4431` | État, TVA facturée sur ventes | TVA collectée |
| `4452` | État, TVA récupérable sur achats | TVA déductible |
| `4441` | État, TVA due | Solde de la déclaration |
| `447` | État, impôts retenus à la source | IRPP, CAC, TDL, RAV |
| `5211` | Banque | Compte bancaire de la boutique |
| `5311`* | Monnaie électronique — MTN MoMo | Portefeuille Mobile Money |
| `5312`* | Monnaie électronique — Orange Money | Portefeuille Mobile Money |
| `5313`* | Compte plateforme HyperMarché | Solde en attente de reversement |
| `571` | Caisse siège social | Espèces au comptoir |
| `6011` | Achats de marchandises | Achats |
| `6031` | Variation des stocks de marchandises | Contrepartie de la sortie de stock |
| `622` | Locations et charges locatives | **Loyer de l'emplacement numérique** |
| `632` | Rémunérations d'intermédiaires | **Commission de la plateforme** |
| `661` | Rémunérations directes versées au personnel | Salaires bruts |
| `664` | Charges sociales patronales | CNPS employeur, CFC, FNE |
| `701` | Ventes de marchandises | Chiffre d'affaires HT |

\* Sous-comptes créés dans la classe 53 « Établissements financiers et assimilés ». Le
rattachement définitif de la monnaie électronique doit être validé par le cabinet partenaire.

---

## 3. Automatisation : de l'opération métier à l'écriture

C'est le cœur de la promesse produit. Chaque événement du système déclenche un modèle d'écriture
prédéfini.

### 3.1 — Vente au comptoir, 119 250 F TTC (100 000 F HT, TVA 19,25 %), payée en espèces

| Journal | Compte | Libellé | Débit | Crédit |
|---|---|---|---:|---:|
| VTE | `411` | Client comptoir | 119 250 | |
| VTE | `701` | Ventes de marchandises | | 100 000 |
| VTE | `4431` | TVA facturée | | 19 250 |
| CAI | `571` | Caisse | 119 250 | |
| CAI | `411` | Client comptoir | | 119 250 |
| STK | `6031` | Variation de stock (coût CMP) | 68 000 | |
| STK | `311` | Marchandises | | 68 000 |

> Trois écritures, zéro saisie humaine. La marge brute réelle (32 000 F) devient calculable
> instantanément — c'est l'information que le persona M. Ateba n'a jamais eue.

### 3.2 — Vente en ligne encaissée par Mobile Money, commission plateforme 5 %

| Journal | Compte | Libellé | Débit | Crédit |
|---|---|---|---:|---:|
| VTE | `411` | Client en ligne | 119 250 | |
| VTE | `701` | Ventes de marchandises | | 100 000 |
| VTE | `4431` | TVA facturée | | 19 250 |
| BQE | `5313` | Compte plateforme (séquestre) | 119 250 | |
| BQE | `411` | Client en ligne | | 119 250 |
| ACH | `632` | Commission de place (5 % HT) | 5 000 | |
| ACH | `4452` | TVA récupérable sur commission | 962 | |
| ACH | `401` | Plateforme HyperMarché | | 5 962 |
| BQE | `5311` | MTN MoMo (reversement net) | 113 288 | |
| BQE | `401` | Plateforme (compensation) | 5 962 | |
| BQE | `5313` | Compte plateforme | | 119 250 |

### 3.3 — Loyer mensuel de l'emplacement, offre « Boutique » à 45 000 F HT

| Journal | Compte | Libellé | Débit | Crédit |
|---|---|---|---:|---:|
| ACH | `622` | Locations — emplacement numérique | 45 000 | |
| ACH | `4452` | TVA récupérable | 8 662 | |
| ACH | `401` | Plateforme HyperMarché | | 53 662 |

### 3.4 — Table de correspondance complète

| Événement métier | Journal | Débit | Crédit |
|---|---|---|---|
| Vente (HT) | VTE | `411` | `701` |
| TVA sur vente | VTE | `411` | `4431` |
| Sortie de stock au CMP | STK | `6031` | `311` |
| Encaissement espèces | CAI | `571` | `411` |
| Encaissement Mobile Money | BQE | `531x` | `411` |
| Achat de marchandises | ACH | `6011` + `4452` | `401` |
| Entrée en stock | STK | `311` | `6031` |
| Règlement fournisseur | BQE | `401` | `521`/`531x` |
| Commission plateforme | ACH | `632` + `4452` | `401` |
| Loyer d'emplacement | ACH | `622` + `4452` | `401` |
| Frais de livraison refacturés | VTE | `411` | `706` |
| Perte / casse de stock | STK | `6031` ou `659` | `311` |
| Écart d'inventaire | OD | selon sens | selon sens |
| Salaires bruts | PAI | `661` | `422` + `431` + `447` |
| Charges patronales | PAI | `664` | `431` |
| Paiement des salaires | BQE | `422` | `531x`/`521` |
| Retour client et avoir | VTE | `701` + `4431` | `411` |
| Déclaration de TVA | OD | `4431` | `4452` + `4441` |

---

## 4. TVA

| Élément | Valeur |
|---|---|
| Taux normal au Cameroun | **19,25 %** (17,5 % de TVA + 10 % de centimes additionnels communaux) |
| Périodicité déclarative | Mensuelle |
| Formule | TVA due = TVA collectée (`4431`) − TVA déductible (`4452`) |
| Crédit de TVA | Reporté sur la période suivante |

Le régime de TVA (assujetti, non assujetti, exonéré) est porté **par produit** et non seulement par
boutique, car certains biens (produits de première nécessité, médicaments) relèvent d'un régime
particulier. Le moteur produit une déclaration pré-remplie, exportable, que le marchand ou son
cabinet dépose.

---

## 5. Régimes fiscaux camerounais

Le régime détermine les obligations comptables et donc les fonctionnalités activées.

| Régime | Chiffre d'affaires annuel HT | Imposition | Obligations comptables |
|---|---|---|---|
| **IGS** — impôt général synthétique | ≤ 50 M F (activités commerciales) | Forfait par classe, **libératoire de la patente, de la TVA et de l'IRPP** sur les bénéfices | Livre de recettes/dépenses |
| **Réel simplifié** | 50 à 100 M F | 25 % + 10 % CAC = **27,5 %** ; acompte mensuel de 2,2 % du CA | Système allégé SYSCOHADA |
| **Réel normal** | > 100 M F | 30 % + 10 % CAC = **33 %** | Système normal SYSCOHADA, états financiers complets |

> **Attention — changement de cadre.** L'**impôt libératoire** (CA < 10 M) et l'ancien **régime
> simplifié** (10 à 50 M) ont été **supprimés et fusionnés dans l'IGS**, institué par la loi
> n° 2024/020 du 23 décembre 2024 sur la fiscalité locale et structuré par la loi de finances 2026.
> Toute documentation antérieure mentionnant l'impôt libératoire est périmée.

**Le barème IGS** compte 10 classes progressives selon la tranche de chiffre d'affaires — de
20 000 F/an pour la classe 1 (CA < 500 000 F) à environ 1 000 000 F/an pour la classe 10
(CA de 20 à 30 M F). **[À VALIDER : barème complet et nombre exact de classes — les sources
publiques divergent entre 10 et 12 ; se référer à l'article C 40 de la loi sur la fiscalité
locale.]**

**Deux conséquences produit, à ne pas manquer :**

1. **Un assujetti à l'IGS ne facture pas de TVA et ne la récupère pas.** Le moteur de facturation
   et les modèles d'écriture doivent en tenir compte : pour ces boutiques, aucune ligne `4431` ni
   `4452`, et la déclaration de TVA n'a pas lieu d'être. C'est le cas de la majorité des petites
   boutiques — donc un cas à traiter dès le lot 1, pas une exception tardive.
2. **L'adhésion à un centre de gestion agréé (CGA) divise l'IGS par deux** pour les classes 8, 9
   et 10 (CA ≥ 10 M F). C'est une **alerte à forte valeur perçue** à intégrer au produit : « en
   adhérant à un CGA, vous économisez X FCFA par an ». Elle ouvre aussi un canal de partenariat
   naturel avec les CGA, au même titre que les cabinets d'expertise comptable
   ([document 16](16-partenariat-cabinet-comptable.md)).

Le persona cible (M. Ateba, 85 M F de CA) relève du **réel simplifié** ; il bascule au réel normal
en franchissant 100 M. La plateforme doit détecter les deux franchissements de seuil — 50 M
(sortie de l'IGS, entrée dans la TVA) et 100 M — et alerter. Le premier est le plus important :
**une boutique qui franchit 50 M sans s'en apercevoir devient redevable de la TVA sans l'avoir
collectée.**

---

## 6. La paie camerounaise

### 6.1 — Retenues salariales

| Retenue | Assiette | Taux | Plafond |
|---|---|---|---|
| **CNPS — pension vieillesse** | Salaire brut | **4,2 %** | 750 000 F/mois |
| **Crédit foncier (CFC) — part salarié** | Salaire brut | **1 %** | — |
| **IRPP** | Revenu net catégoriel | barème progressif | — |
| **CAC sur IRPP** | Montant de l'IRPP | **10 %** | — |
| **Taxe de développement local (TDL)** | Barème par tranche de salaire | forfait | — |
| **Redevance audiovisuelle (RAV)** | Barème par tranche de salaire | forfait | — |

**Barème IRPP** (revenu net catégoriel annuel) :

| Tranche | Taux |
|---|---|
| jusqu'à 2 000 000 F | 10 % |
| 2 000 001 à 3 000 000 F | 15 % |
| 3 000 001 à 5 000 000 F | 25 % |
| au-delà de 5 000 000 F | 35 % |

**Calcul du revenu net catégoriel :**
```
RNC = (Brut annuel − CNPS salarié) × 70 %  −  500 000
                                    └─ abattement forfaitaire de 30 % pour frais professionnels
```

### 6.2 — Charges patronales

| Charge | Assiette | Taux |
|---|---|---|
| **CNPS — pension vieillesse** | Salaire brut, plafonné 750 000 F | **4,2 %** |
| **CNPS — prestations familiales** | Salaire brut, plafonné 750 000 F | **7 %** |
| **CNPS — accidents du travail** | Salaire brut | **1,75 % à 5 %** selon le groupe de risque du secteur |
| **Crédit foncier (CFC) — part patronale** | Salaire brut | **1,5 %** |
| **Fonds national de l'emploi (FNE)** | Salaire brut | **1 %** |

**SMIG :** 60 000 F/mois (non agricole), 45 000 F/mois (agricole).

### 6.3 — Bulletin de paie type — salaire brut 300 000 F, secteur commerce (groupe A)

**Retenues salariales**

| Ligne | Base | Taux | Montant |
|---|---:|---:|---:|
| CNPS pension vieillesse | 300 000 | 4,2 % | 12 600 |
| Crédit foncier (part salarié) | 300 000 | 1 % | 3 000 |
| IRPP | *voir calcul* | barème | 15 951 |
| CAC sur IRPP | 15 951 | 10 % | 1 595 |
| Taxe de développement local | barème | forfait | 2 500 |
| Redevance audiovisuelle | barème | forfait | 3 250 |
| **Total retenues** | | | **38 896** |
| **Net à payer** | | | **261 104** |

*Détail du calcul IRPP :*
```
Brut annuel                        3 600 000
− CNPS salarié (4,2 %)              −151 200
= Base après cotisations            3 448 800
× 70 % (abattement frais prof.)     2 414 160
− abattement annuel                  −500 000
= Revenu net catégoriel             1 914 160
× 10 % (1ʳᵉ tranche)                  191 416  → 15 951 F/mois
```

**Charges patronales**

| Ligne | Base | Taux | Montant |
|---|---:|---:|---:|
| CNPS pension vieillesse | 300 000 | 4,2 % | 12 600 |
| CNPS prestations familiales | 300 000 | 7 % | 21 000 |
| CNPS accidents du travail (groupe A) | 300 000 | 1,75 % | 5 250 |
| Crédit foncier (part patronale) | 300 000 | 1,5 % | 4 500 |
| Fonds national de l'emploi | 300 000 | 1 % | 3 000 |
| **Total charges patronales** | | | **46 350** |
| **Coût total employeur** | | | **346 350** |

### 6.4 — Écritures de paie générées

| Journal | Compte | Libellé | Débit | Crédit |
|---|---|---|---:|---:|
| PAI | `661` | Salaires bruts | 300 000 | |
| PAI | `664` | Charges sociales patronales | 46 350 | |
| PAI | `422` | Personnel, rémunérations dues | | 261 104 |
| PAI | `431` | CNPS (12 600 salarié + 38 850 patronal) | | 51 450 |
| PAI | `447` | État — IRPP, CAC, TDL, RAV, CFC | | 33 796 |
| BQE | `422` | Paiement du salaire (Mobile Money) | 261 104 | |
| BQE | `5311` | MTN MoMo | | 261 104 |

### 6.5 — Exigences de conception du moteur de paie

L'arbitrage A6 conditionne l'ouverture du module. Contraintes techniques :

1. **Versionnement par période d'application.** Un barème porte une date de début et une date de
   fin. Recalculer un bulletin de mars 2027 en 2029 doit produire exactement le même résultat.
   Aucun barème n'est jamais écrasé.
2. **Jeu de tests de non-régression sur bulletins réels.** Au minimum 50 bulletins couvrant tous
   les cas (temps partiel, plafonnement CNPS, tranches IRPP hautes, primes, avances, congés),
   validés et signés par le cabinet partenaire.
3. **Revue annuelle obligatoire** après chaque loi de finances, avec procédure de mise à jour
   documentée et communication aux clients.
4. **Traçabilité du calcul.** Chaque ligne du bulletin conserve la formule, la base et le taux
   utilisés, affichables en cas de contrôle.
5. **Aucun recalcul silencieux.** Un bulletin émis est figé. Une correction produit un bulletin
   rectificatif, jamais une modification en place.

---

## 7. États produits

| État | Périodicité | Destinataire | Lot |
|---|---|---|---|
| Brouillard des écritures | Continu | Gérant, comptable | 3 |
| Grand livre général et auxiliaire | À la demande | Comptable | 3 |
| Balance générale | Mensuelle | Gérant, cabinet | 3 |
| Déclaration de TVA pré-remplie | Mensuelle | Marchand → DGI | 3 |
| Rapprochement bancaire et Mobile Money | Mensuelle | Comptable | 3 |
| Compte de résultat SYSCOHADA | Annuelle | Cabinet | 3 |
| Bilan SYSCOHADA | Annuelle | Cabinet | 3 |
| Tableau des flux de trésorerie | Annuelle | Cabinet | 3 |
| Notes annexes | Annuelle | Cabinet | 3 |
| Bulletin de paie | Mensuelle | Salarié | 4 |
| Livre de paie | Mensuelle | Gérant | 4 |
| État des cotisations CNPS | Mensuelle | Marchand → CNPS | 4 |
| DIPE | Annuelle | Marchand → administration | 4 |

---

## 8. Le rôle du cabinet partenaire

Rappel de l'arbitrage A5 : **un logiciel ne signe pas des états financiers.**

| Fait la plateforme | Fait le cabinet agréé |
|---|---|
| Enregistre les opérations en temps réel | Contrôle la cohérence et la sincérité |
| Génère les écritures automatiques | Passe les écritures d'inventaire et de régularisation |
| Produit balance, grand livre, projets d'états financiers | Révise, corrige, atteste et signe |
| Calcule les bulletins et déclarations | Valide les barèmes et engage sa responsabilité |
| Alerte sur les seuils et anomalies | Conseille et représente en cas de contrôle |

**Formulation marketing imposée :** *« La plateforme prépare, votre expert-comptable révise et
atteste. »* Aucune mention de « comptabilité certifiée » n'est autorisée dans quelque support que
ce soit.
