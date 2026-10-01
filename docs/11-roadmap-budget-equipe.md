# 11 — Roadmap, équipe et budget

Applique les arbitrages **A1** (stock et caisse au lot 1, comptabilité au lot 3), **A2**
(amorçage resserré), **A6** (paie conditionnée) et **A7** (plafond de 200 boutiques).

---

## 1. Vue d'ensemble

```
2026        │ 2027                          │ 2028              │ 2029        │ 2030-31
────────────┼───────────────────────────────┼───────────────────┼─────────────┼──────────
 Étude      │ Lot 0    Lot 1                │ Lot 2    Lot 3    │ Lot 4  Lot 5│ CEMAC
 terrain    │ socle    MVP marchand         │ opé.     compta   │ paie   crois│ Gabon,
 + amorçage │                               │                   │             │ Congo
────────────┼───────────────────────────────┼───────────────────┼─────────────┼──────────
            │        ▲ 30 pilotes           │  ▲ 200 livraisons │ ▲ équilibre │
            │                    ▲ 150 bout.│         ▲ 600 b.  │   EBITDA    │
            │        ▲ Seed levé (M18)      │                   │             │
```

---

## 2. Phase 0 — Étude terrain et amorçage (M-3 à M0)

**Objectif : valider ou invalider H1, H2 et H3 avant d'écrire du code métier.**

| Chantier | Livrable | Durée |
|---|---|---|
| 30 entretiens marchands | Cartographie des douleurs, hiérarchie des modules | 4 sem. |
| Test de prix (Van Westendorp) sur 60 marchands | Grille tarifaire définitive | 2 sem. |
| **Test d'appétence à la traçabilité** (arbitrage A10) | Mesure du frein à la formalisation | 2 sem. |
| 10 lettres d'intention de pilote payant | Preuve de H1 | 4 sem. |
| Panel de 400 acheteurs | Taux d'acceptation du séquestre | 3 sem. |
| Constitution, RCCM, NIU, **dépôt OAPI** | Société opérationnelle | 6 sem. |
| Contrat de partenariat cabinet ONECCA | Prérequis des arbitrages A5 et A6 | 6 sem. |
| Dossier d'amorçage | 400 M FCFA levés | 10 sem. |

**Budget : 12 M FCFA. Critère de passage :** au moins 7 lettres d'intention signées sur 10
sollicitées. En dessous de 5, le modèle d'abonnement est remis en cause et bascule vers du gratuit
financé par la commission.

---

## 3. Lot 0 — Socle technique (6 semaines)

| Contenu | Critère de sortie |
|---|---|
| Projet Django, configuration par environnement, Docker, intégration continue | La chaîne CI tourne sur chaque commit |
| `core` : modèles de base, tenancy, audit, journal d'opérations idempotent | — |
| `accounts` : utilisateurs, rôles, appartenances, OTP SMS | Un utilisateur se connecte et rejoint une boutique |
| `marketplace` : boutiques, rayons, types d'emplacement, baux | Une boutique existe avec un bail actif |
| Admin Django opérationnel sur tout le socle | Le back-office plateforme est utilisable |
| **Jeu de tests d'isolation multi-tenant** | **Aucun accès croisé possible, prouvé par les tests** |

> Le critère d'isolation est **bloquant**. Le lot 1 ne démarre pas tant qu'il n'est pas vert.

---

## 4. Lot 1 — MVP marchand (20 semaines)

**La brique unique du document 04, §9 : stock + caisse. Tout le reste s'y accroche.**

| Bloc | Contenu | Semaines |
|---|---|---|
| Catalogue | Produits, variantes, prix, médias, import CSV, référentiel mutualisé | 3 |
| **Stock** ★ | Dépôts, mouvements, CMP, seuils, inventaire, **hors ligne** | 4 |
| **Caisse** ★ | PWA, scan, encaissement, session, ticket, **hors ligne** | 4 |
| Vitrine & commandes | Recherche, fiche produit, panier multi-boutiques, sous-commandes | 3 |
| Paiement | Abstraction multi-PSP, MTN + Orange, séquestre simple, portefeuille | 3 |
| Affiliation (socle) | Code, lien, QR, attribution, commissions N1/N2, retrait | 2 |
| Back-office plateforme | Tableau de bord, validation KYC, facturation des loyers | 1 |

**Critères de sortie :**
- 30 boutiques pilotes vendent en ligne **et** tiennent leur stock sur la plateforme
- Taux de boutiques avec ≥ 20 opérations de caisse/semaine **> 60 %** *(test de H2)*
- 200 livraisons réalisées avec coût unitaire mesuré *(test de H3)*
- Saisie d'une ligne de caisse mesurée à **moins de 4 secondes** sur appareil d'entrée de gamme

---

## 5. Lot 2 — Opérations (14 semaines)

| Bloc | Contenu | Semaines |
|---|---|---|
| Logistique | Zones, tarifs, transporteurs, OTP de livraison, retours | 5 |
| Séquestre avancé | Libération conditionnelle, litiges, remboursements | 3 |
| WhatsApp | Catalogue et prise de commande conversationnelle | 3 |
| B2B | Tarifs par client, devis, encours | 2 |
| Ventes flash, codes promo | | 1 |

**Critère de sortie (arbitrage A7) : coût unitaire du dernier kilomètre prouvé.** Tant qu'il ne
l'est pas, le catalogue reste plafonné à 200 boutiques.

---

## 6. Lot 3 — Comptabilité (18 semaines)

| Bloc | Contenu | Semaines |
|---|---|---|
| Plan comptable SYSCOHADA, exercices, journaux | | 3 |
| Moteur d'écritures en ajout seul + triggers PostgreSQL | | 4 |
| Modèles d'écriture automatiques (ventes, achats, stock, caisse) | | 4 |
| Grand livre, balance, lettrage, rapprochement | | 3 |
| Déclaration de TVA, alertes de seuils de régime | | 2 |
| Espace de révision pour le cabinet partenaire | | 2 |

**Critère de sortie :** une balance et un grand livre **validés par le cabinet partenaire** sur
3 boutiques réelles, sur un exercice complet.

---

## 7. Lot 4 — RH, paie et entrepôt (16 semaines)

Ouverture conditionnée à l'arbitrage A6.

| Bloc | Contenu | Semaines |
|---|---|---|
| Dossiers salariés, contrats, présences, congés | | 3 |
| Moteur de paie versionné + rubriques | | 5 |
| Bulletins, livre de paie, déclarations CNPS et DIPE | | 3 |
| Versement des salaires par Mobile Money en lot | | 2 |
| Entrepôt mutualisé : réception, préparation, consolidation | | 3 |

**Critère de sortie :** 50 bulletins réels contrôlés et validés par le cabinet partenaire, jeu de
non-régression en intégration continue.

---

## 8. Lot 5 — Croissance (14 semaines)

| Bloc | Contenu | Semaines |
|---|---|---|
| Affiliation complète : vitrine revendeur, catalogue autorisé | | 4 |
| Retail media : emplacements, campagnes, facturation, rapports | | 5 |
| Financement de stock : scoring, octroi, prélèvement, suivi | | 5 |

**Préalable bloquant (arbitrage A3) :** partenariat bancaire ou véhicule dédié signé. **Sans
partenaire de financement, la ligne crédit n'ouvre pas** — les fonds propres n'y sont pas engagés.

---

## 9. Équipe

### Effectif par année

| Fonction | A1 | A2 | A3 | A4 | A5 |
|---|---:|---:|---:|---:|---:|
| Direction (CEO, CTO) | 2 | 2 | 3 | 3 | 4 |
| Ingénierie | 5 | 11 | 18 | 26 | 34 |
| Produit & design | 1 | 3 | 5 | 7 | 9 |
| Commercial terrain | 3 | 8 | 15 | 24 | 32 |
| Succès client & support | 2 | 5 | 10 | 18 | 26 |
| Opérations & logistique | 0 | 2 | 5 | 8 | 12 |
| Finance, comptabilité, juridique | 1 | 1 | 2 | 2 | 3 |
| **Total** | **14** | **32** | **58** | **88** | **120** |

### Les cinq recrutements qui décident du projet

| Poste | Pourquoi il est critique | Quand |
|---|---|---|
| **Directeur technique** | Porte les arbitrages A12 : isolation, hors ligne, journal en ajout seul. Une erreur de fondation coûte une réécriture | M0 |
| **Expert-comptable produit** | Traduit SYSCOHADA et la paie camerounaise en règles logicielles. Sans lui, les lots 3 et 4 sont impossibles | M6 |
| **Directeur commercial terrain** | La vente aux PME camerounaises ne se fait pas en ligne. C'est un métier de terrain, de réseau et de langue | M0 |
| **Responsable des opérations** | Le dernier kilomètre est le point de rupture identifié par le conseil | M12 |
| **Responsable conformité & fraude** | Affiliation, LBC/FT, loi 2024/017. Un incident non traité coûte l'agrément et la réputation | M18 |

### Principes d'organisation

- **Équipes verticales par domaine** (marchand, acheteur, plateforme), pas par couche technique.
- **Chaque équipe embarque un référent métier** — un comptable dans l'équipe comptabilité, un
  ancien commerçant dans l'équipe marchand. C'est ce qui évite de construire un produit théorique.
- **15 jours-homme de recherche utilisateur par lot**, non négociables (exigence du document 04, §3).

---

## 10. Budget par phase

*Millions de FCFA.*

| Poste | Phase 0 | Lot 0-1 | Lot 2-3 | Lot 4-5 | Total |
|---|---:|---:|---:|---:|---:|
| Salaires & prestataires | 6,0 | 118,0 | 295,0 | 480,0 | 899,0 |
| Étude terrain & recherche utilisateur | 12,0 | 8,0 | 10,0 | 12,0 | 42,0 |
| Infrastructure & outillage | 0,5 | 16,0 | 42,0 | 78,0 | 136,5 |
| Marketing & acquisition | 1,0 | 42,0 | 130,0 | 290,0 | 463,0 |
| Juridique, conformité, OAPI, cabinet | 4,0 | 9,0 | 18,0 | 24,0 | 55,0 |
| Logistique & entrepôt | — | 5,0 | 35,0 | 95,0 | 135,0 |
| Structure (locaux, déplacements, divers) | 2,0 | 24,0 | 62,0 | 118,0 | 206,0 |
| **Total** | **25,5** | **222,0** | **592,0** | **1 097,0** | **1 936,5** |

**Rapprochement avec le plan de financement du [business plan](03-business-plan.md) :**

| Ressource | Montant | Couvre |
|---|---:|---|
| Fonds propres fondateurs | 40 M | Phase 0 |
| Amorçage (M3) | 400 M | Lots 0 et 1 + trésorerie de sécurité |
| Seed (M18) | 1 200 M | Lots 2 à 4 |
| Chiffre d'affaires généré | — | Financement partiel du lot 5 |
| Série A (M42) | 4 000 M | Expansion CEMAC + livre de crédit (hors budget ci-dessus) |

---

## 11. Jalons de décision

Chaque jalon est un point d'arrêt formel : on ne passe pas au suivant sans avoir tranché.

| Jalon | Date | Question | Si la réponse est non |
|---|---|---|---|
| **G0** | M0 | 7 lettres d'intention sur 10 ? | Bascule vers un modèle gratuit + commission |
| **G1** | M2 | Isolation multi-tenant prouvée ? | On ne code aucun module métier |
| **G2** | M9 | 60 % des pilotes utilisent la caisse chaque semaine ? *(H2)* | Le produit redevient une marketplace ; réduction de l'ambition ERP |
| **G3** | M11 | Coût du dernier kilomètre positif sur 200 livraisons ? *(H3)* | Restriction aux rayons à forte valeur, ou retrait en point relais |
| **G4** | M18 | 150 boutiques payantes, churn < 32 % ? | Le seed ne se lève pas dans ces conditions : réduction d'effectif |
| **G5** | M30 | Balance validée par un cabinet ? | Le module comptabilité ne sort pas ; risque déontologique |
| **G6** | M42 | Partenaire bancaire signé ? | La ligne financement n'ouvre pas *(arbitrage A3)* |
