"""Traitement des commandes en ligne par le marchand.

L'écran ne montre pas des commandes : il montre **des sous-commandes**, c'est-à-dire
la part qui revient à cette boutique. Un marchand n'a rien à connaître de ce que
l'acheteur a mis dans le même panier chez un confrère — ce serait au mieux du
bruit, au pire une indication commerciale sur un concurrent.

L'écran est organisé par **ce qu'il y a à faire**, pas par date. Une commande en
attente d'acceptation et une commande livrée la semaine dernière n'ont pas le
même statut d'urgence, et une liste triée par date les mélange. Les files
« à traiter » viennent donc en premier, l'historique après.
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
from apps.orders import services as commandes_service
from apps.orders.models import LigneCommande, Retour, SousCommande

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

    for part in parts:
        part.lignes_affichees = lignes.get(part.pk, [])
        part.articles = sum((l.quantite for l in part.lignes_affichees), Decimal("0"))
        geste = GESTE_SUIVANT.get(part.etat)
        part.action_suivante, part.libelle_action = geste if geste else (None, None)
    return parts


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
    contexte = contexte_commun(request, "commandes")

    # `SousCommande.objects` est borné à la boutique courante : la part d'un
    # confrère est introuvable, pas interdite.
    part = get_object_or_404(
        SousCommande.objects.select_related("commande", "commande__acheteur"),
        pk=sous_commande_id,
    )
    part = _decorer([part])[0]

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
        }
    )
    return render(request, "commande.html", contexte)


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
