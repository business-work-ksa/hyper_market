"""Routes de la console de la plateforme — montées sous /plateforme/.

Trois familles d'écrans, dans trois modules :

* `vues_tableau` — les tableaux de bord, le journal des accès, la santé technique ;
* `vues_boutiques` — le suivi : la liste des boutiques, la fiche, les loyers, les rayons, les
  emplacements ;
* `vues_assistants` — les gestes, pas à pas : ouvrir une boutique, nommer un administrateur,
  vendre un emplacement, changer l'état d'une boutique, fixer un taux.
"""

from django.urls import path

from apps.plateforme import (
    vues_assistants,
    vues_boutiques,
    vues_litiges,
    vues_signaux,
    vues_suivi,
    vues_tableau,
    vues_verifications,
)

app_name = "plateforme"

urlpatterns = [
    # --- Tableaux de bord -------------------------------------------------------------------
    path("", vues_tableau.tableau_de_bord, name="tableau_de_bord"),
    path("journal/", vues_tableau.journal, name="journal"),
    path("technique/", vues_tableau.technique, name="technique"),

    # --- Motif de suivi (lecture transverse journalisée) ------------------------------------
    path("suivi/", vues_suivi.suivi_ouvrir, name="suivi_ouvrir"),
    path("suivi/fermer/", vues_suivi.suivi_fermer, name="suivi_fermer"),

    # --- Suivi des boutiques ----------------------------------------------------------------
    path("boutiques/", vues_boutiques.boutiques, name="boutiques"),
    path("boutiques/<uuid:boutique_id>/", vues_boutiques.boutique, name="boutique"),
    path("boutiques/<uuid:boutique_id>/activite/", vues_boutiques.boutique_activite, name="boutique_activite"),
    path("activite/", vues_boutiques.activite, name="activite"),
    path("loyers/", vues_boutiques.loyers, name="loyers"),
    path("rayons/", vues_boutiques.rayons, name="rayons"),
    path("emplacements/", vues_boutiques.emplacements, name="emplacements"),

    # --- Gestes et assistants ---------------------------------------------------------------
    path("assistants/boutique/", vues_assistants.ouvrir_boutique, name="assistant_boutique"),
    path("assistants/boutique/<str:etape>/", vues_assistants.ouvrir_boutique, name="assistant_boutique_etape"),
    path("assistants/emplacement/", vues_assistants.vendre_emplacement, name="assistant_emplacement"),
    path("assistants/emplacement/<str:etape>/", vues_assistants.vendre_emplacement, name="assistant_emplacement_etape"),
    path("assistants/administrateur/", vues_assistants.nommer_administrateur, name="assistant_administrateur"),
    path("assistants/administrateur/<str:etape>/", vues_assistants.nommer_administrateur, name="assistant_administrateur_etape"),
    path("boutiques/<uuid:boutique_id>/etat/", vues_assistants.changer_etat_boutique, name="boutique_etat"),
    path("loyers/<uuid:facture_id>/encaisser/", vues_assistants.encaisser_loyer, name="loyer_encaisser"),
    path("rayons/<uuid:rayon_id>/taux/", vues_assistants.fixer_taux, name="rayon_taux"),
    path("administrateurs/", vues_assistants.administrateurs, name="administrateurs"),
    path("administrateurs/<uuid:role_id>/retirer/", vues_assistants.retirer_administrateur, name="administrateur_retirer"),

    # --- Confiance et lutte contre la fraude (docs/23, ADR-013) -----------------------------
    path("verifications/", vues_verifications.verifications, name="verifications"),
    path("verifications/boutiques/<uuid:boutique_id>/", vues_verifications.dossier, name="verification_dossier"),
    path("verifications/pieces/<uuid:dossier_id>/decider/", vues_verifications.decider_piece, name="verification_piece"),
    path("verifications/comptes/<uuid:compte_id>/decider/", vues_verifications.decider_compte, name="verification_compte"),
    path("litiges/", vues_litiges.litiges, name="litiges"),
    path("litiges/<uuid:litige_id>/", vues_litiges.litige, name="litige"),
    path("versements/", vues_litiges.versements, name="versements"),
    path("versements/<uuid:versement_id>/", vues_litiges.versement, name="versement"),
    path("signaux/", vues_signaux.signaux, name="signaux"),
    path("signaux/<uuid:signal_id>/", vues_signaux.signal, name="signal"),
]
