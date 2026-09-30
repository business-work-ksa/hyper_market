"""ÉCHAFAUDAGE — à remplacer (docs/23)."""

from apps.plateforme.acces import exige_console
from apps.plateforme.echafaudage import en_chantier


@exige_console()
def litiges(request):
    return en_chantier(request, "litiges")


@exige_console()
def litige(request, litige_id):
    return en_chantier(request, "litige")


@exige_console()
def versements(request):
    return en_chantier(request, "versements")


@exige_console()
def versement(request, versement_id):
    return en_chantier(request, "versement")
