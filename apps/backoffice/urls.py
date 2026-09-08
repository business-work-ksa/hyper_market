"""Routes du back-office marchand."""

from django.urls import path

from apps.backoffice import views

urlpatterns = [
    path("", views.tableau_de_bord, name="tableau_de_bord"),
    # Servi depuis la racine : la portée d'un service worker est celle de son URL.
    path("service-worker.js", views.service_worker, name="service_worker"),
    path("connexion/", views.connexion, name="connexion"),
    path("deconnexion/", views.deconnexion, name="deconnexion"),

    path("caisse/", views.caisse, name="caisse"),
    path("caisse/encaisser/", views.caisse_encaisser, name="caisse_encaisser"),
    path("caisse/session/", views.session_caisse, name="session_caisse"),

    path("stock/", views.stock, name="stock"),
    path("stock/nouvel-article/", views.nouvel_article, name="nouvel_article"),
    path("stock/inventaire/", views.inventaire, name="inventaire"),
    path("stock/<uuid:variante_id>/", views.article, name="article"),
    path("stock/<uuid:variante_id>/entree/", views.entree_stock, name="entree_stock"),

    path("ventes/", views.ventes, name="ventes"),
    path("ventes/<uuid:ticket_id>/ticket/", views.ticket, name="ticket"),

    path("comptabilite/", views.comptabilite, name="comptabilite"),

    path("boutique/", views.boutique, name="boutique"),
    path("boutique/export/", views.export_donnees, name="export_donnees"),
]
