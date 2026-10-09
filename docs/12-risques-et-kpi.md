# 12 — Registre des risques et tableau de bord de pilotage

---

## 1. Cotation

**Criticité = Probabilité × Impact**, chacun noté de 1 à 5.
Seuils : `≥ 16` critique · `9-15` élevé · `4-8` moyen · `≤ 3` faible.

---

## 2. Risques stratégiques

| # | Risque | P | I | C | Signal d'alerte | Réponse |
|---|---|---:|---:|---:|---|---|
| S1 | **Le back-office n'est pas adopté** : les marchands n'utilisent que la vitrine, le produit perd son avantage *(H2)* | 3 | 5 | **15** | < 60 % des pilotes avec 20 opérations de caisse/semaine à M9 | Jalon G2. Simplification radicale de la caisse, accompagnement terrain, ou repli assumé sur un modèle marketplace |
| S2 | **La cible refuse la traçabilité** : formaliser ventes, marges et salaires est perçu comme un risque fiscal, pas comme un service | 3 | 5 | **15** | Objection récurrente en entretien ; refus de connecter la caisse | Test dédié en phase 0 *(A10)*. Positionner la confidentialité comme argument produit ; granularité du partage avec le cabinet |
| S3 | **Bolamba casse les prix** avec un soutien public et une logistique subventionnée | 3 | 4 | **12** | Annonce de commission à 0 %, campagne institutionnelle | Arbitrage A4 : rechercher un partenariat logistique. Différenciation par le back-office, que Bolamba n'aura pas |
| S4 | **Dispersion de l'exécution** : deux métiers (marketplace + ERP) menés simultanément à 14 personnes | 4 | 4 | **16** ⚠️ | Retards cumulés > 4 semaines sur 2 lots consécutifs | Arbitrage A2 : périmètre resserré. Découpage en lots à critère de sortie unique et mesurable |
| S5 | **Le take rate de 5 % est intenable** sur les rayons à faible marge | 3 | 3 | 9 | Négociations systématiques à la baisse, churn concentré sur certains rayons | Arbitrage A8 : privilégier les rayons à marge > 30 %. Barème par rayon déjà prévu |
| S6 | Un concurrent bien financé copie le positionnement | 2 | 4 | 8 | Levée annoncée sur un acteur local | Avance sur la donnée comptable, réseau de revendeurs, partenariats cabinets |

---

## 3. Risques opérationnels

| # | Risque | P | I | C | Signal d'alerte | Réponse |
|---|---|---:|---:|---:|---|---|
| O1 | **Économie du dernier kilomètre négative** *(H3)* | 4 | 5 | **20** ⚠️⚠️ | Coût moyen par livraison > 2 500 F ou annulations > 25 % | Jalon G3, arbitrage A7 : plafond de 200 boutiques. Rayons à forte valeur au kilo, points relais, conversion vers le prépaiement |
| O2 | **Taux d'annulation du paiement à la livraison** de 15 à 30 % | 4 | 4 | **16** ⚠️ | Suivi hebdomadaire par transporteur et par zone | Séquestre incitatif : remise sur les frais de livraison en cas de prépaiement, remboursement garanti en 24 h |
| O3 | **Dépendance à un opérateur Mobile Money** | 3 | 5 | **15** | Hausse unilatérale de commission, panne prolongée | Abstraction multi-PSP dès le lot 1, bascule automatique, intégration de Camtel comme 3ᵉ voie |
| O4 | Rupture du service Mobile Money pendant plusieurs heures | 4 | 3 | 12 | Supervision temps réel des taux de succès | Bascule automatique, file d'attente de paiements, repli sur paiement à la livraison |
| O5 | Recrutement d'un expert-comptable produit impossible | 3 | 4 | 12 | Recherche infructueuse > 3 mois | Contrat de prestation avec un cabinet en attendant ; lot 3 décalé, pas dégradé |
| O6 | Fraude à l'affiliation | 4 | 3 | 12 | Taux de fraude détectée > 4 % des gains | Dispositif du document 06, §6 : quarantaine, plafonds, KYC renforcé |
| O7 | Vol ou détournement de stock en entrepôt mutualisé | 3 | 3 | 9 | Écarts d'inventaire répétés | Inventaires tournants, séparation des rôles, assurance |

---

## 4. Risques techniques

| # | Risque | P | I | C | Signal d'alerte | Réponse |
|---|---|---:|---:|---:|---|---|
| T1 | **Fuite de données entre boutiques** | 2 | 5 | **10** | Anomalie en test d'isolation, signalement client | Trois barrières (document 09, §3.2), tests bloquants en CI, `RLS` PostgreSQL |
| T2 | **Double débit Mobile Money** | 3 | 5 | **15** | Réclamation client, écart de rapprochement | Clé d'idempotence unique obligatoire, réconciliation nocturne, procédure de remboursement automatique |
| T3 | Corruption des données comptables | 2 | 5 | 10 | Balance déséquilibrée détectée par la tâche nocturne | Journal en ajout seul, triggers PostgreSQL, contrainte d'équilibre, sauvegardes restaurées mensuellement |
| T4 | Perte de données de caisse hors ligne | 3 | 4 | 12 | Écart entre tickets locaux et serveur | Journal d'opérations idempotent, persistance locale, alerte de synchronisation > 24 h |
| T5 | Sur-ingénierie : moteur générique là où un cas simple suffit | 4 | 3 | 12 | Dérive du planning sans valeur livrée | Revue d'architecture par lot, principe « coder le cas camerounais, généraliser au Gabon » |
| T6 | Dette de performance sur les grandes boutiques | 3 | 3 | 9 | Temps de réponse > 2,5 s, requêtes > 25/page | Agrégats matérialisés, partitionnement prévu dès la conception |

---

## 5. Risques réglementaires et financiers

| # | Risque | P | I | C | Signal d'alerte | Réponse |
|---|---|---:|---:|---:|---|---|
| R1 | **Non-conformité à la loi 2024/017** (applicable au 23/06/2026) | 3 | 5 | **15** | Points J4/J5 du document 08 non tranchés à M0 | Registre des consentements natif, registre des traitements, conseil dédié avant le lot 1 |
| R2 | **Requalification du programme d'affiliation en vente pyramidale** | 2 | 5 | **10** | Communication interne dérivant vers le recrutement | Six garde-fous codés en dur, revue juridique à chaque évolution *(A11)* |
| R3 | **Erreur de barème de paie propagée à tous les clients** | 3 | 5 | **15** | Écart avec un bulletin de contrôle du cabinet | Barèmes versionnés, 50 bulletins de non-régression, revue annuelle après loi de finances *(A6)* |
| R4 | Requalification en établissement de paiement | 2 | 5 | 10 | Interpellation du régulateur | Intermédiaire technique strict, compte de cantonnement, portefeuille = compte de suivi *(document 08, §5)* |
| R5 | Instabilité fiscale (loi de finances annuelle) | 4 | 3 | 12 | Projet de loi de finances | Veille systématique en T4, provision pour adaptation |
| R6 | **Consommation de fonds propres par le livre de crédit** | 3 | 5 | **15** | Toute avance financée sans partenaire | Arbitrage A3 : interdiction formelle. Jalon G6 bloquant |
| R7 | Défaut sur les avances de trésorerie | 3 | 4 | 12 | Taux d'impayés > 6 % | Prélèvement à la source sur les encaissements, plafonds progressifs, scoring sur données réelles |
| R8 | Échec de la levée seed | 3 | 5 | **15** | Jalon G4 non atteint | Trésorerie de sécurité de 6 mois, plan de réduction préparé à l'avance |

---

## 6. Les cinq risques à surveiller en comité mensuel

Extraits du registre par criticité :

1. **O1 — Économie du dernier kilomètre** (20)
2. **S4 — Dispersion de l'exécution** (16)
3. **O2 — Annulations du paiement à la livraison** (16)
4. **S1 / S2 — Adoption et acceptation de la traçabilité** (15 chacun)
5. **R3 / R6 / T2 — Barèmes de paie, fonds propres, double débit** (15 chacun)

---

## 7. Tableau de bord de pilotage

### 7.1 — Indicateurs de direction (revue mensuelle)

| Indicateur | Définition | Cible A1 | Cible A3 | Cible A5 |
|---|---|---:|---:|---:|
| Boutiques payantes | Bail actif et loyer encaissé | 150 | 1 400 | 3 500 |
| GMV traité | Montant TTC des commandes livrées non retournées | 0,9 Md F | 13 Md F | 48 Md F |
| Chiffre d'affaires plateforme | Toutes lignes de revenus | 78 M F | 1 452 M F | 5 565 M F |
| Take rate effectif | CA plateforme / GMV | 8,7 % | 11,2 % | 11,6 % |
| Marge brute | Après coûts directs | 69 % | 73 % | 73 % |
| EBITDA | | -163 M F | -20 M F | +1 717 M F |
| Trésorerie disponible | En mois de charges | > 12 | > 9 | > 12 |

### 7.2 — Santé du produit (revue hebdomadaire)

| Indicateur | Pourquoi il compte | Cible |
|---|---|---|
| **Boutiques avec ≥ 20 opérations de caisse/semaine** | **L'indicateur n° 1 : mesure l'adoption réelle du back-office (H2)** | > 60 % |
| Boutiques tenant leur stock à jour (< 7 j d'écart) | Prédit la fiabilité comptable et l'octroi de crédit | > 55 % |
| Délai médian d'onboarding | Frein d'acquisition principal | < 5 jours |
| Utilisation hors ligne | Valide la contrainte architecturale | > 30 % des tickets |
| Temps de saisie d'une ligne de caisse | Critère de conception imposé | < 4 s |

### 7.3 — Croissance et rétention (revue mensuelle)

| Indicateur | Cible A1 | Cible A3 | Cible A5 |
|---|---:|---:|---:|
| Churn marchand annuel brut | 32 % | 24 % | 18 % |
| Rétention nette du revenu | 85 % | 105 % | 118 % |
| CAC chargé | 700 k F | 560 k F | 480 k F |
| LTV / CAC | 3,0 | 6,0 | 8,8 |
| Retour sur CAC | 14 mois | 9 mois | 7 mois |
| Part du GMV attribuée à l'affiliation | 15 % | 30 % | 35 % |
| Coût d'acquisition acheteur (affiliation) | 1 200 F | 900 F | 750 F |

### 7.4 — Opérations (revue hebdomadaire)

| Indicateur | Cible |
|---|---|
| Taux de livraison réussie à la 1ʳᵉ tentative | > 75 % |
| Coût moyen par livraison | < 1 800 F |
| Taux d'annulation des commandes payées à la livraison | < 15 % |
| Part du GMV prépayée (séquestre) | > 65 % en A3 |
| Délai médian de livraison Douala / Yaoundé | < 48 h |
| Litiges ouverts pour 1 000 commandes | < 12 |
| Délai médian de résolution d'un litige | < 72 h |

### 7.5 — Conformité et risque (revue mensuelle)

| Indicateur | Cible |
|---|---|
| Écarts de rapprochement PSP non résolus | 0 à J+2 |
| Balances déséquilibrées détectées | 0 |
| Fraude à l'affiliation détectée / gains totaux | < 2,5 % |
| Bulletins de paie en écart avec le contrôle cabinet | 0 |
| Demandes d'accès ou d'effacement traitées dans les délais | 100 % |
| Incidents d'isolation multi-tenant | **0 — tolérance zéro** |
| Sauvegardes restaurées avec succès | 1/mois minimum |

---

## 8. Rituels de pilotage

| Rituel | Fréquence | Participants | Sortie |
|---|---|---|---|
| Revue opérationnelle | Hebdomadaire | Direction, produit, opérations | Indicateurs §7.2 et §7.4, décisions immédiates |
| Comité produit | Bimensuel | Produit, ingénierie, référents métier | Arbitrages de périmètre, résultats de recherche utilisateur |
| Comité des risques | Mensuel | Direction, conformité, technique | Les cinq risques du §6, plans d'action |
| Comité de direction | Mensuel | Direction, investisseurs | Indicateurs §7.1, trésorerie, jalons |
| Revue de jalon | Par lot | Tous | Décision de passage G0 à G6 *(document 11, §11)* |
| Revue réglementaire | Trimestrielle + après chaque loi de finances | Conformité, cabinet, technique | Mise à jour des barèmes et des taux |
