# ADR-009 — Recherche : PostgreSQL d'abord, OpenSearch sur preuve

**Statut :** Actée · **Détail :** docs/09, §1

---

## Contexte

Un catalogue se cherche, et la recherche est un domaine où l'outil spécialisé — OpenSearch,
Elasticsearch — est presque toujours proposé d'emblée. Il apporte de vraies capacités :
tolérance aux fautes de frappe, pertinence réglable, facettes, suggestions.

Il apporte aussi, invariablement : un second magasin de données à alimenter, donc un pipeline de
synchronisation, donc une incohérence possible entre ce qui est en base et ce qui est indexé ;
une grappe à dimensionner, surveiller et mettre à jour ; et une dépendance d'infrastructure de
plus, ce qui contrarie directement l'exigence de portabilité de l'ADR-008.

Ce coût se justifie à partir d'un certain volume et d'une certaine exigence de pertinence.
**Rien ne dit qu'on y est.** À l'ouverture, le catalogue d'une boutique compte quelques centaines
à quelques milliers de références.

## Décision

**PostgreSQL d'abord**, avec `pg_trgm` et des index GIN pour la recherche approximative sur les
libellés et les codes-barres. OpenSearch n'est ajouté que **sur preuve** : une mesure de latence
sur des volumes réels, pas une intuition sur des volumes futurs.

Écarté : intégrer OpenSearch dès la conception « puisqu'il faudra bien y venir ». C'est la
formulation qui installe le plus de complexité inutile dans les systèmes, parce qu'elle
ressemble à de la prévoyance.

## Conséquences

**Un seul magasin de données, donc aucune incohérence de synchronisation possible.** Un produit
créé est immédiatement cherchable, dans la même transaction. C'est un avantage de correction, pas
seulement d'exploitation : il n'existe pas d'état où l'index et la base disent des choses
différentes.

**La barrière 3 s'applique à la recherche comme au reste.** Une recherche exécutée dans
PostgreSQL est soumise aux politiques d'isolation au niveau ligne (ADR-002). Un index externe
n'aurait aucune de ces protections : il faudrait réimplémenter le filtrage par boutique dans les
requêtes de recherche, et un oubli y serait une fuite entre commerçants concurrents — exactement
le risque que la barrière 3 existe pour couvrir.

C'est l'argument le plus fort de cette décision, et il n'apparaît pas dans les comparatifs
habituels.

**Ce qu'on n'a pas.** La pertinence de `pg_trgm` est correcte, pas excellente : elle tolère les
fautes de frappe et ignore la sémantique. Pour un catalogue de quincaillerie ou de cosmétiques,
où l'on cherche « ciment » ou un code-barres, c'est suffisant. Pour de la recherche en langue
naturelle sur un catalogue de plusieurs millions de références, non.

## Le seuil de bascule

À définir sur mesure, pas sur intuition. Les indicateurs à surveiller :

- latence de recherche au 95ᵉ centile au-delà de ~300 ms sur le catalogue réel ;
- taux de recherches sans résultat élevé alors que le produit existe ;
- besoin de facettes ou de tri par pertinence multi-critères que SQL rend illisible.

Tant qu'aucun de ces trois n'est constaté **en production**, la décision tient.
