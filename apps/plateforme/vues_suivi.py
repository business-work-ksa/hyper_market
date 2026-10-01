"""Ouvrir et fermer une session de suivi : le motif d'une lecture à travers les boutiques."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.plateforme.acces import (
    DUREE_DU_SUIVI,
    contexte_console,
    exige_console,
    fermer_suivi,
    ouvrir_suivi,
)
from django.utils.translation import gettext as _


def _suite_sure(request, suite: str) -> str:
    """La page où revenir — seulement si elle est sur ce site. Sinon, le tableau de bord."""
    if suite and url_has_allowed_host_and_scheme(
        suite, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return suite
    return "plateforme:tableau_de_bord"


@exige_console()
def suivi_ouvrir(request):
    suite = request.POST.get("suite") or request.GET.get("suite") or ""
    erreur = None
    if request.method == "POST":
        try:
            motif = ouvrir_suivi(
                request, request.POST.get("motif", ""), request.POST.get("precision", "")
            )
        except ValueError as exc:
            erreur = str(exc)
        else:
            messages.success(
                request,
                _('Suivi ouvert pour %(int)s minutes : « %(motif)s ». Chaque écran consulté est inscrit au journal.') % {"int": int(DUREE_DU_SUIVI.total_seconds() // 60), "motif": motif},
            )
            return redirect(_suite_sure(request, suite))

    return render(
        request,
        "plateforme/suivi.html",
        contexte_console(
            request,
            page="",
            suite=suite,
            erreur=erreur,
            motif_choisi=request.POST.get("motif", ""),
            precision=request.POST.get("precision", ""),
            duree=int(DUREE_DU_SUIVI.total_seconds() // 60),
        ),
        status=400 if erreur else 200,
    )


@require_POST
@exige_console()
def suivi_fermer(request):
    fermer_suivi(request)
    messages.success(request, _("Suivi fermé. Les écrans d'activité redemanderont un motif."))
    return redirect("plateforme:tableau_de_bord")
