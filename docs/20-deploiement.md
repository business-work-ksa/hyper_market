# 20 — Déploiement

> **Ce que ce document couvre :** mettre HyperMarché en ligne sur une machine, et savoir
> pourquoi chaque pièce est là. Le plan de financement correspondant est le
> [document 17](17-demarrage-sans-capital.md) ; l'architecture est le
> [document 09](09-architecture-technique.md).

---

## 1. La cible : une machine

Un VPS, un domaine, pas d'orchestrateur. C'est ce que le palier 1 peut payer, et c'est ce que
l'équipe — une personne — peut exploiter. Un cluster mal compris tombe plus souvent qu'une machine
bien comprise, et il tombe d'une manière que personne ne sait diagnostiquer à deux heures du matin.

Quatre conteneurs :

| Service | Rôle | Exposé |
|---|---|---|
| `web` | Django derrière Gunicorn, 3 workers | Oui, sur `PORT_PUBLIC` |
| `worker` | Celery, tâches différées | Non |
| `db` | PostgreSQL 16 | **Non** |
| `redis` | Courtier de tâches | **Non** |

La base **n'est pas publiée sur l'hôte**. Exposer `5432` est la manière la plus courante de se
faire lire la comptabilité de ses clients par le reste d'Internet, et la plus discrète : rien dans
les journaux de l'application ne le montrerait.

### Ce qui n'est pas ici

**Pas de Nginx.** Les fichiers statiques sont servis par WhiteNoise, depuis le processus
applicatif. Le site tient en un fichier CSS, un fichier JavaScript et une planche d'icônes :
exiger un serveur web de plus pour cela ajouterait une configuration à tenir sans rien apporter.

**Pas de terminaison TLS.** Elle est faite en amont — Caddy, Traefik, le reverse proxy de
l'hébergeur — et cet amont **doit** transmettre `X-Forwarded-Proto`. Sans cet en-tête, Django croit
servir en clair, refuse de poser les cookies sécurisés, et boucle indéfiniment sur la redirection
HTTPS. C'est la panne la plus fréquente de cette configuration, et elle ne dit pas son nom.

### Ce que le proxy doit faire, et que Django ne peut pas faire

**Plafonner la taille d'un téléversement.** Django n'a aucun réglage pour cela :
`DATA_UPLOAD_MAX_MEMORY_SIZE` ne borne que le corps **hors fichiers**. Le poids d'un logo est
vérifié dans le formulaire (3 Mo), mais la vérification arrive après la réception — un envoi de
500 Mo aura déjà traversé le réseau et rempli `/tmp`. La ceinture se pose devant :

```nginx
client_max_body_size 8m;          # Nginx
```
```caddy
request_body { max_size 8MB }     # Caddy
```

**Transmettre `X-Forwarded-Proto`**, comme dit ci-dessus.

Ce que le proxy ne peut **pas** faire à notre place : limiter les essais de mot de passe par
compte. Une limite par adresse IP n'a pas de sens ici — derrière le proxy elles sont toutes
identiques, et un seul attaquant fermerait la boutique à tous ses caissiers. Le compteur vit donc
dans l'application (`apps/accounts/limitation.py`) et porte sur le numéro visé.

---

## 2. Mise en ligne

```bash
cp .env.production.example .env.production   # puis remplir — voir §3
make deployer                                # construit et démarre
make journal                                 # suit les journaux
```

Puis, une seule fois :

```bash
CO="docker compose -f docker-compose.prod.yml --env-file .env.production"
$CO exec web python manage.py initialiser_referentiels
$CO exec web python manage.py createsuperuser
```

`--env-file` est nécessaire à chaque appel : c'est de là que `docker compose` tire
`POSTGRES_PASSWORD` pour composer `DATABASE_URL`. Sans lui, l'interpolation est vide et la
commande se connecte à une base qui n'existe pas. `make deployer` le passe déjà.

`charger_demo` n'a **rien à faire en production** : il crée six boutiques fictives avec des mots de
passe connus, et leur journal comptable est en ajout seul — il ne se supprime pas.

---

## 3. Les variables qui décident

Quatre sont obligatoires. Les autres ont un défaut sûr.

**`SECRET_KEY`** — 50 signes aléatoires. La changer déconnecte tous les commerçants ouverts : on la
pose une fois, avant la première mise en ligne.

**`ALLOWED_HOSTS`** — les noms d'hôte servis. Il n'y a **pas de défaut** hors développement : une
mise en production sans cette variable échoue au démarrage. C'est voulu. Le défaut historique
`["*"]` désarme la protection contre les en-têtes `Host` falsifiés, qui sert à fabriquer des liens
de réinitialisation de mot de passe pointant vers un domaine tiers.

**`CSRF_TRUSTED_ORIGINS`** — les origines complètes, schéma compris (`https://hypermarche.cm`).
Sans elles, derrière un proxy, toute soumission de formulaire est refusée pour CSRF, et le message
d'erreur ne dit pas pourquoi.

**`POSTGRES_PASSWORD`** — le mot de passe du rôle applicatif. `docker-compose.prod.yml` compose
`DATABASE_URL` à partir de lui ; ne pas l'écrire à la main.

**`AFFICHER_COMPTE_DEMO`** — faux hors développement, et il faut que cela le reste. L'écran de
connexion sait afficher un compte de démonstration **qui fonctionne** ; c'est utile sur une vitrine
de démonstration et c'est une porte ouverte ailleurs, d'autant que rien n'empêche que
`charger_demo` ait été lancé « juste pour voir » sur l'instance réelle.

**`REDIS_CACHE_URL`** — le compteur d'essais de mot de passe y vit. Sans lui, chaque `worker`
gunicorn tient son propre compteur en mémoire, et la limite annoncée est multipliée par leur
nombre sans que rien ne le signale. `docker-compose.prod.yml` le pose déjà.

**`SECURE_HSTS_SECONDS`** — une heure par défaut, et c'est délibéré. Poser un an dès la première
mise en ligne enferme le domaine en HTTPS dans le navigateur de chaque visiteur, y compris si le
certificat n'est pas encore fiable, et **cela ne se retire pas à distance**. On l'allonge une fois
le certificat éprouvé.

---

## 4. Ce que le démarrage vérifie, et ce qu'il refuse

`infrastructure/entree.sh` fait trois gestes, dans cet ordre :

1. **attendre la base** — sinon un `up` démarre l'application avant PostgreSQL, les migrations
   échouent, le conteneur redémarre, et le journal se remplit d'une erreur de connexion qui
   ressemble à une panne alors que c'est une course au démarrage ;
2. **migrer** ;
3. **vérifier l'isolation au niveau ligne** — et **refuser de démarrer** si elle n'est pas en place.

Le troisième point est le seul endroit du système où l'oubli se voit. Une table scopée sans
politique ne lève aucune erreur : l'application fonctionne, les écrans s'affichent, les tests
passent, et les données de deux commerçants se mélangent au premier `objects_all_tenants` mal
filtré. Une instance qui n'isole pas ses locataires ne doit pas servir de requêtes, même dégradées.

Le piège qu'il attrape en priorité : **le rôle applicatif en superutilisateur**. L'image officielle
PostgreSQL crée le rôle nommé par `POSTGRES_USER` en superutilisateur, et un superutilisateur
ignore toutes les politiques RLS — sans erreur, sans avertissement, sans trace.
`infrastructure/postgres/01-role-applicatif.sql` le corrige à la création du volume. **Sur une base
déjà initialisée, le script n'est pas rejoué** : exécuter l'instruction à la main.

```sql
ALTER ROLE hypermarche NOSUPERUSER NOBYPASSRLS CREATEDB;
```

---

## 5. Les fichiers statiques

`collectstatic` tourne **à la construction de l'image**, pas au démarrage. C'est une opération
déterministe qui ne dépend que du code : la refaire à chaque démarrage retarderait chaque
redémarrage et échouerait sur un disque en lecture seule.

Le stockage est `CompressedManifestStaticFilesStorage`. Il renomme chaque fichier d'après son
contenu — donc le CSS peut être mis en cache un an sans jamais servir une version périmée — et il
**refuse de démarrer si un gabarit référence un fichier absent**. Une faute de frappe dans un
`{% static %}` devient un échec de construction au lieu d'une icône manquante découverte par un
client.

En développement, ce serait l'inverse d'un service : `DEBUG=True` bascule sur le stockage simple,
et le CSS se recharge sans rien relancer.

---

## 6. Intégration continue

`.github/workflows/ci.yml`, sur `main` et sur chaque proposition de fusion.

La suite tourne **sur PostgreSQL 16**, jamais sur SQLite. Ce n'est pas une préférence : le
déclencheur du journal comptable en ajout seul, les politiques de sécurité au niveau ligne et les
contraintes d'exclusion ne s'installent pas sur SQLite. Une suite verte sur SQLite ne dit rien des
trois barrières qui tiennent l'isolation entre commerçants.

Et le rôle de test est créé **sans privilège** (`NOSUPERUSER NOBYPASSRLS`). Sans cette ligne, les
tests d'isolation passeraient triomphalement en ne prouvant rien, et la régression arriverait en
production sans qu'aucun voyant ne s'allume.

Un second travail construit l'image et vérifie qu'elle **refuse de démarrer sans base**.

---

## 7. Éprouver la configuration sans Docker

La pile se vérifie aussi sur une machine de développement, et c'est le moyen le plus rapide de
savoir si un problème vient de la configuration ou de l'image :

```bash
export DEBUG=False
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
export ALLOWED_HOSTS=127.0.0.1,localhost
export DATABASE_URL=postgres://hypermarche:hypermarche@127.0.0.1:5432/hypermarche

python manage.py collectstatic --noinput --clear
./infrastructure/entree.sh gunicorn config.wsgi:application --bind 127.0.0.1:8000
```

Sans en-tête, tout répond **301 vers HTTPS** — c'est `SECURE_SSL_REDIRECT` qui fait son travail.
Pour voir les pages, simuler le proxy :

```bash
curl -sD - -H 'X-Forwarded-Proto: https' http://127.0.0.1:8000/ -o /dev/null
```

Trois choses se lisent dans cette réponse, et chacune signale une pièce en place : `X-Frame-Options:
DENY`, `Strict-Transport-Security`, et une feuille de style servie sous un nom haché
(`hypermarche.<empreinte>.css`) avec `Cache-Control: immutable`.

Un seul réglage du bloc de durcissement est **désactivé pendant `manage.py test`** :
`SECURE_SSL_REDIRECT`. Le client de test parle en clair, et la redirection ferait répondre 301 à
chaque requête de la suite — six cents échecs disant seulement « ce réglage est actif ». Tous les
autres restent posés pendant les tests, parce qu'ils n'ajoutent qu'un en-tête ou un attribut de
cookie. C'est pourquoi la vérification manuelle ci-dessus vaut la peine : elle est le seul endroit
où la redirection elle-même est éprouvée.

---

## 8. Ce qu'un audit a trouvé, et ce qui a été posé

Cinq défauts, tous reproduits avant d'être corrigés, tous tenus par
`tests/test_durcissement.py`. Ils sont consignés ici parce qu'un durcissement dont personne ne
sait à quoi il répond finit par être retiré comme une gêne.

| Ce qui n'allait pas | Mesuré | Posé |
|---|---|---|
| La connexion n'était pas freinée | 60 essais, aucun refusé | Dix essais par quart d'heure, par compte |
| Chaque essai coûtait un hachage | 60 essais = 40 s de processeur | Refus **avant** `authenticate` : 40 s → 7 s |
| Un logo pouvait tuer le serveur | 435 Ko envoyés → 1,1 **Go** en mémoire | Bornes de poids et de pixels, deux verrous |
| Un inventaire > 500 articles était refusé | `400` muet après la saisie complète | `DATA_UPLOAD_MAX_NUMBER_FIELDS` à 10 000 |
| Le stock pesait 475 Ko | ~10 s sur une 3G de Douala | Compression : 30 Ko, ~0,6 s |

Et un sixième, d'une autre nature : l'écran de connexion affichait **des identifiants qui
fonctionnent**, sans condition. Ils ne sont plus composés que si `AFFICHER_COMPTE_DEMO` le dit.

### Ce que l'audit a trouvé sain, et qu'il ne faut pas défaire

Ces points-là ont été vérifiés et n'ont demandé aucune correction. Ils sont listés pour qu'une
modification future sache ce qu'elle mettrait en jeu :

* **aucune requête N+1** sur les écrans principaux. Le nombre de requêtes est *constant* de 6 à
  506 lignes de stock — c'est le fruit des `select_related` posés aux bons endroits, et cela se
  casse en une ligne ;
* **le jeton d'API n'est jamais stocké en clair** (SHA-256), et sa comparaison est en temps
  constant ;
* **aucun `mark_safe`, `|safe`, SQL brut ou `csrf_exempt`** sur une donnée utilisateur ;
* **la vitrine publique filtre à la source** : boutique active, bail en cours, article actif, et
  les médicaments sur ordonnance retirés à la seule porte du catalogue ;
* **les redirections contrôlées par l'utilisateur** passent par
  `url_has_allowed_host_and_scheme`.

---

## 9. Sauvegarde

Deux choses à sauvegarder, et elles ne se remplacent pas :

```bash
# La base — toute la comptabilité, tout le stock, toutes les ventes
docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U hypermarche hypermarche | gzip > sauvegarde-$(date +%F).sql.gz

# Les médias — logos et photos téléversés par les commerçants
docker run --rm -v hyper_market_medias:/m -v "$PWD":/sortie alpine \
    tar czf /sortie/medias-$(date +%F).tar.gz -C /m .
```

**Après toute restauration, relancer `verifier_rls`.** Une restauration peut rétablir les tables
sans leurs politiques : l'application repart, et n'isole plus rien.

Une sauvegarde qui n'a jamais été restaurée n'est pas une sauvegarde. La restauration se répète sur
une machine jetable, pas le jour où elle sert.

---

## 10. Ce qui reste à décider

**L'hébergeur n'est pas choisi.** [ADR-008](adr/008-localisation-de-l-hebergement.md) attend un fait
extérieur (jalon J4) : la loi camerounaise 2024/017 sur les données personnelles et les débits réels
depuis Douala décideront entre un hébergement local et un hébergement européen. Tout ce document
fonctionne dans les deux cas — c'est la raison pour laquelle il ne nomme aucun fournisseur.

**La montée en charge n'est pas traitée.** Le premier étage est d'ajouter des instances `web`
derrière le proxy ; la base reste seule. Le moment de s'en occuper est celui où les journaux le
montrent, pas avant.

**Les journaux ne sont pas centralisés.** Ils sortent sur la sortie standard, donc `docker logs` les
a. C'est suffisant pour une machine, et insuffisant pour trois.
