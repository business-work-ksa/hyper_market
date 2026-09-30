"""Tableaux de bord de la console, journal des accès et santé technique.

ÉCHAFAUDAGE — chaque vue ci-dessous est à remplacer par sa version réelle.
"""

from apps.plateforme.acces import exige_console
from apps.plateforme.echafaudage import en_chantier


@exige_console()
def tableau_de_bord(request):
    return en_chantier(request, "tableau_de_bord")


@exige_console()
def journal(request):
    return en_chantier(request, "journal")


@exige_console()
def technique(request):
    return en_chantier(request, "technique")
