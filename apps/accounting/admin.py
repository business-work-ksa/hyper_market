from django.contrib import admin

from apps.accounting.models import (
    CompteBoutique,
    CompteGeneral,
    DeclarationTva,
    EcritureComptable,
    Exercice,
    Journal,
    LigneEcriture,
    PlanComptable,
)
from apps.core.admin import TenantModelAdmin


@admin.register(PlanComptable)
class PlanComptableAdmin(admin.ModelAdmin):
    list_display = ("code", "libelle", "version")


@admin.register(CompteGeneral)
class CompteGeneralAdmin(admin.ModelAdmin):
    list_display = ("numero", "intitule", "classe", "type")
    list_filter = ("classe", "type")
    search_fields = ("numero", "intitule")


@admin.register(CompteBoutique)
class CompteBoutiqueAdmin(TenantModelAdmin):
    list_display = ("numero", "intitule", "boutique", "type", "actif")
    list_filter = ("boutique", "type", "actif")
    search_fields = ("numero", "intitule")


@admin.register(Exercice)
class ExerciceAdmin(TenantModelAdmin):
    list_display = ("boutique", "debut", "fin", "etat")
    list_filter = ("boutique", "etat")


@admin.register(Journal)
class JournalAdmin(TenantModelAdmin):
    list_display = ("code", "libelle", "boutique")
    list_filter = ("boutique", "code")


class LigneEcritureInline(admin.TabularInline):
    model = LigneEcriture
    extra = 0
    readonly_fields = ("compte", "libelle", "debit", "credit", "lettrage")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(EcritureComptable)
class EcritureComptableAdmin(TenantModelAdmin):
    """Journal en ajout seul : l'admin est en lecture seule sur les écritures validées."""

    list_display = ("date_ecriture", "journal", "piece", "libelle", "equilibree", "validee")
    list_filter = ("boutique", "journal", "validee")
    search_fields = ("piece", "libelle")
    date_hierarchy = "date_ecriture"
    inlines = [LigneEcritureInline]

    @admin.display(boolean=True, description="équilibrée")
    def equilibree(self, obj):
        return obj.equilibree

    def has_change_permission(self, request, obj=None):
        return obj is None or not obj.validee

    def has_delete_permission(self, request, obj=None):
        return obj is not None and not obj.validee


@admin.register(DeclarationTva)
class DeclarationTvaAdmin(TenantModelAdmin):
    list_display = ("periode", "boutique", "collectee", "deductible", "solde", "etat")
    list_filter = ("boutique", "etat")
