# HyperMarché — la place de marché qui gère aussi la boutique

> **Nom de code : `hyper_market`.** Plateforme d'hypermarché en ligne pour la zone CEMAC :
> des commerçants louent un **emplacement numérique**, y vendent en ligne, et la plateforme
> pilote pour eux **stock, comptabilité SYSCOHADA, personnel, paie, trésorerie et marketing**.
> Un réseau de **comptes marketing et revendeurs** (liens de filiation, commissions) alimente
> le trafic et les ventes.

---

## L'idée en une phrase

Là où les places de marché africaines s'arrêtent à la vitrine, HyperMarché descend jusqu'au
back-office : **le commerçant ne loue pas une page, il loue une boutique qui tourne toute
seule.** C'est ce back-office (compta, stock, paie) qui crée la rétention qu'aucune marketplace
pure ne réussit à obtenir.

## Positionnement retenu

| Axe | Choix |
|---|---|
| Marché de lancement | **CEMAC**, en commençant par le **Cameroun** (Douala / Yaoundé) |
| Devise | **XAF (FCFA)** |
| Cible marchand | **PME et boutiques structurées** (RCCM, NIU, salariés déclarés) |
| Référentiel comptable | **SYSCOHADA révisé** |
| Encaissement | **Mobile Money** (MTN MoMo, Orange Money) + carte + paiement à la livraison |
| Stack technique | **Django 5 / DRF / PostgreSQL** (monolithe modulaire) |

## Dossier projet

Le dossier complet est dans [`docs/`](docs/). Ordre de lecture conseillé :

| # | Document | À quoi ça sert |
|---|---|---|
| 01 | [Vision & enrichissement produit](docs/01-vision-et-enrichissement-produit.md) | Le problème, la proposition de valeur, les 12 briques ajoutées à l'idée initiale |
| 02 | [Étude de marché](docs/02-etude-de-marche.md) | Taille du marché, TAM/SAM/SOM, concurrence, PESTEL, Porter, personas |
| 03 | [Business plan](docs/03-business-plan.md) | Modèle de revenus, pricing, unit economics, prévisionnel 5 ans, financement |
| 04 | [Conseil d'experts (LLM Council)](docs/04-conseil-llm.md) | 7 avis contradictoires sur le projet + arbitrages rendus |
| 05 | [Périmètre fonctionnel](docs/05-perimetre-fonctionnel.md) | Les 14 modules, epics, user stories, priorisation MoSCoW |
| 06 | [Affiliation, marketing & revendeurs](docs/06-affiliation-marketing-revendeurs.md) | Liens de filiation, commissions, garde-fous anti-pyramidal |
| 07 | [Comptabilité & paie SYSCOHADA](docs/07-comptabilite-paie-syscohada.md) | Partie double, plan comptable, bulletin de paie camerounais |
| 08 | [Conformité juridique & fiscale](docs/08-conformite-juridique-et-fiscale.md) | OHADA, TVA 19,25 %, loi 2024/017 données personnelles, statut d'intermédiaire |
| 09 | [Architecture technique](docs/09-architecture-technique.md) | Monolithe modulaire Django, multi-tenant, sécurité, infrastructure |
| 10 | [Modèle de données](docs/10-modele-de-donnees.md) | Entités, relations, règles d'intégrité |
| 11 | [Roadmap, budget & équipe](docs/11-roadmap-budget-equipe.md) | 5 lots de livraison, staffing, budget par phase |
| 12 | [Risques & KPI](docs/12-risques-et-kpi.md) | Registre des risques cotés, tableau de bord de pilotage |
| 13 | [Sources](docs/13-sources.md) | Toutes les références chiffrées utilisées |
| 14 | [Guide du développeur](docs/14-guide-developpeur.md) | Mise en route du code, règles à ne pas enfreindre |
| 15 | [Plan de validation terrain](docs/15-plan-de-validation-terrain.md) | Protocole des 10 semaines de phase 0, guides d'entretien, seuils du jalon G0 |
| 16 | [Partenariat cabinet comptable](docs/16-partenariat-cabinet-comptable.md) | Sélection, frontière de responsabilité, recette des barèmes de paie |
| 17 | [Démarrer sans capital](docs/17-demarrage-sans-capital.md) | **Le plan effectivement applicable aujourd'hui** : 450 000 F, 5 paliers autofinancés |
| 18 | [Produit du palier 1](docs/18-produit-palier-1.md) | Le plan raffiné : les 6 écrans, l'installation en 90 minutes, critères d'acceptation |
| 19 | [Système de design](docs/19-systeme-de-design.md) | Jetons validés, règles de visualisation, pièges rencontrés |

> **Deux conditions bloquantes** avant d'engager les 400 M FCFA d'amorçage et d'ouvrir les modules
> réglementés : la [validation terrain](docs/15-plan-de-validation-terrain.md) (jalon G0) et le
> [partenariat cabinet](docs/16-partenariat-cabinet-comptable.md) (arbitrages A5 et A6).
>
> **Sans capital de départ**, le plan de financement du document 03 n'est pas exécutable. Le
> [document 17](docs/17-demarrage-sans-capital.md) le remplace pour la phase de démarrage : les
> deux conditions ci-dessus y sont remplies **avec du temps plutôt qu'avec de l'argent**.

## Mise en route du code

```bash
make installer                  # environnement virtuel + dépendances
cp .env.example .env            # DEBUG=True, sinon le CSS n'est pas servi
docker compose up -d db redis   # PostgreSQL 16 + Redis
make migrer
make demo                       # référentiels + 2 boutiques, 20 jours de ventes
make servir                     # http://localhost:8000/
make tester                     # 89 tests
```

Comptes de démonstration (mot de passe `demo1234`) :
`+237699110011` — Quincaillerie Ateba, Douala · `+237677220022` — Bella Cosmétiques, Yaoundé.

Détails dans le [guide du développeur](docs/14-guide-developpeur.md).

## Le back-office marchand

Six écrans, en français, mode clair et sombre, du bureau au téléphone d'entrée de gamme.
Captures dans [`captures/`](captures/) — régénérables par `node scripts/captures.js`.

| Écran | Ce qu'il fait |
|---|---|
| **Tableau de bord** | Ventes du jour, **marge réelle au coût moyen pondéré**, valeur du stock, alertes, graphe sur 14 jours |
| **Caisse** ★ | Grille tactile, recherche et code-barres, ticket, 3 moyens de paiement, encaissement idempotent |
| **Stock** | Liste, filtres, valeur au CMP, historique des mouvements par article |
| **Ventes** | Journal des tickets clôturés, HT / TVA / TTC |
| **Comptabilité** | Balance SYSCOHADA, dernières écritures, marge brute — en lecture seule |
| **Ma boutique** | Identité, bail, équipe, dépôts |

Un encaissement produit d'un seul geste **le ticket, la sortie de stock au coût moyen et les trois
écritures comptables** — c'est la promesse « zéro double saisie », et elle est testée de bout en
bout.

## État du projet

- [x] Cadrage marché et positionnement
- [x] Étude de marché et business plan
- [x] Dossier de conception fonctionnelle et technique
- [x] **Lot 0** — Socle Django : multi-tenant, rôles, emplacements, isolation prouvée par les tests
- [x] **Interface du palier 1** — 6 écrans, système de design, captures de recette
- [ ] **Lot 1** — MVP marchand : catalogue, **stock, caisse**, commandes, paiement, affiliation
  *(domaine, moteurs métier et back-office posés et testés ; restent le mode hors ligne réel,
  l'écran de reprise de stock, l'impression du ticket et les adaptateurs Mobile Money —
  voir [docs/18](docs/18-produit-palier-1.md), §6)*
- [ ] **Lot 2** — Opérations : logistique, séquestre, WhatsApp, B2B
- [ ] **Lot 3** — Comptabilité SYSCOHADA
- [ ] **Lot 4** — RH & paie
- [ ] **Lot 5** — Affiliation complète, retail media, financement de stock

> L'ordre stock/caisse avant comptabilité résulte de l'arbitrage **A1** du
> [conseil d'experts](docs/04-conseil-llm.md) : le stock crée l'usage quotidien, la comptabilité
> crée la rétention — mais on ne retient pas un client qu'on n'a pas encore acquis.

## Avertissement

Les chiffres réglementaires (taux de TVA, barèmes CNPS et IRPP, seuils de régimes fiscaux) sont
donnés à titre de cadrage et sourcés dans [`docs/13-sources.md`](docs/13-sources.md). Ils doivent
être **validés par un conseil fiscal et un expert-comptable agréé OHADA** avant toute mise en
production des modules comptabilité et paie.
