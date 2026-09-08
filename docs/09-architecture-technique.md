# 09 — Architecture technique

Applique l'arbitrage **A12** : monolithe modulaire Django, schéma partagé avec discriminant
`boutique_id`, offline-first natif, journal comptable en ajout seul.

---

## 1. Choix de la pile

| Couche | Technologie | Justification |
|---|---|---|
| Langage | **Python 3.12** | Bassin de recrutement en Afrique francophone, lisibilité, écosystème |
| Cadre applicatif | **Django 5.x** | ORM et migrations fiables pour un domaine comptable ; **l'admin intégré fait gagner 4 à 6 mois** sur le back-office plateforme |
| API | **Django REST Framework** | Standard, mature, sérialisation et permissions granulaires |
| Base de données | **PostgreSQL 16** | Transactions strictes, contraintes d'exclusion, `RLS`, JSONB, extensions de recherche |
| Tâches asynchrones | **Celery + Redis** | Écritures comptables différées, relances, notifications, rapprochements |
| Cache & sessions | **Redis** | |
| Recherche catalogue | `pg_trgm` + index GIN, puis **OpenSearch** si nécessaire | Ne pas ajouter un moteur de recherche avant d'en avoir la preuve |
| Front public & marchand | **Django templates + HTMX + Alpine.js** | Pages légères, essentiel sur 3G. Pas de SPA lourde |
| Application caisse | **PWA** (service worker + IndexedDB) puis **Android natif** | Le hors-ligne est une contrainte, pas une option |
| Fichiers | S3-compatible (MinIO en local) | Portabilité de l'hébergement |
| Déploiement | Docker + Compose, puis orchestrateur si le besoin apparaît | Frugalité |
| Observabilité | OpenTelemetry, Sentry, Prometheus, Grafana | |

### Ce qu'on refuse explicitement

- **Pas de microservices.** À 14 personnes, c'est un impôt organisationnel sans contrepartie.
- **Pas de SPA React sur le front marchand.** Le poids de la page est un critère produit.
- **Pas de moteur de règles comptables générique.** Le Cameroun a un plan comptable et un taux de
  TVA. Coder le cas simple, généraliser à l'ouverture du Gabon (document 04, §4).
- **Pas d'adhérence à un service propriétaire non substituable** : la localisation de
  l'hébergement peut devoir changer (document 08, §4.4).

---

## 2. Découpage en applications Django

```
hypermarche/
├── config/                  # réglages, urls, wsgi/asgi, celery
├── apps/
│   ├── core/                # modèles de base, tenancy, audit, utilitaires
│   ├── accounts/            # utilisateurs, rôles, appartenances, KYC
│   ├── marketplace/         # rayons, types d'emplacement, boutiques, baux, loyers
│   ├── catalog/             # produits, variantes, prix, médias
│   ├── inventory/           # dépôts, stock, mouvements, CMP, inventaires
│   ├── pos/                 # caisse, sessions, tickets, synchronisation hors ligne
│   ├── orders/              # panier, commandes, sous-commandes, retours
│   ├── payments/            # PSP, transactions, séquestre, portefeuilles
│   ├── logistics/           # zones, expéditions, transporteurs, preuve de livraison
│   ├── accounting/          # plan comptable, journaux, écritures, états
│   ├── hr/                  # salariés, contrats, présences, congés
│   ├── payroll/             # barèmes versionnés, bulletins, déclarations
│   ├── affiliation/         # filiation, attribution, commissions, revendeurs
│   ├── adverts/             # retail media
│   └── backoffice/          # tableaux de bord plateforme, litiges, facturation
└── tests/
```

### Règles de dépendance entre applications

```
adverts ─┐
affiliation ─┤
payroll ─────┤
hr ──────────┤
accounting ──┤──▶ orders, inventory, payments, marketplace ──▶ catalog ──▶ accounts ──▶ core
logistics ───┤
pos ─────────┘
```

**Deux règles absolues :**

1. **Les dépendances ne remontent jamais.** `catalog` ne connaît pas `orders`. `core` ne connaît
   personne.
2. **La communication montante passe par des signaux de domaine**, jamais par un import direct.
   `orders` émet `commande_livree` ; `accounting` et `affiliation` y réagissent sans que `orders`
   ne les connaisse.

C'est ce qui rend le monolithe découpable plus tard, si le besoin s'en présente réellement.

---

## 3. Multi-tenant

### 3.1 — Stratégie retenue

**Schéma partagé, discriminant `boutique_id` sur chaque table métier.**

| Stratégie | Retenue ? | Motif |
|---|---|---|
| Base par boutique | Non | 3 500 bases à migrer, coût opérationnel prohibitif |
| Schéma PostgreSQL par boutique | Non | Migrations lentes au-delà de quelques centaines de schémas |
| **Schéma partagé + `boutique_id`** | **Oui** | Migrations uniques, requêtes transverses possibles pour la plateforme, coût maîtrisé |

### 3.2 — Trois barrières successives

Une seule fuite inter-boutiques dans un module comptable et le produit est mort commercialement.
D'où trois protections indépendantes, dont aucune n'est suffisante seule :

**Barrière 1 — Contexte de requête.** Un middleware résout la boutique courante (sous-domaine,
en-tête, appartenance de l'utilisateur) et la place dans une variable de contexte
(`contextvars`, sûre en asynchrone).

**Barrière 2 — Gestionnaire par défaut filtrant.** Tout modèle métier hérite de
`TenantScopedModel`, dont le gestionnaire par défaut filtre automatiquement sur la boutique
courante. Accéder à l'ensemble des données exige un gestionnaire explicite
(`objects_all_tenants`), réservé aux rôles plateforme et **journalisé**.

```python
class TenantScopedModel(BaseModel):
    boutique = models.ForeignKey("marketplace.Boutique", on_delete=models.PROTECT)

    objects = TenantManager()              # filtré sur la boutique courante
    objects_all_tenants = models.Manager() # non filtré, usage plateforme uniquement

    class Meta:
        abstract = True
```

**Barrière 3 — Sécurité au niveau ligne PostgreSQL.** *Implémentée* (`apps/core/rls.py`, migration
`core.0002`). Une politique sur **chacune des 24 tables scopées** compare `boutique_id` au réglage
de session `hypermarche.boutique_id`, posé par le contexte Python à chaque changement de boutique.
Même une requête SQL brute mal écrite ne franchit pas la frontière.

```sql
CREATE POLICY hm_isolation_boutique ON catalog_variante
    USING (boutique_id::text = current_setting('hypermarche.boutique_id', true)
           OR current_setting('hypermarche.boutique_id', true) = 'plateforme')
    WITH CHECK (…même condition…);
```

Trois choix qui décident de son efficacité :

1. **`FORCE ROW LEVEL SECURITY`.** Sans lui, le propriétaire des tables — c'est-à-dire le rôle
   applicatif — contourne toutes les politiques.
2. **Le rôle applicatif ne doit être ni `SUPERUSER` ni `BYPASSRLS`.** Ces attributs annulent la
   barrière **sans lever la moindre erreur** : les politiques existent, elles sont correctes, et
   elles ne s'appliquent à personne. C'est le piège le plus coûteux du dispositif ; `manage.py
   verifier_rls` et un test dédié le détectent.
3. **Réglage absent = rien n'est visible.** Un oubli de contexte produit une absence de données,
   jamais une fuite — exactement le choix déjà fait à la barrière 2.

Conséquence pour le code : `objects_all_tenants` ne contourne plus que le **gestionnaire**, jamais
la base. Un service de confiance doit désormais *annoncer* la boutique qu'il manipule
(`with contexte_boutique(...)`), et pas seulement la connaître.

### 3.3 — Tests d'isolation obligatoires

Un jeu de tests systématique vérifie, pour **chaque** modèle métier, qu'un utilisateur de la
boutique A ne peut ni lire, ni écrire, ni compter, ni agréger les données de la boutique B — par
l'ORM, par l'API et par l'admin. Ce jeu de tests est un critère de sortie du lot 0.

---

## 4. Le hors-ligne

L'arbitrage A12 en fait une contrainte d'architecture. Trois conséquences structurantes :

### 4.1 — Identifiants générés côté client

Toutes les clés primaires métier sont des **UUIDv7** (ordonnés dans le temps, donc indexables
efficacement), générés par le client. Une vente saisie hors ligne possède son identifiant définitif
avant même d'atteindre le serveur.

### 4.2 — Journal d'opérations idempotent

Le client n'envoie pas un état, il envoie une **suite d'opérations** :

```json
{
  "operation_id": "018f...c3",     // UUIDv7, clé d'idempotence
  "type": "pos.vente",
  "horodatage_client": "2027-03-14T09:12:44+01:00",
  "boutique_id": "018e...a1",
  "charge_utile": { "lignes": [...], "paiements": [...] }
}
```

Le serveur rejoue chaque opération **au plus une fois**. Une opération déjà appliquée renvoie le
résultat précédent. C'est ce qui rend la synchronisation sûre malgré les coupures et les
retransmissions.

### 4.3 — Résolution des conflits sur le stock

Le seul conflit réellement problématique : deux caisses vendent hors ligne le dernier article.

**Règle retenue : le stock peut devenir négatif, et c'est assumé.** Les deux ventes sont valides —
la marchandise est physiquement sortie. Le système enregistre un stock négatif, lève une
**anomalie d'inventaire** que le gérant régularise. Refuser une vente déjà encaissée serait pire
qu'un compteur temporairement faux.

En revanche, sont **interdits hors ligne** : la validation d'écritures comptables, l'émission de
bulletins de paie et la libération de séquestre. Ces opérations exigent le serveur.

---

## 5. Le noyau comptable

### 5.1 — Journal en ajout seul

```python
class EcritureComptable(TenantScopedModel):
    """Une écriture validée est immuable. Correction par contre-passation uniquement."""
    journal      = models.ForeignKey(Journal, on_delete=models.PROTECT)
    date_ecriture = models.DateField()
    piece        = models.CharField(max_length=32)          # séquence continue
    libelle      = models.CharField(max_length=255)
    validee      = models.BooleanField(default=False)
    contrepassee_par = models.OneToOneField("self", null=True, blank=True, ...)
    origine_type = models.CharField(max_length=64)          # "orders.Commande", "pos.Ticket"...
    origine_id   = models.UUIDField()                       # traçabilité descendante
```

Trois protections cumulées :

1. `save()` et `delete()` lèvent une exception si `validee=True`.
2. Un **trigger PostgreSQL** rejette tout `UPDATE`/`DELETE` sur une ligne validée — la base refuse
   même une requête brute.
3. Une contrainte de base garantit l'équilibre : **somme des débits = somme des crédits** pour
   chaque écriture.

### 5.2 — Génération automatique

Le module `accounting` s'abonne aux signaux de domaine et applique des **modèles d'écriture**
paramétrés (table de correspondance du [document 07](07-comptabilite-paie-syscohada.md), §3.4) :

```
orders.commande_livree ──▶ modèle « vente en ligne »   ──▶ 3 écritures
pos.ticket_cloture     ──▶ modèle « vente comptoir »   ──▶ 3 écritures
inventory.reception    ──▶ modèle « entrée en stock »  ──▶ 1 écriture
payroll.bulletin_emis  ──▶ modèle « paie »             ──▶ 2 écritures
```

La génération est **asynchrone mais transactionnelle** : la tâche Celery est publiée après
validation de la transaction métier (`transaction.on_commit`), et son échec déclenche une alerte
bloquante — jamais une perte silencieuse.

### 5.3 — Réconciliation permanente

Une tâche nocturne vérifie que, pour chaque boutique : toute vente possède ses écritures, tout
mouvement de stock est comptabilisé, la balance est équilibrée, et le solde théorique de trésorerie
correspond aux relevés PSP. Tout écart produit une anomalie affichée au gérant et au support.

---

## 6. Paiement : abstraction multi-PSP

L'analyse de Porter identifie le pouvoir des fournisseurs (MTN ≈ 55 %, Orange ≈ 45 %) comme le
risque externe le plus élevé. **Aucune dépendance à un opérateur unique n'est acceptable.**

```python
class PrestatairePaiement(Protocol):
    def initier(self, transaction: Transaction) -> ReponseInitiation: ...
    def statut(self, reference: str) -> StatutTransaction: ...
    def rembourser(self, reference: str, montant: Decimal) -> ReponseRemboursement: ...
    def verser(self, beneficiaire: str, montant: Decimal) -> ReponseVersement: ...
```

État : le contrat, le routage, le disjoncteur, le cycle de vie idempotent et un `FauxPrestataire`
déterministe sont écrits et testés (`apps/payments/`). Les **appels HTTP vers MTN, Orange et
Camtel ne le sont pas** : ils seront écrits contre un bac à sable d'opérateur, jamais à l'aveugle.
Sur un chemin où l'erreur s'appelle « double débit », du code vraisemblable et jamais exécuté est
pire que pas de code. Les adaptateurs existent donc en coquille et refusent avec un message
explicite tant qu'aucun identifiant n'est fourni.

**Correction d'une affirmation de ce document.** Il annonçait une « bascule automatique en cas
d'indisponibilité d'un opérateur ». C'est faux : le numéro du payeur *décide* de l'opérateur, et
un numéro MTN ne s'encaisse pas chez Orange. Ce qui bascule réellement, c'est le **généraliste** —
agrégateur ou passerelle carte, reconnaissable à sa liste de préfixes vide, qui accepte n'importe
quel numéro. À défaut, le routage refuse franchement et renvoie le commerçant vers les espèces,
plutôt que d'envoyer un paiement chez le mauvais opérateur.

Chaque appel sortant est protégé par un disjoncteur (*circuit breaker*) — son état est en mémoire
de processus, ce qui suffit tant qu'il n'y a qu'un serveur — et porte une **clé d'idempotence
obligatoire**, arbitrée par une contrainte d'unicité en base : un double débit est le pire incident
possible sur ce marché. La transaction est enregistrée et validée **avant** l'appel réseau : une
transaction SQL ouverte pendant un appel d'opérateur durerait le temps d'un délai réseau et
annulerait, à l'échec, la trace de cet échec.

---

## 7. Sécurité

| Domaine | Mesure |
|---|---|
| Authentification | Téléphone + mot de passe, OTP SMS, double facteur pour les rôles sensibles |
| Autorisation | Permissions granulaires par rôle **et** par boutique, vérifiées côté serveur systématiquement. Matrice en code (`apps/accounts/permissions.py`), porte unique (`apps/backoffice/acces.py`) : ce qu'un rôle n'ouvre pas n'est pas masqué à l'affichage, il n'est pas calculé |
| Isolation | Trois barrières (§3.2), jeu de tests d'isolation en intégration continue |
| Chiffrement | TLS partout ; pièces d'identité et coordonnées bancaires chiffrées au repos (`pgcrypto`) |
| Journal d'audit | Toute lecture de données sensibles et toute écriture métier journalisées, horodatées, inaltérables |
| Secrets | Jamais dans le dépôt ; variables d'environnement puis coffre dédié |
| Limitation de débit | Sur l'authentification, l'OTP, les API publiques, la création de comptes affiliés |
| Dépendances | Analyse automatique des vulnérabilités en intégration continue |
| Sauvegardes | Quotidiennes chiffrées, **restauration testée mensuellement** — une sauvegarde jamais restaurée n'existe pas |
| Données personnelles | Registre des consentements, export, anonymisation en cascade (document 08, §4) |

---

## 8. Performance et frugalité

Contraintes issues du terrain : 3G intermittente, données payantes, appareils d'entrée de gamme.

| Cible | Valeur | Moyen |
|---|---|---|
| Page catalogue | < 2,5 s sur 3G | HTMX, pas de SPA, images WebP progressives, pagination |
| Saisie d'une ligne de caisse | < 4 s | PWA hors ligne, aucun aller-retour réseau |
| Poids de la page marchand | < 400 Ko | Pas de framework front lourd |
| Application caisse | < 15 Mo | PWA, puis Android natif si nécessaire |
| Requêtes SQL par page | < 25 | `select_related`, `prefetch_related`, détection systématique des N+1 en tests |

**Une règle de conception structurante :** aucune page du back-office marchand ne doit exécuter de
requête dont le coût croît avec la taille de la boutique. Les agrégats (chiffre d'affaires du jour,
valeur du stock, marge) sont **précalculés et matérialisés**, pas recalculés à chaque affichage.

---

## 9. Environnements et livraison

| Environnement | Usage | Données |
|---|---|---|
| Local | Développement | Jeu de données de démonstration réaliste |
| CI | Tests automatisés | Éphémère |
| Recette | Validation métier, démonstrations commerciales | Anonymisées |
| Production | Exploitation | Réelles |

**Intégration continue** — la chaîne échoue si l'un des points suivants échoue :
formatage et analyse statique · tests unitaires · **tests d'isolation multi-tenant** · **tests
d'équilibre comptable** · **tests de non-régression des barèmes de paie** · analyse de
vulnérabilités · vérification des migrations réversibles.

**Livraison :** migrations toujours rétrocompatibles (ajout puis retrait en deux temps),
déploiement sans interruption, retour arrière possible en une commande.

---

## 10. Décisions d'architecture à consigner

Chaque décision structurante fait l'objet d'une fiche courte dans `docs/adr/`.

| # | Décision | Statut |
|---|---|---|
| ADR-001 | Monolithe modulaire Django plutôt que microservices | Actée (A12) |
| ADR-002 | Schéma partagé + `boutique_id` pour le multi-tenant | Actée (A12) |
| ADR-003 | Journal comptable en ajout seul, contre-passation obligatoire | Actée (A12) |
| ADR-004 | UUIDv7 générés côté client, journal d'opérations idempotent | Actée (A12) |
| ADR-005 | Stock négatif autorisé, régularisation par inventaire | Actée |
| ADR-006 | Abstraction multi-PSP, aucune dépendance à un opérateur | Actée |
| ADR-007 | HTMX plutôt qu'une SPA sur le front marchand | Actée |
| ADR-008 | Localisation de l'hébergement | **En attente de J4** (document 08) |
| ADR-009 | Moteur de recherche : PostgreSQL d'abord, OpenSearch sur preuve | Actée |
