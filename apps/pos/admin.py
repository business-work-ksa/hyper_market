from django.contrib import admin

from apps.core.admin import TenantModelAdmin
from apps.pos.models import LigneTicket, ReglementTicket, SessionCaisse, Ticket


@admin.register(SessionCaisse)
class SessionCaisseAdmin(TenantModelAdmin):
    list_display = ("depot", "caissier", "ouverte_le", "fermee_le", "fonds_theorique", "ecart", "etat")
    list_filter = ("boutique", "etat", "depot")


class LigneTicketInline(admin.TabularInline):
    model = LigneTicket
    extra = 0
    readonly_fields = ("libelle", "quantite", "pu_ttc", "taux_tva", "remise")


class ReglementTicketInline(admin.TabularInline):
    model = ReglementTicket
    extra = 0
    readonly_fields = ("moyen", "montant", "reference_psp")


@admin.register(Ticket)
class TicketAdmin(TenantModelAdmin):
    list_display = ("numero", "boutique", "total_ttc", "etat", "cloture_le")
    list_filter = ("boutique", "etat")
    search_fields = ("numero", "client_telephone")
    inlines = [LigneTicketInline, ReglementTicketInline]
