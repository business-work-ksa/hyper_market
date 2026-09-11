"""L'ordonnancier : ce qui a été délivré sur ordonnance, et par qui prescrit.

Écran réservé au métier qui l'active. Une officine doit pouvoir répondre à la
question « qu'avez-vous délivré, quand, et sur quelle ordonnance ? » — c'est ce
qu'un inspecteur demande, et c'est la seule raison d'être de ce registre.

Deux choix gouvernent l'écran.

**La délivrance non consignée n'est pas refusée, elle est rendue visible.** La
boîte est partie avec le client ; refuser d'enregistrer la vente ne la ferait pas
revenir, cela ferait seulement disparaître la trace. C'est la même règle que le
stock négatif (ADR-005) : le logiciel encaisse, puis réclame. Les incomplètes
sont donc en tête, avec leur champ de saisie — pas reléguées dans un filtre qu'il
faut penser à ouvrir.

**La mention est le seul champ modifiable d'un ticket clôturé.** Les montants,
eux, sont partis en comptabilité, où le journal est en ajout seul. Un registre
doit pouvoir être complété ; une écriture, jamais.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts import permissions as droit
from apps.backoffice.acces import contexte_commun, exige
from apps.marketplace import metiers
from apps.pos.models import Ticket
from apps.pos.services import TicketInvalide, consigner_ordonnance, delivrances_sur_ordonnance

# Un registre se tient sur la durée, mais un écran qui déroule trois ans de
# délivrances n'est plus consultable. Les incomplètes remontent quel que soit
# leur âge ; le reste est borné.
DELIVRANCES_AFFICHEES = 200


def _exiger_le_metier(contexte):
    metier = contexte["metier"]
    if metier is None or not metier.a(metiers.ORDONNANCE):
        raise Http404("Ce métier ne délivre pas sur ordonnance.")
    return metier


@exige(droit.VENTES_VOIR)
def ordonnancier(request):
    contexte = contexte_commun(request, "ordonnancier")
    _exiger_le_metier(contexte)

    delivrances = list(
        delivrances_sur_ordonnance().prefetch_related("lignes")[:DELIVRANCES_AFFICHEES]
    )
    contexte.update(
        {
            "incompletes": [t for t in delivrances if not t.mention_ordonnance],
            "consignees": [t for t in delivrances if t.mention_ordonnance],
            "peut_consigner": droit.CAISSE_ENCAISSER in contexte["droits"],
        }
    )
    return render(request, "ordonnancier.html", contexte)


@require_POST
@exige(droit.CAISSE_ENCAISSER)
def ordonnancier_consigner(request, ticket_id):
    contexte = contexte_commun(request, "ordonnancier")
    _exiger_le_metier(contexte)

    ticket = get_object_or_404(Ticket.objects, pk=ticket_id, etat=Ticket.CLOTURE)
    try:
        consigner_ordonnance(ticket, mention=request.POST.get("mention", ""))
    except TicketInvalide as erreur:
        messages.error(request, str(erreur))
        return redirect("ordonnancier")

    messages.success(request, f"Ordonnance consignée pour le ticket {ticket.numero}.")
    return redirect("ordonnancier")
