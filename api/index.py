"""Point d'entrée WSGI pour une plateforme sans serveur.

Vercel cherche un module dans `api/` et y prend la variable `app`. C'est tout
ce que ce fichier fait : il expose l'application Django, déjà écrite, déjà
testée, sans rien lui ajouter.

**C'est délibérément le seul fichier propre à la plateforme**, avec
`vercel.json`. L'ADR-008 pose que rien d'irremplaçable ne doit être adopté tant
que la localisation de l'hébergement n'est pas tranchée : douze lignes qui
exposent un objet WSGI standard respectent cette règle — elles se jettent sans
rien emporter. Un adaptateur qui aurait modifié les vues, le routage ou les
modèles, non.

Ce que cette plateforme change, en revanche, est réel, et `config/settings.py`
en tire les conséquences sous le drapeau `SANS_SERVEUR` : cache en base plutôt
qu'en mémoire — sinon le compteur d'essais de mot de passe ne compte rien — et
connexions non persistantes, sinon chaque invocation en abandonne une derrière
elle jusqu'à saturer le pool.

Ce qu'elle casse et qu'aucun réglage ne rattrape : **le disque est éphémère**.
Les logos et photos téléversés disparaissent au redémarrage suivant, qui n'est
pas annoncé. Acceptable pour une démonstration, disqualifiant pour une vraie
boutique — voir docs/20.

Ce qu'elle impose enfin : **la construction a un délai maximal**, et le
garnissage de la démonstration n'y tient pas. Il émet plus de neuf mille
requêtes — une écriture à la fois, à travers les vrais services, pour que le
journal comptable soit cohérent — et il n'est pas transactionnel. Il est donc
lancé à part, jamais dans la construction : voir docs/20, §2 bis.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Le nom de domaine est tiré au sort à chaque déploiement, et chaque
# prévisualisation a le sien. Personne ne peut donc l'écrire à l'avance dans
# `ALLOWED_HOSTS`, et une adresse absente fait répondre 400 à tout, sans rien
# expliquer. La plateforme le pose dans ses propres variables ; la traduction
# vers le nom neutre que lisent les réglages se fait **ici**, dans le fichier de
# la plateforme, pour que `config/settings.py` continue de n'en nommer aucune.
#
# Les deux valeurs comptent : `VERCEL_URL` est l'adresse de *ce* déploiement,
# `VERCEL_PROJECT_PRODUCTION_URL` celle, stable, de la production. Servir l'une
# sans l'autre casse soit les prévisualisations, soit le domaine principal.
_hotes = [
    os.environ.get("VERCEL_URL", ""),
    os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", ""),
]
_connus = os.environ.get("HOTE_EXTERNE", "")
_tous = [h for h in [_connus, *_hotes] if h]
if _tous:
    os.environ["HOTE_EXTERNE"] = ",".join(dict.fromkeys(_tous))

app = get_wsgi_application()

# Vercel accepte `app` ou `handler` selon les versions de son exécuteur Python ;
# exposer les deux évite un échec au déploiement dont le message ne dit pas ce
# qu'il cherchait.
handler = app
