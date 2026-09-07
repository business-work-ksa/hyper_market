from django.contrib import admin

from apps.catalog.models import Categorie, MediaProduit, Produit, ProduitReference, Variante
from apps.core.admin import TenantModelAdmin


@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ("libelle", "rayon", "parent")
    list_filter = ("rayon",)
    search_fields = ("libelle",)
    prepopulated_fields = {"slug": ("libelle",)}


@admin.register(ProduitReference)
class ProduitReferenceAdmin(admin.ModelAdmin):
    list_display = ("libelle", "code_barres", "marque", "categorie")
    search_fields = ("libelle", "code_barres", "marque")


class VarianteInline(admin.TabularInline):
    model = Variante
    extra = 1
    fields = ("sku", "code_barres", "attributs", "prix_vente", "prix_barre", "actif")


@admin.register(Produit)
class ProduitAdmin(TenantModelAdmin):
    list_display = ("libelle", "sku", "boutique", "categorie", "regime_tva", "actif")
    list_filter = ("boutique", "regime_tva", "actif", "revente_autorisee")
    search_fields = ("libelle", "sku")
    inlines = [VarianteInline]


@admin.register(Variante)
class VarianteAdmin(TenantModelAdmin):
    list_display = ("__str__", "sku", "boutique", "prix_vente", "actif")
    list_filter = ("boutique", "actif")
    search_fields = ("sku", "code_barres", "produit__libelle")


@admin.register(MediaProduit)
class MediaProduitAdmin(TenantModelAdmin):
    list_display = ("produit", "ordre")
