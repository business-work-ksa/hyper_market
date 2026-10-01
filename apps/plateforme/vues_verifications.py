"""La console des vérifications : la file, le dossier d'une boutique, et les décisions.

Les vues recueillent et affichent ; **tout ce qui décide est dans
`apps/confiance/verification.py`** — qui revérifie le droit, applique les quatre yeux et écrit la
trace. Une vue n'est jamais la dernière barrière.

Deux règles d'affichage, toutes deux tenues ici :

* **aucun numéro complet dans une liste** — la file ne montre que `••••••4521`. Le numéro entier
  n'apparaît que dans le dossier d'une boutique, à qui a le droit `plateforme.boutiques` ;
* **chaque affichage d'un dossier laisse une ligne au journal des accès** : il montre des numéros
  de pièce et des noms tels qu'ils figurent sur des pièces d'identité. La loi n° 2024/017 demande
  un journal d'accès pour ces données (docs/08, §4.2), et l'ADR-012 en donne le moyen.
"""

from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import DossierKyc
from apps.accounts.permissions import PLATEFORME_BOUTIQUES
from apps.confiance import verification
from apps.confiance.formulaires_verification import (
    AppelForm,
    AttestationForm,
    CompteForm,
    DecisionForm,
    reporter_erreurs,
)
from apps.core.models import AccesPlateforme
from apps.marketplace import cemac
from apps.marketplace.models import Boutique, CompteVersement
from apps.plateforme.acces import contexte_console, exige_console
from django.utils.translation import gettext as _

STYLES = "css/plateforme-verifications.css"
PAGE = "plateforme:verifications"


# ============================================================================
# La file
# ============================================================================
@exige_console(PLATEFORME_BOUTIQUES)
def verifications(request):
    """Ce qui attend un geste. Masqué partout : la file se montre par-dessus une épaule."""
    file = verification.file_des_verifications()
    for c in file["comptes"]:
        c.numero_masque = verification.masquer(c.numero)
    compteurs = {cle: len(valeur) for cle, valeur in file.items()}
    return render(
        request,
        "plateforme/verifications.html",
        contexte_console(
            request,
            page=PAGE,
            styles=STYLES,
            file=file,
            compteurs=compteurs,
            total=compteurs["pieces"] + compteurs["comptes"] + compteurs["candidatures"] + compteurs["a_regulariser"],
        ),
    )


# ============================================================================
# Le dossier d'une boutique
# ============================================================================
def _pieces_du_dossier(boutique, gerants):
    return (
        DossierKyc.objects.filter(boutique_id=boutique.pk)
        | DossierKyc.objects.filter(utilisateur__in=gerants)
    ).select_related("utilisateur", "declare_par", "verifie_par").distinct().order_by("-cree_le")


def _page_dossier(request, boutique, *, status=200, refus=None, cible=None, formulaires=None):
    formulaires = formulaires or {}
    moi = request.user
    gerants = verification.gerants(boutique)
    controles = verification.controles(boutique)
    p = verification.pays_ou_none(boutique.pays)

    pieces = []
    for d in _pieces_du_dossier(boutique, gerants):
        ligne = {"dossier": d, "alertes": [], "refus_moi": None}
        if d.etat == DossierKyc.EN_ATTENTE:
            ligne["alertes"] = verification.alertes_piece(d)
            ligne["refus_moi"] = verification.refus_quatre_yeux(
                moi,
                declare_par_id=d.declare_par_id,
                boutique_ids=verification._boutiques_du_sujet(d),
                sujet_id=d.utilisateur_id,
                quoi="cette pièce",
            )
        pieces.append(ligne)

    comptes = []
    for c in CompteVersement.objects.filter(boutique=boutique).select_related("declare_par").order_by("-cree_le"):
        ligne = {
            "compte": c,
            "concorde": verification.titulaire_concorde(c, boutique),
            "alertes": verification.alertes_compte(c) if c.etat == CompteVersement.EN_ATTENTE else [],
            "refus_moi": None,
            "par_le_commercant": c.declare_par_id in {g.pk for g in gerants},
            "en_carence": bool(c.etat == CompteVersement.VERIFIE and c.utilisable_le and c.utilisable_le > timezone.now()),
        }
        if c.etat == CompteVersement.EN_ATTENTE:
            ligne["refus_moi"] = verification.refus_quatre_yeux(
                moi, declare_par_id=c.declare_par_id, boutique_ids={boutique.pk}, quoi="ce compte"
            )
        comptes.append(ligne)

    AccesPlateforme.objects.create(
        utilisateur=moi,
        boutique_id=boutique.pk,
        ecran="verification_dossier",
        motif=f"Instruction du dossier de vérification de « {boutique.enseigne} » : consultation des pièces",
    )

    manques = [c.manque for c in controles if not c.fait]
    contexte = contexte_console(
        request,
        page=PAGE,
        styles=STYLES,
        boutique=boutique,
        pays=p,
        sigle_fiscal=verification.sigle_fiscal(boutique),
        pays_ouvert=boutique.pays in cemac.PAYS_OUVERTS,
        gerants=gerants,
        controles=controles,
        faits=sum(1 for c in controles if c.fait),
        manques=manques,
        pieces=pieces,
        comptes=comptes,
        compte_utilisable=verification.compte_de_versement_utilisable(boutique),
        form_attestation=formulaires.get("attester") or AttestationForm(boutique=boutique),
        form_appel=formulaires.get("appel") or AppelForm(boutique=boutique),
        form_compte=formulaires.get("compte") or CompteForm(boutique=boutique),
        geste_ouvert=next(iter(formulaires), ""),
        refus=refus,
        cible=str(cible or ""),
        pays_cemac=cemac.PAYS.values(),
        delai_carence_heures=int(verification.DELAI_DE_CARENCE.total_seconds() // 3600),
        journal=AccesPlateforme.objects.filter(boutique_id=boutique.pk, ecran__startswith="verification_")
        .exclude(ecran="verification_dossier")
        .select_related("utilisateur")[:12],
    )
    return render(request, "plateforme/verification_dossier.html", contexte, status=status)


def _servir_copie(request, boutique, dossier_id):
    """La copie conservée d'une pièce, si le stockage désigné en garde une — journalisé.

    Téléchargée, jamais affichée en ligne : une image ouverte dans un onglet reste dans le cache
    du navigateur et dans l'historique ; une pièce jointe se supprime.
    """
    dossier = get_object_or_404(DossierKyc, pk=dossier_id, boutique_id=boutique.pk)
    stockage = verification.stockage_des_copies()
    if not dossier.copie or stockage is None or not stockage.exists(dossier.copie):
        raise Http404("Aucune copie conservée pour cette pièce.")
    AccesPlateforme.objects.create(
        utilisateur=request.user,
        boutique_id=boutique.pk,
        ecran="verification_copie",
        motif=f"Consultation de la copie {dossier.get_type_piece_display()} {dossier.numero_masque}",
    )
    type_mime = mimetypes.guess_type(dossier.copie)[0] or "application/octet-stream"
    reponse = FileResponse(stockage.open(dossier.copie, "rb"), as_attachment=True, filename=f"piece-{dossier.pk}", content_type=type_mime)
    reponse["Cache-Control"] = "no-store"
    return reponse


@exige_console(PLATEFORME_BOUTIQUES)
def dossier(request, boutique_id):
    boutique = get_object_or_404(Boutique.objects.select_related("rayon_principal"), pk=boutique_id)
    if request.method == "GET" and request.GET.get("copie"):
        return _servir_copie(request, boutique, request.GET["copie"])
    if request.method != "POST":
        return _page_dossier(request, boutique)

    geste = request.POST.get("geste", "")
    try:
        if geste == "attester":
            formulaire = AttestationForm(request.POST, request.FILES, boutique=boutique)
            if not formulaire.is_valid():
                return _page_dossier(request, boutique, status=400, formulaires={"attester": formulaire})
            f = formulaire.cleaned_data
            try:
                d = verification.attester_piece(
                    boutique,
                    par=request.user,
                    type_piece=f["type_piece"],
                    numero=f["numero"],
                    mode=f["mode"],
                    utilisateur=f.get("gerant"),
                    pays=f.get("pays") or "",
                    expire_le=f.get("expire_le"),
                    nom_lu=f.get("nom_lu") or "",
                    empreinte=f.get("empreinte") or "",
                    copie=f.get("copie"),
                )
            except ValidationError as erreur:
                reporter_erreurs(formulaire, erreur, correspondances={"utilisateur": "gerant"})
                return _page_dossier(request, boutique, status=400, formulaires={"attester": formulaire})
            messages.success(
                request,
                _("%(get_type_piece_display)s %(numero_masque)s attestée. Elle attend maintenant le regard d'un autre administrateur.") % {"get_type_piece_display": d.get_type_piece_display(), "numero_masque": d.numero_masque},
            )
        elif geste == "appel":
            formulaire = AppelForm(request.POST, boutique=boutique)
            if not formulaire.is_valid() or formulaire.cleaned_data.get("gerant") is None:
                if formulaire.is_valid():
                    formulaire.add_error("gerant", _("Choisissez le gérant appelé."))
                return _page_dossier(request, boutique, status=400, formulaires={"appel": formulaire})
            gerant = formulaire.cleaned_data["gerant"]
            verification.attester_appel(boutique, gerant, par=request.user, note=formulaire.cleaned_data.get("note", ""))
            messages.success(request, _('Téléphone de %(nom_complet)s vérifié par appel, et inscrit au journal.') % {"nom_complet": gerant.nom_complet})
        elif geste == "compte":
            formulaire = CompteForm(request.POST, boutique=boutique)
            if not formulaire.is_valid():
                return _page_dossier(request, boutique, status=400, formulaires={"compte": formulaire})
            f = formulaire.cleaned_data
            try:
                compte = verification.declarer_compte(
                    boutique, par=request.user, operateur=f["operateur"], numero=f["numero"],
                    titulaire=f["titulaire"], depuis_console=True,
                )
            except ValidationError as erreur:
                reporter_erreurs(formulaire, erreur)
                return _page_dossier(request, boutique, status=400, formulaires={"compte": formulaire})
            messages.success(
                request,
                _('Compte %(get_operateur_display)s %(masquer)s déclaré. Un autre administrateur doit le vérifier.') % {"get_operateur_display": compte.get_operateur_display(), "masquer": verification.masquer(compte.numero)},
            )
        else:
            return _page_dossier(request, boutique, status=400, refus=["Geste inconnu."])
    except PermissionDenied as erreur:
        return _page_dossier(request, boutique, status=403, refus=[str(erreur)])
    return redirect("plateforme:verification_dossier", boutique_id=boutique.pk)


# ============================================================================
# Les décisions
# ============================================================================
def _decider(request, *, boutique, cible, valider, rejeter, libelle):
    """Valider ou rejeter, puis revenir au dossier. Un refus s'affiche dans le dossier, en clair."""
    if request.method != "POST":
        return redirect("plateforme:verification_dossier", boutique_id=boutique.pk)
    formulaire = DecisionForm(request.POST)
    if not formulaire.is_valid():
        return _page_dossier(request, boutique, status=400, cible=cible.pk, refus=["Choisissez : valider ou rejeter."])
    try:
        if formulaire.cleaned_data["decision"] == DecisionForm.VALIDER:
            valider(cible, par=request.user)
            messages.success(request, _('%(libelle)s : validé, et inscrit au journal.') % {"libelle": libelle})
        else:
            rejeter(cible, par=request.user, motif=formulaire.cleaned_data.get("motif", ""))
            messages.success(request, _('%(libelle)s : rejeté. Le commerçant verra le motif.') % {"libelle": libelle})
    except PermissionDenied as erreur:
        return _page_dossier(request, boutique, status=403, cible=cible.pk, refus=[str(erreur)])
    except ValidationError as erreur:
        return _page_dossier(request, boutique, status=400, cible=cible.pk, refus=erreur.messages)
    return redirect("plateforme:verification_dossier", boutique_id=boutique.pk)


@exige_console(PLATEFORME_BOUTIQUES)
def decider_piece(request, dossier_id):
    piece = get_object_or_404(DossierKyc.objects.select_related("boutique", "utilisateur"), pk=dossier_id)
    boutique = piece.boutique
    if boutique is None:
        # Une pièce sans boutique (héritée d'avant) se décide depuis la boutique de son sujet.
        appartenance = piece.utilisateur.appartenances.select_related("boutique").first() if piece.utilisateur_id else None
        if appartenance is None:
            raise Http404("Cette pièce n'est rattachée à aucune boutique.")
        boutique = appartenance.boutique
    return _decider(
        request,
        boutique=boutique,
        cible=piece,
        valider=verification.valider_piece,
        rejeter=verification.rejeter_piece,
        libelle=f"{piece.get_type_piece_display()} {piece.numero_masque}",
    )


@exige_console(PLATEFORME_BOUTIQUES)
def decider_compte(request, compte_id):
    compte = get_object_or_404(CompteVersement.objects.select_related("boutique"), pk=compte_id)
    return _decider(
        request,
        boutique=compte.boutique,
        cible=compte,
        valider=verification.verifier_compte,
        rejeter=verification.rejeter_compte,
        libelle=f"Compte {compte.get_operateur_display()} {verification.masquer(compte.numero)}",
    )
