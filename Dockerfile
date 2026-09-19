# Image de production d'HyperMarché.
#
# En deux étapes, pour une raison précise : `psycopg[binary]` et `pillow` tirent
# des dépendances de compilation qui pèsent plusieurs centaines de mégaoctets et
# ne servent qu'à l'installation. Les garder dans l'image livrée alourdirait
# chaque déploiement sur une ligne camerounaise — le débit compte ici plus que
# partout ailleurs — et offrirait un compilateur à qui obtiendrait un shell.

# ---------------------------------------------------------------------------
# Étape 1 — construction des dépendances
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS construction

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Étape 2 — image livrée
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings

# `libpq5` seul : la bibliothèque cliente PostgreSQL, sans les en-têtes ni le
# compilateur qui ont servi à construire `psycopg`.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 \
    && rm -rf /var/lib/apt/lists/*

# L'application ne tourne pas en root. Une faille dans une dépendance donne
# alors les droits d'un compte qui ne peut rien écrire hors de /app/media.
RUN useradd --create-home --uid 10001 hypermarche

COPY --from=construction /opt/venv /opt/venv

WORKDIR /app
COPY --chown=hypermarche:hypermarche . .

# Les fichiers statiques sont collectés **à la construction**, pas au démarrage :
# c'est une opération déterministe qui dépend du code et de rien d'autre. La
# faire à chaque démarrage retarderait chaque redémarrage et la ferait échouer
# sur un disque en lecture seule.
#
# `SECRET_KEY` et `ALLOWED_HOSTS` sont fournis pour cette seule commande : les
# réglages sont lus au chargement, et la vraie valeur n'a rien à faire dans une
# couche d'image.
RUN SECRET_KEY=construction ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput --clear

RUN mkdir -p /app/media && chown hypermarche:hypermarche /app/media

USER hypermarche
EXPOSE 8000

ENTRYPOINT ["/app/infrastructure/entree.sh"]
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
