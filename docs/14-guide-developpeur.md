# 14 — Guide du développeur

Mise en route du socle technique et règles à respecter dans le code.

---

## 1. Démarrage

```bash
make installer          # environnement virtuel + dépendances
cp .env.example .env    # puis adapter

docker compose up -d db redis   # PostgreSQL 16 + Redis
make migrer
make demo               # référentiels + 2 boutiques de démonstration
make servir             # http://localhost:8000/admin/
```

Sans `DATABASE_URL`, le projet bascule sur SQLite. C'est commode pour lancer les tests sans
infrastructure, **et ce n'est jamais acceptable en production** : les triggers qui rendent le
journal comptable inaltérable ne s'y installent pas.

```bash
make tester      # 67 tests
make verifier    # contrôles Django + détection de migration manquante
```

Comptes de démonstration (mot de passe `demo1234`) :

| Téléphone | Rôle |
|---|---|
| `+237699110011` | Gérant, Quincaillerie Ateba (Douala) |
| `+237677220022` | Gérante, Bella Cosmétiques (Yaoundé) |

Pour l'administration : `python manage.py createsuperuser` (l'identifiant est le téléphone).

---

## 2. Structure

```
config/            réglages, urls, celery
apps/
  core/            modèles de base, tenancy, audit, synchronisation, consentements
  accounts/        utilisateurs (identifiés par téléphone), rôles, appartenances, KYC
  marketplace/     rayons, types d'emplacement, boutiques, baux, loyers
  catalog/         référentiel mutualisé, produits, variantes
  inventory/       dépôts, mouvements, CMP, inventaires   ★
  pos/             caisse, sessions, tickets                ★
  orders/          commandes, sous-commandes, retours
  payments/        prestataires, transactions, séquestre, portefeuilles
  accounting/      plan SYSCOHADA, journaux, écritures, balance
  affiliation/     filiation, attribution, commissions, revendeurs
tests/             tests transverses (isolation, CMP, comptabilité, affiliation)
docs/              dossier projet
```

★ Briques critiques : c'est sur elles que repose tout le reste (docs/04, §9).

---

## 3. Les cinq règles à ne jamais enfreindre

### 3.1 — Toute donnée métier appartient à une boutique

Un modèle métier hérite de `TenantScopedModel`. Son gestionnaire par défaut est filtré sur la
boutique courante.

```python
from apps.core.tenancy import contexte_boutique, contexte_plateforme

with contexte_boutique(boutique):
    Produit.objects.count()      # borné à cette boutique

with contexte_plateforme():
    Produit.objects.count()      # accès transverse, à justifier et journaliser

Produit.objects.count()          # hors contexte : renvoie 0, jamais tout
```

**Dans les vues**, on s'appuie sur le contexte : c'est le garde-fou. **Dans les services**, on
filtre explicitement avec `objects_all_tenants` et un `boutique_id` connu : le code de confiance
sait quel tenant il manipule, et ne doit pas dépendre d'un contexte ambiant.

Attention : les gestionnaires inverses (`ticket.lignes`, `ecriture.lignes`) héritent du
gestionnaire filtré. Dans un service, préférer
`LigneTicket.objects_all_tenants.filter(ticket=ticket)`.

### 3.2 — Le journal comptable est en ajout seul

Aucune écriture validée n'est modifiée ni supprimée. On corrige par contre-passation :

```python
from apps.accounting.services import contrepasser, passer_ecriture

ecriture = passer_ecriture(
    boutique_id=boutique.pk,
    code_journal="OD",
    date_ecriture=date.today(),
    libelle="Régularisation",
    lignes=[("571", Decimal("1000"), Decimal("0")),
            ("701", Decimal("0"), Decimal("1000"))],
)
contrepasser(ecriture, motif="Erreur de saisie")
```

Toute conception permettant un `UPDATE` ou un `DELETE` sur une écriture validée est **rejetée en
revue de code**. Trois protections : le code Python, un trigger PostgreSQL, une contrainte
d'équilibre.

### 3.3 — Le stock est un journal, pas un compteur

`MouvementStock` est la source de vérité ; `NiveauStock` n'est qu'un agrégat reconstructible.
Aucune écriture directe sur `NiveauStock` : tout passe par `apps.inventory.services`.

```python
from apps.inventory.services import entrer_stock, sortir_stock, transferer_stock

entrer_stock(depot=depot, variante=variante, quantite=10, cout_unitaire=Decimal("6800"))
sortir_stock(depot=depot, variante=variante, quantite=3)
```

Le stock peut devenir négatif (ADR-005) : c'est une anomalie à régulariser, pas une erreur à
bloquer. Refuser une vente déjà encaissée serait pire qu'un compteur temporairement faux.

### 3.4 — Toute opération issue du terrain porte une clé d'idempotence

La caisse fonctionne hors ligne ; une opération est retransmise autant de fois qu'il le faut. Le
serveur doit la rejouer **au plus une fois**.

```python
entrer_stock(..., operation_id=uuid_du_client)   # rejouable sans effet de bord
caisse.cloturer_ticket(ticket)                    # idempotent
```

### 3.5 — Les dépendances entre applications ne remontent jamais

`catalog` ne connaît pas `orders`. `core` ne connaît personne. La communication montante passe par
un import tardif dans un service ou par un signal de domaine, jamais par un import de module.

---

## 4. Recettes courantes

**Ouvrir une boutique de bout en bout**

```python
from apps.accounting.referentiel import initialiser_boutique

boutique = Boutique.objects.create(...)
Bail.objects.create(boutique=boutique, ..., etat=Bail.ACTIF)
initialiser_boutique(boutique)   # plan de comptes, journaux, exercice ouvert
```

**Encaisser une vente au comptoir** — une seule chaîne produit stock et comptabilité :

```python
from apps.pos import services as caisse

session = caisse.ouvrir_session(depot=depot, caissier=utilisateur)
ticket = caisse.creer_ticket(session=session)
caisse.ajouter_ligne(ticket=ticket, variante=variante, quantite=2)
ticket.refresh_from_db()
caisse.regler(ticket=ticket, moyen="especes", montant=ticket.total_ttc)
caisse.cloturer_ticket(ticket)   # → sortie de stock au CMP + 3 écritures
```

**Lire une balance**

```python
from apps.accounting.services import balance, solde_compte

balance(boutique_id=boutique.pk)
solde_compte("701", boutique_id=boutique.pk)   # chiffre d'affaires (au crédit, donc négatif)
```

---

## 5. Ce que la suite de tests protège

| Fichier | Protège |
|---|---|
| `test_isolation_tenant.py` | **Critère bloquant du lot 0** : aucun accès croisé entre boutiques, y compris par un simple compteur ou une somme |
| `test_stock_cmp.py` | Valorisation CMP, stock négatif assumé, immuabilité des mouvements, idempotence hors ligne, inventaires |
| `test_comptabilite.py` | Équilibre débit/crédit, immuabilité, contre-passation, chaîne caisse → stock → écritures, marge brute calculable |
| `test_affiliation.py` | Filiation à 2 niveaux, plafond de 35 %, séparation des sources de financement, délai de retour avant acquisition |
| `test_journal_ajout_seul_postgres.py` | Le trigger résiste au SQL brut (ignoré sur SQLite) |

Un test qui échoue dans `test_isolation_tenant.py` ou dans les invariants d'affiliation n'est
jamais « à ajuster » : c'est une règle produit ou juridique qui vient d'être enfreinte.

---

## 6. Reste à faire sur le socle

| Sujet | État | Référence |
|---|---|---|
| Sécurité au niveau ligne (`RLS`) PostgreSQL | **Non implémentée.** Barrières 1 et 2 en place ; la 3ᵉ attend le paramètre de session porté par la connexion | docs/09, §3.2 |
| API REST (DRF) | Sérialiseurs et vues à écrire | docs/05 |
| Application caisse (PWA hors ligne) | Modèle et service serveur prêts ; client à construire | docs/09, §4 |
| Adaptateurs Mobile Money | Interface définie ; implémentations MTN/Orange/Camtel à écrire | docs/09, §6 |
| Logistique, RH, paie, retail media | Lots 2 à 5 | docs/11 |
| Fiches ADR dans `docs/adr/` | À créer à partir du tableau du docs/09, §10 | docs/09 |
