# Décisions d'architecture

Une fiche par décision structurante, c'est-à-dire par décision **coûteuse à défaire**. Le critère
d'entrée est celui-là et pas un autre : un choix de bibliothèque se change en une semaine et n'a
rien à faire ici ; un choix de modèle de données se paie en migrations, en reprises de code et
parfois en données perdues.

Chaque fiche répond à quatre questions, dans cet ordre :

1. **Contexte** — la contrainte qui existait avant la décision. Le lecteur qui arrive dans deux ans
   doit pouvoir juger si elle tient encore.
2. **Décision** — ce qui a été retenu, et ce qui a été écarté. Une décision sans alternative
   écartée n'est pas une décision, c'est un constat.
3. **Conséquences** — ce que cela impose au code, y compris ce que cela coûte.
4. **Vérification** — l'endroit du dépôt où la décision est **tenue par un test**, quand elle peut
   l'être. Une fiche que rien ne vérifie décrit une intention, pas une architecture.

## Registre

| # | Décision | Statut |
|---|---|---|
| [ADR-001](001-monolithe-modulaire.md) | Monolithe modulaire Django plutôt que microservices | Actée (A12) |
| [ADR-002](002-multi-tenant-schema-partage.md) | Schéma partagé + `boutique_id`, protégé par trois barrières | Actée (A12) |
| [ADR-003](003-journal-comptable-ajout-seul.md) | Journal comptable en ajout seul, contre-passation obligatoire | Actée (A12) |
| [ADR-004](004-uuidv7-et-idempotence.md) | UUIDv7 générés côté client, journal d'opérations idempotent | Actée (A12) |
| [ADR-005](005-stock-negatif-autorise.md) | Stock négatif autorisé, régularisation par inventaire | Actée |
| [ADR-006](006-abstraction-multi-prestataire.md) | Abstraction multi-prestataire de paiement | Actée |
| [ADR-007](007-htmx-plutot-qu-une-spa.md) | HTMX plutôt qu'une SPA sur le front marchand | Actée |
| [ADR-008](008-localisation-de-l-hebergement.md) | Localisation de l'hébergement | **En attente** (jalon J4) |
| [ADR-009](009-recherche-postgresql-d-abord.md) | Recherche : PostgreSQL d'abord, OpenSearch sur preuve | Actée |
| [ADR-010](010-jeton-d-api-porteur-de-la-boutique.md) | Le jeton d'API porte la boutique, le client ne la déclare pas | Actée |
| [ADR-011](011-equivalence-deduite-des-designations.md) | L'équivalence entre articles se déduit des désignations partagées | Actée |

## Statuts

**Actée** — appliquée dans le code. La fiche décrit ce qui existe.

**En attente** — la décision est identifiée, ses options sont posées, et **il manque un fait
extérieur** pour trancher. Une fiche en attente nomme ce fait et le jalon qui l'apportera ; elle
n'invente pas une réponse provisoire, parce qu'une réponse provisoire est appliquée comme une
réponse définitive.

**Remplacée** — une décision ultérieure l'a annulée. La fiche reste, avec un renvoi vers celle qui
la remplace. On ne supprime pas une fiche : le raisonnement écarté fait partie de l'histoire du
système, et il revient dans les discussions tous les six mois.
