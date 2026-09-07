from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

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
    list_display = ("type_piece", "numero", "utilisateur", "boutique", "etat", "cree_le")
    list_filter = ("etat", "type_piece")
    search_fields = ("numero",)
