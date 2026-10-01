from django.contrib import admin

from apps.core.admin import TenantModelAdmin
from apps.pos.models import (
    ClientCahier,
    LigneTicket,
    ReglementCahier,
    ReglementTicket,
    SessionCaisse,
    Ticket,
)


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


@admin.register(ClientCahier)
class ClientCahierAdmin(TenantModelAdmin):
    """Le cahier de crédit client (docs/22, §2.1).

    L'encours n'est **pas** une colonne modifiable : c'est une différence calculée
    (`apps.pos.cahier.solde_de`). L'exposer en lecture seule ici évite qu'on croie
    pouvoir « corriger » un solde — un solde ne se corrige pas, on passe une écriture.
    """

    list_display = ("nom", "telephone", "plafond_credit", "encours_affiche", "actif")
    list_filter = ("boutique", "actif")
    search_fields = ("nom", "telephone")
    readonly_fields = ("encours_affiche",)

    @admin.display(description="encours")
    def encours_affiche(self, obj):
        from apps.pos.cahier import solde_de

        return f"{solde_de(obj):.0f} FCFA"


@admin.register(ReglementCahier)
class ReglementCahierAdmin(TenantModelAdmin):
    list_display = ("client", "moyen", "montant", "recu_le")
    list_filter = ("boutique", "moyen")
    search_fields = ("client__nom", "client__telephone")
    date_hierarchy = "recu_le"
