#!/bin/sh
# Démarrage d'une instance HyperMarché.
#
# Trois gestes, dans cet ordre, et le troisième peut refuser de démarrer.
#
# L'ordre n'est pas négociable : la vérification de la barrière 3 lit l'état
# réel des politiques dans le catalogue PostgreSQL, et ne veut rien dire tant
# que les migrations qui les installent ne sont pas passées.
set -eu

# Décrit la base visée **sans son mot de passe**. Un message d'échec qui ne dit
# pas à quoi on a essayé de se connecter oblige à deviner ; un message qui
# recopie `DATABASE_URL` en entier écrit le mot de passe dans les journaux de
# l'hébergeur, qui sont conservés et souvent partagés.
ou_va_t_on() {
    python - <<'PY' 2>/dev/null || echo "DATABASE_URL illisible"
import os
from urllib.parse import urlparse

u = urlparse(os.environ.get("DATABASE_URL", ""))
print(f"{u.hostname or '?'}:{u.port or 5432}, base « {(u.path or '/?')[1:]} », rôle « {u.username or '?'} »")
PY
}

attendre_la_base() {
    # Sans cette attente, un `docker compose up` démarre l'application avant
    # PostgreSQL, les migrations échouent, le conteneur redémarre, et le journal
    # se remplit d'une erreur de connexion qui ressemble à une panne alors que
    # c'est une course au démarrage.
    #
    # L'erreur de chaque tentative est mise de côté plutôt que jetée : pendant
    # l'attente elle n'apprend rien — la base démarre, c'est normal — mais si
    # l'attente échoue, elle est **toute** l'information. Une version
    # précédente la supprimait, et le seul message restant était « la base ne
    # répond pas » : vrai, et inutilisable. Un nom d'hôte qui ne résout pas et
    # une base encore en cours de création donnent alors la même phrase.
    essai=0
    derniere=/tmp/derniere-erreur-base
    until python -c "
import sys

import django

django.setup()
from django.db import connection

try:
    connection.ensure_connection()
except Exception as erreur:
    print(erreur, file=sys.stderr)
    sys.exit(1)
" 2>"$derniere"; do
        essai=$((essai + 1))
        if [ "$essai" -ge 30 ]; then
            echo "La base de données ne répond pas après 60 secondes." >&2
            echo "  Adresse visée : $(ou_va_t_on)" >&2
            echo "  Dernière erreur :" >&2
            sed 's/^/    /' "$derniere" >&2
            echo "  Si l'hôte ne résout pas : chez la plupart des hébergeurs, la" >&2
            echo "  chaîne fournie est une adresse interne, et le réseau interne" >&2
            echo "  ne franchit pas les régions. Vérifiez que la base et le" >&2
            echo "  service sont dans la même." >&2
            exit 1
        fi
        sleep 2
    done
}

echo "→ Attente de la base de données"
attendre_la_base

echo "→ Migrations"
python manage.py migrate --noinput

# Contrôle d'exploitation, pas contrôle de développement. Une table scopée sans
# politique ne lève aucune erreur : l'application fonctionne, les écrans
# s'affichent, et les données de deux commerçants se mélangent au premier
# `objects_all_tenants` mal filtré. Le seul moment où cela se voit est ici.
#
# La commande sort en erreur, `set -e` arrête le script, et le conteneur ne
# démarre pas. C'est voulu : une instance qui n'isole pas ses locataires ne doit
# pas servir de requêtes, même dégradées.
echo "→ Vérification de l'isolation au niveau ligne"
python manage.py verifier_rls

# Garnissage, sur les seules instances de démonstration. Hors de là, la variable
# est absente et pas une ligne n'est écrite.
#
# Deux verrous plutôt qu'un, parce que la conséquence d'un oubli serait un jeu de
# boutiques fictives déversé dans une vraie base : cette variable, **et**
# `preparer_demo` qui refuse de travailler dès qu'une boutique existe.
if [ "${GARNIR_DEMO:-}" = "True" ] || [ "${GARNIR_DEMO:-}" = "true" ]; then
    echo "→ Jeu de démonstration"
    python manage.py preparer_demo
fi

echo "→ Démarrage"
exec "$@"
