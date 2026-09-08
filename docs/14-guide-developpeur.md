# 14 — Guide du développeur

Mise en route du socle technique et règles à respecter dans le code.

---

## 1. Démarrage

```bash
make installer          # environnement virtuel + dépendances
cp .env.example .env    # DEBUG=True, sinon les fichiers statiques ne sont pas servis

docker compose up -d db redis   # PostgreSQL 16 + Redis
make migrer
make demo               # référentiels + 2 boutiques de démonstration
make servir             # http://localhost:8000/
```

Sans `DATABASE_URL`, le projet bascule sur SQLite. C'est commode pour lancer les tests sans
infrastructure, **et ce n'est jamais acceptable en production** : ni les triggers qui rendent le
journal comptable inaltérable, ni les politiques d'isolation au niveau ligne ne s'y installent.
Sur SQLite, 17 tests sont ignorés — ceux qui attaquent la base par en dessous.

```bash
make tester      # 190 tests (17 ignorés sur SQLite)
make verifier    # contrôles Django + détection de migration manquante
make securite    # la barrière 3 est-elle réellement active ?
```

> **Le rôle applicatif ne doit être ni `SUPERUSER` ni `BYPASSRLS`.** Ces attributs annulent les
> politiques d'isolation **sans lever la moindre erreur** : tout fonctionne, les tests passent, et
> plus rien n'est isolé. `docker compose` s'en charge (`infrastructure/postgres/`) ; sur une base
> existante, `ALTER ROLE <role> NOSUPERUSER NOBYPASSRLS CREATEDB;`, puis `make securite`.

Comptes de démonstration (mot de passe `demo1234`) :

| Téléphone | Rôle | Ce qu'il voit |
|---|---|---|
| `+237699110011` | Gérant, Quincaillerie Ateba (Douala) | Tout |
| `+237699110022` | Caissière, Quincaillerie Ateba | Caisse, ventes, stock — **ni coût, ni marge** |
| `+237699110033` | Magasinier, Quincaillerie Ateba | Stock et coûts d'achat — **pas la marge**, pas la caisse |
| `+237677220022` | Gérante, Bella Cosmétiques (Yaoundé) | Tout |
| `+237677220033` | Comptable, Bella Cosmétiques | Comptabilité, marge, export — pas le stock |

Se connecter successivement avec ces comptes est le moyen le plus rapide de voir
ce que la matrice de droits change réellement à l'écran.

Pour l'administration : `python manage.py createsuperuser` (l'identifiant est le téléphone).

---

## 2. Structure

```
config/            réglages, urls, celery
apps/
  core/            modèles de base, tenancy, audit, synchronisation, consentements
  accounts/        utilisateurs (identifiés par téléphone), rôles, appartenances, KYC
                   permissions.py — matrice des droits, source de vérité      ★
  marketplace/     rayons, types d'emplacement, boutiques, baux, loyers
  catalog/         référentiel mutualisé, produits, variantes
  inventory/       dépôts, mouvements, CMP, inventaires   ★
  pos/             caisse, sessions, tickets                ★
  orders/          commandes, sous-commandes, retours
  payments/        prestataires, transactions, séquestre, portefeuilles
  accounting/      plan SYSCOHADA, journaux, écritures, balance
  affiliation/     filiation, attribution, commissions, revendeurs
  backoffice/      vues et formulaires du back-office marchand
                   acces.py — boutique courante, dépôt courant, porte des droits
                   vues_equipe.py — embauche, rôles, retrait d'accès
static/            CSS écrit à la main, service worker, file hors ligne (IndexedDB),
                   pilote d'imprimante thermique ESC/POS, icônes
templates/         gabarits Django
scripts/           captures d'écran et vérification du mode hors ligne
tests/             tests transverses (isolation, droits, CMP, comptabilité, affiliation, dépôts)
docs/              dossier projet
```

★ Briques critiques : c'est sur elles que repose tout le reste (docs/04, §9).

---

## 3. Les six règles à ne jamais enfreindre

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

**Mais `objects_all_tenants` ne contourne que le gestionnaire, jamais la base.** Sur PostgreSQL,
la barrière 3 (`apps/core/rls.py`) filtre au niveau de la ligne, et un service qui n'annonce pas sa
boutique ne voit rien et n'écrit rien. Un service de confiance qui reçoit un tenant explicite
l'établit donc autour de sa transaction :

```python
def passer_ecriture(*, boutique_id, **arguments):
    with contexte_boutique(boutique_id):      # autour, jamais dedans : un SET est transactionnel
        return _passer_ecriture(boutique_id=boutique_id, **arguments)
```

Connaître son tenant ne suffit plus : il faut le déclarer.

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

### 3.6 — Un écran ne décide jamais seul de ce qu'il montre

Le rattachement à une boutique n'est pas un droit sur tout ce qu'elle contient. Toute vue passe par
la porte, et tout affichage sensible lit le **même** ensemble de droits qu'elle :

```python
from apps.accounts import permissions as droit
from apps.backoffice.acces import contexte_commun, exige, exige_json

@exige(droit.STOCK_MOUVEMENTER)          # connexion + boutique + droit, avant la vue
def entree_stock(request, variante_id):
    contexte = contexte_commun(request, "stock")   # porte `droits` aux gabarits
    ...

@exige_json(droit.CAISSE_ENCAISSER)      # refus en JSON : la file hors ligne lit le code
def caisse_encaisser(request):
    ...
```

```django
{% if 'cout.voir' in droits %}<td class="num">{{ niveau.cmp|fcfa }}</td>{% endif %}
```

Deux points qui ne se négocient pas :

- **La source de vérité est `apps/accounts/permissions.py`, en code.** `Role.permissions` en base
  n'en est qu'un miroir d'affichage, jamais relu pour décider : une table modifiable à chaud n'a
  pas à pouvoir ouvrir la marge à un caissier.
- **Masquer ne suffit pas : on ne calcule pas.** Le tableau de bord d'un magasinier ne contient pas
  de marge cachée en CSS — la valeur n'est jamais mise dans le contexte. Un `display:none` voyage
  quand même sur le réseau et se lit dans la source de la page.

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
| `test_rls_postgres.py` | **Barrière 3** : la base refuse ce que le code aurait pu laisser passer — isolation en SQL brut, `WITH CHECK` à l'insertion, rôle sans privilège de contournement, couverture de toutes les tables scopées |
| `test_backoffice.py` | Isolation vue par le navigateur, chaîne d'encaissement, géométrie du graphe |
| `test_backoffice_gestion.py` | Reprise de stock, inventaire, session de caisse, ticket, export |
| `test_permissions.py` | **Frontière d'exposition** : matrice des droits, porte des écrans, coût et marge absents des pages où ils n'ont rien à faire |
| `test_multi_depots.py` | Dépôt courant, transferts, quota d'ouverture, réception hors ligne idempotente, catalogue JSON |
| `test_equipe.py` | Embauche, changement de rôle, retrait d'accès — **un accès se retire, un compte ne se supprime pas** ; les garde-fous qui empêchent un gérant de se fermer la porte |

Le mode hors ligne ne se teste pas là : `node scripts/verifier-hors-ligne.js` coupe réellement le
réseau du navigateur et rejoue le parcours d'un caissier en panne de connexion.

Un test qui échoue dans `test_isolation_tenant.py`, `test_permissions.py`, `test_rls_postgres.py`
ou dans les invariants d'affiliation n'est jamais « à ajuster » : c'est une règle produit ou
juridique qui vient d'être enfreinte. Dans les trois premiers cas, c'est une fuite de données.

---

## 6. Reste à faire sur le socle

| Sujet | État | Référence |
|---|---|---|
| API REST (DRF) | Sérialiseurs et vues à écrire | docs/05 |
| Adaptateurs Mobile Money | Interface définie ; implémentations MTN/Orange/Camtel à écrire | docs/09, §6 |
| Impression thermique hors Bluetooth LE | Le pilote ESC/POS couvre le Bluetooth basse consommation sur Chromium ; USB, Wi-Fi, SPP et iOS demandent une application native | docs/18, §9 |
| Logistique, RH, paie, retail media | Lots 2 à 5 | docs/11 |
| Fiches ADR dans `docs/adr/` | À créer à partir du tableau du docs/09, §10 | docs/09 |
