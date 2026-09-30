"""Les gestes de la console, pas à pas.

ÉCHAFAUDAGE — chaque vue ci-dessous est à remplacer par sa version réelle.
"""

from apps.plateforme.acces import CONSOLE_ADMINISTRATEURS, exige_console
from apps.plateforme.echafaudage import en_chantier


@exige_console()
def ouvrir_boutique(request, etape=None):
    return en_chantier(request, "ouvrir_boutique")


@exige_console()
def vendre_emplacement(request, etape=None):
    return en_chantier(request, "vendre_emplacement")


@exige_console(CONSOLE_ADMINISTRATEURS)
def nommer_administrateur(request, etape=None):
    return en_chantier(request, "nommer_administrateur")


@exige_console()
def changer_etat_boutique(request, boutique_id):
    return en_chantier(request, "changer_etat_boutique")


@exige_console()
def encaisser_loyer(request, facture_id):
    return en_chantier(request, "encaisser_loyer")


@exige_console()
def fixer_taux(request, rayon_id):
    return en_chantier(request, "fixer_taux")


@exige_console(CONSOLE_ADMINISTRATEURS)
def administrateurs(request):
    return en_chantier(request, "administrateurs")


@exige_console(CONSOLE_ADMINISTRATEURS)
def retirer_administrateur(request, role_id):
    return en_chantier(request, "retirer_administrateur")
