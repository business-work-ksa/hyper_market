"""Les tâches de nuit, appelées par la plateforme d'hébergement plutôt que par un démon.

Deux commandes doivent tourner seules, sans quoi le séquestre ne libère jamais rien et les
paliers ne bougent jamais :

* `liberer_sequestres` — confirme d'office les livraisons restées sans réponse et libère les fonds
  arrivés au terme du délai de leur palier ;
* `evaluer_confiance` — recalcule les paliers et les signaux de risque.

Sur une plateforme sans serveur, il n'y a pas de `cron` ni de Celery beat à qui les confier : la
plateforme appelle une adresse à heure fixe (`vercel.json`, clé `crons`). Cette adresse est donc
une porte vers des gestes qui déplacent de l'argent, et elle se ferme par un secret partagé,
`CRON_SECRET`, que la plateforme envoie dans l'en-tête `Authorization`. **Sans secret configuré, la
porte est fermée** — jamais ouverte par défaut.

Une fois par jour et non chaque heure : c'est la limite de l'offre gratuite de l'hébergeur, et elle
suffit — les délais de libération se comptent en jours. Ailleurs (serveur classique), on lance les
deux commandes directement depuis `cron`, et cette vue ne sert pas.

Les deux commandes sont idempotentes : un appel rejoué ne libère rien deux fois.
"""

from __future__ import annotations

import hmac
import io
import os

from django.core.management import call_command
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_GET


def _secret_attendu() -> str:
    return os.environ.get("CRON_SECRET", "")


@require_GET
def taches_quotidiennes(request):
    attendu = _secret_attendu()
    recu = request.headers.get("Authorization", "")
    # `compare_digest` : une comparaison ordinaire s'arrête au premier caractère faux, et le temps
    # de réponse dirait à un attaquant combien il en a trouvé.
    if not attendu or not hmac.compare_digest(recu.encode(), f"Bearer {attendu}".encode()):
        return HttpResponseForbidden("Accès refusé.")

    resultats = {}
    for commande in ("liberer_sequestres", "evaluer_confiance"):
        sortie = io.StringIO()
        try:
            call_command(commande, stdout=sortie, stderr=sortie)
        except Exception as exc:  # noqa: BLE001 — une commande qui échoue n'empêche pas l'autre
            resultats[commande] = {"ok": False, "erreur": f"{type(exc).__name__}: {exc}"}
        else:
            resultats[commande] = {"ok": True, "sortie": sortie.getvalue()[-2000:]}

    statut = 200 if all(r["ok"] for r in resultats.values()) else 500
    return JsonResponse(resultats, status=statut)
