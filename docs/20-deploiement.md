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

### Quand le démarrage échoue

`infrastructure/entree.sh` distingue deux pannes que « la base ne répond pas » confondait :

* **« Django n'a pas pu lire sa configuration. La base n'est pas en cause. »** — la sonde n'a pas
  pu charger les réglages. Attendre n'y changerait rien, donc le script s'arrête immédiatement au
  lieu de perdre soixante secondes puis d'accuser la base ;
* **« La base de données ne répond pas après 60 secondes. »** — là, la configuration est bonne.
  Le message donne l'adresse visée, **sans le mot de passe**, et la dernière erreur reçue. Si
  l'hôte ne résout pas, il ajoute la piste des régions.

La distinction se fait sur le **code de sortie** de la sonde, pas sur le texte de l'erreur : un
module de réglages absent lève `ModuleNotFoundError` et non `ImproperlyConfigured`, et une liste de
messages à reconnaître se périme à chaque version de Django.

Ce que le proxy ne peut **pas** faire à notre place : limiter les essais de mot de passe par
compte. Une limite par adresse IP n'a pas de sens ici — derrière le proxy elles sont toutes
identiques, et un seul attaquant fermerait la boutique à tous ses caissiers. Le compteur vit donc
dans l'application (`apps/accounts/limitation.py`) et porte sur le numéro visé.

---

## 2. Une adresse publique, gratuitement, sans serveur à soi

Avant la machine à soi, il y a le besoin plus simple : **une adresse qu'on partage**. Montrer
l'outil à un commerçant de Douala, à un cabinet comptable, à quelqu'un qui hésite. Deux chemins y
mènent sans terminal : **Render** (§2, un processus qui attend) et **Vercel** (§2 bis, aucun
processus entre deux visites). `render.yaml` décrit le premier.

Render lit ce fichier, crée la base PostgreSQL 16 et le service web, fabrique lui-même la
`SECRET_KEY`, et garnit la démonstration au premier démarrage.

**Le dépôt est privé**, donc le bouton « Deploy to Render » — qui prend une URL de dépôt public —
ne s'applique pas. Le chemin est celui-ci :

1. créer un compte sur Render et y connecter GitHub ;
2. **New → Blueprint**, choisir `Arseneksa/hyper_market` ;
3. branche `claude/online-marketplace-platform-97d5tr` ;
4. Render affiche ce qu'il va créer (un service, une base) — **Apply**.

Le premier déploiement prend cinq à dix minutes : installation, `collectstatic`, migrations,
vérification de l'isolation, puis chargement des six boutiques et de leurs vingt jours de ventes.
L'adresse est de la forme `https://hypermarche-XXXX.onrender.com`, et les identifiants de
démonstration sont affichés sur l'écran de connexion.

> Si le dépôt devient public, l'URL suivante suffit — un clic, rien à choisir :
> `https://render.com/deploy?repo=https://github.com/Arseneksa/hyper_market`

### Ce que l'offre gratuite coûte vraiment

Trois limites, qui se découvrent autrement au mauvais moment :

**L'instance s'endort** après un quart d'heure sans visite, et met environ cinquante secondes à se
réveiller. Le premier écran d'un lien partagé est donc souvent lent — dire « patientez une minute »
au destinataire évite qu'il croie à une panne.

**La base gratuite expire au bout de trente jours.** Ce n'est pas une limite de taille mais une
date : Render la supprime, et la démonstration se recharge vide au redémarrage suivant. Pour une
vitrine c'est acceptable ; pour autre chose, non.

**Les identifiants de démonstration sont publics.** `AFFICHER_COMPTE_DEMO` est à `True` dans ce
fichier, délibérément : c'est le but d'une démonstration. Quiconque a le lien peut entrer, vendre,
modifier le stock. **Aucune donnée réelle n'a sa place sur cette instance** — et `preparer_demo`
refuse de garnir une base qui contient déjà des boutiques, pour que cette commande ne puisse pas
faire de dégât si elle atterrit un jour dans le démarrage d'une vraie.

### Deux pièges de l'offre gratuite, déjà désamorcés

Ils ne se voient pas à la lecture du fichier, et coûtent chacun un déploiement raté.

**`preDeployCommand` n'existe pas sur l'offre gratuite.** Le blueprint qui l'emploie est rejeté
d'emblée : `pre-deploy command is not supported for free tier services`. Migrations, vérification
de l'isolation et garnissage sont donc dans le **démarrage**, en réutilisant
`infrastructure/entree.sh` — l'entrée déjà écrite pour la production.

Ce n'est pas qu'une question de champ disponible. Une suite de commandes posée à la main dans
`startCommand` ne s'arrête pas à la première erreur : `verifier_rls` pourrait échouer et gunicorn
démarrer quand même, servant des données que rien n'isole. Le script, lui, est en `set -e` — et
c'est vérifié : en retirant une politique, le démarrage s'interrompt et le serveur ne répond pas.

**`healthCheckPath` fait échouer le déploiement** quand `SECURE_SSL_REDIRECT` est actif. Render
appelle cette adresse en clair, sans `X-Forwarded-Proto` ; l'application répond `301`, le contrôle
de santé n'y voit pas un succès, et le déploiement boucle sur un service qui marche par ailleurs.
Le champ est donc absent : Render vérifie alors que le port écoute, ce qui est la question utile.

### Le piège de la région, qui coûte plusieurs déploiements

Render apparie les ressources d'un blueprint **par leur nom**, et il ne déplace **jamais** une base
déjà provisionnée. Ajouter `region:` à une base qui existe déjà est donc sans effet : le réglage
est lu, accepté, et ignoré.

Conséquence, vécue ici sur quatre déploiements : une base créée sans région (donc à la région par
défaut) pendant que le service part à Francfort, un nom d'hôte interne qui ne résout pas d'une
région à l'autre, et un message qui accuse la base sans nommer la cause.

**Pour changer la région d'une base, il faut la recréer** — c'est-à-dire lui donner un nom neuf
dans le blueprint, ou la supprimer avant de réappliquer. C'est pourquoi la base s'appelle ici
`hypermarche-base-fra` : le nom porte la région, pour que le jour où elle change, le nom change
avec elle.

### Ce que le blueprint fait autrement que la production

| | Machine à soi (§3 et suivants) | Démonstration gratuite |
|---|---|---|
| Exécution | Image Docker, 3 `workers` | Constructeur natif, **1 `worker`** |
| Cache | Redis partagé | Mémoire du processus |
| Tâches différées | Celery | `ALWAYS_EAGER`, dans la requête |
| Compte de démonstration | Masqué | **Affiché** |

Le `worker` unique n'est pas qu'une affaire de mémoire : sans Redis, le compteur d'essais de mot de
passe est local au processus. Trois `workers` tiendraient trois compteurs et laisseraient passer
trente essais là où dix sont annoncés. Un seul processus, un seul compteur, la limite annoncée est
la vraie.

### 2 bis. La même adresse publique, mais sans serveur du tout (Vercel)

Render fait tourner un processus qui attend. Vercel ne fait tourner **rien** entre deux visites :
il réveille une fonction à la requête, la laisse mourir après. Le prix est plus doux — pas de
sommeil de cinquante secondes, pas de base qui expire au trentième jour — et trois hypothèses du
code tombent d'un coup. `vercel.json` et `api/index.py` décrivent cette instance-là.

**Ce qu'il faut savoir avant de choisir ce chemin :** deux des trois ruptures sont réparées dans le
code, la troisième ne l'est pas et ne peut pas l'être.

**Le disque est éphémère — les logos téléversés disparaissent.** C'est la rupture qu'aucun réglage
ne rattrape. L'écran d'identité visuelle fonctionne, la couleur est extraite, la charte se compose ;
puis la fonction meurt et le fichier avec elle. Aucun avertissement, aucune erreur — simplement une
image absente au retour. Acceptable pour montrer l'outil, **disqualifiant pour une vraie boutique**.
Le remède n'est pas un réglage mais un stockage d'objets (S3 ou compatible), et l'ADR-008 le garde
ouvert.

**Le cache en mémoire ne compte plus — c'est réparé.** Le compteur d'essais de mot de passe
(`apps/accounts/limitation.py`) vivait dans la mémoire du processus. Chaque invocation sans serveur
repart d'un cache neuf : dix mille essais passeraient, et rien dans les journaux ne le signalerait —
un durcissement défait en silence, ce qui est pire qu'un durcissement absent. Sous
`SANS_SERVEUR=True`, le cache passe donc **en base** (`cache_partage`, posée par la migration
`core/0009`), et le verrou redevient réel. Vérifié en faisant incrémenter le compteur par dix
processus Python séparés : le onzième voit le verrou.

**Les connexions persistantes fuient — c'est réparé.** `CONN_MAX_AGE` à 600 suppose un processus qui
réutilise sa connexion. Ici chaque invocation en ouvrirait une et l'abandonnerait derrière elle
jusqu'à saturer le pool. Sous `SANS_SERVEUR=True`, `CONN_MAX_AGE` vaut **0**.

**Le nom de domaine est tiré au sort à chaque déploiement**, et chaque prévisualisation a le sien.
Personne ne peut donc l'écrire à l'avance dans `ALLOWED_HOSTS`, et une adresse absente fait répondre
`400` à tout, sans rien expliquer. `HOTE_EXTERNE` est pour cela une **liste**, et `api/index.py` y
verse les deux variables que la plateforme fournit : celle de *ce* déploiement et celle, stable, de
la production. Servir l'une sans l'autre casse soit les prévisualisations, soit le domaine principal.

**Les migrations tournent à la construction, pas au démarrage.** Il n'y a pas de démarrage : une
fonction sans serveur n'a pas de hook d'entrée où poser `entree.sh`. Migrations, vérification de
l'isolation et garnissage sont donc dans le `buildCommand` — enchaînés en `&&`, ce qui suffit ici :
une construction qui échoue n'est pas déployée.

**L'installation des dépendances est déclarée à la main.** Le dépôt contient un `package.json` —
l'outillage de capture d'écran, avec Playwright et un navigateur complet en dépendance de
développement. Laissé à sa détection, l'hébergeur y voit un projet Node, installe trois cents
mégaoctets de navigateur, et n'installe pas Django. `installCommand` nomme donc explicitement
`pip install -r requirements.txt`, et `.vercelignore` écarte du téléversement ce qui n'a rien à
faire dans une fonction : `node_modules`, les captures, les médias, la documentation, les tests.
`static/` reste, lui, parce que `collectstatic` tourne à la construction et le lit — ce fichier
écarte de la machine de construction, pas seulement de la fonction.

**Le répertoire de sortie est vide, et il doit exister.** Sans `outputDirectory` déclaré, la
plateforme cherche `public/`, ne le trouve pas, et **se replie sur la racine du dépôt** : `manage.py`
et `requirements.txt` deviennent alors des fichiers publics servis par le CDN, et un fichier servi
par le CDN passe **avant** la réécriture vers l'application. La construction fabrique donc
`sortie_vide/`, qui ne contient rien : le CDN ne sert rien, tout tombe dans l'application, et
WhiteNoise sert les fichiers statiques comme partout ailleurs.

**`SECURE_SSL_REDIRECT` est à `False`**, et c'est le seul réglage de durcissement relâché. La
plateforme termine TLS en amont et sert déjà tout en HTTPS ; laisser la redirection active ajoute un
`301` que le client a déjà suivi, et fait boucler les contrôles internes qui appellent la fonction
en clair. `SECURE_HSTS_SECONDS` reste posé, à une heure — assez pour valoir quelque chose, assez peu
pour qu'une erreur de domaine ne condamne pas les visiteurs.

**La région est choisie, pas subie.** `regions: ["pdx1"]` place la fonction à côté de la base
PostgreSQL. Le piège décrit plus haut vaut ici aussi, sous une autre forme : une fonction en Europe
et une base en Oregon ajoutent cent cinquante millisecondes à **chaque** requête SQL, et un écran
qui en fait vingt les paie vingt fois.

#### Le chemin par GitHub, sans terminal

1. créer un compte Vercel et y connecter GitHub ;
2. **Add New → Project**, choisir `Arseneksa/hyper_market`, branche
   `claude/online-marketplace-platform-97d5tr` ;
3. poser deux variables d'environnement — `SECRET_KEY` et `DATABASE_URL` — **et rien d'autre** : le
   reste est dans `vercel.json`, donc versionné et relu ;
4. **Deploy**.

`SECRET_KEY` et `DATABASE_URL` ne sont **jamais** dans le dépôt, ni dans `vercel.json`. Elles se
posent dans les variables du projet, qui ne sont pas du code.

#### Le chemin par le terminal, quand GitHub n'est pas connecté

Le dépôt est privé. Tant que le compte Vercel n'a pas d'autorisation GitHub valide, l'API répond
`no_github_account_connected` et **aucun réglage ne contourne cela** : la plateforme ne peut tout
simplement pas lire le dépôt.

Le CLI, lui, n'en a pas besoin — c'est lui qui téléverse les fichiers, depuis la copie locale :

```bash
npx vercel login          # ouvre le navigateur, une fois
npx vercel link --yes --project hypermarche
npx vercel --prod
```

Rien d'autre à régler : le projet `hypermarche` porte déjà la région, les commandes d'installation et
de construction, le répertoire de sortie, et les deux variables chiffrées. `vercel.json` est lu dans
la copie locale, et `.vercelignore` décide de ce qui monte.

C'est aussi le chemin à connaître pour une raison qui n'a rien à voir avec GitHub : il déploie **ce
qui est sur le disque**, pas ce qui est poussé. Utile pour éprouver un correctif avant de le pousser,
dangereux si on l'oublie — un `--prod` depuis une copie modifiée met en ligne quelque chose que le
dépôt ne contient pas.

---

## 3. Mise en ligne sur une machine à soi

```bash
cp .env.production.example .env.production   # puis remplir — voir §4
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

## 4. Les variables qui décident

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

**`DATABASE_URL_SECOURS`** — normalement absente. Elle l'emporte sur `DATABASE_URL` quand elle est
posée, et c'est une porte de sortie, pas une élégance.

Chez un hébergeur qui compose `DATABASE_URL` depuis son fichier de déploiement, cette valeur n'est
rafraîchie **qu'à la resynchronisation** de ce fichier — pas à un simple redéploiement. Tant que la
synchronisation n'a pas lieu, le service vise une base qui n'existe plus ou n'a jamais été
joignable, et **aucune modification du dépôt n'y change rien** : on pousse, on redéploie, et le
même nom d'hôte revient.

Ajouter une variable, en revanche, marche toujours : un hébergeur peut verrouiller la modification
d'une valeur qu'il gère, jamais l'ajout d'une nouvelle. D'où ce nom distinct plutôt qu'une
tentative d'écraser l'autre.

À retirer une fois la situation rétablie. Deux sources pour une même information finissent par
diverger, et c'est alors celle qu'on avait oubliée qui décide.

**`CONN_MAX_AGE`** — dix minutes par défaut. Django ouvre sinon une connexion neuve à chaque
requête : imperceptible sur une base locale, ruineux dès que la base est loin, car la poignée de
main TCP puis TLS se paie en allers-retours réseau. Un écran de stock passe alors de quelques
dizaines de millisecondes à plusieurs secondes sans qu'aucune requête SQL soit en cause.

Attention au produit `workers × threads` : chaque fil garde sa connexion ouverte, et les offres
gratuites plafonnent bas. Un `worker` et quatre fils, c'est quatre connexions.

Et une précision qui touche la sécurité : le contexte de boutique est posé par
`set_config(..., false)`, donc **il vit aussi longtemps que la session**. Sur une connexion
réutilisée, un réglage laissé derrière serait hérité par la requête suivante — deux commerçants
qui se lisent l'un l'autre, sans qu'aucune barrière ne proteste. Le middleware le restaure dans un
`finally`, et `tests/test_connexions_persistantes.py` le vérifie plutôt que de s'y fier.

**`SECURE_HSTS_SECONDS`** — une heure par défaut, et c'est délibéré. Poser un an dès la première
mise en ligne enferme le domaine en HTTPS dans le navigateur de chaque visiteur, y compris si le
certificat n'est pas encore fiable, et **cela ne se retire pas à distance**. On l'allonge une fois
le certificat éprouvé.

---

## 5. Ce que le démarrage vérifie, et ce qu'il refuse

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

## 6. Les fichiers statiques

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

## 7. Intégration continue

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

## 8. Éprouver la configuration sans Docker

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

## 9. Ce qu'un audit a trouvé, et ce qui a été posé

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

## 10. Sauvegarde

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

## 11. Ce qui reste à décider

**L'hébergeur n'est pas choisi.** [ADR-008](adr/008-localisation-de-l-hebergement.md) attend un fait
extérieur (jalon J4) : la loi camerounaise 2024/017 sur les données personnelles et les débits réels
depuis Douala décideront entre un hébergement local et un hébergement européen. Tout ce document
fonctionne dans les deux cas — c'est la raison pour laquelle il ne nomme aucun fournisseur.

**La montée en charge n'est pas traitée.** Le premier étage est d'ajouter des instances `web`
derrière le proxy ; la base reste seule. Le moment de s'en occuper est celui où les journaux le
montrent, pas avant.

**Les journaux ne sont pas centralisés.** Ils sortent sur la sortie standard, donc `docker logs` les
a. C'est suffisant pour une machine, et insuffisant pour trois.
