"""Les signaux de risque : la file, la fiche d'un signal, et la décision humaine.

**Ce que ces écrans lisent.** Uniquement `SignalRisque`, `ChangementPalier` et la boutique — des
données de la plateforme *à propos* d'une boutique, non scopées. Les preuves ont été écrites dans
le signal par la tâche de nuit (`apps/confiance/signaux.py`), sous une forme lisible et déjà
agrégée (« 14 commandes prépayées en 7 jours contre 1,2 par semaine auparavant », numéros de
compte masqués). Aucune table scopée n'est relue ici : pas de motif de suivi à demander, et rien
qui n'ait sa place dans le journal pour une simple lecture.

**Ce que ces écrans écrivent.** Une décision — écarter ou confirmer — avec un motif, inscrite au
journal des accès (ADR-012) par `apps.confiance.signaux.trancher`. Confirmer ne suspend pas : la
fiche mène à l'assistant de suspension, qui demande son propre motif. Un signal est un indice ; la
sanction reste un second geste, délibéré.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import PLATEFORME_BOUTIQUES
from apps.confiance import signaux as detecteurs
from apps.confiance.models import ChangementPalier, MesureConfiance, SignalRisque
from apps.confiance.templatetags.confiance import CLE_PASTILLE
from apps.marketplace.confiance import palier
from apps.marketplace.models import Boutique
from apps.plateforme.acces import contexte_console, exige_console

PAR_PAGE = 25

# Chaque gravité a son ton, son icône et son mot : jamais la couleur seule (docs/19, §2.2).
TONS = {
    SignalRisque.CRITIQUE: ("critique", "ic-alerte"),
    SignalRisque.ELEVEE: ("alerte", "ic-alerte"),
    SignalRisque.MODEREE: ("modere", "ic-info"),
}

VUES = {
    "ouverts": ("À décider", Q(etat=SignalRisque.OUVERT)),
    "traites": ("Traités", ~Q(etat=SignalRisque.OUVERT)),
    "tous": ("Tous", Q()),
}


def _habiller(signal: SignalRisque) -> SignalRisque:
    signal.ton, signal.icone = TONS.get(signal.gravite, TONS[SignalRisque.MODEREE])
    return signal


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            (detecteurs.ECARTER, "Écarter — c'est un faux positif"),
            (detecteurs.CONFIRMER, "Confirmer — l'indice est fondé"),
        ],
        widget=forms.RadioSelect,
        error_messages={"required": "Choisissez : écarter ou confirmer."},
    )
    motif = forms.CharField(
        min_length=10,
        max_length=280,
        widget=forms.Textarea(attrs={"rows": 3, "class": "champ"}),
        error_messages={
            "required": "Dites pourquoi : ce motif est inscrit au journal des accès.",
            "min_length": "Une phrase, au moins : « vérifié par téléphone avec le gérant… »",
        },
    )


@exige_console(PLATEFORME_BOUTIQUES)
def signaux(request):
    vue = request.GET.get("vue") if request.GET.get("vue") in VUES else "ouverts"
    type_ = request.GET.get("type") if request.GET.get("type") in dict(SignalRisque.TYPES) else ""

    requete = SignalRisque.objects.filter(VUES[vue][1]).select_related("boutique", "traite_par")
    if type_:
        requete = requete.filter(type=type_)
    # Le tri de la file est celui du modèle : gravité, puis score, puis fraîcheur. Les traités
    # se lisent plutôt par date de décision.
    if vue != "ouverts":
        requete = requete.order_by("-traite_le", "-gravite", "-constate_le")

    page = Paginator(requete, PAR_PAGE).get_page(request.GET.get("page"))
    for s in page.object_list:
        _habiller(s)

    ouverts = SignalRisque.objects.filter(etat=SignalRisque.OUVERT)
    par_gravite = dict(ouverts.order_by().values_list("gravite").annotate(n=Count("id")))
    par_type = dict(ouverts.order_by().values_list("type").annotate(n=Count("id")))
    return render(
        request,
        "plateforme/signaux.html",
        contexte_console(
            request,
            page="plateforme:signaux",
            page_signaux=page,
            parametres=urlencode({k: v for k, v in (("vue", vue), ("type", type_)) if v}),
            vue=vue,
            vues=[(code, libelle) for code, (libelle, _) in VUES.items()],
            type_courant=type_,
            types=[(code, libelle, par_type.get(code, 0)) for code, libelle in SignalRisque.TYPES],
            compteurs={
                "critique": par_gravite.get(SignalRisque.CRITIQUE, 0),
                "elevee": par_gravite.get(SignalRisque.ELEVEE, 0),
                "moderee": par_gravite.get(SignalRisque.MODEREE, 0),
                "total": sum(par_gravite.values()),
            },
            derniere_evaluation=MesureConfiance.objects.aggregate(d=Max("mesuree_le"))["d"],
        ),
    )


@exige_console(PLATEFORME_BOUTIQUES)
def signal(request, signal_id):
    s = get_object_or_404(SignalRisque.objects.select_related("boutique", "traite_par"), pk=signal_id)
    _habiller(s)
    formulaire = DecisionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if formulaire.is_valid():
            try:
                detecteurs.trancher(
                    s,
                    decision=formulaire.cleaned_data["decision"],
                    motif=formulaire.cleaned_data["motif"],
                    par=request.user,
                )
            except ValidationError as erreur:
                if hasattr(erreur, "message_dict"):
                    for champ, textes in erreur.message_dict.items():
                        for texte in textes:
                            formulaire.add_error(champ if champ in formulaire.fields else None, texte)
                else:
                    for texte in erreur.messages:
                        formulaire.add_error(None, texte)
            else:
                # La pastille du rail est gardée une minute en session : on l'efface pour qu'elle
                # compte tout de suite la décision qu'on vient de prendre.
                request.session.pop(CLE_PASTILLE, None)
                verbe = "écarté" if formulaire.cleaned_data["decision"] == detecteurs.ECARTER else "confirmé"
                messages.success(request, f"Signal {verbe} — décision inscrite au journal des accès.")
                return redirect("plateforme:signal", signal_id=s.pk)

    b = s.boutique
    autres = [
        _habiller(x)
        for x in SignalRisque.objects.filter(boutique=b).exclude(pk=s.pk).order_by("-constate_le")[:6]
    ]
    return render(
        request,
        "plateforme/signal.html",
        contexte_console(
            request,
            page="plateforme:signaux",
            s=s,
            b=b,
            palier_boutique=palier(b.palier_confiance),
            autres=autres,
            changements=ChangementPalier.objects.filter(boutique=b)[:3],
            form=formulaire,
            peut_suspendre=b.etat == Boutique.ACTIVE,
            partiel=f"plateforme/partials/s_preuve_{s.type}.html",
        ),
        status=400 if request.method == "POST" else 200,
    )
