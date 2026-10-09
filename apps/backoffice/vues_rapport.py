"""Le rapport de la semaine, prêt à partir sur WhatsApp (docs/22, §2.2).

L'écran montre le message tel que le patron le recevra, et un bouton qui ouvre WhatsApp avec ce
message déjà écrit. Il le choisit lui-même : le transférer à son associé, se l'envoyer, ou rien.

Le droit demandé est `ventes.voir` : le rapport commence par le chiffre d'affaires. Le reste —
ruptures, cahier — n'y entre que si le rôle a le droit de le voir (`rapport_hebdo`).
"""

from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from apps.accounts import permissions as droit
from apps.backoffice import rapport_hebdo
from apps.backoffice.acces import contexte_commun, exige


@exige(droit.VENTES_VOIR)
def rapport_semaine(request):
    contexte = contexte_commun(request, "tableau_de_bord")
    boutique = contexte["boutique"]

    # « Une semaine plus tôt » : le patron qui a manqué le lundi retrouve aussi la précédente.
    recul = 1 if request.GET.get("precedente") else 0
    aujourdhui = timezone.localdate() - timedelta(days=7 * recul)
    rapport = rapport_hebdo.rapport_de_la_semaine(
        boutique, droits=contexte["droits"], aujourdhui=aujourdhui
    )
    message = rapport_hebdo.texte(rapport)
    contexte.update(
        {
            "rapport": rapport,
            "message": message,
            "lien_whatsapp": rapport_hebdo.lien_whatsapp(message),
            "lien_moi": (
                rapport_hebdo.lien_whatsapp(message, request.user.telephone)
                if getattr(request.user, "telephone", "")
                else ""
            ),
            "precedente": bool(recul),
        }
    )
    return render(request, "rapport_semaine.html", contexte)
