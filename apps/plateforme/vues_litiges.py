"""Console : les litiges et les versements — les deux endroits où la plateforme ordonne de l'argent.

**Les litiges.** Un acheteur conteste une part prépayée ; son argent est gelé. La plateforme
instruit sous 72 heures (docs/08, §8) et rend une décision **motivée** : en faveur du marchand (la
part est libérée), de l'acheteur (remboursement total), ou partielle. Le litige est une donnée de
la boutique, scopée : le lire franchit la barrière 3, donc l'écran exige un motif de suivi et
chaque consultation laisse une ligne au journal des accès (`lecture_journalisee`, ADR-012). La
décision, elle, laisse sa propre ligne, dont le motif est la motivation elle-même.

**Les versements.** La file de ce qui attend d'être versé aux marchands. L'exécution constate un
virement fait chez l'opérateur ou l'agrégateur, par la saisie de sa référence ; **l'appel à leur
API n'existe pas encore** et rien ici ne fait semblant. Un versement ne se supprime pas : il
s'annule, motivé, et l'argent revient au disponible du marchand.

Droit requis : `plateforme.litiges` pour les deux familles d'écrans. Les versements n'ont pas
encore de droit propre ; les rattacher aux litiges plutôt qu'à `plateforme.boutiques` garde une
séparation entre qui **vérifie** un compte de versement et qui **y fait partir** l'argent.

Aucune lecture transverse n'emprunte ici l'accès technique sans trace : un test l'interdit dans
toute la console.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.permissions import PLATEFORME_LITIGES, PLATEFORME_VERSEMENTS
from apps.core.tenancy import acces_plateforme
from apps.marketplace.confiance import palier_de
from apps.orders.models import LigneCommande, Litige
from apps.payments import sequestre as sequestre_service
from apps.payments import versements as versements_service
from apps.payments.models import MouvementPortefeuille, Sequestre, Versement
from apps.plateforme.acces import contexte_console, exige_console, lecture_journalisee

DROIT_VERSEMENTS = PLATEFORME_VERSEMENTS

# L'engagement pris envers l'acheteur (docs/08, §8) : une décision sous 72 heures.
DELAI_D_INSTRUCTION = timedelta(hours=72)


def _age(depuis, maintenant) -> dict:
    ecoule = maintenant - depuis
    heures = int(ecoule.total_seconds() // 3600)
    return {
        "heures": heures,
        "libelle": f"{heures} h" if heures < 48 else f"{heures // 24} j {heures % 24} h",
        "depasse": ecoule > DELAI_D_INSTRUCTION,
        "proche": DELAI_D_INSTRUCTION - timedelta(hours=12) < ecoule <= DELAI_D_INSTRUCTION,
    }


# ----------------------------------------------------------------------------
# Litiges
# ----------------------------------------------------------------------------
@exige_console(PLATEFORME_LITIGES, suivi=True)
def litiges(request):
    vue = request.GET.get("vue") or "en_cours"
    maintenant = timezone.now()
    with lecture_journalisee(request, ecran="Litiges — file d'instruction"):
        tous = list(
            Litige.objects.select_related(
                "sous_commande", "sous_commande__commande", "boutique"
            ).order_by("cree_le")
        )
    en_cours = [l for l in tous if l.en_cours]
    tranches = sorted((l for l in tous if not l.en_cours), key=lambda l: l.tranche_le or l.cree_le, reverse=True)
    sequestres = {
        s.sous_commande_id: s
        for s in Sequestre.objects.filter(sous_commande_id__in=[l.sous_commande_id for l in tous])
    }
    for litige in tous:
        litige.age = _age(litige.cree_le, maintenant)
        litige.sequestre_vu = sequestres.get(litige.sous_commande_id)

    affiches = en_cours if vue == "en_cours" else tranches[:100]
    return render(
        request,
        "plateforme/litiges.html",
        contexte_console(
            request,
            page="litiges",
            vue=vue,
            litiges=affiches,
            nb_en_cours=len(en_cours),
            nb_tranches=len(tranches),
            nb_en_retard=sum(1 for l in en_cours if l.age["depasse"]),
            montant_gele=sum(
                (l.sequestre_vu.montant_encaisse for l in en_cours if l.sequestre_vu),
                Decimal("0"),
            ),
        ),
    )


def _lire_litige(litige_id):
    """Le litige et tout ce que la fiche montre. À appeler sous un accès journalisé."""
    litige = (
        Litige.objects.select_related(
            "sous_commande",
            "sous_commande__commande",
            "sous_commande__commande__acheteur",
            "boutique",
            "tranche_par",
        )
        .filter(pk=litige_id)
        .first()
    )
    if litige is None:
        return None, {}
    part = litige.sous_commande
    sequestre = Sequestre.objects.filter(sous_commande=part).first()
    donnees = {
        "part": part,
        "lignes": list(LigneCommande.objects.filter(sous_commande=part)),
        "sequestre": sequestre,
        "precedents": list(
            Litige.objects.filter(sous_commande=part).exclude(pk=litige.pk).order_by("cree_le")
        ),
        "mouvements": list(
            MouvementPortefeuille.objects.filter(origine_id=sequestre.pk).order_by("cree_le")
        )
        if sequestre
        else [],
    }
    return litige, donnees


def _historique(litige, part, sequestre) -> list[dict]:
    """La chronologie de la part : ce qui s'est passé, dans l'ordre, sans interprétation."""
    faits = [
        (part.cree_le, "Commande passée", part.get_mode_paiement_display()),
        (sequestre.cree_le if sequestre else None, "Paiement constaté, séquestre ouvert", ""),
        (part.expediee_le, "Expédition déclarée par le marchand", ""),
        (part.livree_le, "Livraison déclarée par le marchand", "Déclaration seule : ne libère rien"),
        (
            part.livraison_confirmee_le,
            "Livraison confirmée",
            sequestre.get_confirmation_display() if sequestre and sequestre.confirmation else "",
        ),
        (litige.cree_le, "Litige ouvert par l'acheteur", litige.get_motif_display()),
        (litige.tranche_le, "Décision rendue", litige.get_etat_display()),
        (sequestre.libere_le if sequestre else None, "Part libérée au marchand", ""),
        (sequestre.rembourse_le if sequestre else None, "Remboursement ordonné", ""),
    ]
    return sorted(
        ({"quand": q, "quoi": quoi, "detail": d} for q, quoi, d in faits if q),
        key=lambda f: f["quand"],
    )


@exige_console(PLATEFORME_LITIGES, suivi=True)
def litige(request, litige_id):
    if request.method == "POST":
        return _agir_sur_le_litige(request, litige_id)

    with lecture_journalisee(request, ecran=f"Litige {litige_id}"):
        litige_vu, donnees = _lire_litige(litige_id)
    if litige_vu is None:
        raise Http404("Ce litige n'existe pas.")
    part = donnees["part"]
    sequestre = donnees["sequestre"]
    return render(
        request,
        "plateforme/litige.html",
        contexte_console(
            request,
            page="litiges",
            l=litige_vu,
            age=_age(litige_vu.cree_le, timezone.now()),
            historique=_historique(litige_vu, part, sequestre),
            decisions=sequestre_service.DECISIONS,
            palier=palier_de(litige_vu.boutique),
            decision_choisie=request.GET.get("decision", ""),
            **donnees,
        ),
    )


def _agir_sur_le_litige(request, litige_id):
    """Prendre en instruction, ou trancher. Chaque geste laisse sa ligne au journal des accès.

    Le motif de cette ligne est la motivation de la décision elle-même : dans un an, le journal
    doit dire non seulement qui a tranché, mais pourquoi.
    """
    action = request.POST.get("action") or ""
    motivation = (request.POST.get("motivation") or "").strip()
    decision = request.POST.get("decision") or ""
    try:
        if action == "instruire":
            with acces_plateforme(
                utilisateur=request.user,
                motif="Prise en instruction d'un litige",
                ecran=f"Litige {litige_id} — instruction",
            ):
                litige_vu = Litige.objects.get(pk=litige_id)
                sequestre_service.prendre_en_instruction(litige_vu, par=request.user)
            messages.success(request, "Litige pris en instruction.")
        elif action == "trancher":
            if len(motivation) < sequestre_service.LONGUEUR_MIN_MOTIVATION:
                raise sequestre_service.SequestreRefuse(
                    "Une décision se motive : quelques phrases, que l'acheteur et le marchand liront."
                )
            libelle = dict(sequestre_service.DECISIONS).get(decision, decision)
            with acces_plateforme(
                utilisateur=request.user,
                motif=f"Décision : {libelle}. {motivation}",
                ecran=f"Litige {litige_id} — décision",
            ):
                litige_vu = Litige.objects.select_related("sous_commande").get(pk=litige_id)
                sequestre_service.trancher_litige(
                    litige_vu,
                    decision=decision,
                    motivation=motivation,
                    par=request.user,
                    montant=request.POST.get("montant"),
                )
            messages.success(request, f"Litige tranché — {libelle.split(' —')[0].lower()}.")
        else:
            messages.error(request, "Geste inconnu.")
    except Litige.DoesNotExist:
        messages.error(request, "Ce litige n'existe pas.")
        return redirect("plateforme:litiges")
    except sequestre_service.SequestreRefuse as refus:
        messages.error(request, str(refus))
    return redirect("plateforme:litige", litige_id=litige_id)


# ----------------------------------------------------------------------------
# Versements
# ----------------------------------------------------------------------------
@exige_console(DROIT_VERSEMENTS, suivi=True)
def versements(request):
    vue = request.GET.get("vue") or "a_executer"
    maintenant = timezone.now()
    with lecture_journalisee(request, ecran="Versements — file d'exécution"):
        a_executer = list(
            Versement.objects.filter(etat=Versement.DEMANDE)
            .select_related("boutique", "compte")
            .order_by("cree_le")
        )
        passes = list(
            Versement.objects.exclude(etat=Versement.DEMANDE)
            .select_related("boutique", "execute_par", "annule_par")
            .order_by("-modifie_le")[:100]
        )
    for v in a_executer:
        v.age = _age(v.cree_le, maintenant)
    return render(
        request,
        "plateforme/versements.html",
        contexte_console(
            request,
            page="versements",
            vue=vue,
            versements=a_executer if vue == "a_executer" else passes,
            nb_a_executer=len(a_executer),
            nb_passes=len(passes),
            total_a_executer=sum((v.montant for v in a_executer), Decimal("0")),
        ),
    )


@exige_console(DROIT_VERSEMENTS, suivi=True)
def versement(request, versement_id):
    if request.method == "POST":
        return _agir_sur_le_versement(request, versement_id)

    v = (
        Versement.objects.select_related(
            "boutique", "compte", "demande_par", "execute_par", "annule_par"
        )
        .filter(pk=versement_id)
        .first()
    )
    if v is None:
        raise Http404("Ce versement n'existe pas.")
    with lecture_journalisee(
        request, ecran=f"Versement {versement_id}", boutique_id=v.boutique_id
    ):
        bilan = sequestre_service.bilan(v.boutique)
        mouvements = list(
            MouvementPortefeuille.objects.filter(boutique_id=v.boutique_id).order_by("-cree_le")[
                :15
            ]
        )
    compte = v.compte
    # La destination figée et le compte tel qu'il est aujourd'hui : s'ils divergent, ou si le
    # compte n'est plus vérifié, l'administrateur le voit avant de faire partir l'argent.
    ecarts = []
    if compte.numero != v.numero or compte.operateur != v.operateur:
        ecarts.append("Le compte a changé depuis la demande : le versement part vers la destination figée.")
    if compte.etat != compte.VERIFIE:
        ecarts.append(
            f"Le compte de destination est aujourd'hui « {compte.get_etat_display().lower()} » : "
            "ce versement ne peut plus être exécuté, il doit être annulé."
        )
    return render(
        request,
        "plateforme/versement.html",
        contexte_console(
            request,
            page="versements",
            v=v,
            compte=compte,
            ecarts=ecarts,
            bilan=bilan,
            mouvements=mouvements,
            anomalie=bilan["ecart"] != 0,
            envoi_api=versements_service.envoi_par_api_possible(v) and not ecarts,
            envoi_en_cours=versements_service.envoi_en_cours(v),
        ),
    )


def _agir_sur_le_versement(request, versement_id):
    action = request.POST.get("action") or ""
    try:
        v = Versement.objects.select_related("compte").get(pk=versement_id)
    except Versement.DoesNotExist:
        messages.error(request, "Ce versement n'existe pas.")
        return redirect("plateforme:versements")

    try:
        if action == "executer":
            reference = (request.POST.get("reference") or "").strip()
            with acces_plateforme(
                utilisateur=request.user,
                motif=f"Exécution du versement, référence opérateur {reference or '—'}",
                ecran=f"Versement {versement_id} — exécution",
                boutique_id=v.boutique_id,
            ):
                versements_service.executer_versement(v, reference=reference, par=request.user)
            messages.success(request, "Versement exécuté : la référence de l'opérateur est enregistrée.")
        elif action == "envoyer_api":
            with acces_plateforme(
                utilisateur=request.user,
                motif="Envoi du versement par l'API de l'opérateur",
                ecran=f"Versement {versement_id} — envoi par API",
                boutique_id=v.boutique_id,
            ):
                operation = versements_service.envoyer_par_api(v, par=request.user)
            v.refresh_from_db()
            if v.etat == v.EXECUTE:
                messages.success(request, "Versement parti et confirmé par l'opérateur.")
            else:
                messages.success(
                    request,
                    "Versement transmis à l'opérateur ; il sera marqué exécuté dès sa confirmation "
                    f"({operation.get_etat_display().lower()}).",
                )
        elif action == "annuler":
            motif = (request.POST.get("motif") or "").strip()
            if len(motif) < versements_service.LONGUEUR_MIN_MOTIF:
                raise versements_service.VersementRefuse("Une annulation se motive, en une phrase.")
            with acces_plateforme(
                utilisateur=request.user,
                motif=f"Annulation du versement : {motif}",
                ecran=f"Versement {versement_id} — annulation",
                boutique_id=v.boutique_id,
            ):
                versements_service.annuler_versement(v, motif=motif, par=request.user)
            messages.success(request, "Versement annulé : le montant est revenu au disponible du marchand.")
        else:
            messages.error(request, "Geste inconnu.")
    except versements_service.VersementRefuse as refus:
        messages.error(request, str(refus))
    return redirect("plateforme:versement", versement_id=versement_id)
