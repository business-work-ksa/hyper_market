"""Adresses publiques du marché.

Préfixées par `/marche/` et non montées à la racine : la racine appartient au
back-office marchand, qui est le produit que paie le commerçant. Le jour où la
vitrine deviendra la porte d'entrée, c'est un choix de domaine ou de préfixe
qu'il faudra faire, pas une réécriture.
"""

from django.urls import path

from apps.vitrine import views

urlpatterns = [
    path("", views.accueil, name="vitrine_accueil"),
    path("catalogue/", views.catalogue, name="vitrine_catalogue"),
    path("design-system/", views.design_system, name="vitrine_design_system"),
    path("article/<uuid:identifiant>/", views.article, name="vitrine_article"),
    path("boutique/<slug:slug>/", views.boutique, name="vitrine_boutique"),
    # Le passage compté d'un lien d'emplacement premium, puis la page visée (`mise_en_avant.py`).
    path("en-avant/<uuid:emplacement_id>/", views.mise_en_avant_clic, name="vitrine_mise_en_avant"),

    path("panier/", views.panier, name="vitrine_panier"),
    path("panier/ajouter/<uuid:identifiant>/", views.panier_ajouter, name="vitrine_panier_ajouter"),
    path("panier/modifier/<uuid:identifiant>/", views.panier_modifier, name="vitrine_panier_modifier"),

    path("commander/", views.commander, name="vitrine_commander"),
    path("commande/<uuid:identifiant>/", views.commande, name="vitrine_commande"),
    path("commande/<uuid:identifiant>/payer/", views.payer, name="vitrine_payer"),
    path("commande/<uuid:identifiant>/paiement/", views.paiement_etat, name="vitrine_paiement_etat"),
    path(
        "commande/<uuid:identifiant>/part/<uuid:part_id>/reception/",
        views.confirmer_reception,
        name="vitrine_confirmer_reception",
    ),
    path(
        "commande/<uuid:identifiant>/part/<uuid:part_id>/litige/",
        views.ouvrir_litige,
        name="vitrine_litige",
    ),
]
