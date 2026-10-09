from django.contrib import admin

from apps.affiliation.models import (
    Apporteur,
    Attribution,
    CatalogueRevendeur,
    Commission,
    Revendeur,
    SignalFraude,
)


@admin.register(Apporteur)
class ApporteurAdmin(admin.ModelAdmin):
    list_display = ("code", "utilisateur", "parrain_n1", "parrain_n2", "etat", "kyc_renforce")
    list_filter = ("etat", "kyc_renforce")
    search_fields = ("code", "utilisateur__nom_complet", "utilisateur__telephone")
    readonly_fields = ("parrain_n2",)


@admin.register(Attribution)
class AttributionAdmin(admin.ModelAdmin):
    list_display = ("apporteur", "cible_type", "cible_id", "origine", "debut", "fin")
    list_filter = ("cible_type", "origine")


@admin.register(Revendeur)
class RevendeurAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "slug_vitrine", "etat", "plafond_remise")
    list_filter = ("etat",)
    search_fields = ("slug_vitrine", "utilisateur__nom_complet")


@admin.register(CatalogueRevendeur)
class CatalogueRevendeurAdmin(admin.ModelAdmin):
    list_display = ("revendeur", "variante", "marge", "actif")
    list_filter = ("actif",)


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = ("cree_le", "beneficiaire", "role", "assiette", "taux", "montant", "etat")
    list_filter = ("role", "etat")
    date_hierarchy = "cree_le"


@admin.register(SignalFraude)
class SignalFraudeAdmin(admin.ModelAdmin):
    list_display = ("cree_le", "apporteur", "type", "score", "traite_par")
    list_filter = ("type",)
