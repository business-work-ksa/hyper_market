"""Suivi des boutiques : liste, fiche, activité, loyers, rayons, emplacements.

ÉCHAFAUDAGE — chaque vue ci-dessous est à remplacer par sa version réelle.
"""

from apps.plateforme.acces import exige_console
from apps.plateforme.echafaudage import en_chantier


@exige_console()
def boutiques(request):
    return en_chantier(request, "boutiques")


@exige_console()
def boutique(request, boutique_id):
    return en_chantier(request, "boutique")


@exige_console(suivi=True)
def boutique_activite(request, boutique_id):
    return en_chantier(request, "boutique_activite")


@exige_console(suivi=True)
def activite(request):
    return en_chantier(request, "activite")


@exige_console()
def loyers(request):
    return en_chantier(request, "loyers")


@exige_console()
def rayons(request):
    return en_chantier(request, "rayons")


@exige_console()
def emplacements(request):
    return en_chantier(request, "emplacements")
