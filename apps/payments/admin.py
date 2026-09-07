from django.contrib import admin

from apps.core.admin import TenantModelAdmin
from apps.payments.models import (
    MouvementPortefeuille,
    PortefeuilleMarchand,
    Prestataire,
    Sequestre,
    Transaction,
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


@admin.register(Sequestre)
class SequestreAdmin(admin.ModelAdmin):
    list_display = ("commande", "montant", "etat", "libere_le")
    list_filter = ("etat",)


@admin.register(PortefeuilleMarchand)
class PortefeuilleMarchandAdmin(TenantModelAdmin):
    list_display = ("boutique", "solde_disponible", "solde_bloque", "numero_momo")


@admin.register(MouvementPortefeuille)
class MouvementPortefeuilleAdmin(TenantModelAdmin):
    list_display = ("cree_le", "portefeuille", "type", "montant", "solde_apres")
    list_filter = ("boutique", "type")
