"""Routes du back-office marchand."""

from django.urls import path

from apps.backoffice import views

urlpatterns = [
    path("", views.tableau_de_bord, name="tableau_de_bord"),
    path("connexion/", views.connexion, name="connexion"),
    path("deconnexion/", views.deconnexion, name="deconnexion"),
    path("caisse/", views.caisse, name="caisse"),
    path("caisse/encaisser/", views.caisse_encaisser, name="caisse_encaisser"),
    path("stock/", views.stock, name="stock"),
    path("stock/<uuid:variante_id>/", views.article, name="article"),
    path("ventes/", views.ventes, name="ventes"),
    path("comptabilite/", views.comptabilite, name="comptabilite"),
    path("boutique/", views.boutique, name="boutique"),
]
