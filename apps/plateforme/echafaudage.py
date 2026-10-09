"""Page provisoire des écrans pas encore écrits. À supprimer quand tous le sont."""

from django.shortcuts import render

from apps.plateforme.acces import contexte_console


def en_chantier(request, nom: str):
    return render(request, "plateforme/chantier.html", contexte_console(request, page="", nom=nom))
