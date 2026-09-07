# 10 — Modèle de données

Conventions : identifiants **UUIDv7** générés côté client ; montants en `Decimal(18,2)` exprimés
en **XAF** (le franc CFA n'a pas de subdivision en usage, mais les calculs intermédiaires de
commission et de TVA exigent des décimales) ; toute table métier porte `boutique_id`, `cree_le`,
`modifie_le`, `cree_par`.

---

## 1. Vue d'ensemble

```
                    ┌──────────────┐
                    │  Utilisateur │
                    └──────┬───────┘
                           │ appartenances
                    ┌──────▼───────┐        ┌──────────┐
                    │ Appartenance │───────▶│  Rôle    │
                    └──────┬───────┘        └──────────┘
                           │
      ┌────────────────────▼─────────────────────┐
      │              BOUTIQUE  (tenant)          │
      │  ◀── Bail ── TypeEmplacement ── Rayon    │
      └───┬──────┬───────┬───────┬───────┬───────┘
          │      │       │       │       │
     ┌────▼──┐ ┌─▼────┐ ┌▼─────┐ ┌▼────┐ ┌▼────────┐
     │Produit│ │Stock │ │Vente │ │Compta│ │Personnel│
     └───────┘ └──────┘ └──────┘ └──────┘ └─────────┘
```

---

## 2. `core` — socle

| Modèle | Champs clés | Notes |
|---|---|---|
| `BaseModel` *(abstrait)* | `id` UUIDv7, `cree_le`, `modifie_le`, `cree_par` | Hérité par tout |
| `TenantScopedModel` *(abstrait)* | `boutique` FK | Gestionnaire filtrant par défaut |
| `EntreeAudit` | `acteur`, `action`, `objet_type`, `objet_id`, `avant` JSONB, `apres` JSONB, `ip`, `horodatage` | Inaltérable |
| `OperationSync` | `operation_id` UUIDv7 **unique**, `type`, `charge_utile` JSONB, `etat`, `resultat` JSONB, `horodatage_client` | Clé d'idempotence du hors-ligne |
| `Consentement` | `utilisateur`, `finalite`, `accorde`, `horodatage`, `preuve` JSONB, `revoque_le` | Loi 2024/017 |

---

## 3. `accounts` — identité

| Modèle | Champs clés | Notes |
|---|---|---|
| `Utilisateur` | `telephone` **unique**, `email` optionnel, `nom_complet`, `est_actif`, `code_apporteur` unique | Le téléphone est l'identifiant principal |
| `Role` | `code`, `libelle`, `portee` (`boutique` \| `plateforme`), `permissions` | `GERANT`, `VENDEUR`, `CAISSIER`, `MAGASINIER`, `COMPTABLE`, `RH`, `RESP_RAYON`, `ADMIN_MARCHE`, `CABINET` |
| `Appartenance` | `utilisateur`, `boutique`, `role`, `actif`, `depuis`, `jusqu_a` | Un utilisateur peut appartenir à plusieurs boutiques |
| `DossierKyc` | `utilisateur` ou `boutique`, `type_piece`, `numero`, `fichier` chiffré, `etat`, `verifie_par`, `verifie_le` | |
| `AppareilConnu` | `utilisateur`, `empreinte`, `dernier_usage` | Détection de fraude affiliation |

**Contraintes :** unicité `(utilisateur, boutique, role)` sur les appartenances actives.

---

## 4. `marketplace` — le marché et ses emplacements

| Modèle | Champs clés | Notes |
|---|---|---|
| `Rayon` | `code`, `libelle`, `parent`, `taux_commission`, `responsable`, `actif` | Le rayon porte le taux de commission |
| `TypeEmplacement` | `code` (`ETAL`,`BOUTIQUE`,`GRANDE_SURFACE`), `loyer_mensuel`, `taux_commission_defaut`, `quota_utilisateurs`, `modules_inclus` JSONB | Grille du document 03 |
| `Boutique` ★ | `raison_sociale`, `enseigne`, `rccm`, `niu`, `regime_fiscal`, `rayon_principal`, `etat` (`candidature`→`active`→`suspendue`→`resiliee`), `devise`, `fuseau` | **Le tenant** |
| `Bail` | `boutique`, `type_emplacement`, `debut`, `fin`, `loyer_mensuel`, `depot_garantie`, `taux_commission`, `preavis_jours`, `etat` | Contrat de location |
| `AvenantBail` | `bail`, `motif`, `champs_modifies` JSONB, `date_effet` | Historique des révisions |
| `FactureLoyer` | `bail`, `periode`, `montant_ht`, `tva`, `etat`, `echeance`, `paye_le` | Déclenche suspension si impayé |
| `EmplacementPremium` | `rayon`, `type` (tête de gondole, bandeau), `periode`, `tarif`, `boutique_occupante` | Recette retail media |
| `EtatDesLieux` | `bail`, `type` (entrée/sortie), `stock_initial` JSONB, `comptes_initiaux` JSONB, `constate_le` | Audit d'onboarding |

---

## 5. `catalog` — catalogue

| Modèle | Champs clés | Notes |
|---|---|---|
| `Categorie` | `rayon`, `parent`, `libelle`, `chemin` | Arborescence |
| `ProduitReference` | `code_barres` **unique global**, `libelle`, `marque`, `fiche` JSONB | **Référentiel mutualisé plateforme** : évite que 40 boutiques ressaisissent le même article |
| `Produit` ⊂tenant | `boutique`, `reference` FK optionnelle, `sku`, `libelle`, `categorie`, `unite`, `regime_tva`, `actif`, `revente_autorisee`, `marge_revendeur` | |
| `Variante` ⊂tenant | `produit`, `attributs` JSONB, `sku`, `code_barres`, `prix_vente`, `prix_barre` | Le prix vit sur la variante |
| `MediaProduit` ⊂tenant | `produit`, `fichier`, `ordre`, `alt` | WebP, compression agressive |
| `TarifClient` ⊂tenant | `variante`, `groupe_client`, `prix` | Segment B2B |

**Contraintes :** `sku` unique par boutique ; `code_barres` unique par boutique ;
`prix_vente >= 0`.

---

## 6. `inventory` — stock

| Modèle | Champs clés | Notes |
|---|---|---|
| `Depot` ⊂tenant | `libelle`, `type` (boutique, réserve, entrepôt plateforme), `adresse` | |
| `NiveauStock` ⊂tenant | `depot`, `variante`, `quantite`, `cmp`, `seuil_alerte`, `version` | Agrégat matérialisé ; `version` pour verrou optimiste |
| `MouvementStock` ⊂tenant ★ | `depot`, `variante`, `type` (`ENTREE`,`SORTIE`,`TRANSFERT`,`AJUSTEMENT`,`PERTE`,`CASSE`), `quantite` signée, `cout_unitaire`, `cmp_apres`, `origine_type`, `origine_id`, `operation_id` | **Ajout seul.** Source de vérité du stock |
| `Inventaire` ⊂tenant | `depot`, `date`, `etat`, `valide_par` | |
| `LigneInventaire` ⊂tenant | `inventaire`, `variante`, `qte_theorique`, `qte_comptee`, `ecart`, `motif` | |
| `Fournisseur` ⊂tenant | `nom`, `contact`, `niu`, `conditions_paiement` | |
| `CommandeFournisseur` ⊂tenant | `fournisseur`, `etat`, `date`, `total_ht` | |
| `ReceptionLigne` ⊂tenant | `commande_fournisseur`, `variante`, `qte_recue`, `cout_unitaire`, `lot`, `peremption` | Met à jour le CMP |

**Règle de valorisation (CMP) :** à chaque entrée,
`cmp = (stock × cmp + qté_entrée × coût_entrée) / (stock + qté_entrée)`.
Les sorties ne modifient jamais le CMP. Recalcul impossible a posteriori : le CMP après chaque
mouvement est historisé sur la ligne (`cmp_apres`).

**Stock négatif autorisé** (ADR-005) : un `NiveauStock` négatif lève une anomalie d'inventaire,
il ne bloque pas la vente.

---

## 7. `pos` — caisse

| Modèle | Champs clés | Notes |
|---|---|---|
| `SessionCaisse` ⊂tenant | `depot`, `caissier`, `ouverte_le`, `fonds_ouverture`, `fermee_le`, `fonds_theorique`, `fonds_compte`, `ecart` | |
| `Ticket` ⊂tenant | `session`, `numero`, `client` optionnel, `total_ht`, `total_tva`, `total_ttc`, `etat`, `operation_id` | Numérotation continue par boutique |
| `LigneTicket` ⊂tenant | `ticket`, `variante`, `qte`, `pu_ht`, `taux_tva`, `remise` | |
| `ReglementTicket` ⊂tenant | `ticket`, `moyen` (espèces, MoMo, mixte), `montant`, `reference_psp` | |

---

## 8. `orders` — commandes en ligne

| Modèle | Champs clés | Notes |
|---|---|---|
| `Panier` | `acheteur` ou `session`, `code_apporteur` | Le code d'affiliation est capté ici |
| `Commande` | `numero`, `acheteur`, `total_ttc`, `frais_livraison`, `etat`, `apporteur_n1`, `apporteur_n2`, `revendeur` | **Non scopée à une boutique** : elle les traverse |
| `SousCommande` ⊂tenant ★ | `commande`, `boutique`, `total_ht`, `tva`, `commission_plateforme`, `etat` | **L'unité de travail du marchand** |
| `LigneCommande` ⊂tenant | `sous_commande`, `variante`, `qte`, `pu_ht`, `taux_tva`, `remise` | |
| `Retour` ⊂tenant | `sous_commande`, `motif`, `etat`, `montant_rembourse` | Annule les commissions liées |
| `Litige` | `commande`, `ouvert_par`, `motif`, `etat`, `decision`, `decide_par` | Bloque le séquestre |

**Règle centrale :** un panier multi-boutiques produit **une `Commande` et N `SousCommande`**.
L'acheteur voit une commande et paie une fois ; chaque marchand ne voit et ne gère que sa
sous-commande. Toute la comptabilité, la commission et l'affiliation s'appuient sur la
`SousCommande`.

---

## 9. `payments` — encaissement

| Modèle | Champs clés | Notes |
|---|---|---|
| `Prestataire` | `code` (`MTN_MOMO`,`ORANGE_MONEY`,`CAMTEL`,`CARTE`,`COD`), `actif`, `config` chiffrée, `taux_frais` | |
| `Transaction` | `commande`, `prestataire`, `montant`, `sens` (encaissement/versement), `etat`, `reference_externe`, `cle_idempotence` **unique**, `charge_utile_psp` JSONB | |
| `Sequestre` | `commande`, `montant`, `etat` (`bloque`,`libere`,`rembourse`), `libere_le`, `motif` | Libéré à la preuve de livraison |
| `PortefeuilleMarchand` ⊂tenant | `solde_disponible`, `solde_bloque`, `iban_momo` | **Compte de suivi, pas un dépôt** (document 08) |
| `MouvementPortefeuille` ⊂tenant | `portefeuille`, `type`, `montant`, `solde_apres`, `origine_type`, `origine_id` | Ajout seul |
| `DemandeRetrait` ⊂tenant | `portefeuille`, `montant`, `etat`, `transaction` | |

**Contraintes :** `cle_idempotence` unique globale — la protection la plus importante du système
(un double débit Mobile Money est l'incident le plus grave possible sur ce marché).

---

## 10. `logistics` — livraison

| Modèle | Champs clés | Notes |
|---|---|---|
| `Adresse` | `utilisateur`, `libelle`, `point_gps`, `repere_textuel`, `contact_telephone`, `zone` | **L'adressage postal n'existe pas** : GPS + repère + contact obligatoires |
| `ZoneLivraison` | `libelle`, `polygone`, `delai_moyen` | |
| `GrilleTarifaire` | `zone`, `poids_min`, `poids_max`, `tarif` | |
| `Transporteur` | `nom`, `contact`, `zones`, `actif`, `note_qualite` | |
| `Expedition` ⊂tenant | `sous_commande`, `transporteur`, `etat`, `code_otp`, `tentatives`, `livre_le`, `preuve` | L'OTP remis par l'acheteur libère le séquestre |
| `EvenementExpedition` ⊂tenant | `expedition`, `type`, `horodatage`, `commentaire`, `position` | |

---

## 11. `accounting` — comptabilité

| Modèle | Champs clés | Notes |
|---|---|---|
| `PlanComptable` | `code` (`SYSCOHADA_REVISE`), `version` | Référentiel plateforme |
| `CompteGeneral` | `plan`, `numero`, `intitule`, `classe`, `type`, `collectif` | Modèle |
| `CompteBoutique` ⊂tenant | `boutique`, `numero`, `intitule`, `compte_modele`, `actif` | Plan personnalisé par boutique |
| `Exercice` ⊂tenant | `debut`, `fin`, `etat` (`ouvert`,`cloture`) | |
| `Journal` ⊂tenant | `code` (`VTE`,`ACH`,`BQE`,`CAI`,`PAI`,`STK`,`OD`), `libelle` | |
| `EcritureComptable` ⊂tenant ★ | `journal`, `exercice`, `date_ecriture`, `piece`, `libelle`, `validee`, `contrepassee_par`, `origine_type`, `origine_id` | **Ajout seul**, trigger PostgreSQL |
| `LigneEcriture` ⊂tenant | `ecriture`, `compte`, `libelle`, `debit`, `credit`, `lettrage` | |
| `ModeleEcriture` | `evenement`, `lignes` JSONB | Table de correspondance du document 07, §3.4 |
| `DeclarationTva` ⊂tenant | `periode`, `collectee`, `deductible`, `due`, `credit_reporte`, `etat` | |
| `RapprochementBancaire` ⊂tenant | `compte`, `periode`, `solde_releve`, `solde_comptable`, `ecart`, `etat` | |

**Contraintes de base de données :**
- `SUM(debit) = SUM(credit)` par écriture — vérifiée par contrainte
- `debit = 0 OR credit = 0` sur chaque ligne
- Trigger rejetant `UPDATE`/`DELETE` si `validee = true`
- `piece` : séquence continue par `(boutique, exercice, journal)`

---

## 12. `hr` et `payroll` — personnel et paie

| Modèle | Champs clés | Notes |
|---|---|---|
| `Salarie` ⊂tenant | `nom`, `matricule`, `numero_cnps`, `niu`, `date_naissance`, `situation_familiale`, `nb_enfants` | |
| `Contrat` ⊂tenant | `salarie`, `type` (CDI, CDD, essai, apprentissage), `poste`, `debut`, `fin`, `salaire_base`, `groupe_risque_at` | Le groupe de risque pilote le taux d'accident du travail |
| `Presence` ⊂tenant | `salarie`, `date`, `heures`, `heures_sup`, `type` | |
| `Conge` ⊂tenant | `salarie`, `type`, `debut`, `fin`, `etat` | |
| `BaremePaie` ★ | `code`, `pays`, `date_debut`, `date_fin`, `parametres` JSONB | **Versionné par période, jamais écrasé** |
| `Rubrique` | `code`, `libelle`, `type` (gain, retenue, patronal), `formule`, `base`, `ordre` | |
| `BulletinPaie` ⊂tenant ★ | `salarie`, `periode`, `brut`, `net`, `total_retenues`, `total_patronal`, `bareme_utilise`, `etat`, `emis_le` | **Figé à l'émission**, correction par rectificatif |
| `LigneBulletin` ⊂tenant | `bulletin`, `rubrique`, `base`, `taux`, `montant`, `formule_appliquee` | Traçabilité du calcul |
| `DeclarationSociale` ⊂tenant | `periode`, `type` (CNPS, DIPE), `donnees` JSONB, `etat` | |

**Règle :** un bulletin conserve la référence du barème utilisé. Recalculer un bulletin de mars
2027 en 2029 doit produire **exactement** le même résultat.

---

## 13. `affiliation` — filiation et commissions

| Modèle | Champs clés | Notes |
|---|---|---|
| `Apporteur` | `utilisateur`, `code` **unique**, `parrain_n1`, `parrain_n2`, `etat`, `kyc_renforce` | **`parrain_n2` est dénormalisé et figé** : la profondeur ne peut structurellement pas dépasser 2 |
| `Attribution` | `apporteur`, `cible_type` (acheteur, marchand, revendeur), `cible_id`, `origine` (code, clic, rattachement), `debut`, `fin`, `preuve` JSONB | Fenêtre de 12 mois |
| `Revendeur` | `utilisateur`, `etat`, `slug_vitrine`, `plafond_remise` | |
| `CatalogueRevendeur` | `revendeur`, `variante`, `marge`, `actif` | Liste blanche, jamais liste noire |
| `Commission` ★ | `beneficiaire`, `role` (`N1`,`N2`,`REVENDEUR`), `sous_commande`, `assiette`, `taux`, `montant`, `etat` (`attendue`→`acquise`→`payable`→`payee` \| `annulee` \| `reprise`) | |
| `SignalFraude` | `apporteur`, `type`, `score`, `preuve` JSONB, `traite_par`, `decision` | |

**Invariants codés en dur et testés :**
1. `parrain_n2` ne peut jamais avoir lui-même de parrain pris en compte (profondeur ≤ 2)
2. `SUM(commissions d'une sous-commande) ≤ 0,35 × commission_plateforme`
3. Aucune commission ne passe à `payable` avant expiration du délai de retour (7 jours)
4. Auto-parrainage rejeté à l'écriture (même utilisateur, appareil, numéro ou compte MoMo)

---

## 14. `adverts` — retail media

| Modèle | Champs clés |
|---|---|
| `EmplacementPub` | `type`, `zone`, `rayon`, `tarif_base`, `capacite` |
| `Campagne` ⊂tenant | `boutique`, `budget`, `debut`, `fin`, `etat`, `ciblage` JSONB |
| `Impression` | `campagne`, `emplacement`, `horodatage`, `contexte` |
| `Clic` | `campagne`, `emplacement`, `horodatage`, `cout` |

---

## 15. Volumétrie à 5 ans

Dimensionnement de l'infrastructure, sur la base des hypothèses du [business plan](03-business-plan.md).

| Table | Volume estimé A5 | Stratégie |
|---|---|---|
| `MouvementStock` | ~180 M lignes | Partitionnement par mois, archivage à 24 mois |
| `LigneEcriture` | ~140 M lignes | Partitionnement par exercice |
| `Ticket` / `LigneTicket` | ~45 M / ~160 M | Partitionnement par mois |
| `Commande` / `SousCommande` | ~9 M / ~13 M | Index sur `(boutique, etat, cree_le)` |
| `Commission` | ~25 M | Partitionnement par mois |
| `EntreeAudit` | ~400 M | Table séparée, archivage froid à 12 mois |
| `Impression` (retail media) | ~2 Md | **Ne jamais stocker en base transactionnelle** : agrégats horaires uniquement |

**Décision :** le partitionnement natif PostgreSQL est prévu dès la conception des tables
concernées (clé de partition présente dès le lot 1), même s'il n'est activé qu'à partir du lot 3.
Ajouter un partitionnement après coup sur 100 M de lignes coûte une fenêtre de maintenance qu'on
ne peut pas se permettre.
