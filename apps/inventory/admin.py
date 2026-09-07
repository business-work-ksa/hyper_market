from django.contrib import admin

from apps.core.admin import TenantModelAdmin
from apps.inventory.models import (
    Depot,
    Fournisseur,
    Inventaire,
    LigneInventaire,
    MouvementStock,
    NiveauStock,
)


@admin.register(Depot)
class DepotAdmin(TenantModelAdmin):
    list_display = ("libelle", "boutique", "type", "principal", "actif")
    list_filter = ("boutique", "type", "actif")


@admin.register(NiveauStock)
class NiveauStockAdmin(TenantModelAdmin):
    list_display = ("variante", "depot", "quantite", "cmp", "valeur", "sous_le_seuil", "en_anomalie")
    list_filter = ("boutique", "depot")
    search_fields = ("variante__sku",)

    @admin.display(boolean=True, description="sous le seuil")
    def sous_le_seuil(self, obj):
        return obj.sous_le_seuil

    @admin.display(boolean=True, description="anomalie")
    def en_anomalie(self, obj):
        return obj.en_anomalie


@admin.register(MouvementStock)
class MouvementStockAdmin(TenantModelAdmin):
    list_display = ("cree_le", "type", "variante", "depot", "quantite", "cout_unitaire", "cmp_apres")
    list_filter = ("boutique", "type", "depot")
    date_hierarchy = "cree_le"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class LigneInventaireInline(admin.TabularInline):
    model = LigneInventaire
    extra = 0


@admin.register(Inventaire)
class InventaireAdmin(TenantModelAdmin):
    list_display = ("depot", "date", "etat", "valide_le")
    list_filter = ("boutique", "etat")
    inlines = [LigneInventaireInline]


@admin.register(Fournisseur)
class FournisseurAdmin(TenantModelAdmin):
    list_display = ("nom", "boutique", "telephone", "niu")
    search_fields = ("nom", "niu")
