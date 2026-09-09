# ADR-002 — Schéma partagé + `boutique_id`, protégé par trois barrières

**Statut :** Actée · **Arbitrage :** A12 (docs/04, §10) · **Détail :** docs/09, §3

---

## Contexte

Chaque marchand loue un emplacement numérique et n'a aucune raison de voir les données d'un
autre. Trois façons d'isoler des locataires dans PostgreSQL :

| Approche | Isolation | Coût |
|---|---|---|
| Une base par boutique | Totale | Ingérable : une migration à répéter *n* fois, un pool de connexions par base |
| Un schéma par boutique | Forte | Le catalogue PostgreSQL s'effondre à quelques milliers de schémas ; les migrations restent multipliées |
| Schéma partagé + discriminant | À construire | Une migration, un pool — et **toute la responsabilité de l'isolation portée par le code** |

L'objectif est de dix mille boutiques (docs/03). Les deux premières approches sont hors jeu à
cette échelle. La troisième est retenue **à condition de traiter honnêtement son défaut** : dans
un schéma partagé, un `filter()` oublié est une fuite de données entre commerçants concurrents.

## Décision

Schéma partagé, colonne `boutique_id` sur tout modèle métier (`TenantScopedModel`), et **trois
barrières indépendantes** plutôt qu'une seule.

**Barrière 1 — le contexte de requête** (`apps/core/tenancy.py`). Une `ContextVar` porte la
boutique courante. Une `ContextVar` et non une variable globale ni un attribut de thread : elle
survit à l'asynchrone et se propage correctement dans une tâche Celery.

**Barrière 2 — le gestionnaire par défaut filtrant.** `objects` est un `TenantManager` qui
applique le contexte à chaque requête. La règle qui compte est le comportement en l'absence de
contexte : **`.none()`, pas `.all()`.** Un oubli produit une absence de données, visible et
signalée par les utilisateurs, jamais une fuite silencieuse.

**Barrière 3 — la sécurité au niveau ligne PostgreSQL** (`apps/core/rls.py`, migration
`core.0002`). Une politique par table scopée, comparant `boutique_id` à un réglage de session
que le contexte Python pousse sur la connexion. Les deux premières barrières protègent le code
qui les respecte ; celle-ci protège de tout le reste — un `objects_all_tenants` mal filtré, une
requête brute, un script d'exploitation, un client `psql`.

Écarté : se contenter des deux barrières Python. Elles sont contournables par accident, et
l'accident est précisément le scénario à couvrir.

## Conséquences

**`objects_all_tenants` ne contourne plus que le gestionnaire.** Un service de confiance qui
manipule une boutique doit désormais l'annoncer à la base :

```python
with contexte_boutique(boutique_id):
    Journal.objects_all_tenants.get_or_create(...)
```

C'est une contrainte, et c'est le but : le tenant manipulé devient explicite partout, y compris
dans le code qui croyait pouvoir s'en passer.

**Le contexte s'établit autour de la transaction, jamais dedans.** Un `SET` PostgreSQL est
transactionnel. Posé à l'intérieur d'un bloc atomique qui échoue, sa restauration se heurterait à
une transaction en erreur et masquerait l'exception d'origine par une erreur de plomberie. D'où
la forme systématique des services : une fonction publique qui établit le contexte, un corps
privé `@transaction.atomic`.

**Le réglage de session n'est jamais mémorisé.** Un `SET` disparaît au `ROLLBACK` ; un cache
applicatif, non. Les deux divergeraient au premier échec de transaction, et les requêtes
suivantes ne verraient plus rien — ou verraient la mauvaise boutique. Une requête minuscule à
chaque frontière de contexte coûte moins cher que ce risque.

**Le rôle applicatif ne doit être ni `SUPERUSER` ni `BYPASSRLS`.** Ces deux attributs annulent
toutes les politiques **sans lever la moindre erreur**. C'est le piège le plus coûteux du
dispositif : il n'apparaît ni dans le code, ni dans le schéma, seulement dans les attributs du
rôle. Lors de la première mise en place, la suite complète est passée sans qu'une seule ligne ne
change de comportement — le rôle était superutilisateur, et les tests d'isolation passaient
triomphalement en ne testant rien. `infrastructure/postgres/01-role-applicatif.sql` retire
l'attribut à l'initialisation, `make securite` refuse de valider si le rôle l'a récupéré.

## Vérification

- `tests/test_isolation_tenant.py` — les trois barrières, dont `objects_all_tenants` qui ne
  franchit plus la base.
- `tests/test_rls_postgres.py` — la barrière 3 sur un vrai PostgreSQL : lecture bornée, écriture
  chez le voisin rejetée par le `WITH CHECK`, mise à jour d'une ligne invisible sans effet, et
  **le rôle qui ne doit pas contourner la sécurité**.
- `python manage.py verifier_rls` (`make securite`) — l'état réel lu dans le catalogue
  PostgreSQL, et la liste des modèles scopés qui ne seraient pas déclarés.

Sur SQLite, la barrière 3 n'existe pas et ces tests sont ignorés. C'est pourquoi une exécution
qui affiche des tests ignorés ne prouve pas l'isolation : elle l'a contournée.
