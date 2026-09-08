"""Contexte de la requête : boutique, dépôt, droits — et la porte qui les vérifie.

Trois choses que toute vue du back-office doit résoudre avant de faire quoi que
ce soit, et qu'il vaut mieux résoudre au même endroit :

  — **quelle boutique** (le tenant, barrière 1 du multi-tenant) ;
  — **quel dépôt** (l'unité d'exploitation : une caisse, un comptage, une
    réception se font dans un dépôt, pas dans une boutique) ;
  — **quels droits** y a l'utilisateur (`apps.accounts.permissions`).

Le décorateur `exige` fait les trois et refuse avant d'entrer dans la vue. Une
vue décorée peut donc supposer que la boutique existe et que le droit est
acquis : c'est ce qui évite les vérifications oubliées.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from apps.accounts.permissions import LIBELLES, droits_de
from apps.inventory.models import Depot, NiveauStock
from apps.marketplace.models import Boutique


# ----------------------------------------------------------------------------
# Boutique courante
# ----------------------------------------------------------------------------
def boutique_courante(request) -> Boutique | None:
    """Boutique de la session, avec repli sur l'appartenance unique.

    Une session peut perdre sa boutique — cookie effacé, session régénérée après
    changement de mot de passe, connexion par un autre chemin. Renvoyer alors le
    gérant à l'écran de connexion serait absurde s'il n'appartient qu'à une seule
    boutique : on la rétablit. Ce repli reprend celui du middleware de tenancy,
    pour que la vue et le contexte de requête ne divergent jamais.
    """
    identifiant = request.session.get("boutique_id")
    if identifiant:
        boutique = Boutique.objects.filter(pk=identifiant).first()
        if boutique is not None:
            return boutique

    utilisateur = getattr(request, "user", None)
    if utilisateur is None or not utilisateur.is_authenticated:
        return None

    appartenances = list(
        utilisateur.appartenances.filter(actif=True).select_related("boutique")[:2]
    )
    if len(appartenances) != 1:
        # Zéro appartenance, ou plusieurs : c'est à l'utilisateur de choisir.
        return None

    boutique = appartenances[0].boutique
    request.session["boutique_id"] = str(boutique.pk)
    return boutique


# ----------------------------------------------------------------------------
# Dépôt d'exploitation
# ----------------------------------------------------------------------------
def depots_disponibles():
    """Dépôts actifs de la boutique courante, le principal en tête.

    `Depot.objects` est filtré sur le tenant : un identifiant de dépôt venu d'une
    autre boutique ne se résout tout simplement pas.
    """
    return list(Depot.objects.filter(actif=True).order_by("-principal", "libelle"))


def depot_courant(request):
    """Dépôt sur lequel portent les opérations : caisse, réception, comptage.

    Le modèle a toujours été multi-dépôts ; l'interface, elle, supposait le dépôt
    principal. Une réserve et un point de vente ont pourtant des stocks
    différents, et un comptage fait dans la mauvaise réserve produit des écarts
    inventés de toutes pièces.
    """
    identifiant = request.session.get("depot_id") if hasattr(request, "session") else None
    if identifiant:
        depot = Depot.objects.filter(pk=identifiant, actif=True).first()
        if depot is not None:
            return depot

    depot = (
        Depot.objects.filter(actif=True, principal=True).first()
        or Depot.objects.filter(actif=True).first()
    )
    if depot is not None and hasattr(request, "session"):
        request.session["depot_id"] = str(depot.pk)
    return depot


# ----------------------------------------------------------------------------
# Contexte commun aux gabarits
# ----------------------------------------------------------------------------
def niveaux_en_alerte():
    """Articles en rupture ou sous leur seuil de réapprovisionnement."""
    from django.db.models import F, Q

    return NiveauStock.objects.filter(
        Q(quantite__lte=0) | Q(quantite__lte=F("seuil_alerte"))
    ).select_related("variante__produit", "depot")


def contexte_commun(request, page: str) -> dict:
    """Socle passé à tous les gabarits : boutique, dépôts, droits, alertes.

    `droits` est un ensemble de chaînes, testé dans les gabarits par
    `{% if 'marge.voir' in droits %}`. Un écran ne décide jamais seul de ce qu'il
    montre : il lit le même ensemble que le décorateur qui l'a laissé passer.

    Le calcul est mémorisé sur la requête : `exige` l'a déjà fait avant d'ouvrir
    la porte, la vue le redemande ensuite, et il n'y a aucune raison de compter
    deux fois les alertes de stock pour un seul affichage.
    """
    calcule = getattr(request, "_contexte_backoffice", None)
    if calcule is not None:
        return {**calcule, "page": page}

    boutique = boutique_courante(request)
    contexte = {
        "page": page,
        "boutique": boutique,
        "droits": frozenset(),
        "depots": [],
        "depot_courant": None,
        "alertes": None,
    }
    if boutique is None:
        request._contexte_backoffice = contexte
        return contexte

    droits = droits_de(request.user, boutique)
    depots = depots_disponibles() if droits else []

    alertes = None
    if "stock.voir" in droits:
        alertes = niveaux_en_alerte().count() or None

    contexte.update(
        {
            "droits": droits,
            "depots": depots,
            "depot_courant": depot_courant(request) if depots else None,
            "alertes": alertes,
        }
    )
    request._contexte_backoffice = contexte
    return contexte


# ----------------------------------------------------------------------------
# La porte
# ----------------------------------------------------------------------------
def exige(*droits_requis: str):
    """Exige une connexion, une boutique courante, et les droits nommés.

    Un droit manquant produit une page de refus explicite en 403, jamais une
    redirection silencieuse : l'utilisateur doit comprendre que l'écran existe et
    que c'est son rôle qui le lui ferme, sinon il croit à une panne et appelle.
    """

    def decorateur(vue):
        @wraps(vue)
        @login_required(login_url="connexion")
        def enveloppe(request, *args, **kwargs):
            contexte = contexte_commun(request, page="")
            if contexte["boutique"] is None:
                return redirect("connexion")

            manquants = [d for d in droits_requis if d not in contexte["droits"]]
            if manquants:
                return _refuser(request, contexte, manquants)

            return vue(request, *args, **kwargs)

        return enveloppe

    return decorateur


def exige_json(*droits_requis: str):
    """Même porte, pour les points d'entrée appelés par la caisse hors ligne.

    Une redirection HTML vers l'écran de connexion serait interprétée par la file
    d'attente comme une réponse valide : elle jetterait la vente. Ici, un refus
    est un JSON avec un code d'état franc.
    """

    def decorateur(vue):
        @wraps(vue)
        def enveloppe(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse(
                    {"ok": False, "erreur": "Session expirée. Reconnectez-vous."}, status=401
                )
            boutique = boutique_courante(request)
            if boutique is None:
                return JsonResponse(
                    {"ok": False, "erreur": "Aucune boutique active."}, status=403
                )
            acquis = droits_de(request.user, boutique)
            manquants = [d for d in droits_requis if d not in acquis]
            if manquants:
                return JsonResponse(
                    {
                        "ok": False,
                        "erreur": "Votre rôle ne permet pas cette opération.",
                        "droits_manquants": manquants,
                    },
                    status=403,
                )
            return vue(request, *args, **kwargs)

        return enveloppe

    return decorateur


def _refuser(request, contexte, manquants):
    contexte = dict(contexte)
    contexte.update(
        {
            "manquants": [LIBELLES.get(code, code) for code in manquants],
            "roles": _roles_de(request.user, contexte["boutique"]),
        }
    )
    return render(request, "refus.html", contexte, status=403)


def _roles_de(utilisateur, boutique) -> list[str]:
    return list(
        utilisateur.appartenances.filter(actif=True, boutique=boutique)
        .select_related("role")
        .values_list("role__libelle", flat=True)
    )


def page_d_accueil(droits) -> str:
    """Premier écran accessible après connexion, selon le rôle.

    Un caissier n'a rien à faire sur un tableau de bord dont il ne peut lire
    aucune tuile : il ouvre directement sur sa caisse.
    """
    for droit, cible in (
        ("tableau_de_bord", "tableau_de_bord"),
        ("caisse.encaisser", "caisse"),
        ("stock.voir", "stock"),
        ("ventes.voir", "ventes"),
        ("comptabilite.voir", "comptabilite"),
        ("boutique.voir", "boutique"),
    ):
        if droit in droits:
            return cible
    return "boutique"
