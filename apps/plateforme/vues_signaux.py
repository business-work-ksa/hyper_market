"""ÉCHAFAUDAGE — à remplacer (docs/23)."""

from apps.plateforme.acces import exige_console
from apps.plateforme.echafaudage import en_chantier


@exige_console()
def signaux(request):
    return en_chantier(request, "signaux")


@exige_console()
def signal(request, signal_id):
    return en_chantier(request, "signal")
