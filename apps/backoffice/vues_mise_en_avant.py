"""Mise en avant sur le marché : ce que les emplacements premium loués ont produit (docs/22, §4.1).

Lecture seule. L'emplacement se vend dans la console de la plateforme ; le commerçant, lui, voit
ce que son argent a acheté — affichages, clics, commandes attribuées — jour par jour.

Ouvert à qui voit « Ma boutique » (`boutique.voir`) : ce sont des chiffres de visibilité, pas de
marge ni de coût d'achat.
"""

from django.shortcuts import render

from apps.accounts import permissions as droit
from apps.backoffice.acces import contexte_commun, exige
from apps.marketplace import mesures


@exige(droit.BOUTIQUE_VOIR)
def mise_en_avant(request):
    contexte = contexte_commun(request, "boutique")
    bilans = mesures.bilans_de_la_boutique(contexte["boutique"])
    en_cours = [b for b in bilans if b.statut == mesures.EN_COURS]
    contexte.update(
        {
            "bilans": bilans,
            "en_cours": en_cours,
            "EN_COURS": mesures.EN_COURS,
            "A_VENIR": mesures.A_VENIR,
            "total_affichages": sum(b.affichages for b in bilans),
            "total_clics": sum(b.clics for b in bilans),
            "total_commandes": sum(b.commandes for b in bilans),
            "total_montant": sum((b.montant for b in bilans), start=0),
        }
    )
    return render(request, "mise_en_avant.html", contexte)
