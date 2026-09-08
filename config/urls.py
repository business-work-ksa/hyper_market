from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "HyperMarché — administration du marché"
admin.site.site_title = "HyperMarché"
admin.site.index_title = "Gestion de la place de marché"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.backoffice.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
