from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import RolePlateforme  # noqa: F401  (enregistré plus bas)
from apps.accounts.models import Appartenance, DossierKyc, Role, Utilisateur


class AppartenanceInline(admin.TabularInline):
    model = Appartenance
    extra = 0
    autocomplete_fields = ("boutique", "role")


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):
    ordering = ("nom_complet",)
    list_display = ("nom_complet", "telephone", "code_apporteur", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "telephone_verifie")
    search_fields = ("nom_complet", "telephone", "code_apporteur", "email")
    readonly_fields = ("code_apporteur", "date_joined", "last_login")
    inlines = [AppartenanceInline]
    fieldsets = (
        (None, {"fields": ("telephone", "password")}),
        ("Identité", {"fields": ("nom_complet", "email", "telephone_verifie", "code_apporteur")}),
        ("Droits", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("telephone", "nom_complet", "password1", "password2")}),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "libelle", "portee")
    list_filter = ("portee",)
    search_fields = ("code", "libelle")


@admin.register(Appartenance)
class AppartenanceAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "boutique", "role", "actif", "depuis")
    list_filter = ("actif", "role")
    autocomplete_fields = ("utilisateur", "boutique", "role")


@admin.register(DossierKyc)
class DossierKycAdmin(admin.ModelAdmin):
    """Consultation seulement : les décisions se prennent dans la console.

    L'administration technique ne connaît pas les quatre yeux. Un champ `etat` modifiable ici
    permettrait à n'importe quel administrateur de valider sa propre attestation d'un clic — la
    règle se contournerait par la porte de service. Les décisions passent donc par
    `apps/confiance/verification.py`, qui refuse, explique et laisse une trace.

    Le numéro n'est pas en base, seulement son empreinte à clé et ses quatre derniers caractères.
    La recherche prend donc un numéro **exact**, en calcule l'empreinte, et retrouve la pièce —
    c'est ainsi qu'on vérifie un doublon sans jamais relire un numéro stocké.
    """

    list_display = ("type_piece", "numero_masque", "utilisateur", "boutique", "etat", "expire_le", "cree_le")
    list_filter = ("etat", "type_piece", "mode_verification")
    search_fields = ("nom_lu",)
    search_help_text = "Un numéro de pièce exact, ou un nom tel qu'il figure sur la pièce."
    readonly_fields = (
        "utilisateur", "boutique", "type_piece", "numero_masque", "pays", "expire_le", "nom_lu",
        "mode_verification", "empreinte", "copie", "etat", "declare_par", "verifie_par",
        "verifie_le", "motif_rejet", "cree_le",
    )

    @admin.display(description="numéro")
    def numero_masque(self, obj):
        return obj.numero_masque

    def get_search_results(self, request, queryset, search_term):
        from apps.confiance.verification import empreinte_numero

        resultats, doublons = super().get_search_results(request, queryset, search_term)
        if search_term.strip():
            resultats = resultats | queryset.filter(numero_empreinte=empreinte_numero(search_term))
        return resultats, doublons

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RolePlateforme)
class RolePlateformeAdmin(admin.ModelAdmin):
    """Qui exploite cette place de marché (ADR-012).

    C'est la table que consulte un auditeur, et elle répond en une requête. Elle est
    délibérément séparée des appartenances : une appartenance dit « travaille dans cette
    boutique », un rôle de plateforme dit l'inverse.
    """

    list_display = ("utilisateur", "role", "actif", "depuis", "jusqu_a")
    list_filter = ("actif", "role")
    search_fields = ("utilisateur__nom_complet", "utilisateur__telephone")
    autocomplete_fields = ()
