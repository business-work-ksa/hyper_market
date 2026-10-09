#!/bin/sh
# Démarrage d'une instance HyperMarché.
#
# Trois gestes, dans cet ordre, et le troisième peut refuser de démarrer.
#
# L'ordre n'est pas négociable : la vérification de la barrière 3 lit l'état
# réel des politiques dans le catalogue PostgreSQL, et ne veut rien dire tant
# que les migrations qui les installent ne sont pas passées.
set -eu

# `manage.py` pose lui-même ce réglage ; un `python -c` nu, non. L'attente de la
# base appelle `django.setup()` directement — sans cette ligne, elle échoue sur
# « settings are not configured » **quel que soit l'état de la base**, et la
# boucle attend soixante secondes une réponse qu'elle ne saura jamais lire.
#
# L'image Docker le posait, Render ne le posait pas : le script ne doit pas
# dépendre de ce que l'hébergeur a pensé à déclarer. Même valeur par défaut que
# `manage.py`, et une variable déjà définie l'emporte.
: "${DJANGO_SETTINGS_MODULE:=config.settings}"
export DJANGO_SETTINGS_MODULE

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
    # La sonde distingue ses deux échecs **par son code de sortie**, pas par le
    # texte de l'erreur : un module de réglages absent lève `ModuleNotFoundError`
    # et non `ImproperlyConfigured`, une clé manquante lève encore autre chose, et
    # une liste de messages à reconnaître se périme à chaque version de Django.
    #
    #   2 → Django n'a pas pu se configurer. Attendre n'y changera rien.
    #   1 → la configuration est bonne, la base ne répond pas encore.
    essai=0
    derniere=/tmp/derniere-erreur-base
    until python -c "
import sys, traceback

try:
    import django
    django.setup()
    from django.db import connection
except Exception:
    traceback.print_exc()
    sys.exit(2)

try:
    connection.ensure_connection()
except Exception as erreur:
    print(erreur, file=sys.stderr)
    sys.exit(1)
" 2>"$derniere"; do
        # Une configuration illisible ne guérit pas en attendant : on sort tout
        # de suite plutôt que de faire perdre soixante secondes avant un message
        # qui accuserait la base.
        if [ "$?" -eq 2 ]; then
            echo "Django n'a pas pu lire sa configuration. La base n'est pas en cause." >&2
            sed 's/^/    /' "$derniere" >&2
            exit 1
        fi
        essai=$((essai + 1))
        if [ "$essai" -ge 30 ]; then
            # Ici, la configuration est forcément bonne : le code 2 est sorti
            # plus haut. La base est donc réellement en cause.
            echo "La base de données ne répond pas après 60 secondes." >&2
            echo "  Adresse visée : $(ou_va_t_on)" >&2
            echo "  Dernière erreur :" >&2
            sed 's/^/    /' "$derniere" >&2

            # Indice **conditionnel**. Affiché à chaque échec, il devient du
            # bruit qui oriente vers la mauvaise piste : celui-ci m'a fait
            # chercher une région alors que la configuration manquait.
            if grep -q "resolve\|Name or service not known\|Temporary failure" "$derniere"; then
                echo "  L'hôte ne résout pas. Chez la plupart des hébergeurs, la chaîne" >&2
                echo "  fournie est une adresse interne, et ce réseau ne franchit pas" >&2
                echo "  les régions : la base et le service doivent être dans la même." >&2
                echo "  Attention, corriger le fichier ne suffit pas — une base déjà" >&2
                echo "  provisionnée ne change jamais de région. Il faut la recréer," >&2
                echo "  donc lui donner un nom neuf dans le blueprint, ou la supprimer" >&2
                echo "  avant de réappliquer." >&2
                echo "" >&2
                echo "  Et si l'adresse ci-dessus est **inchangée** depuis votre" >&2
                echo "  dernière modification du blueprint : le blueprint n'a pas été" >&2
                echo "  resynchronisé. Un simple redéploiement reconstruit le code et" >&2
                echo "  **conserve les variables d'environnement** posées lors de la" >&2
                echo "  dernière application. Le nom d'hôte de la base en fait partie." >&2
                echo "  Cherchez « Sync » ou « Apply » sur le blueprint lui-même, pas" >&2
                echo "  sur le service." >&2
            fi
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
