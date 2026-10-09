# 05 — Périmètre fonctionnel

Ce document décrit **ce que fait le produit**. Il applique les arbitrages du
[conseil d'experts](04-conseil-llm.md) — notamment A1 (stock et caisse au lot 1, comptabilité au
lot 3) et A2 (périmètre d'amorçage resserré).

Priorisation **MoSCoW** : `M` indispensable au lot · `S` souhaité · `C` confort · `W` hors périmètre.

---

## 1. Les acteurs

| Acteur | Description | Portée d'accès |
|---|---|---|
| **Visiteur** | Non authentifié | Catalogue public, recherche |
| **Acheteur** | Client final | Ses commandes, son compte, ses adresses |
| **Gérant de boutique** | Locataire de l'emplacement | Tout sa boutique |
| **Employé de boutique** | Vendeur, caissier, magasinier, comptable | Selon rôle, dans sa boutique uniquement |
| **Revendeur** | Vend le catalogue sans porter de stock | Son catalogue autorisé, ses commissions |
| **Apporteur / affilié** | Recrute marchands, revendeurs ou acheteurs | Son arbre de filiation, ses gains |
| **Responsable de rayon** | Category manager plateforme | Son rayon, toutes boutiques |
| **Gestionnaire du marché** | Exploitant de la plateforme | Global |
| **Comptable partenaire** | Cabinet agréé externe | Les boutiques qui lui sont rattachées, en lecture + révision |
| **Livreur / transporteur** | Partenaire logistique | Ses tournées |

---

## 2. Cartographie des modules

```
┌──────────────────────── GESTION DU MARCHÉ (plateforme) ─────────────────────────┐
│  M13 Administration du marché · M14 Retail media · Rayons · Règles · Litiges    │
└─────────────────────────────────────────────────────────────────────────────────┘
        ▲                                                            ▲
┌───────┴──────────── FRONT DE VENTE ─────────┐   ┌──────────────────┴────────────┐
│ M03 Catalogue · M04 Vente & commandes       │   │ M11 Affiliation & revendeurs  │
│ M05 Paiement & escrow · M06 Logistique      │   │ M12 Marketing & fidélité      │
└─────────────────────────────────────────────┘   └───────────────────────────────┘
        ▲
┌───────┴────────────── BACK-OFFICE BOUTIQUE ────────────────────────────────────┐
│ M07 Stock & achats · M08 Caisse (POS) · M09 Comptabilité · M10 RH & paie       │
└────────────────────────────────────────────────────────────────────────────────┘
        ▲
┌───────┴────────────── SOCLE ───────────────────────────────────────────────────┐
│ M01 Identité, rôles, multi-tenant · M02 Emplacements & baux                    │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Modules en détail

### M01 — Identité, rôles et multi-tenant `Lot 0`

Fondation de l'isolation des données. Toute donnée métier appartient à une boutique ; aucun accès
transversal n'est possible sans un rôle plateforme explicite.

| Fonctionnalité | Prio | Note |
|---|---|---|
| Compte utilisateur par téléphone (identifiant principal) + e-mail optionnel | M | Le numéro est l'identité au Cameroun, pas l'e-mail |
| Authentification par mot de passe + OTP SMS | M | |
| Appartenance multi-boutiques (un utilisateur peut travailler dans 2 boutiques) | M | |
| Rôles et permissions granulaires par boutique | M | Gérant, vendeur, caissier, magasinier, comptable, RH |
| Journal d'audit horodaté et inaltérable | M | Exigence comptable et preuve en cas de litige |
| Double authentification pour les rôles sensibles | S | |
| Fédération d'identité (Google, Apple) | C | |

### M02 — Emplacements et baux `Lot 1`

Le cœur de la métaphore : on loue un emplacement, pas un abonnement.

| Fonctionnalité | Prio | Note |
|---|---|---|
| Catalogue des types d'emplacement (Étal, Boutique, Grande surface) | M | |
| Candidature marchand avec pièces (RCCM, NIU, CNI du gérant) | M | Vérification KYC obligatoire |
| Contrat de bail : durée, loyer, dépôt de garantie, préavis, commission applicable | M | |
| Facturation automatique du loyer, relances, suspension pour impayé | M | Suspension = vitrine masquée, back-office accessible |
| État des lieux d'entrée (audit d'onboarding : stock initial, comptes de départ) | M | |
| Résiliation : préavis, restitution du dépôt, **export intégral des données du marchand** | M | Obligation légale et argument de confiance |
| Emplacements premium (tête de gondole, bandeau de rayon) réservables | S | Recette du retail media |
| Renouvellement automatique et révision annuelle du loyer | S | |
| Multi-emplacements pour une même entreprise | C | |

### M03 — Catalogue produits `Lot 1`

| Fonctionnalité | Prio | Note |
|---|---|---|
| Produits, variantes (taille, couleur), unités de mesure, SKU, code-barres | M | |
| Rayons et catégories plateforme, hiérarchiques | M | Le rayon détermine la commission |
| Prix de vente, prix barré, prix d'achat (privé), régime de TVA par produit | M | |
| Médias produits avec compression agressive | M | Contrainte de bande passante |
| Import/export CSV et Excel | M | Indispensable pour l'onboarding d'un stock existant |
| Catalogue partagé (référentiel plateforme mutualisé par code-barres) | S | Évite que 40 boutiques ressaisissent le même produit |
| Modération et standards qualité par rayon | S | |
| Tarifs B2B par client ou groupe de clients | S | Segment grossiste |
| Fiches produit multilingues (français, anglais) | C | Cameroun bilingue |

### M04 — Vente et commandes `Lot 1`

| Fonctionnalité | Prio | Note |
|---|---|---|
| Panier multi-boutiques, éclaté en sous-commandes par boutique | M | Une commande client, N commandes marchand |
| Cycle de vie : brouillon → confirmée → préparée → expédiée → livrée → clôturée | M | |
| Annulation, retour, remboursement partiel | M | |
| Devis et bons de commande B2B | S | |
| Prise de commande par WhatsApp | S | Canal réel du marché |
| Prise de commande USSD | C | Acheteurs sans smartphone |
| Abonnements et commandes récurrentes | W | |

### M05 — Paiement et séquestre `Lot 1`

| Fonctionnalité | Prio | Note |
|---|---|---|
| Abstraction multi-PSP (MTN MoMo, Orange Money, Camtel) derrière une interface unique | M | **Aucune dépendance à un opérateur unique** (Porter : pouvoir des fournisseurs) |
| Paiement à la livraison avec encaissement par le livreur | M | Réalité du marché |
| Séquestre : fonds bloqués jusqu'à confirmation de livraison | M | Levier de conversion majeur |
| Portefeuille marchand : solde, retrait vers Mobile Money, historique | M | |
| Réconciliation automatique des paiements et rapprochement PSP | M | |
| Carte bancaire (Visa/Mastercard) | S | Faible usage local, utile pour la diaspora |
| Paiement fractionné acheteur | W | |

### M06 — Logistique et livraison `Lot 2`

| Fonctionnalité | Prio | Note |
|---|---|---|
| Adresse = point GPS + repère textuel + contact téléphonique | M | L'adressage postal n'existe pas |
| Zones de livraison et grille tarifaire par zone et par poids | M | |
| Affectation aux transporteurs partenaires, suivi de statut | M | |
| Preuve de livraison (code OTP remis par l'acheteur au livreur) | M | Déclenche la libération du séquestre |
| Gestion des retours et de la logistique inverse | M | |
| Entrepôt mutualisé : réception, emplacement, préparation, expédition | S | Lot 4 — décision capitalistique |
| Consolidation multi-boutiques en un colis unique | S | Nécessite l'entrepôt |
| Retrait en point relais | S | Alternative économique à la livraison |
| Optimisation de tournées | C | |

### M07 — Stock et achats `Lot 1` ★ brique critique

> Arbitrage A1 et §9 du document 04 : **c'est la brique qui, seule, doit tenir debout.**

| Fonctionnalité | Prio | Note |
|---|---|---|
| Dépôts multiples (boutique, réserve, entrepôt plateforme) | M | |
| Mouvements de stock : entrée, sortie, transfert, ajustement, perte, casse | M | Journal en ajout seul |
| Valorisation en **coût moyen pondéré (CMP)** | M | Méthode SYSCOHADA la plus courante ; FIFO en option |
| Seuils d'alerte et suggestions de réapprovisionnement | M | Douleur n° 1 du persona |
| Inventaire physique avec écarts et régularisation tracée | M | |
| Fonctionnement **hors ligne** avec synchronisation différée | M | Contrainte architecturale (A12) |
| Commandes fournisseurs, réception partielle, bons de livraison | S | |
| Lots, numéros de série, dates de péremption | S | Requis pour parapharmacie et alimentaire |
| Nomenclatures et articles composés | C | |
| Prévision de demande | W | |

### M08 — Caisse / point de vente `Lot 1` ★ brique critique

| Fonctionnalité | Prio | Note |
|---|---|---|
| Interface tactile Android, saisie d'une ligne en **moins de 4 secondes** | M | Critère de conception imposé (document 04, §3) |
| Scan de code-barres via l'appareil photo | M | |
| Encaissement espèces, Mobile Money, mixte | M | |
| Ouverture/fermeture de caisse, comptage, écart de caisse | M | |
| Ticket imprimé (imprimante Bluetooth) ou envoyé par SMS/WhatsApp | M | |
| **Fonctionnement hors ligne intégral**, file d'opérations rejouable | M | |
| Remises, avoirs, retours comptoir | M | |
| Facture normalisée conforme aux mentions DGI (NIU, RCCM, TVA) | M | Voir document 08 |
| Multi-caisses et multi-caissiers | S | |
| Fidélité client au comptoir | C | |

### M09 — Comptabilité SYSCOHADA `Lot 3`

Détail complet dans le [document 07](07-comptabilite-paie-syscohada.md).

| Fonctionnalité | Prio | Note |
|---|---|---|
| Plan comptable SYSCOHADA révisé, personnalisable par boutique | M | |
| Journal en **partie double, en ajout seul**, correction par contre-passation uniquement | M | Exigence OHADA (A12) |
| Écritures générées automatiquement depuis les ventes, achats, stock, caisse, paie | M | **Zéro double saisie : c'est la promesse du produit** |
| Journaux (ventes, achats, banque, caisse, opérations diverses, paie) | M | |
| Grand livre, balance générale et auxiliaire, brouillard | M | |
| Lettrage clients et fournisseurs, suivi des encours | M | |
| Déclaration de TVA (collectée, déductible, à payer) au taux de 19,25 % | M | |
| Rapprochement bancaire et Mobile Money | M | |
| Exercices, clôture, à-nouveaux | M | |
| États financiers SYSCOHADA (bilan, compte de résultat, TFT, notes annexes) | S | Sortie révisée par un cabinet (arbitrage A5) |
| Espace de révision pour le comptable partenaire | S | |
| Comptabilité analytique par point de vente ou par rayon | C | |
| Consolidation multi-sociétés | W | |

### M10 — Ressources humaines et paie `Lot 4`

Ouverture conditionnée à l'arbitrage A6 (partenariat cabinet agréé signé).

| Fonctionnalité | Prio | Note |
|---|---|---|
| Dossier salarié : identité, contrat, CNPS, poste, rémunération | M | |
| Types de contrat (CDI, CDD, essai, apprentissage) et échéances | M | |
| Pointage, présences, absences, congés payés | M | |
| Moteur de paie **versionné par période d'application** | M | Barèmes horodatés, jamais écrasés |
| Bulletin de paie conforme : CNPS, CFC, FNE, IRPP, CAC, TDL, RAV | M | Voir document 07 |
| Livre de paie, états de cotisations, déclarations CNPS et DIPE | M | |
| Écritures de paie déversées automatiquement en comptabilité | M | |
| Versement des salaires par Mobile Money en lot | S | Argument différenciant fort |
| Avances sur salaire et acomptes | S | |
| Soldes de tout compte, indemnités de licenciement | S | |
| Évaluation et gestion des compétences | W | |

### M11 — Affiliation, marketing et revendeurs `Lot 1 (socle)` / `Lot 5 (complet)`

Détail dans le [document 06](06-affiliation-marketing-revendeurs.md).

| Fonctionnalité | Prio | Lot |
|---|---|---|
| Compte affilié, lien de parrainage, code personnel, QR code | M | 1 |
| Attribution des ventes (cookie 30 j + code + dernier clic non direct) | M | 1 |
| Arbre de filiation à **2 niveaux maximum** | M | 1 |
| Moteur de commissions avec plafond à 35 % de la commission plateforme | M | 1 |
| Portefeuille affilié, seuil de retrait, paiement Mobile Money | M | 1 |
| Détection de fraude (auto-parrainage, comptes multiples, annulations anormales) | M | 1 |
| Compte revendeur : catalogue autorisé, marge, prise de commande pour un tiers | S | 5 |
| Vitrine personnalisée du revendeur (mini-boutique sans stock) | S | 5 |
| Campagnes marketing plateforme, codes promo, coupons | S | 5 |
| Programme de fidélité acheteur | C | 5 |

### M12 — Espace acheteur `Lot 1`

| Fonctionnalité | Prio |
|---|---|
| Recherche, filtres, navigation par rayon | M |
| Fiche produit, avis et notes | M |
| Suivi de commande, historique, factures | M |
| Carnet d'adresses avec points GPS | M |
| Litiges et demandes de remboursement | M |
| Listes d'envies, alertes de prix | C |

### M13 — Administration du marché `Lot 1`

| Fonctionnalité | Prio | Note |
|---|---|---|
| Tableau de bord global : GMV, boutiques actives, commissions, impayés | M | |
| Gestion des rayons, des grilles de commission, des règles d'assortiment | M | |
| Validation des candidatures marchands, contrôle KYC | M | |
| Arbitrage des litiges acheteur/marchand | M | |
| Facturation plateforme : loyers, commissions, services, relevés marchands | M | |
| Suspension, sanction, résiliation de bail | M | |
| Console de supervision technique et de qualité de service | S | |

### M14 — Retail media `Lot 5`

| Fonctionnalité | Prio |
|---|---|
| Inventaire d'emplacements publicitaires (recherche, rayon, accueil) | M |
| Campagnes marchand : budget, ciblage, période | M |
| Facturation au clic ou au forfait, rapport de performance | M |
| Enchères en temps réel | C |

---

## 4. Répartition par lot

| Lot | Contenu | Durée | Jalon de sortie |
|---|---|---|---|
| **Lot 0 — Socle** | M01 + fondations techniques, CI, environnements | 6 sem. | Un utilisateur se connecte, une boutique existe, l'isolation est prouvée par des tests |
| **Lot 1 — MVP marchand** | M02, M03, M04, M05, M07, M08, M11 (socle), M12, M13 | 20 sem. | 30 boutiques pilotes vendent en ligne et tiennent leur stock ; 200 livraisons réalisées |
| **Lot 2 — Opérations** | M06 complet, escrow avancé, WhatsApp, retours, B2B | 14 sem. | Coût unitaire de livraison prouvé ; ouverture au-delà de 200 boutiques (A7) |
| **Lot 3 — Comptabilité** | M09 | 18 sem. | Une balance et un grand livre SYSCOHADA validés par un cabinet partenaire |
| **Lot 4 — RH & paie** | M10, entrepôt mutualisé | 16 sem. | 50 bulletins réels conformes, contrôlés par le cabinet partenaire |
| **Lot 5 — Croissance** | M11 complet, M14, financement de stock | 14 sem. | Premier euro de retail media, première avance de trésorerie remboursée |

---

## 5. Exigences transverses (non fonctionnelles)

| Domaine | Exigence |
|---|---|
| **Performance** | Page catalogue < 2,5 s sur 3G ; saisie d'une ligne de caisse < 4 s |
| **Hors ligne** | Caisse et stock pleinement opérationnels sans réseau, synchronisation idempotente |
| **Disponibilité** | 99,5 % sur le back-office marchand, 99,9 % sur l'encaissement |
| **Sécurité** | Isolation stricte par boutique, chiffrement au repos des pièces d'identité, journal d'audit inaltérable |
| **Conformité** | Loi 2024/017 (données personnelles, applicable au 23 juin 2026), SYSCOHADA, mentions DGI |
| **Réversibilité** | Export intégral des données du marchand à tout moment, sans frais |
| **Frugalité** | Application marchand < 15 Mo, mode économie de données, fonctionnement sur Android 8+ |
| **Langues** | Français (défaut), anglais (Cameroun bilingue) |
| **Traçabilité** | Toute écriture comptable remonte à l'opération métier qui l'a produite, et réciproquement |
