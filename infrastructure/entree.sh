#!/bin/sh
# Démarrage d'une instance HyperMarché.
#
# Trois gestes, dans cet ordre, et le troisième peut refuser de démarrer.
#
# L'ordre n'est pas négociable : la vérification de la barrière 3 lit l'état
# réel des politiques dans le catalogue PostgreSQL, et ne veut rien dire tant
# que les migrations qui les installent ne sont pas passées.
set -eu

attendre_la_base() {
    # Sans cette attente, un `docker compose up` démarre l'application avant
    # PostgreSQL, les migrations échouent, le conteneur redémarre, et le journal
    # se remplit d'une erreur de connexion qui ressemble à une panne alors que
    # c'est une course au démarrage.
    essai=0
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
" 2>/dev/null; do
        essai=$((essai + 1))
        if [ "$essai" -ge 30 ]; then
            echo "La base de données ne répond pas après 60 secondes." >&2
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
