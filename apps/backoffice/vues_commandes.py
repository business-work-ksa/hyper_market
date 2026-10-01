"""Traitement des commandes en ligne par le marchand.

L'écran ne montre pas des commandes : il montre **des sous-commandes**, c'est-à-dire
la part qui revient à cette boutique. Un marchand n'a rien à connaître de ce que
l'acheteur a mis dans le même panier chez un confrère — ce serait au mieux du
bruit, au pire une indication commerciale sur un concurrent.

L'écran est organisé par **ce qu'il y a à faire**, pas par date. Une commande en
attente d'acceptation et une commande livrée la semaine dernière n'ont pas le
même statut d'urgence, et une liste triée par date les mélange. Les files
« à traiter » viennent donc en premier, l'historique après.

Chaque part prépayée montre **où en est son argent** : bloqué en séquestre,
libéré, remboursé. Et la fiche porte la saisie du **code de remise** — la seule
preuve de livraison qui libère quelque chose. Marquer « livrée » reste une
déclaration, utile au suivi, sans effet sur l'argent.

Une part gelée — quelle qu'en soit la raison — s'affiche avec un message neutre
et toujours le même (`MESSAGE_GEL`) : la lutte contre le blanchiment interdit
d'avertir la personne visée par une vérification, et un libellé qui varierait
selon la cause la trahirait.
"""

from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts import permissions as droit
from apps.backoffice.acces import contexte_commun, depot_courant, exige
from apps.backoffice.filtres import FiltresCommandesForm
from apps.marketplace.confiance import palier_de
from apps.orders import services as commandes_service
from apps.core import whatsapp
from apps.orders import avis as avis_service
from apps.orders.models import AvisCommande, Commande, LigneCommande, Litige, Retour, SousCommande
from apps.payments import sequestre as sequestre_service
from apps.payments.models import Sequestre

# Ce que le marchand peut faire, et le geste suivant à lui proposer. Écrit ici
# plutôt que dans le gabarit : un bouton qui n'existe pas dans cette table ne
# doit pas pouvoir apparaître à l'écran.
GESTE_SUIVANT = {
    SousCommande.EN_ATTENTE: ("accepter", "Accepter"),
    SousCommande.ACCEPTEE: ("preparer", "Marquer préparée"),
    SousCommande.PREPAREE: ("expedier", "Expédier"),
    SousCommande.EXPEDIEE: ("livrer", "Marquer livrée"),
}

ACTIONS = {
    "accepter": (commandes_service.accepter, "acceptée"),
    "preparer": (commandes_service.preparer, "préparée"),
    "livrer": (commandes_service.livrer, "livrée"),
}

FILES = [
    (SousCommande.EN_ATTENTE, "À accepter"),
    (SousCommande.ACCEPTEE, "À préparer"),
    (SousCommande.PREPAREE, "À expédier"),
    (SousCommande.EXPEDIEE, "En livraison"),
]

TERMINEES = (SousCommande.LIVREE, SousCommande.ANNULEE)


def _parts(etats=None):
    parts = SousCommande.objects.select_related("commande", "commande__acheteur")
    if etats is not None:
        parts = parts.filter(etat__in=etats)
    return parts.order_by("cree_le")


def _decorer(parts) -> list[SousCommande]:
    """Attache à chaque part ses lignes et son geste suivant.

    Une seule requête pour toutes les lignes : la liste affiche jusqu'à quelques
    dizaines de sous-commandes, et une requête par ligne les rendrait lentes
    exactement le jour où il y en a beaucoup.
    """
    parts = list(parts)
    lignes = {}
    for ligne in LigneCommande.objects.filter(sous_commande__in=parts):
        lignes.setdefault(ligne.sous_commande_id, []).append(ligne)

    # Le séquestre n'est pas scopé (c'est un ordre de la plateforme) : on ne lit que ceux des
    # parts déjà bornées à cette boutique, jamais une requête ouverte.
    sequestres = {s.sous_commande_id: s for s in Sequestre.objects.filter(sous_commande__in=parts)}
    gelees = set(
        Litige.objects.filter(
            sous_commande__in=parts, etat__in=Litige.ETATS_OUVERTS
        ).values_list("sous_commande_id", flat=True)
    )

    for part in parts:
        part.lignes_affichees = lignes.get(part.pk, [])
        part.articles = sum((l.quantite for l in part.lignes_affichees), Decimal("0"))
        geste = GESTE_SUIVANT.get(part.etat)
        part.action_suivante, part.libelle_action = geste if geste else (None, None)
        part.sequestre_vu = sequestres.get(part.pk)
        if part.sequestre_vu is not None:
            part.sequestre_vu.sous_commande = part
        part.argent = _etat_de_l_argent(part, part.sequestre_vu, part.pk in gelees)
    return parts


def _etat_de_l_argent(part, sequestre, gelee: bool) -> dict:
    """Ce que le marchand voit de l'argent d'une part : un libellé, un ton, une date.

    Une part gelée ne dit **jamais** pourquoi (voir l'en-tête du module).
    """
    if not part.prepayee:
        return {"code": "livraison", "libelle": "Payée à la livraison", "ton": ""}
    if sequestre is None:
        if part.etat == SousCommande.ANNULEE:
            return {"code": "aucun", "libelle": "Aucun paiement", "ton": ""}
        return {"code": "attendu", "libelle": "Paiement attendu", "ton": "alerte"}
    if sequestre.etat == Sequestre.BLOQUE:
        if gelee:
            return {"code": "gele", "libelle": sequestre_service.MESSAGE_GEL, "ton": "alerte"}
        echeance = sequestre_service.echeance_de_liberation(sequestre)
        if echeance is not None:
            return {
                "code": "bloque",
                "libelle": "En séquestre — libération prévue",
                "ton": "marque",
                "date": echeance,
            }
        return {
            "code": "bloque",
            "libelle": "En séquestre — livraison à confirmer",
            "ton": "marque",
        }
    if sequestre.etat == Sequestre.LIBERE:
        return {"code": "libere", "libelle": "Libéré", "ton": "bon", "date": sequestre.libere_le}
    if sequestre.etat == Sequestre.REMBOURSE:
        return {
            "code": "rembourse",
            "libelle": "Remboursé à l'acheteur",
            "ton": "critique",
            "date": sequestre.rembourse_le,
        }
    return {
        "code": "partage",
        "libelle": "Libéré en partie",
        "ton": "bon",
        "date": sequestre.libere_le,
    }


@exige(droit.COMMANDES_TRAITER)
def commandes(request):
    contexte = contexte_commun(request, "commandes")

    filtres = FiltresCommandesForm(request.GET)
    valeurs = filtres.valeurs

    files = []
    for etat, libelle in FILES:
        # Un filtre d'état vide les autres files : c'est l'effet recherché, et
        # c'est aussi pourquoi la pastille de la barre compte les filtres posés.
        if valeurs.get("etat") and valeurs["etat"] != etat:
            files.append({"etat": etat, "libelle": libelle, "parts": [], "nombre": 0})
            continue
        parts = _decorer(_restreindre(_parts([etat]), valeurs))
        files.append({"etat": etat, "libelle": libelle, "parts": parts, "nombre": len(parts)})

    historique = _decorer(
        _restreindre(_parts(TERMINEES), valeurs).order_by("-modifie_le")[:30]
    )

    a_traiter = sum(f["nombre"] for f in files)
    agregat = SousCommande.objects.filter(
        etat__in=[e for e, _ in FILES]
    ).aggregate(total=Sum("total_ttc"))

    contexte.update(
        {
            "files": files,
            "historique": historique,
            "url_versements": reverse("versements_marchand"),
            "a_traiter": a_traiter,
            "montant_en_cours": agregat["total"] or Decimal("0"),
            "depot": depot_courant(request),
            "filtres": filtres,
            "url_commandes": reverse("commandes"),
        }
    )
    return render(request, "commandes.html", contexte)


def _restreindre(parts, valeurs):
    """Applique la recherche et la borne de date aux parts d'une file.

    L'état, lui, est traité plus haut : il ne restreint pas une file, il en
    choisit une.
    """
    if valeurs.get("q"):
        from django.db.models import Q

        parts = parts.filter(
            Q(commande__numero__icontains=valeurs["q"])
            | Q(commande__acheteur__nom_complet__icontains=valeurs["q"])
        )
    if valeurs.get("depuis"):
        parts = parts.filter(cree_le__date__gte=valeurs["depuis"])
    return parts


@exige(droit.COMMANDES_TRAITER)
def commande(request, sous_commande_id):
    # `SousCommande.objects` est borné à la boutique courante : la part d'un
    # confrère est introuvable, pas interdite.
    part = get_object_or_404(
        SousCommande.objects.select_related("commande", "commande__acheteur"),
        pk=sous_commande_id,
    )
    if request.method == "POST":
        return _saisir_le_code(request, part)

    contexte = contexte_commun(request, "commandes")
    part = _decorer([part])[0]
    sequestre = part.sequestre_vu
    # Le code se saisit une fois la marchandise partie, tant que l'argent attend la preuve
    # de sa remise — et jamais sur une part gelée.
    saisie_code = (
        sequestre is not None
        and sequestre.etat == Sequestre.BLOQUE
        and part.livraison_confirmee_le is None
        and part.argent["code"] != "gele"
        and part.etat in (SousCommande.EXPEDIEE, SousCommande.LIVREE)
    )

    # Deux chemins distincts, et jamais les deux à la fois : avant expédition on
    # refuse, après on retourne. Rien n'est sorti du dépôt tant que la commande
    # n'est pas expédiée, donc un refus n'a rien à réintégrer ; une fois partie,
    # c'est un retour qu'il faut, avec sa réintégration au coût de sortie.
    peut_refuser = part.etat in (
        SousCommande.EN_ATTENTE,
        SousCommande.ACCEPTEE,
        SousCommande.PREPAREE,
    )
    peut_retourner = part.etat in (SousCommande.EXPEDIEE, SousCommande.LIVREE)

    contexte.update(
        {
            "part": part,
            "retours": list(Retour.objects.filter(sous_commande=part)),
            "peut_refuser": peut_refuser,
            "peut_retourner": peut_retourner,
            # La grille à deux colonnes laisse un trou quand une seule carte
            # subsiste : le modificateur la replie sur une colonne (docs/19, §7.5).
            "duo_plein": peut_refuser != peut_retourner,
            "sequestre": sequestre,
            "saisie_code": saisie_code,
            "code_verrouille": saisie_code and sequestre.code_verrouille_le is not None,
            "essais_restants": (
                sequestre_service.ESSAIS_CODE_MAX - sequestre.essais_code_echoues
                if sequestre
                else None
            ),
            "palier": palier_de(contexte["boutique"]),
            "prevenir": (
                avis_service.liens(part, request.build_absolute_uri("/")) if _a_faire(part) else []
            ),
            "avis_envoyes": list(
                AvisCommande.objects.filter(sous_commande=part).select_related("destinataire")
            ),
            "avis_automatiques": whatsapp.api_configuree("gabarit_commande"),
        }
    )
    return render(request, "commande.html", contexte)


def _a_faire(part) -> bool:
    """La part attend-elle un geste de la boutique ? Une part prépayée non payée, pas encore."""
    if part.etat in TERMINEES:
        return False
    return not (part.prepayee and part.commande.etat == Commande.CONFIRMEE)


def _saisir_le_code(request, part):
    """Le livreur rapporte le code que l'acheteur lui a donné : la remise est prouvée.

    Ce n'est pas un geste de l'automate d'états — c'est une preuve, qui peut arriver sur une
    part « expédiée » comme sur une part déjà déclarée « livrée ». Les essais sont comptés en
    base et le code se verrouille après quelques échecs (`apps/payments/sequestre.py`).
    """
    code = request.POST.get("code_remise") or ""
    try:
        sequestre_service.confirmer_par_code(part, code, par=request.user)
    except sequestre_service.SequestreRefuse as refus:
        messages.error(request, str(refus))
    else:
        delai = palier_de(part.boutique).delai_liberation_jours
        messages.success(
            request,
            f"Remise confirmée par le code de l'acheteur. Votre part sera libérée dans {delai} "
            f"jour{'s' if delai > 1 else ''}, sauf réclamation.",
        )
    return redirect("commande", sous_commande_id=part.pk)


@require_POST
@exige(droit.COMMANDES_TRAITER)
def commande_avancer(request, sous_commande_id):
    """Fait avancer une part d'un cran, et d'un seul.

    L'action attendue est envoyée par le formulaire et **confrontée à l'état
    réel** : un bouton resté affiché dans un onglet ouvert depuis ce matin ne
    doit pas pouvoir expédier une commande que quelqu'un a annulée entre-temps.
    """
    part = get_object_or_404(SousCommande.objects, pk=sous_commande_id)
    demandee = request.POST.get("action") or ""
    attendue = GESTE_SUIVANT.get(part.etat, (None, None))[0]

    if demandee != attendue:
        messages.error(
            request,
            "Cette commande a changé d'état entre-temps : rechargez la page.",
        )
        return redirect("commande", sous_commande_id=part.pk)

    try:
        if demandee == "expedier":
            commandes_service.expedier(
                part, depot=depot_courant(request), cree_par=request.user
            )
            messages.success(
                request,
                f"Commande {part.commande.numero} expédiée. Le stock est sorti au coût moyen.",
            )
        else:
            action, participe = ACTIONS[demandee]
            action(part)
            messages.success(request, f"Commande {part.commande.numero} {participe}.")
    except commandes_service.CommandeInvalide as erreur:
        messages.error(request, str(erreur))

    return redirect("commande", sous_commande_id=part.pk)


@require_POST
@exige(droit.COMMANDES_TRAITER)
def commande_annuler(request, sous_commande_id):
    part = get_object_or_404(SousCommande.objects, pk=sous_commande_id)
    motif = (request.POST.get("motif") or "").strip()

    try:
        commandes_service.annuler_sous_commande(part, motif=motif, cree_par=request.user)
    except commandes_service.CommandeInvalide as erreur:
        messages.error(request, str(erreur))
        return redirect("commande", sous_commande_id=part.pk)

    messages.success(
        request,
        f"Commande {part.commande.numero} refusée. Les commissions d'affiliation "
        "sont annulées ; le stock n'avait pas encore bougé.",
    )
    return redirect("commande", sous_commande_id=part.pk)


@require_POST
@exige(droit.COMMANDES_TRAITER)
def commande_retour(request, sous_commande_id):
    part = get_object_or_404(SousCommande.objects, pk=sous_commande_id)
    motif = (request.POST.get("motif") or "").strip()
    if not motif:
        messages.error(request, "Un retour se justifie : indiquez le motif.")
        return redirect("commande", sous_commande_id=part.pk)

    try:
        retour = commandes_service.demander_retour(part, motif=motif)
        commandes_service.accepter_retour(retour, cree_par=request.user)
    except commandes_service.CommandeInvalide as erreur:
        messages.error(request, str(erreur))
        return redirect("commande", sous_commande_id=part.pk)

    messages.success(
        request,
        "Retour accepté. La marchandise est réintégrée au coût auquel elle était sortie.",
    )
    return redirect("commande", sous_commande_id=part.pk)
