from django.contrib import admin

from apps.marketplace.models import (
    Bail,
    Boutique,
    EmplacementPremium,
    EtatDesLieux,
    FactureLoyer,
    Rayon,
    TypeEmplacement,
)


@admin.register(Rayon)
class RayonAdmin(admin.ModelAdmin):
    list_display = ("libelle", "code", "taux_commission_pct", "responsable", "ouvert")
    list_filter = ("ouvert",)
    search_fields = ("libelle", "code")
    prepopulated_fields = {"code": ("libelle",)}

    @admin.display(description="commission", ordering="taux_commission")
    def taux_commission_pct(self, obj):
        return f"{obj.taux_commission * 100:.1f} %"


@admin.register(TypeEmplacement)
class TypeEmplacementAdmin(admin.ModelAdmin):
    list_display = ("libelle", "code", "loyer_mensuel", "taux_commission_defaut", "quota_utilisateurs")
    search_fields = ("code", "libelle")


class BailInline(admin.TabularInline):
    model = Bail
    extra = 0
    fields = ("type_emplacement", "debut", "fin", "loyer_mensuel", "taux_commission", "etat")


@admin.register(Boutique)
class BoutiqueAdmin(admin.ModelAdmin):
    list_display = ("enseigne", "raison_sociale", "rayon_principal", "ville", "regime_fiscal", "etat")
    list_filter = ("etat", "regime_fiscal", "ville", "rayon_principal")
    search_fields = ("enseigne", "raison_sociale", "rccm", "niu")
    prepopulated_fields = {"slug": ("enseigne",)}
    inlines = [BailInline]


@admin.register(Bail)
class BailAdmin(admin.ModelAdmin):
    list_display = ("boutique", "type_emplacement", "debut", "fin", "loyer_mensuel", "etat")
    list_filter = ("etat", "type_emplacement")
    autocomplete_fields = ("boutique",)


@admin.register(FactureLoyer)
class FactureLoyerAdmin(admin.ModelAdmin):
    list_display = ("bail", "periode", "montant_ht", "montant_ttc", "echeance", "etat")
    list_filter = ("etat",)
    date_hierarchy = "periode"


@admin.register(EtatDesLieux)
class EtatDesLieuxAdmin(admin.ModelAdmin):
    list_display = ("bail", "type", "constate_le")
    list_filter = ("type",)


@admin.register(EmplacementPremium)
class EmplacementPremiumAdmin(admin.ModelAdmin):
    list_display = ("type", "rayon", "debut", "fin", "tarif", "boutique_occupante")
    list_filter = ("type", "rayon")
