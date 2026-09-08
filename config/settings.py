"""Réglages Django du projet HyperMarché.

La configuration privilégie PostgreSQL (contraintes, triggers, RLS, partitionnement — voir
docs/09-architecture-technique.md). Une bascule SQLite est prévue pour les tests hors
infrastructure : les objets spécifiques à PostgreSQL sont alors ignorés par les migrations.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["*"]),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-a-remplacer-en-production")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

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
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

DEVISE = "XAF"
DEVISE_SYMBOLE = "FCFA"
PAYS_DEFAUT = "CM"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

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

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=DEBUG)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
