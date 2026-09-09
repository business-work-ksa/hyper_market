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
    path("article/<uuid:identifiant>/", views.article, name="vitrine_article"),
    path("boutique/<slug:slug>/", views.boutique, name="vitrine_boutique"),

    path("panier/", views.panier, name="vitrine_panier"),
    path("panier/ajouter/<uuid:identifiant>/", views.panier_ajouter, name="vitrine_panier_ajouter"),
    path("panier/modifier/<uuid:identifiant>/", views.panier_modifier, name="vitrine_panier_modifier"),

    path("commander/", views.commander, name="vitrine_commander"),
    path("commande/<uuid:identifiant>/", views.commande, name="vitrine_commande"),
]
