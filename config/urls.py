from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.backoffice import vues_identite
from apps.confiance.taches import taches_quotidiennes
from apps.payments import notifications

admin.site.site_header = "HyperMarché — administration du marché"
admin.site.site_title = "HyperMarché"
admin.site.index_title = "Gestion de la place de marché"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.api.urls")),
    path("marche/", include("apps.vitrine.urls")),
    # La console du superadministrateur et de l'administrateur du marché (ADR-012).
    path("plateforme/", include("apps.plateforme.urls")),
    # Lien court d'une boutique : il est fait pour être dicté et imprimé, donc
    # monté à la racine et pas sous /marche/.
    path("l/<str:code>/", vues_identite.suivre_lien, name="suivre_lien"),
    # Notifications des opérateurs Mobile Money : elles ne prouvent rien, elles font relire le
    # statut auprès de l'opérateur (`apps/payments/notifications.py`).
    path("paiements/notifications/mtn/", notifications.notification_mtn, name="notification_mtn"),
    path(
        "paiements/notifications/orange/<str:transaction_id>/",
        notifications.notification_orange,
        name="notification_orange",
    ),
    # Appelée une fois par jour par la plateforme d'hébergement, fermée par `CRON_SECRET`.
    path("taches/quotidiennes/", taches_quotidiennes, name="taches_quotidiennes"),
    path("", include("apps.backoffice.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
