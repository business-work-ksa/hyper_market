from django.contrib import admin

from apps.core.admin import TenantModelAdmin
from apps.orders.models import Commande, LigneCommande, Retour, SousCommande


class SousCommandeInline(admin.TabularInline):
    model = SousCommande
    extra = 0
    readonly_fields = ("boutique", "total_ttc", "commission_plateforme", "etat")


@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = ("numero", "acheteur", "total_ttc", "etat", "code_apporteur", "cree_le")
    list_filter = ("etat",)
    search_fields = ("numero", "code_apporteur")
    inlines = [SousCommandeInline]


class LigneCommandeInline(admin.TabularInline):
    model = LigneCommande
    extra = 0


@admin.register(SousCommande)
class SousCommandeAdmin(TenantModelAdmin):
    list_display = ("commande", "boutique", "total_ttc", "commission_plateforme", "etat")
    list_filter = ("boutique", "etat")
    inlines = [LigneCommandeInline]


@admin.register(Retour)
class RetourAdmin(TenantModelAdmin):
    list_display = ("sous_commande", "etat", "montant_rembourse", "cree_le")
    list_filter = ("boutique", "etat")
