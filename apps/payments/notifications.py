"""Les notifications des opérateurs : une sonnette, jamais une preuve.

MTN ne signe pas ses notifications. Orange y joint un jeton, mais un jeton se rejoue. N'importe qui
connaissant l'adresse pourrait donc nous « annoncer » un paiement réussi. D'où la règle, sans
exception : **le corps d'une notification n'est jamais cru**. Il sert à retrouver la transaction ;
son statut est ensuite **relu auprès de l'opérateur** (`paiement_en_ligne.actualiser`), et c'est
cette relecture seule qui peut ouvrir un séquestre.

La réponse est la même quoi qu'il arrive — `200`, corps vide — sauf pour un jeton Orange faux : un
appelant n'apprend rien sur nos transactions en essayant des identifiants.
"""

from __future__ import annotations

import hmac
import json
import logging
import uuid

from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.payments.models import Prestataire, Transaction
from apps.payments.operateurs import AdaptateurOrangeMoney
from apps.payments.paiement_en_ligne import actualiser

journal = logging.getLogger(__name__)


def _corps_json(request) -> dict:
    try:
        donnees = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return donnees if isinstance(donnees, dict) else {}


def _transaction(identifiant, code_prestataire: str) -> Transaction | None:
    try:
        uuid.UUID(str(identifiant))
    except (TypeError, ValueError):
        return None
    return Transaction.objects.filter(pk=identifiant, prestataire_id=code_prestataire).first()


@csrf_exempt
@require_http_methods(["POST", "PUT"])
def notification_mtn(request):
    """MTN rappelle avec le corps de la demande ; `externalId` est notre identifiant de transaction."""
    donnees = _corps_json(request)
    operation = _transaction(donnees.get("externalId"), Prestataire.MTN_MOMO)
    if operation is not None:
        actualiser(operation)
    else:
        journal.info("Notification MTN sans transaction reconnue.")
    return HttpResponse(status=200)


@csrf_exempt
@require_http_methods(["POST"])
def notification_orange(request, transaction_id):
    """Orange notifie sur une adresse qui porte notre identifiant, avec son `notif_token`."""
    operation = _transaction(transaction_id, Prestataire.ORANGE_MONEY)
    if operation is None:
        return HttpResponse(status=200)
    attendu = (operation.charge_utile_psp or {}).get("notif_token_empreinte", "")
    recu = AdaptateurOrangeMoney.empreinte_jeton(str(_corps_json(request).get("notif_token", "")))
    if not attendu or not hmac.compare_digest(attendu, recu):
        journal.warning("Notification Orange au jeton invalide pour la transaction %s.", operation.pk)
        return HttpResponseForbidden()
    actualiser(operation)
    return HttpResponse(status=200)
