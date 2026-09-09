"""Adresses de l'API v1.

La version est dans le chemin, pas dans un en-tête. Les clients visés sont des
caisses installées sur des tablettes qu'on ne met pas à jour à volonté : une
version lisible dans l'URL se diagnostique dans un journal d'accès, sans avoir à
inspecter les en-têtes d'une requête qu'on n'a plus.
"""

from django.urls import path

from apps.api import vues

app_name = "api"

urlpatterns = [
    path("moi/", vues.MoiVue.as_view(), name="moi"),
    path("depots/", vues.DepotsVue.as_view(), name="depots"),
    path("articles/", vues.ArticlesVue.as_view(), name="articles"),
    path("stock/mouvements/", vues.MouvementsStockVue.as_view(), name="stock-mouvements"),
    path("stock/entrees/", vues.EntreesStockVue.as_view(), name="stock-entrees"),
    path("ventes/", vues.VentesVue.as_view(), name="ventes"),
    path("ventes/<uuid:identifiant>/", vues.VenteDetailVue.as_view(), name="vente-detail"),
    path("commandes/", vues.CommandesVue.as_view(), name="commandes"),
    path("commandes/<uuid:identifiant>/avancer/", vues.CommandeAvancerVue.as_view(), name="commande-avancer"),
    path("comptabilite/balance/", vues.BalanceVue.as_view(), name="balance"),
]
