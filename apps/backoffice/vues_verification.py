"""« Vérification » : ce que le commerçant voit de son propre dossier (docs/23, §2.3-2.4).

Ce qui est fait, ce qui manque, en langage clair ; et le seul geste qui lui revient : déclarer
son compte de versement. Il voit le **résultat** des décisions et le **motif** d'un rejet — pas
qui a décidé, ni les alertes que la console montre à l'administrateur : ce sont des éléments
d'instruction, pas de relation commerciale, et les montrer apprendrait à un fraudeur ce qu'on
regarde.

La page se lit avec `BOUTIQUE_VOIR` ; déclarer un compte exige `BOUTIQUE_ADMINISTRER` (le
gérant) — le service le revérifie.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts import permissions as droit
from apps.accounts.models import DossierKyc
from apps.backoffice.acces import boutique_courante, contexte_commun, exige
from apps.confiance import verification as regles
from apps.confiance.formulaires_verification import CompteForm, reporter_erreurs
from apps.marketplace.models import CompteVersement
from django.utils.translation import gettext as _

# Les contrôles, redits pour le commerçant : ce qu'il doit faire, pas ce que l'administrateur voit.
CE_QU_IL_FAUT_FAIRE = {
    "pays": "Votre pays n'est pas encore ouvert sur le marché. Nous vous préviendrons dès qu'il le sera.",
    "gerant": "Aucun gérant n'est rattaché à votre boutique. Contactez l'équipe HyperMarché.",
    "identite": "Présentez l'original de votre pièce d'identité à un administrateur, en personne ou en visio.",
    "telephone": "Un administrateur vous appellera sur votre numéro pour le vérifier. Décrochez !",
    "RCCM": "Présentez votre RCCM — ou, si vous êtes entreprenant, votre déclaration d'entreprenant.",
    "NIU": "Présentez votre attestation de NIU (numéro d'identifiant unique).",
    "NIF": "Présentez votre attestation de NIF (numéro d'identification fiscale).",
    "compte": "Déclarez ci-dessous le compte où recevoir votre argent, à votre nom ou à celui de votre entreprise.",
}


@exige(droit.BOUTIQUE_VOIR)
def verification(request):
    boutique = boutique_courante(request)
    contexte = contexte_commun(request, page="boutique")
    peut_declarer = droit.BOUTIQUE_ADMINISTRER in contexte["droits"]

    formulaire = CompteForm(request.POST or None, boutique=boutique)
    if request.method == "POST":
        if not peut_declarer:
            raise PermissionDenied("Seul un gérant déclare le compte de versement.")
        if formulaire.is_valid():
            f = formulaire.cleaned_data
            try:
                regles.declarer_compte(
                    boutique, par=request.user, operateur=f["operateur"], numero=f["numero"], titulaire=f["titulaire"]
                )
            except ValidationError as erreur:
                reporter_erreurs(formulaire, erreur)
            else:
                messages.success(
                    request,
                    _('Compte déclaré. Un administrateur va le vérifier ; il ne recevra de versement que %(int)s heures après.') % {"int": int(regles.DELAI_DE_CARENCE.total_seconds() // 3600)},
                )
                return redirect("verification")

    controles = regles.controles(boutique)
    for c in controles:
        c.a_faire = CE_QU_IL_FAUT_FAIRE.get(c.code, c.manque)
    pieces = (
        DossierKyc.objects.filter(boutique_id=boutique.pk)
        .exclude(type_piece=DossierKyc.TELEPHONE)
        .order_by("-cree_le")
    )
    maintenant = timezone.now()
    comptes = []
    for c in CompteVersement.objects.filter(boutique=boutique).exclude(etat=CompteVersement.RETIRE).order_by("-cree_le")[:5]:
        comptes.append(
            {
                "compte": c,
                "numero_masque": regles.masquer(c.numero),
                "en_carence": bool(c.etat == CompteVersement.VERIFIE and c.utilisable_le and c.utilisable_le > maintenant),
            }
        )
    return render(
        request,
        "verification.html",
        {
            **contexte,
            "controles": controles,
            "faits": sum(1 for c in controles if c.fait),
            "complet": all(c.fait for c in controles),
            "pieces": pieces,
            "comptes": comptes,
            "formulaire": formulaire,
            "peut_declarer": peut_declarer,
            "delai_carence_heures": int(regles.DELAI_DE_CARENCE.total_seconds() // 3600),
        },
        status=400 if request.method == "POST" else 200,
    )


# ----------------------------------------------------------------------------
# L'avis au gérant : « c'est bien moi » / « ce n'est pas moi »
# ----------------------------------------------------------------------------
def _compte_de_la_boutique(request, compte_id):
    boutique = boutique_courante(request)
    return CompteVersement.objects.filter(pk=compte_id, boutique_id=getattr(boutique, "pk", None)).first()


def _retour(request):
    from django.utils.http import url_has_allowed_host_and_scheme

    precedente = request.META.get("HTTP_REFERER", "")
    if precedente and url_has_allowed_host_and_scheme(precedente, allowed_hosts={request.get_host()}):
        return redirect(precedente)
    return redirect("verification")


@require_POST
@exige(droit.BOUTIQUE_ADMINISTRER)
def compte_confirmer(request, compte_id):
    compte = _compte_de_la_boutique(request, compte_id)
    if compte is not None:
        regles.confirmer_compte_par_gerant(compte, par=request.user)
        messages.success(request, _("Merci. Le compte de versement est confirmé de votre part."))
    return _retour(request)


@require_POST
@exige(droit.BOUTIQUE_ADMINISTRER)
def compte_contester(request, compte_id):
    compte = _compte_de_la_boutique(request, compte_id)
    if compte is not None:
        regles.contester_compte(compte, par=request.user)
        messages.success(
            request,
            _("Ce compte est retiré et aucun versement n'y partira. L'équipe HyperMarché est prévenue "
            "et vous contactera. Changez votre mot de passe, puis déclarez votre vrai compte ci-dessous."),
        )
    return redirect("verification")
