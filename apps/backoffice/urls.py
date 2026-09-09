"""Routes du back-office marchand."""

from django.urls import path

from apps.backoffice import views, vues_commandes, vues_equipe

urlpatterns = [
    path("", views.tableau_de_bord, name="tableau_de_bord"),
    # Servi depuis la racine : la portée d'un service worker est celle de son URL.
    path("service-worker.js", views.service_worker, name="service_worker"),
    path("connexion/", views.connexion, name="connexion"),
    path("deconnexion/", views.deconnexion, name="deconnexion"),
    path("depot/", views.choisir_depot, name="choisir_depot"),

    path("caisse/", views.caisse, name="caisse"),
    path("caisse/encaisser/", views.caisse_encaisser, name="caisse_encaisser"),
    path("caisse/catalogue.json", views.catalogue_json, name="catalogue_json"),
    path("caisse/session/", views.session_caisse, name="session_caisse"),

    path("stock/", views.stock, name="stock"),
    path("stock/nouvel-article/", views.nouvel_article, name="nouvel_article"),
    path("stock/inventaire/", views.inventaire, name="inventaire"),
    path("stock/peremptions/", views.peremptions, name="peremptions"),
    path("stock/<uuid:variante_id>/", views.article, name="article"),
    path("stock/<uuid:variante_id>/entree/", views.entree_stock, name="entree_stock"),
    path("stock/<uuid:variante_id>/entree.json", views.entree_stock_json, name="entree_stock_json"),
    path("stock/<uuid:variante_id>/transfert/", views.transfert_stock, name="transfert_stock"),

    path("ventes/", views.ventes, name="ventes"),
    path("ventes/<uuid:ticket_id>/ticket/", views.ticket, name="ticket"),

    path("commandes/", vues_commandes.commandes, name="commandes"),
    path("commandes/<uuid:sous_commande_id>/", vues_commandes.commande, name="commande"),
    path("commandes/<uuid:sous_commande_id>/avancer/", vues_commandes.commande_avancer, name="commande_avancer"),
    path("commandes/<uuid:sous_commande_id>/annuler/", vues_commandes.commande_annuler, name="commande_annuler"),
    path("commandes/<uuid:sous_commande_id>/retour/", vues_commandes.commande_retour, name="commande_retour"),

    path("comptabilite/", views.comptabilite, name="comptabilite"),

    path("boutique/", views.boutique, name="boutique"),
    path("boutique/export/", views.export_donnees, name="export_donnees"),
    path("boutique/depots/nouveau/", views.nouveau_depot, name="nouveau_depot"),

    path("boutique/equipe/", vues_equipe.equipe, name="equipe"),
    path("boutique/equipe/<uuid:appartenance_id>/role/", vues_equipe.equipe_role, name="equipe_role"),
    path("boutique/equipe/<uuid:appartenance_id>/retirer/", vues_equipe.equipe_retirer, name="equipe_retirer"),
    path("boutique/equipe/<uuid:appartenance_id>/reactiver/", vues_equipe.equipe_reactiver, name="equipe_reactiver"),
    path("boutique/equipe/<uuid:appartenance_id>/mot-de-passe/", vues_equipe.equipe_mot_de_passe, name="equipe_mot_de_passe"),
]
