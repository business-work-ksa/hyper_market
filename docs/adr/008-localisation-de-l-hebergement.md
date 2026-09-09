# ADR-008 — Localisation de l'hébergement

**Statut : EN ATTENTE** — jalon J4 · **Détail :** docs/08, §4.4 ; docs/09, §8

---

## Contexte

La loi camerounaise n° 2024/017 encadre le transfert de données personnelles hors du Cameroun.
Les conditions exactes — et l'existence même d'une obligation de localisation — doivent être
établies par un conseil en protection des données auprès de l'autorité compétente. C'est le
jalon **J4** du document 08, §9, positionné avant le lot 1.

Deux options se dessinent, et elles ne se départagent pas sur des critères techniques :

| Option | Ce qu'elle apporte | Ce qu'elle coûte |
|---|---|---|
| Hébergement local (centre de données camerounais) | Conformité maximale, latence faible, argument commercial et souverain | Coût, disponibilité, qualité de service variable |
| Cloud régional (Afrique du Sud, Europe) avec clauses de transfert | Fiabilité, élasticité, outillage | Risque réglementaire, latence, dépendance |

## Pourquoi cette fiche reste ouverte

**Parce qu'il manque un fait, pas une analyse.** Trancher aujourd'hui reviendrait à parier sur
une interprétation du droit, et un pari de ce genre est appliqué comme une certitude par tout le
code qui vient ensuite. Si le pari est perdu, ce n'est pas une migration d'infrastructure qu'il
faut faire : c'est un déménagement de données personnelles sous contrainte réglementaire, avec
notification et, potentiellement, interruption de service.

Une fiche en attente qui nomme son point de blocage vaut mieux qu'une fiche actée qui invente une
réponse.

## La décision qui, elle, est prise

**L'architecture est conçue pour être portable, et cette contrainte s'applique dès maintenant.**
C'est ce qui permet d'attendre J4 sans bloquer le développement.

Concrètement, dans le code tel qu'il existe :

- **Aucune adhérence à un service propriétaire non substituable.** PostgreSQL, Redis et un
  stockage d'objets compatible S3 — trois briques disponibles chez tous les hébergeurs et
  installables sur un serveur nu.
- **Aucune fonction gérée dont l'équivalent n'existe ailleurs** : pas de base de données
  propriétaire, pas de file d'attente maison, pas de moteur de recherche géré (voir ADR-009, qui
  reporte OpenSearch pour cette raison autant que pour son coût).
- **La configuration passe par des variables d'environnement** (`DATABASE_URL`, `REDIS_URL`) :
  changer d'hébergeur ne modifie aucun fichier de code.
- **Le déploiement est décrit par `docker compose`**, y compris l'initialisation du rôle
  PostgreSQL applicatif. Ce qui tourne en développement tourne ailleurs.

## Ce qui déclenchera la clôture de cette fiche

Le rendu du conseil J4. La fiche sera alors mise à jour avec l'option retenue, la base légale qui
la fonde, et — si c'est le cloud régional — le texte des clauses de transfert effectivement
signées.

En attendant, **aucun composant ne doit être ajouté qui ne serait pas déplaçable.** C'est le
critère à opposer à toute proposition d'infrastructure d'ici là.
