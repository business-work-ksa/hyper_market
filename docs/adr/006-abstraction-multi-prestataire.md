# ADR-006 — Abstraction multi-prestataire de paiement

**Statut :** Actée · **Détail :** docs/09, §6 ; `apps/payments/adaptateurs.py`

---

## Contexte

MTN et Orange se partagent l'essentiel du Mobile Money camerounais. Le pouvoir de négociation
qui en découle est identifié comme **le risque externe le plus élevé du projet** (docs/02, §3.3) :
un opérateur qui double sa commission, ferme un accès ou impose une exclusivité met la plateforme
en difficulté du jour au lendemain.

Une dépendance à un opérateur unique n'est donc pas acceptable, et — c'est le point qui engage le
code — **aucun code métier ne doit connaître le nom d'un prestataire.**

## Décision

Un contrat d'adaptateur (`PrestatairePaiement`) à quatre opérations — initier, statut,
rembourser, verser — et un registre qui associe un code de prestataire à son implémentation. Le
code métier appelle `adaptateur_pour(code)` et ne sait rien d'autre. Un déploiement réel remplace
une entrée par `enregistrer_adaptateur`, sans toucher au métier.

Autour du contrat, trois éléments qui appartiennent à la plateforme et non aux opérateurs :

- **Le routage par préfixe** (`choisir_prestataire`), avec le préfixe le plus long prioritaire :
  `650` appartient à MTN alors que `65` ne dit rien.
- **Le disjoncteur** (`Disjoncteur`) : trois échecs consécutifs coupent les appels vers un
  prestataire pendant trente secondes, puis un appel de demi-ouverture teste le retour. Sans lui,
  une panne d'opérateur fige les caisses, chaque encaissement attendant l'expiration du délai
  réseau.
- **Le cycle de vie de la transaction** : clé d'idempotence unique en base, états terminaux
  irréversibles.

### Une affirmation retirée

Le document 09 §6 annonçait une « bascule automatique en cas d'indisponibilité d'un opérateur ».
**C'était faux, et cela a été corrigé.** Le numéro du payeur décide de l'opérateur : un numéro MTN
ne s'encaisse pas chez Orange. Ce n'est pas un choix de routage, c'est une impossibilité
technique.

Ce qui bascule réellement, c'est un **généraliste** — agrégateur ou passerelle carte, reconnaissable
à sa liste de préfixes vide, qui accepte n'importe quel numéro. À défaut, le routage refuse
franchement et renvoie le commerçant vers les espèces, plutôt que d'envoyer un paiement chez le
mauvais opérateur.

### Une frontière assumée

Les appels HTTP vers MTN, Orange et Camtel **ne sont pas écrits**. Les adaptateurs existent en
coquille : ils portent la configuration attendue et refusent avec un message explicite tant
qu'aucun identifiant de bac à sable n'est fourni.

C'est délibéré. Une intégration bancaire qu'on ne peut exécuter une seule fois produit du code
vraisemblable et faux, sur un chemin où l'erreur s'appelle « double débit ». Un refus lisible
dans un journal d'exploitation — « clé MTN absente » — vaut mieux qu'un échec déguisé en erreur
réseau à trois heures du matin.

Restent à écrire, contre un bac à sable : l'obtention du jeton, la demande de paiement, la
lecture de statut, et **la vérification de signature des notifications entrantes**. Aucune de ces
quatre choses ne peut être écrite honnêtement sans pouvoir l'exécuter.

## Conséquences

**Un état terminal ne recule jamais.** Les notifications d'opérateur arrivent en double, en
désordre, et parfois après une interrogation manuelle. Sans cette règle, la dernière reçue
ferait loi, et une transaction réussie pourrait « échouer » une minute plus tard.

**La transaction est enregistrée et validée en base avant l'appel réseau.** La première version
de `initier_encaissement` était entièrement transactionnelle : un échec du prestataire annulait
la trace de cet échec avec le reste. Une transaction dont on ne sait plus qu'elle a été tentée
est une enquête impossible, et potentiellement un débit fantôme.

**Le disjoncteur est en mémoire de processus.** Avec plusieurs serveurs, chacun apprend la panne
de son côté. Le partager demande Redis, et cela n'a d'intérêt qu'à partir du deuxième serveur.

## Vérification

`tests/test_paiements.py` — routage par préfixe le plus long, bascule vers le généraliste, refus
en son absence, disjoncteur et demi-ouverture, non-régression des états terminaux, et
l'invariant qui justifie le module : **la même clé ne débite jamais deux fois.**
