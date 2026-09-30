"""ÉCHAFAUDAGE — à remplacer (docs/23)."""

from django.http import HttpResponse

from apps.accounts import permissions as droit
from apps.backoffice.acces import exige


@exige(droit.COMPTABILITE_VOIR)
def versements(request):
    return HttpResponse("En préparation.")
