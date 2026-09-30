from django.contrib import admin

from apps.core.admin import TenantModelAdmin
from apps.payments.models import (
    MouvementPortefeuille,
    PortefeuilleMarchand,
    Prestataire,
    Sequestre,
    Transaction,
    Versement,
)


@admin.register(Prestataire)
class PrestataireAdmin(admin.ModelAdmin):
    list_display = ("code", "libelle", "actif", "taux_frais")
    list_filter = ("actif",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("cree_le", "sens", "prestataire", "montant", "etat", "reference_externe")
    list_filter = ("sens", "etat", "prestataire")
    search_fields = ("reference_externe", "cle_idempotence", "numero_payeur")
    date_hierarchy = "cree_le"


class LectureSeuleMixin:
    """Le séquestre et les versements se tranchent par leurs services, jamais à la main ici :
    une ligne modifiée dans l'administration brute ne laisserait pas de trace dans le journal."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Sequestre)
class SequestreAdmin(LectureSeuleMixin, admin.ModelAdmin):
    list_display = ("commande", "boutique", "montant_encaisse", "montant", "etat", "libere_le")
    list_filter = ("etat",)


@admin.register(Versement)
class VersementAdmin(LectureSeuleMixin, admin.ModelAdmin):
    list_display = ("cree_le", "boutique", "montant", "operateur", "numero", "etat", "reference_operateur")
    list_filter = ("etat", "operateur")


@admin.register(PortefeuilleMarchand)
class PortefeuilleMarchandAdmin(TenantModelAdmin):
    list_display = ("boutique", "solde_disponible", "solde_bloque", "numero_momo")


@admin.register(MouvementPortefeuille)
class MouvementPortefeuilleAdmin(TenantModelAdmin):
    list_display = ("cree_le", "portefeuille", "type", "montant", "solde_apres")
    list_filter = ("boutique", "type")
