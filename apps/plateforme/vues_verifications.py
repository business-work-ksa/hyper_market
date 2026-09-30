"""ÉCHAFAUDAGE — à remplacer (docs/23)."""

from apps.plateforme.acces import exige_console
from apps.plateforme.echafaudage import en_chantier


@exige_console()
def verifications(request):
    return en_chantier(request, "verifications")


@exige_console()
def dossier(request, boutique_id):
    return en_chantier(request, "dossier")


@exige_console()
def decider_piece(request, dossier_id):
    return en_chantier(request, "decider_piece")


@exige_console()
def decider_compte(request, compte_id):
    return en_chantier(request, "decider_compte")
