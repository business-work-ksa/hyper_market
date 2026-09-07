from django.contrib import admin
from django.urls import path

admin.site.site_header = "HyperMarché — administration du marché"
admin.site.site_title = "HyperMarché"
admin.site.index_title = "Gestion de la place de marché"

urlpatterns = [
    path("admin/", admin.site.urls),
]
