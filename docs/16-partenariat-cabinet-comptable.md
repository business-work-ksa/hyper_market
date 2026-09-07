# 16 — Partenariat avec un cabinet d'expertise comptable

**Prérequis bloquant des lots 3 et 4** (arbitrages A5 et A6). Sans convention signée, le module
comptabilité ne sort pas et le module paie n'ouvre pas.

---

## 1. Pourquoi c'est une condition, et pas une bonne pratique

Trois raisons distinctes, dont deux seulement sont des raisons de conformité.

### 1.1 — Un logiciel ne signe pas des états financiers

L'attestation d'états financiers est un acte professionnel réservé aux experts-comptables inscrits
au tableau de l'ONECCA. Toute communication laissant croire que la plateforme « fait la
comptabilité » du marchand vous expose à l'Ordre — et, plus gravement, détruit votre crédibilité
auprès des cabinets, qui sont par ailleurs **votre meilleur canal d'acquisition** (un cabinet
gère 40 à 150 PME).

> **Formulation imposée, sur tous les supports :**
> *« La plateforme prépare, votre expert-comptable révise et atteste. »*
> Aucune mention de « comptabilité certifiée » n'est autorisée.

### 1.2 — Une erreur de barème de paie est démultipliée par le nombre de clients

C'est le risque R3 du [registre](12-risques-et-kpi.md), coté 15. Un cabinet qui se trompe sur un
taux pénalise un client. Une plateforme qui se trompe sur un taux **pénalise tous ses clients le
même mois**, avec effet rétroactif sur toutes les périodes déjà closes. Le bulletin camerounais
combine CNPS plafonnée, charges patronales à taux variable selon le groupe de risque, CFC, FNE,
IRPP progressif, CAC, TDL et RAV : la surface d'erreur est large et elle bouge à chaque loi de
finances.

Aucune équipe produit ne doit porter seule cette responsabilité.

### 1.3 — Le cabinet est un canal d'acquisition, pas seulement une caution

C'est le point que le [business plan](03-business-plan.md) classe **premier par efficience**,
devant la vente terrain directe. Un cabinet apporte un portefeuille déjà qualifié, déjà formalisé,
et il apporte surtout sa recommandation — qui vaut, sur ce marché, plus que n'importe quelle
campagne.

---

## 2. Trois rôles à ne jamais confondre

L'erreur classique est de confier les trois au même cabinet. Ils sont incompatibles.

| Rôle | Mission | Rémunération | Incompatibilité |
|---|---|---|---|
| **A. Cabinet de référence produit** | Co-conception du module comptable, validation des barèmes de paie, recette des bulletins, veille réglementaire | Forfait de prestation | **Ne peut pas être le commissaire aux comptes de la plateforme** (auto-révision) |
| **B. Cabinets partenaires distributeurs** | Amènent leurs clients, révisent et attestent leurs états, utilisent l'espace de révision | Commission d'apport + honoraires de révision facturés au marchand | Ne participent pas à la conception : ils sont utilisateurs, pas concepteurs |
| **C. Commissaire aux comptes de la plateforme** | Certifie les comptes de la société d'exploitation | Honoraires de mandat | **Doit être indépendant de A et de B** |

**Un seul cabinet A. Beaucoup de cabinets B. Un cabinet C, distinct.** Cette séparation est à
inscrire noir sur blanc dans les conventions : un régulateur, un investisseur ou un auditeur la
vérifiera.

---

## 3. Choisir le cabinet de référence (rôle A)

### 3.1 — Critères éliminatoires

| Critère | Vérification |
|---|---|
| Inscrit au tableau de l'**ONECCA**, à jour de cotisation | Tableau de l'Ordre, attestation datée |
| **Assurance de responsabilité civile professionnelle** en cours de validité | Attestation d'assurance, montant de garantie |
| Portefeuille d'au moins **40 PME du commerce** de détail ou de gros | Déclaration sur l'honneur + 3 références appelables |
| Pratique effective de la **paie** pour au moins 15 clients | Références |
| **Aucun lien d'exclusivité avec un éditeur ou intégrateur concurrent** (Sage, Odoo, Dynamics) | Déclaration d'absence de conflit d'intérêts, contractuelle |
| Capacité à mobiliser **4 jours-homme par mois pendant 12 mois** | Engagement nominatif d'un associé et d'un collaborateur |
| Travail en **français et en anglais** | Cameroun bilingue |

### 3.2 — Critères de préférence

- Un associé ayant pratiqué le **contentieux fiscal** ou accompagné des contrôles DGI : il sait
  ce qu'un contrôleur regarde, et c'est exactement ce que le logiciel doit produire.
- Présence à Douala **et** Yaoundé.
- Antériorité sur la digitalisation (a déjà déployé un outil chez ses clients).
- Disposé à figurer publiquement comme partenaire — la caution n'a de valeur que si elle est
  visible.

### 3.3 — Processus de sélection (semaines 1 à 6 de la phase 0)

| Semaine | Étape |
|---|---|
| S1 | Liste longue : 12 cabinets, via l'ONECCA, le GICAM et les recommandations des marchands rencontrés en E1 |
| S2 | Qualification téléphonique sur les critères éliminatoires → liste courte de 5 |
| S3 | Rencontres approfondies : présentation du projet, discussion technique sur 3 cas concrets de paie |
| S4 | **Épreuve de mise en situation** (voir §3.4) |
| S5 | Négociation des deux meilleures propositions |
| S6 | Signature de la convention |

### 3.4 — L'épreuve de mise en situation

Ne pas sélectionner sur un discours. Soumettre aux 5 cabinets de la liste courte **trois cas réels
à traiter par écrit en une semaine**, rémunérés 150 000 FCFA chacun :

1. **Un bulletin de paie complet** pour un salarié à 300 000 F brut, secteur commerce, marié,
   2 enfants — avec le détail de chaque ligne, la base, le taux, la référence du texte applicable.
2. **Le schéma d'écritures** d'une vente en ligne encaissée par Mobile Money avec commission de
   plateforme retenue à la source, en précisant le rattachement comptable retenu pour la monnaie
   électronique et pourquoi.
3. **Une note de 2 pages** sur les mentions obligatoires d'une facture conforme à la DGI et sur les
   conséquences, pour une marketplace, du statut d'intermédiaire transparent.

**Ce que révèle l'épreuve :** la précision, la capacité à citer ses sources, l'honnêteté sur les
points incertains (« ce point mérite confirmation auprès de la DGI » est une bonne réponse, une
affirmation péremptoire est un signal d'alarme), et la qualité rédactionnelle — ce cabinet va
produire de la documentation que votre équipe devra transformer en code.

Les 750 000 FCFA de l'épreuve sont inclus dans la ligne « Conseil expertise comptable » du budget
de phase 0.

---

## 4. La frontière de responsabilité

C'est le cœur de la convention. À écrire avant de négocier le prix.

| Acte | Plateforme | Cabinet | Marchand |
|---|---|---|---|
| Enregistrer les opérations en temps réel | **Exécute** | — | Saisit ce qui n'est pas automatique |
| Générer les écritures automatiques | **Exécute** | Valide les schémas | — |
| Paramétrer le plan de comptes | **Exécute** | **Valide** | Approuve |
| Définir et versionner les barèmes de paie | Implémente | **Définit et valide** | — |
| Calculer les bulletins | **Exécute** | Contrôle par sondage | Fournit les éléments variables |
| Passer les écritures d'inventaire et de régularisation | Outille | **Exécute** | — |
| Réviser, attester, signer les états financiers | — | **Exécute seul** | — |
| Déposer les déclarations | Pré-remplit | Contrôle | **Dépose et assume** |
| Représenter en cas de contrôle | Fournit les justificatifs et l'historique | **Assiste** | **Assume** |

### 4.1 — Matrice de responsabilité en cas d'erreur

| Origine de l'erreur | Responsable | Mécanisme |
|---|---|---|
| Barème erroné, alors qu'il a été validé par le cabinet | **Cabinet**, en première ligne | RCP du cabinet ; garantie plateforme en second rang, plafonnée à 12 mois d'abonnement |
| Calcul non conforme au barème validé (défaut logiciel) | **Plateforme** | Correction sous 5 jours ouvrés, bulletins rectificatifs pris en charge, indemnisation plafonnée |
| Donnée saisie fausse par le marchand | **Marchand** | Exclusion de garantie contractuelle |
| Évolution réglementaire non répercutée dans le délai convenu | **Partagée** | Selon que le cabinet a alerté ou non dans le délai de veille |
| Interprétation divergente d'un texte ambigu | **Aucune des deux** | Procédure de rescrit ou consultation DGI, à frais partagés |

> **À exiger de votre propre côté :** une assurance responsabilité civile professionnelle pour la
> plateforme, couvrant explicitement l'édition de logiciel de paie et de comptabilité. Ce n'est
> pas une couverture standard ; elle se négocie et elle coûte.

---

## 5. Économie du partenariat

### 5.1 — Cabinet de référence (rôle A)

| Poste | Montant | Période |
|---|---|---|
| Épreuve de sélection (5 cabinets) | 750 000 F | Phase 0 |
| Cadrage initial : plan comptable, schémas d'écritures | 1 800 000 F | Lot 3, sur 4 mois |
| Validation et recette des barèmes de paie | 2 400 000 F | Lot 4, sur 4 mois |
| Veille et revue annuelle post-loi de finances | 900 000 F / an | Récurrent |
| Astreinte de conseil (2 j-h/mois) | 600 000 F / an | Récurrent |
| **Total sur 24 mois** | **≈ 8,7 M FCFA** | |

Ce montant est déjà couvert par la ligne « Juridique, conformité, OAPI, cabinet » du budget du
[document 11](11-roadmap-budget-equipe.md).

### 5.2 — Cabinets distributeurs (rôle B)

| Flux | Montant |
|---|---|
| Commission d'apport | **20 % du loyer encaissé la première année** de chaque boutique apportée |
| Honoraires de révision annuelle | 150 000 F / boutique / an, facturés au marchand |
| Partage de ces honoraires | 70 % cabinet · 30 % plateforme |
| Accès à l'espace de révision | Gratuit, illimité |
| Formation et certification du cabinet | Gratuite, 2 jours |

**Le calcul du cabinet :** un cabinet qui bascule 50 clients encaisse 50 × 45 000 × 12 × 20 % =
5,4 M FCFA de commission la première année, plus 50 × 150 000 × 70 % = 5,25 M d'honoraires de
révision — et il gagne surtout un temps considérable sur la tenue, qui devient automatique.

**Le calcul de la plateforme :** 50 boutiques acquises pour 5,4 M, soit **108 000 F de CAC**,
contre 520 000 F en vente terrain. C'est ce rapport de 1 à 5 qui justifie de traiter ce canal en
priorité.

### 5.3 — Le piège à éviter

Un cabinet qui apporte 200 clients devient un point de dépendance : s'il part, il peut les
reprendre. Deux contre-mesures contractuelles : **pas d'exclusivité territoriale ni sectorielle**,
et **relation contractuelle directe entre la plateforme et chaque marchand**, jamais par
l'intermédiaire du cabinet. Plafond de vigilance : alerte au-delà de **15 % des boutiques
provenant d'un même cabinet**.

---

## 6. Contenu de la convention (rôle A)

| # | Clause | Point d'attention |
|---|---|---|
| 1 | Objet et périmètre : conception, validation, veille | Distinguer explicitement de toute mission d'attestation |
| 2 | Livrables et délais | Schémas d'écritures, barèmes versionnés, jeu de bulletins de recette |
| 3 | **Engagement nominatif** d'un associé et d'un collaborateur | Nommer les personnes, pas seulement le cabinet |
| 4 | Niveau de service : délai de réponse aux questions bloquantes | 48 h ouvrées sur un point bloquant, 5 jours sinon |
| 5 | **Veille réglementaire** : délai de notification d'un changement | 15 jours après publication de la loi de finances |
| 6 | Matrice de responsabilité | Reprendre le §4.1 en annexe contractuelle |
| 7 | Assurance RCP : montant, attestation annuelle | Vérifier que l'édition logicielle n'est pas exclue |
| 8 | **Propriété intellectuelle du paramétrage** | Les barèmes, schémas et jeux de test appartiennent à la plateforme, y compris après la fin de la convention. **Clause critique** — sans elle, un départ du cabinet gèle le produit |
| 9 | Confidentialité et protection des données | Le cabinet accède à des données de marchands : loi 2024/017 applicable, sous-traitance à encadrer |
| 10 | Absence de conflit d'intérêts | Déclaration, et obligation d'information en cas de changement |
| 11 | Non-concurrence limitée | Ne pas co-développer un produit concurrent pendant la convention + 12 mois |
| 12 | Réversibilité | Transmission documentée de tout le paramétrage, en 30 jours |
| 13 | Durée, renouvellement, résiliation | 24 mois, préavis 3 mois |
| 14 | Communication publique | Autorisation d'usage du nom, validation des mentions |
| 15 | Règlement des différends | Conciliation préalable, puis juridiction de Douala |

---

## 7. Le protocole de validation des barèmes de paie

C'est le contenu concret de l'arbitrage A6. **Le module paie n'ouvre pas tant que ce protocole
n'est pas passé.**

### 7.1 — Le jeu de 50 bulletins de référence

Chaque cas est calculé **à la main par le cabinet**, signé, et devient un test automatisé de
non-régression dans l'intégration continue. Un bulletin de mars 2027 recalculé en 2029 doit
produire exactement le même résultat.

| Famille | Cas à couvrir | Nb |
|---|---|---:|
| **Plafonnement CNPS** | SMIG exact (60 000) · salaire sous plafond · salaire au plafond exact (750 000) · salaire au-dessus (1 200 000) | 4 |
| **Tranches IRPP** | Un cas dans chaque tranche (10 / 15 / 25 / 35 %) + deux cas à la frontière exacte entre deux tranches | 6 |
| **Barèmes forfaitaires** | TDL et RAV : un cas dans chaque tranche du barème et un cas à chaque frontière | 8 |
| **Groupes de risque AT** | Taux 1,75 % · taux intermédiaire · taux 5 % | 3 |
| **Mois incomplets** | Embauche en cours de mois · départ en cours de mois · absence non rémunérée | 3 |
| **Éléments variables** | Heures supplémentaires avec majorations · prime exceptionnelle · prime de transport (limite d'exonération) · commission sur ventes | 4 |
| **Avantages en nature** | Logement · véhicule · cumul des deux | 3 |
| **Situations familiales** | 0 enfant · 2 enfants · 5 enfants · célibataire vs marié | 4 |
| **Absences protégées** | Congés payés · maladie · maternité | 3 |
| **Types de contrat** | Apprenti · CDD à échéance · rupture de période d'essai · temps partiel | 4 |
| **Fin de contrat** | Solde de tout compte · indemnité de licenciement · indemnité de congés non pris | 3 |
| **Cas particuliers** | Avance sur salaire · rappel sur mois antérieur · bulletin rectificatif · salarié expatrié · salarié multi-employeurs | 5 |
| **Total** | | **50** |

### 7.2 — Procédure de recette

1. Le cabinet produit les 50 bulletins de référence, **signés**, avec pour chaque ligne : la base,
   le taux, le montant, et la **référence du texte applicable**.
2. L'équipe implémente le moteur sans voir les résultats attendus au-delà de 10 cas d'amorce.
3. Exécution comparée sur les 50 cas. **Tolérance : zéro écart au franc près.**
4. Écarts analysés un par un : soit le logiciel a tort, soit le bulletin de référence a tort. Le
   second cas arrive, et il est précieux.
5. Le cabinet signe un **procès-verbal de recette** nominatif.
6. Les 50 cas entrent en intégration continue. Toute modification du moteur les rejoue.

### 7.3 — Ouverture progressive

Même après recette, ne pas ouvrir à tous :

| Étape | Périmètre | Contrôle |
|---|---|---|
| Palier 1 | 3 boutiques, 15 salariés | **Double calcul systématique** : le cabinet recalcule 100 % des bulletins pendant 3 mois |
| Palier 2 | 15 boutiques | Contrôle par sondage sur 25 % des bulletins |
| Palier 3 | Ouverture générale | Sondage mensuel sur 5 %, alerte automatique sur variation anormale |

### 7.4 — Revue annuelle

Déclenchée par la publication de la loi de finances, en décembre-janvier :

1. Le cabinet notifie les changements dans les **15 jours** suivant la publication (clause 5).
2. Nouveaux barèmes versionnés avec date d'entrée en vigueur — **jamais d'écrasement** : recalculer
   un bulletin antérieur doit rester possible.
3. Jeu de 50 cas rejoué sur les nouveaux barèmes, écarts documentés et justifiés.
4. Nouveau procès-verbal de recette.
5. Communication aux clients **avant** la première paie concernée.

---

## 8. Répartition des points à valider du document 08

Les 11 points marqués `[À VALIDER]` dans le [document 08](08-conformite-juridique-et-fiscale.md)
n'ont pas tous le même interlocuteur. Les confier tous au cabinet comptable est une erreur : il
n'est compétent ni sur les données personnelles, ni sur la réglementation des paiements.

| # | Point | Interlocuteur | Échéance |
|---|---|---|---|
| J1 | Statut d'intermédiaire transparent, assiette de TVA | Conseil fiscal + cabinet A | Avant lot 1 |
| J2 | Mentions obligatoires de facturation | Cabinet A (traité dans l'épreuve de sélection) | Avant lot 1 |
| J3 | Régime du compte de cantonnement et du séquestre | **Conseil bancaire / réglementation BEAC** | Avant lot 1 |
| J4 | Transfert de données hors Cameroun | **Conseil en protection des données** | Avant lot 1 — **conditionne ADR-008** |
| J5 | Délai de notification de violation de données | Conseil en protection des données | Avant lot 1 |
| J6 | Qualification du programme d'affiliation | **Avocat, droit de la consommation** | Avant lot 1 |
| J7 | Seuils de déclaration LBC/FT (ANIF) | Conseil conformité | Avant lot 2 |
| J8 | Rattachement comptable de la monnaie électronique | Cabinet A (traité dans l'épreuve) | Avant lot 3 |
| J9 | Table des groupes de risque accidents du travail | Cabinet A + CNPS | Avant lot 4 |
| J10 | Barèmes TDL et RAV en vigueur | Cabinet A | Avant lot 4 |
| J11 | Convention de partenariat | Direction + avocat | **Phase 0** |

**Quatre interlocuteurs distincts, pas un.** Budgéter en conséquence : le cabinet comptable couvre
J1, J2, J8, J9, J10 ; il faut en plus un conseil fiscal, un conseil en protection des données et un
avocat d'affaires.

---

## 9. Calendrier consolidé

```
Phase 0        Lot 1-2                  Lot 3                    Lot 4
S1──S6         M3────────M17            M18───────M30            M31──────M46
│              │                        │                        │
├ sélection    ├ J1,J2,J4,J5,J6 tranchés├ cadrage comptable      ├ barèmes de paie
├ épreuve      │                        ├ recette balance        ├ recette 50 bulletins
├ convention   │                        │   sur 3 boutiques      ├ paliers 1→3
└ signature ✓  │                        └ jalon G5 ✓             └ ouverture ✓
                                                                  puis revue annuelle
```

---

## 10. Ce qui se passe si la condition n'est pas remplie

Réponse préparée à l'avance, pour ne pas improviser sous pression de calendrier.

| Situation | Décision |
|---|---|
| Aucun cabinet ne passe l'épreuve de sélection | Élargir à Yaoundé et Kribi, et envisager un cabinet régional OHADA (Libreville, Abidjan) avec un correspondant local. Ne pas baisser les critères. |
| Le cabinet refuse d'engager sa responsabilité sur le paramétrage | **Éliminatoire.** Un cabinet qui valide sans engager sa RCP n'apporte aucune garantie, seulement une caution de façade. |
| Le coût demandé dépasse largement 8,7 M sur 24 mois | Renégocier le périmètre : cadrage comptable d'abord, paie reportée. Le lot 4 glisse, le lot 3 non. |
| Signature impossible avant le lot 3 | **Le lot 3 ne démarre pas.** Redéployer l'équipe sur le lot 2 (logistique, WhatsApp, B2B), qui n'a pas de dépendance réglementaire. Le calendrier glisse, le risque ne se prend pas. |
| Rupture du partenariat en cours de route | La clause 8 (propriété du paramétrage) et la clause 12 (réversibilité) permettent de reprendre avec un autre cabinet sans repartir de zéro. **C'est précisément à ça qu'elles servent.** |

> **La règle à ne pas contourner :** aucun bulletin de paie n'est émis pour un client réel sans
> procès-verbal de recette signé. Aucun état financier n'est présenté comme définitif sans révision
> d'un professionnel agréé. Ces deux phrases valent mieux qu'un chapitre de bonnes intentions.
