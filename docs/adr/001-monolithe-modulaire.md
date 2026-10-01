# ADR-001 — Monolithe modulaire Django plutôt que microservices

**Statut :** Actée · **Arbitrage :** A12 (docs/04, §10) · **Détail :** docs/09, §2

---

## Contexte

L'équipe d'ingénierie de la première année compte cinq personnes (docs/11, §9). Le produit couvre
la caisse, le stock, la comptabilité, les paiements et l'affiliation — cinq domaines qui,
découpés en services, produiraient cinq déploiements, cinq bases, et autant de frontières
réseau à gérer.

Le découpage en microservices est souvent présenté comme la trajectoire par défaut. Il a un
prérequis que ce projet n'a pas : **des équipes assez nombreuses pour que la coordination
humaine coûte plus cher que la coordination technique.** À cinq personnes, c'est l'inverse.

Une contrainte du domaine tranche plus fermement encore. La clôture d'un ticket de caisse écrit
une sortie de stock au coût moyen pondéré **et** les écritures comptables correspondantes
(`apps/pos/services.py`, `cloturer_ticket`). Ces deux effets doivent être atomiques : un stock
sorti sans écriture, ou une écriture sans sortie, produit une comptabilité fausse qu'aucun
rapprochement ultérieur ne rattrape. Dans un monolithe, c'est une transaction. Entre services,
c'est une saga, avec son état intermédiaire, ses compensations et ses cas non couverts.

## Décision

Un seul projet Django, découpé en applications par domaine, avec **un graphe de dépendances
orienté et respecté** : `core` → `accounts` → `marketplace` → `catalog` → `inventory` → `pos` →
`orders` → `payments` → `accounting` → `affiliation` → `backoffice`. L'ordre de `LOCAL_APPS`
dans `config/settings.py` est exactement cet ordre, et il n'est pas décoratif : une application
ne doit jamais importer une application située plus bas.

Écarté : des services séparés par domaine. Écarté aussi : un monolithe non découpé, où
`pos` importerait `accounting` au chargement des modèles — la modularité interne est ce qui
rendra une extraction possible le jour où elle se justifiera.

## Conséquences

**Ce que cela donne.** Une transaction de base de données suffit là où il aurait fallu une saga.
Un déploiement au lieu de dix. Un test d'intégration qui traverse réellement la chaîne
caisse → stock → comptabilité, en mémoire, en quelques millisecondes.

**Ce que cela impose.** Le graphe de dépendances n'est tenu que par la discipline. Quand `pos`
doit appeler `accounting`, l'import se fait **à l'intérieur de la fonction**, pas en tête de
module :

```python
# apps/pos/services.py — dans cloturer_ticket()
from apps.accounting.services import comptabiliser_ticket
```

Ce n'est pas un contournement, c'est la forme que prend la règle : le sens de la dépendance reste
`accounting` ← `pos` au chargement des modèles, et l'appel descendant est explicite et localisé.

**Ce que cela coûte.** Une montée en charge se fait par réplication du monolithe entier, pas par
service. Tant que le goulot est PostgreSQL — ce qui est le cas et le restera longtemps — cela ne
change rien. Le jour où un domaine justifiera son extraction, le découpage en applications et le
graphe de dépendances rendront l'opération mécanique plutôt qu'archéologique.

## Vérification

`python manage.py check` et l'exécution de la suite valident le graphe indirectement : une
dépendance circulaire entre applications se manifeste par un `ImportError` au chargement. C'est
une vérification faible — c'est la relecture qui tient réellement cette décision.
