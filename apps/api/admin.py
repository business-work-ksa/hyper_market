from django.contrib import admin

from apps.api.models import JetonApi


@admin.register(JetonApi)
class JetonApiAdmin(admin.ModelAdmin):
    """Le secret n'est visible nulle part ici, et c'est le but.

    L'administration sert à voir quels jetons existent, à qui, pour quelle
    boutique, et à en révoquer un. Elle ne sert pas à retrouver un jeton perdu :
    un jeton perdu se remplace.
    """

    list_display = ("libelle", "utilisateur", "boutique", "prefixe", "cree_le", "dernier_usage_le", "revoque_le")
    list_filter = ("boutique", "revoque_le")
    search_fields = ("libelle", "prefixe", "utilisateur__nom_complet", "utilisateur__telephone")
    readonly_fields = ("prefixe", "empreinte", "cree_le", "dernier_usage_le")
    actions = ["revoquer"]

    @admin.action(description="Révoquer les jetons sélectionnés")
    def revoquer(self, request, queryset):
        nombre = 0
        for jeton in queryset.filter(revoque_le__isnull=True):
            jeton.revoquer()
            nombre += 1
        self.message_user(request, f"{nombre} jeton(s) révoqué(s).")

    def has_add_permission(self, request):
        # Un jeton créé ici n'aurait pas de secret exploitable : il est fabriqué
        # par `JetonApi.emettre`, qui seul retourne le secret en clair une fois.
        return False
