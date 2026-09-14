"""Routes du back-office marchand."""

from django.urls import path

from apps.backoffice import (
    views,
    vues_commandes,
    vues_equipe,
    vues_identite,
    vues_ordonnancier,
    vues_production,
    vues_sav,
)

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
    path("stock/supprimer/", views.articles_supprimer, name="articles_supprimer"),
    path("stock/inventaire/", views.inventaire, name="inventaire"),
    path("stock/peremptions/", views.peremptions, name="peremptions"),
    path("stock/<uuid:variante_id>/", views.article, name="article"),
    path("stock/<uuid:variante_id>/modifier/", views.article_modifier, name="article_modifier"),
    path("stock/<uuid:variante_id>/entree/", views.entree_stock, name="entree_stock"),
    path("stock/<uuid:variante_id>/entree.json", views.entree_stock_json, name="entree_stock_json"),
    path("stock/<uuid:variante_id>/transfert/", views.transfert_stock, name="transfert_stock"),
    path("stock/<uuid:variante_id>/exemplaires/", views.exemplaires_declarer, name="exemplaires_declarer"),
    path("stock/<uuid:variante_id>/vehicules/", views.compatibilite_ajouter, name="compatibilite_ajouter"),
    path("stock/<uuid:variante_id>/vehicules/<uuid:compatibilite_id>/retirer/", views.compatibilite_retirer, name="compatibilite_retirer"),

    path("production/", vues_production.production, name="production"),
    path("production/invendus/", vues_production.production_invendus, name="production_invendus"),
    path("production/fiches/", vues_production.fiches, name="fiches"),
    path("production/fiches/nouvelle/", vues_production.fiche_creer, name="fiche_creer"),
    path("production/fiches/<uuid:recette_id>/", vues_production.fiche, name="fiche"),
    path("production/fiches/<uuid:recette_id>/produire/", vues_production.production_lancer, name="production_lancer"),
    path("production/fiches/<uuid:recette_id>/basculer/", vues_production.fiche_basculer, name="fiche_basculer"),
    path("production/fiches/<uuid:recette_id>/ingredients/", vues_production.fiche_ingredient, name="fiche_ingredient"),
    path("production/fiches/<uuid:recette_id>/ingredients/<uuid:ligne_id>/retirer/", vues_production.fiche_ingredient_retirer, name="fiche_ingredient_retirer"),

    path("ventes/", views.ventes, name="ventes"),
    path("ventes/<uuid:ticket_id>/ticket/", views.ticket, name="ticket"),

    path("garantie/", vues_sav.garantie, name="garantie"),
    path("garantie/<uuid:exemplaire_id>/atelier/", vues_sav.atelier_entrer, name="atelier_entrer"),
    path("garantie/<uuid:exemplaire_id>/atelier/sortie/", vues_sav.atelier_sortir, name="atelier_sortir"),

    path("ordonnancier/", vues_ordonnancier.ordonnancier, name="ordonnancier"),
    path("ordonnancier/<uuid:ticket_id>/consigner/", vues_ordonnancier.ordonnancier_consigner, name="ordonnancier_consigner"),

    path("commandes/", vues_commandes.commandes, name="commandes"),
    path("commandes/<uuid:sous_commande_id>/", vues_commandes.commande, name="commande"),
    path("commandes/<uuid:sous_commande_id>/avancer/", vues_commandes.commande_avancer, name="commande_avancer"),
    path("commandes/<uuid:sous_commande_id>/annuler/", vues_commandes.commande_annuler, name="commande_annuler"),
    path("commandes/<uuid:sous_commande_id>/retour/", vues_commandes.commande_retour, name="commande_retour"),

    path("comptabilite/", views.comptabilite, name="comptabilite"),

    path("boutique/", views.boutique, name="boutique"),
    path("boutique/export/", views.export_donnees, name="export_donnees"),
    path("boutique/depots/nouveau/", views.nouveau_depot, name="nouveau_depot"),

    path("boutique/identite/", vues_identite.identite, name="identite"),
    path("boutique/identite/liens/", vues_identite.lien_creer, name="lien_creer"),
    path("boutique/identite/liens/<uuid:lien_id>/retirer/", vues_identite.lien_retirer, name="lien_retirer"),

    path("boutique/equipe/", vues_equipe.equipe, name="equipe"),
    path("boutique/equipe/<uuid:appartenance_id>/role/", vues_equipe.equipe_role, name="equipe_role"),
    path("boutique/equipe/<uuid:appartenance_id>/retirer/", vues_equipe.equipe_retirer, name="equipe_retirer"),
    path("boutique/equipe/<uuid:appartenance_id>/reactiver/", vues_equipe.equipe_reactiver, name="equipe_reactiver"),
    path("boutique/equipe/<uuid:appartenance_id>/mot-de-passe/", vues_equipe.equipe_mot_de_passe, name="equipe_mot_de_passe"),
]
