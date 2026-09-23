"""Réglages Django du projet HyperMarché.

La configuration privilégie PostgreSQL (contraintes, triggers, RLS, partitionnement — voir
docs/09-architecture-technique.md). Une bascule SQLite est prévue pour les tests hors
infrastructure : les objets spécifiques à PostgreSQL sont alors ignorés par les migrations.
"""

import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-a-remplacer-en-production")
DEBUG = env("DEBUG")

# `["*"]` est un défaut acceptable en développement et une porte ouverte en
# production : il désarme la protection contre les en-têtes `Host` falsifiés,
# qui sert à fabriquer des liens de réinitialisation pointant vers un domaine
# tiers. Le défaut suit donc `DEBUG`.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"] if DEBUG else [])

# Les hébergeurs d'aujourd'hui tirent au sort le nom de domaine qu'ils vous
# donnent — `hypermarche-a7f3.quelquechose.com` — et le publient dans une
# variable d'environnement. Personne ne peut donc écrire `ALLOWED_HOSTS` à
# l'avance, et exiger qu'il soit rempli à la main condamnerait le premier
# démarrage à échouer sur un nom que l'exploitant ne connaît pas encore.
#
# La variable est nommée ici de façon neutre, et c'est le fichier de l'hébergeur
# qui fait la correspondance (`render.yaml` y met `RENDER_EXTERNAL_HOSTNAME`).
# Un réglage Django qui nommerait un fournisseur l'épouserait pour toujours.
_HOTE_EXTERNE = env("HOTE_EXTERNE", default="").strip()
if _HOTE_EXTERNE:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, _HOTE_EXTERNE]

# La suite de tests n'a pas d'hôte à servir : le client de test parle à
# `testserver`, que Django ajoute lui-même. Exiger la variable ici obligerait
# chaque dépôt fraîchement cloné à en inventer une pour lancer `make tester`.
_EN_TEST = sys.argv[1:2] == ["test"]

if not DEBUG and not ALLOWED_HOSTS and not _EN_TEST:
    # Levé ici, et non laissé au contrôle `security.W020` : celui-ci n'est qu'un
    # avertissement, il ne sort que si quelqu'un lance `check --deploy`, et
    # l'application démarre sans lui. Une instance sans `ALLOWED_HOSTS` ne
    # servirait de toute façon aucune requête — elle répondrait 400 à chacune,
    # sans dire pourquoi. Autant refuser de démarrer en le disant.
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "ALLOWED_HOSTS est vide alors que DEBUG est faux. Nommez les hôtes "
        "servis, séparés par des virgules — voir .env.production.example."
    )

# --------------------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
]

# Ordre volontairement aligné sur le graphe de dépendances du document 09 :
# les applications ne dépendent jamais d'une application située plus bas.
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.marketplace",
    "apps.catalog",
    "apps.inventory",
    "apps.pos",
    "apps.orders",
    "apps.payments",
    "apps.accounting",
    "apps.affiliation",
    "apps.backoffice",
    "apps.api",
    "apps.vitrine",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Une page de stock de cinq cents articles pèse 475 Ko en HTML. Sur une ligne 3G
# de Douala — quatre cents kilobits utiles — cela fait **dix secondes** avant que
# le commerçant voie sa première ligne, et vingt fois plus sur un catalogue de
# mille articles. Comprimée, la même page tombe autour de quarante kilooctets.
#
# WhiteNoise ne couvre que les fichiers statiques ; le HTML, lui, est produit à
# chaque requête et personne ne le comprimait.
#
# Sur BREACH : l'attaque exige un secret et une entrée contrôlée par l'attaquant
# dans la **même** réponse comprimée. Django masque le jeton CSRF différemment à
# chaque requête depuis la version 4.1, ce qui retire à l'attaque sa cible
# habituelle. Le reste du contenu sensible ici — prix, stocks, écritures — n'est
# pas un secret dont on devine un caractère à la fois.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    # Juste après la sécurité et avant tout le reste : WhiteNoise doit pouvoir
    # répondre à une requête de fichier statique sans réveiller les sessions,
    # l'authentification et la résolution de boutique. Placé plus bas, il ferait
    # payer à chaque image le prix d'une requête applicative complète.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Barrière 1 du multi-tenant : résolution de la boutique courante.
    "apps.core.middleware.BoutiqueCouranteMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------------------
# Base de données
# --------------------------------------------------------------------------------------
if env("DATABASE_URL", default=None):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:  # repli local / CI sans PostgreSQL
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.Utilisateur"
LOGIN_URL = "connexion"
LOGIN_REDIRECT_URL = "tableau_de_bord"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------------------
# Localisation — zone CEMAC
# --------------------------------------------------------------------------------------
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Douala"
USE_I18N = True
USE_TZ = True

# L'écran de connexion affiche un compte de démonstration utilisable. C'est une
# bonne idée sur une vitrine de démonstration, et une porte ouverte en
# production : le jeu de démonstration se charge avec des mots de passe connus,
# et rien n'empêche qu'il ait été chargé « juste pour voir » sur l'instance
# réelle. Le défaut suit donc `DEBUG`, et rendre la mention publique demande un
# geste explicite — celui qu'on fait en connaissance de cause sur une démo.
AFFICHER_COMPTE_DEMO = env.bool("AFFICHER_COMPTE_DEMO", default=DEBUG)

DEVISE = "XAF"
DEVISE_SYMBOLE = "FCFA"
PAYS_DEFAUT = "CM"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# L'écran d'inventaire poste **deux champs par article** — la quantité comptée et
# le motif de l'écart. Avec la valeur par défaut de Django (1000), un commerçant
# de plus de cinq cents références voyait son comptage refusé par un `400` muet,
# après l'avoir saisi en entier. C'est l'écran de la reprise de stock : celui
# qu'on utilise le jour de l'installation, justement quand la liste est longue.
#
# Le garde-fou reste posé — il protège l'analyse du formulaire contre un envoi
# forgé — mais à une hauteur qui laisse passer un inventaire réel : cinq mille
# articles. Au-delà, l'écran devra découper le comptage par rayon, et ce sera un
# choix d'ergonomie, pas une erreur technique.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10_000

# `DATA_UPLOAD_MAX_MEMORY_SIZE` garde sa valeur par défaut, et il faut savoir ce
# qu'elle ne fait pas : elle borne le **corps hors fichiers**, pas les fichiers
# eux-mêmes. Django n'a aucun réglage qui plafonne la taille d'un téléversement.
# Le poids du logo est donc borné par `CharteForm.clean_logo` (3 Mo), et la
# ceinture générale se pose devant l'application, dans le proxy — voir docs/20.

# Le stockage « manifest » renomme chaque fichier d'après son contenu et refuse
# de démarrer si un gabarit référence un fichier absent. Les deux comptent :
# le premier permet de mettre le CSS en cache un an sans jamais servir une
# version périmée, le second transforme une faute de frappe dans un `{% static %}`
# en échec de déploiement au lieu d'une icône manquante découverte par un client.
#
# En développement, ce serait l'inverse d'un service : il faudrait relancer
# `collectstatic` après chaque retouche de CSS.
#
# La suite de tests prend le stockage simple pour une autre raison : le stockage
# manifeste exige un `collectstatic` préalable, et faire dépendre les tests d'une
# étape de construction les ferait échouer sur un dépôt fraîchement cloné avec
# une erreur — « Missing staticfiles manifest entry » — qui ne parle de rien de
# ce qu'ils vérifient. Que `collectstatic` passe est éprouvé ailleurs : à la
# construction de l'image, et par une étape dédiée de l'intégration continue.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or _EN_TEST
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# --------------------------------------------------------------------------------------
# Durcissement — actif dès que `DEBUG` est faux
# --------------------------------------------------------------------------------------
# Ces réglages ne sont pas dans un module `settings.production` séparé, et c'est
# délibéré : deux fichiers de réglages divergent, et celui qui n'est jamais
# exécuté en développement est celui dont on découvre les erreurs en production.
if not DEBUG:
    # Le TLS est terminé par le reverse proxy ; sans cet en-tête Django croit
    # servir en clair, laisse passer les cookies non sécurisés et boucle
    # indéfiniment sur la redirection HTTPS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # Pas pendant les tests : le client de test parle en `http://`, et la
    # redirection ferait répondre 301 à chaque requête de la suite — six cents
    # échecs qui ne diraient rien d'autre que « ce réglage est actif ». C'est le
    # seul réglage de ce bloc qui change ce que voit le client de test ; les
    # autres ne posent qu'un en-tête ou un attribut de cookie, et restent donc
    # éprouvés par la suite.
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not _EN_TEST)

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    # `Lax` et non `Strict` : en `Strict`, revenir sur la boutique depuis un lien
    # de parrainage ou un SMS de confirmation déconnecte le marchand.
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"

    # HSTS commence court. Un an posé dès la première mise en ligne enferme le
    # domaine en HTTPS dans le navigateur de chaque visiteur, y compris si le
    # certificat n'est pas encore fiable — et cela ne se retire pas à distance.
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
    SECURE_HSTS_PRELOAD = False

    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

    # Django 4+ exige l'origine complète, schéma compris. Sans elle, toute
    # soumission de formulaire derrière un proxy est refusée pour CSRF — et le
    # message d'erreur ne dit pas pourquoi.
    CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
    if _HOTE_EXTERNE:
        # Même raison qu'`ALLOWED_HOSTS` : le nom est tiré au sort au premier
        # déploiement. Sans cette ligne, toutes les pages s'affichent et **aucun
        # formulaire ne s'envoie** — y compris celui de la connexion. C'est la
        # panne la plus déroutante de ces hébergeurs, parce que le site a l'air
        # de marcher.
        origine = f"https://{_HOTE_EXTERNE}"
        if origine not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, origine]

# --------------------------------------------------------------------------------------
# Règles métier — voir docs/03-business-plan.md et docs/06-affiliation-*.md
# --------------------------------------------------------------------------------------
TAUX_TVA_DEFAUT = "19.25"  # 17,5 % + 10 % de centimes additionnels communaux

AFFILIATION = {
    "PROFONDEUR_MAX": 2,  # arbitrage A11 : non paramétrable au-delà
    "PART_N1": "0.10",  # 10 % de la commission plateforme
    "PART_N2": "0.03",  # 3 % de la commission plateforme
    "PLAFOND_REVERSEMENT": "0.35",  # 35 % maximum de la commission plateforme
    "FENETRE_ATTRIBUTION_JOURS": 365,
    "DELAI_RETOUR_JOURS": 7,
    "SEUIL_RETRAIT": "10000",
    "DELAI_PREMIER_RETRAIT_HEURES": 72,
}

# --------------------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------------------
# Il ne sert pas à accélérer des pages : il porte le compteur d'essais de mot de
# passe (`apps/accounts/limitation.py`). D'où l'exigence d'être **partagé entre
# les processus** — trois `workers` gunicorn avec un cache local chacun offrent
# trois fois plus d'essais qu'annoncé, sans que rien ne le signale.
#
# Redis est déjà dans la pile pour Celery ; le cache prend sa base 2. Le repli en
# mémoire n'est là que pour les tests et le développement à un seul processus.
_REDIS_CACHE = env("REDIS_CACHE_URL", default=None)
if _REDIS_CACHE and not _EN_TEST:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache",
                          "LOCATION": _REDIS_CACHE}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "hypermarche",
        }
    }

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=DEBUG)

# Les vues de l'API déclarent elles-mêmes leur authentification et leurs droits
# (`apps/api/acces.py`) : ces valeurs par défaut sont un filet, pas la règle.
# Elles sont volontairement fermées — une vue qui oublierait de déclarer sa porte
# refuse au lieu d'ouvrir.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.api.authentification.AuthentificationJeton",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
