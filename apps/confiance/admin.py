"""L'administration technique de la confiance : en lecture seule.

Ni un palier ni un signal ne se décide ici. Un palier se calcule (`evaluer_confiance`) ; un signal
se tranche dans la console, avec un motif inscrit au journal des accès. Laisser `/admin/` les
modifier ouvrirait une porte sans trace à côté de celle qui en laisse une.
"""

from django.contrib import admin

from apps.confiance.models import ChangementPalier, MesureConfiance, SignalRisque


class LectureSeule(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SignalRisque)
class SignalRisqueAdmin(LectureSeule):
    list_display = ("boutique", "type", "gravite", "score", "etat", "constate_le", "traite_par")
    list_filter = ("etat", "type", "gravite")
    search_fields = ("boutique__enseigne", "resume")


@admin.register(ChangementPalier)
class ChangementPalierAdmin(LectureSeule):
    list_display = ("boutique", "ancien", "nouveau", "decide_le")
    list_filter = ("nouveau",)
    search_fields = ("boutique__enseigne",)


@admin.register(MesureConfiance)
class MesureConfianceAdmin(LectureSeule):
    list_display = ("boutique", "livraisons_confirmees", "taux_litiges_perdus", "premiere_activation", "mesuree_le")
    search_fields = ("boutique__enseigne",)
