from django.contrib import admin

from apps.core.models import Consentement, EntreeAudit, OperationSync


class TenantModelAdmin(admin.ModelAdmin):
    """Admin des modèles scopés, pour le back-office de la plateforme.

    L'administration est l'outil du gestionnaire du marché : elle doit voir toutes les boutiques.
    Elle utilise donc le gestionnaire non filtré — c'est l'un des rares accès transverses
    légitimes, et il reste réservé aux comptes `is_staff` (docs/09, §3.2).
    """

    list_filter = ("boutique",)

    def get_queryset(self, request):
        return self.model.objects_all_tenants.all()


@admin.register(EntreeAudit)
class EntreeAuditAdmin(admin.ModelAdmin):
    list_display = ("horodatage", "action", "objet_type", "objet_id", "acteur")
    list_filter = ("action", "objet_type")
    search_fields = ("objet_id",)
    date_hierarchy = "horodatage"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OperationSync)
class OperationSyncAdmin(admin.ModelAdmin):
    list_display = ("operation_id", "type", "etat", "horodatage_client", "recue_le")
    list_filter = ("etat", "type")


@admin.register(Consentement)
class ConsentementAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "finalite", "accorde", "horodatage", "revoque_le")
    list_filter = ("finalite", "accorde")
