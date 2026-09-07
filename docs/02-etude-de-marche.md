# 02 — Étude de marché

**Périmètre :** zone CEMAC, marché pilote Cameroun. Cible : PME et boutiques structurées du
commerce. Sources chiffrées listées en [document 13](13-sources.md).

---

## 1. Cadre macro et environnement

La CEMAC regroupe six pays (Cameroun, Gabon, Congo, Tchad, Guinée équatoriale, RCA) autour d'une
monnaie commune, le franc CFA d'Afrique centrale (XAF), à parité fixe avec l'euro
(1 EUR = 655,957 XAF). Cette parité fixe est un avantage rare : elle supprime le risque de change
pour un investisseur en euros, contrairement au Nigeria, au Ghana ou au Kenya.

Le Cameroun est le poumon économique de la zone. En matière de paiement numérique il concentre
**62,1 % des comptes enregistrés, 63,6 % du volume de transactions et 76,6 % de la valeur** des
opérations Mobile Money de la CEMAC. Toute stratégie régionale part donc de Douala et Yaoundé.

### PESTEL

| Dimension | Facteurs favorables | Facteurs défavorables |
|---|---|---|
| **Politique** | Volonté publique de digitaliser le commerce (lancement de Bolamba par Campost, plateformes logistiques aux aéroports de Douala et Yaoundé) | Instabilité régionale (RCA, Tchad) ; lenteur administrative ; risque de politisation d'un opérateur public concurrent |
| **Économique** | Parité fixe XAF/EUR ; croissance du e-commerce (+18 % de CA des plateformes en 2024) ; 472 000 PME actives, +6,5 % sur un an | Pouvoir d'achat contraint ; coût du crédit ; accès aux devises ; forte informalité (3,8 M d'unités informelles contre 568 000 formelles) |
| **Socioculturel** | 42 % des PME créées en 2025 portées par des moins de 35 ans ; usage massif de WhatsApp ; culture de la tontine et du réseau, favorable à l'affiliation | Défiance envers le paiement en ligne ; préférence pour le paiement à la livraison ; faible littératie comptable |
| **Technologique** | Mobile Money mature : 52,4 M de comptes actifs CEMAC, 71 % des transactions scripturales, ~23 800 Md FCFA/an ; interopérabilité en progrès ; arrivée d'un 3ᵉ acteur (Camtel Blue Mobile Money) | Pénétration internet ~41,9 % au Cameroun ; qualité et coût de la data ; délestages électriques ; adressage postal inexistant |
| **Écologique** | Circuits courts valorisables ; mutualisation logistique réductrice d'empreinte | Emballage, gestion des retours, flotte thermique |
| **Légal** | Fiscalité 2026 protectrice du local (3 % du CA pour les plateformes étrangères sans présence physique) ; cadre OHADA harmonisé sur 17 pays | Loi 2024/017 sur les données personnelles applicable au **23 juin 2026** ; TVA à 19,25 % ; complexité déclarative |

**Lecture stratégique :** le cadre légal 2026 est un *tailwind* décisif. Un acteur local
constitué au Cameroun n'affronte plus Temu, Shein ou Amazon à armes inégales. La fenêtre est
ouverte maintenant.

---

## 2. Dimensionnement du marché

Deux marchés se superposent, et c'est la thèse du projet : **HyperMarché les adresse tous les
deux avec le même produit.**

### 2.1 — Marché A : le e-commerce (assiette de commission)

| Indicateur | Valeur |
|---|---|
| Taille estimée du e-commerce camerounais | **~490 Md FCFA** (≈ 747 M EUR) |
| Croissance du CA des plateformes (2024) | **+18 %** |
| Pénétration internet Cameroun | **41,9 %** |
| Rang du Cameroun en Afrique | 10ᵉ marché e-commerce |

### 2.2 — Marché B : le logiciel de gestion (assiette d'abonnement)

| Indicateur | Valeur |
|---|---|
| Unités économiques formelles au Cameroun | **569 208** |
| dont PME actives | **472 208** (+6,5 %/an) |
| Part du tertiaire dans les PME créées (2024) | **85,4 %** |
| Unités de production informelles | 3,8 M (hors cible au lancement) |

### 2.3 — TAM / SAM / SOM

Le modèle retenu combine abonnement et commission ; on raisonne donc en **revenu annuel
adressable pour la plateforme**, pas en volume d'affaires du secteur.

**Hypothèses de descente :**

| Étape | Raisonnement | Nombre d'entreprises |
|---|---|---|
| Univers | PME formelles Cameroun | 472 000 |
| Filtre secteur | Commerce de gros et détail ≈ 32 % du tissu formel | ~151 000 |
| Filtre géographique | Douala + Yaoundé + villes secondaires connectées ≈ 55 % | ~83 000 |
| Filtre solvabilité | Capacité et volonté de payer ≥ 15 000 FCFA/mois ≈ 27 % | **~22 400** |
| Extension CEMAC | Cameroun ≈ 58 % de la cible régionale | **~38 600** |

**Résultat :**

| Agrégat | Définition | Valeur annuelle |
|---|---|---|
| **TAM** | Revenu plateforme si l'ensemble des 38 600 PME commerçantes CEMAC étaient équipées, à un ARPU de 1,1 M FCFA/an (abonnement + commission + services) | **~42,5 Md FCFA** (≈ 65 M EUR) |
| **SAM** | Cameroun uniquement, 22 400 entreprises, même ARPU | **~24,6 Md FCFA** (≈ 37,5 M EUR) |
| **SOM à 5 ans** | 3 500 boutiques actives, soit **15,6 % du SAM camerounais** | **~4,7 Md FCFA** (≈ 7,1 M EUR) |

> **Contrôle de cohérence.** Le SOM à 5 ans suppose 48 Md FCFA de GMV traité, soit environ
> **9,8 % du e-commerce camerounais actuel**. Compte tenu de la croissance du secteur (+18 %/an),
> cela représente en réalité ~4,3 % du marché en 2031. Le chiffre est ambitieux mais pas
> irréaliste pour un acteur ayant capté le leadership du back-office marchand.

---

## 3. Analyse concurrentielle

### 3.1 — Cartographie

La concurrence est **fragmentée en deux camps qui ne se parlent pas** : les vendeurs en ligne
d'un côté, les éditeurs de gestion de l'autre. Personne n'occupe l'intersection.

#### Camp 1 — Places de marché et e-commerçants

| Acteur | Position | Forces | Faiblesses exploitables |
|---|---|---|---|
| **Glotelho** | Leader local depuis le retrait de Jumia (2019), 100 % camerounais | Notoriété, logistique rodée, présence physique, conformité fiscale 2026 | Modèle e-commerçant/retailer, pas de back-office marchand, peu de vendeurs tiers autonomes |
| **Iziway** | Challenger local | Implantation physique, conformité | Assortiment limité, faible outillage vendeur |
| **Bolamba (Campost)** | Plateforme publique annoncée pour 2026, adossée à 2 hubs logistiques (Douala, Yaoundé) | Soutien de l'État, réseau postal national, logistique subventionnée | Exécution publique, lenteur, pas de proposition de gestion, risque de rupture politique |
| **Kerawa, Afrimalin, Coinafrique** | Petites annonces | Trafic, gratuité | Pas de transaction, pas de confiance, monétisation faible |
| **Temu, Shein, AliExpress** | Import transfrontalier | Prix, assortiment | Frappés par la fiscalité 2026 (3 % du CA local) ; délais ; pas de service local |
| **WhatsApp / Facebook** | Le vrai concurrent | Gratuit, universel, confiance sociale | Aucune gestion, aucune traçabilité, aucun paiement intégré |

#### Camp 2 — Éditeurs et intégrateurs de gestion

| Acteur | Position | Forces | Faiblesses exploitables |
|---|---|---|---|
| **Sage 100** | Standard historique des moyennes/grandes entreprises via intégrateurs locaux | Crédibilité auprès des cabinets comptables, SYSCOHADA | Coût de licence et d'intégration, pas de canal de vente, pas de Mobile Money natif, expérience datée |
| **Odoo** | Montée en puissance chez les PME | Modularité, e-commerce intégré, prix | Localisation SYSCOHADA/paie camerounaise à faire soi-même ou via partenaire, complexité de paramétrage, pas de place de marché mutualisée |
| **Éditeurs locaux** | Solutions sur mesure, proches du terrain | Connaissance OHADA, fiscalité, Mobile Money | Sous-capitalisés, peu scalables, pas de marketplace |
| **Excel / cahier** | **Le concurrent réel n° 1** | Gratuit, connu, flexible | Aucune fiabilité, aucune traçabilité fiscale, aucun canal de vente |

### 3.2 — Positionnement : la case vide

```
              FORT outillage de gestion (ERP, compta, paie)
                              ▲
                              │
                   Sage 100 ● │ ● Odoo
                              │
                              │        ★ HyperMarché
                              │           (case vide)
   FAIBLE canal ──────────────┼──────────────────── FORT canal de vente
   de vente                   │                     (marketplace, trafic)
                              │
              Excel / cahier ●│● WhatsApp   ● Glotelho, Iziway, Bolamba
                              │             ● Temu / Shein
                              ▼
              FAIBLE outillage de gestion
```

**La case en haut à droite est libre.** Aucun acteur ne propose à la fois le canal de vente et le
système de gestion. C'est structurellement difficile à construire (deux produits, deux
compétences), ce qui en fait précisément une barrière à l'entrée une fois franchie.

### 3.3 — Les 5 forces de Porter

| Force | Intensité | Analyse |
|---|---|---|
| **Menace de nouveaux entrants** | **Moyenne** | Le e-commerce pur s'ouvre facilement, mais l'ERP SYSCOHADA + paie camerounaise + Mobile Money représente 18 à 24 mois de développement spécialisé. La barrière n'est pas le code, c'est la connaissance réglementaire et la donnée accumulée. |
| **Pouvoir des fournisseurs** | **Élevée** | MTN et Orange contrôlent les rails de paiement (~45/55 % de part). Le risque de commission imposée est réel. **Mitigation :** agrégateur multi-PSP dès le jour 1, intégration Camtel Blue Mobile Money comme troisième voie, jamais de dépendance à un seul opérateur. |
| **Pouvoir des clients (marchands)** | **Faible à moyenne, décroissante** | Fort au début (le marchand peut partir sans coût). S'effondre après 6 mois : quand la comptabilité, l'historique de stock et les bulletins de paie sont sur la plateforme, le coût de sortie devient prohibitif. **C'est tout l'enjeu du produit.** |
| **Pouvoir des clients (acheteurs)** | **Élevée** | Zéro coût de changement, forte sensibilité prix. **Mitigation :** assortiment large, fiabilité de livraison, programme de fidélité, ancrage par les revendeurs de quartier. |
| **Menace de substituts** | **Élevée** | WhatsApp + cahier + Mobile Money manuel couvre 80 % du besoin perçu à coût zéro. **C'est le vrai concurrent.** Le produit doit gagner sur la douleur fiscale (produire une liasse conforme), pas sur le confort. |

### 3.4 — Avantages concurrentiels durables visés

1. **Coût de sortie comptable.** Trois ans de grand livre et de bulletins de paie ne se
   déménagent pas.
2. **Donnée de crédit propriétaire.** Personne d'autre ne verra ces flux ; ils fondent l'offre de
   financement, la ligne la plus rentable.
3. **Effet de réseau croisé.** Plus de boutiques → assortiment → acheteurs → revendeurs →
   boutiques.
4. **Réseau de revendeurs affiliés.** Une force de vente distribuée, rémunérée à la performance,
   impossible à répliquer rapidement.
5. **Conformité locale profonde.** SYSCOHADA, CNPS, IRPP, TVA 19,25 %, loi 2024/017 : un
   concurrent étranger mettra des années à l'atteindre.

---

## 4. Segmentation et personas

### Segment prioritaire — « La boutique structurée » (cœur de cible, lot 1 à 3)

**Persona : M. Ateba, 41 ans, gérant de quincaillerie, Akwa (Douala).**
SARL, RCCM et NIU en règle, régime simplifié, 4 salariés déclarés dont 2 à la CNPS, chiffre
d'affaires ~85 M FCFA/an, deux points de vente. Il tient son stock sur un cahier et un fichier
Excel qu'il est le seul à comprendre. Son comptable externe lui coûte 250 000 FCFA/an et rend une
liasse toujours en retard. Il vend déjà via WhatsApp mais perd des commandes faute de suivi.

- *Douleur n° 1 :* il ne sait jamais ce qu'il a réellement en stock ni sa marge réelle par produit.
- *Douleur n° 2 :* la paie et les déclarations CNPS lui prennent deux jours par mois.
- *Déclencheur d'achat :* un contrôle fiscal, ou un vol de stock non détecté.
- *Prix acceptable :* 30 000 à 60 000 FCFA/mois si cela remplace une partie du coût comptable.

### Segment secondaire — « Le grossiste-distributeur » (lot 3+)

**Persona : Mme Ngo Bell, 52 ans, dépôt de produits cosmétiques, Yaoundé.**
Vend à 60 détaillants. Besoin : catalogue B2B avec tarifs par client, encours et relances, gestion
de 6 commerciaux. Fort ARPU, mais cycle de vente long et exigences d'intégration élevées.

### Segment relais — « Le revendeur social » (lot 5, mais amorcé dès le lot 1)

**Persona : Junior, 26 ans, étudiant à Douala, 3 200 contacts WhatsApp.**
Ne veut ni stock ni trésorerie. Veut un lien, un code, une commission visible et un retrait Mobile
Money rapide. C'est le canal d'acquisition d'acheteurs, pas une source d'abonnement.

### Segment acheteur — « L'acheteuse urbaine »

**Persona : Sandrine, 33 ans, cadre, Bonapriso.**
Achète en ligne pour gagner du temps. Paie à la livraison par défaut, par méfiance. Passera au
Mobile Money prépayé si l'escrow lui garantit un remboursement. **Convertir Sandrine du paiement
à la livraison vers l'escrow est l'un des trois leviers économiques majeurs du projet.**

### Segment explicitement écarté au lancement

Le commerçant informel (3,8 M d'unités). Volume énorme, capacité à payer quasi nulle, coût
d'acquisition et de support élevé, aucune obligation comptable à soulager. Il constitue le
marché de la phase 2, avec une offre gratuite financée par la commission.

---

## 5. Étude de la demande — protocole de validation terrain

Aucun chiffre secondaire ne remplace le terrain. Avant l'écriture du code métier :

| Étude | Méthode | Échantillon | Livrable |
|---|---|---|---|
| **Découverte marchands** | Entretiens semi-directifs, 45 min, sur le lieu de vente | 30 PME (20 Douala, 10 Yaoundé), 5 secteurs | Cartographie des douleurs, hiérarchie des modules, prix psychologique |
| **Test de prix** | Van Westendorp + choix forcé sur 3 offres | 60 marchands | Grille tarifaire définitive |
| **Lettres d'intention** | Engagement écrit de pilote payant | 10 signatures visées | Preuve de H1 |
| **Panel acheteurs** | Questionnaire en ligne + 8 entretiens | 400 réponses | Taux d'acceptation de l'escrow, panier moyen cible |
| **Pilote logistique** | 200 livraisons réelles à Douala | 3 transporteurs | Coût réel/livraison, taux d'annulation, preuve de H3 |
| **Veille concurrentielle** | Achat mystère chez Glotelho, Iziway, Bolamba | 10 commandes | Benchmark délais, frais, expérience |

**Budget de l'étude terrain : 12 M FCFA, 10 semaines.** C'est la dépense la plus rentable du
projet : elle conditionne 350 M FCFA d'amorçage.

---

## 6. Synthèse SWOT

| | **Positif** | **Négatif** |
|---|---|---|
| **Interne** | **Forces**<br>• Positionnement unique (canal + gestion)<br>• Lock-in comptable structurel<br>• Donnée propriétaire → crédit<br>• Réseau de revendeurs à coût variable<br>• Modèle « bail » culturellement lisible | **Faiblesses**<br>• Projet à double complexité (marketplace ET ERP)<br>• Time-to-market long avant valeur complète<br>• Exigence forte en expertise SYSCOHADA/paie<br>• Besoin de vente terrain, donc capitalistique<br>• Aucune notoriété initiale |
| **Externe** | **Opportunités**<br>• Départ de Jumia, marché sans dominant<br>• Fiscalité 2026 protégeant les acteurs locaux<br>• Mobile Money mature (76,6 % de la valeur CEMAC au Cameroun)<br>• Loi 2024/017 → besoin d'outils conformes<br>• Réplicabilité sur 17 pays OHADA | **Menaces**<br>• Bolamba adossé à l'État et subventionné<br>• Dépendance MTN/Orange sur le paiement<br>• Coût et fiabilité du dernier kilomètre<br>• Taux d'annulation du paiement à la livraison<br>• Concurrence gratuite de WhatsApp<br>• Instabilité réglementaire (lois de finances annuelles) |

---

## 7. Conclusion de l'étude de marché

**Le marché existe, il croît, et la case visée est vide.** Les trois conditions de succès ne sont
pas d'ordre commercial mais opérationnel :

1. **Livrer le back-office avant que le concurrent ne livre la marketplace.** La vitrine se copie
   en trois mois ; la comptabilité SYSCOHADA et la paie camerounaise, non. C'est là qu'il faut
   investir en premier, même si c'est moins spectaculaire.
2. **Ne jamais dépendre d'un seul rail de paiement.** L'architecture doit rendre MTN, Orange et
   Camtel interchangeables dès le premier jour.
3. **Prouver l'économie du dernier kilomètre avant d'ouvrir grand le catalogue.** C'est là que
   meurent la plupart des places de marché africaines.

Le go/no-go se joue sur les résultats de l'étude terrain du §5, pas sur ce document.
