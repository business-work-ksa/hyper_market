"""Fabriquer : fiches techniques, production du jour, invendus.

Écrans réservés aux métiers qui **fabriquent** ce qu'ils vendent — restauration,
boulangerie. Un quincaillier revend ce qu'il a acheté ; lui proposer une fiche
technique serait lui proposer une saisie sans objet, et les écrans qui ne
servent à personne finissent par faire douter de ceux qui servent.

Ce que ces trois écrans essaient de dire
----------------------------------------

**Fabriquer, c'est transformer du stock en stock.** La farine sort, les
baguettes entrent, et elles entrent exactement à ce que la farine a coûté. Le
boulanger n'a donc rien à saisir sur la valeur : elle est constatée, pas
estimée. C'est aussi la seule manière d'obtenir un coût de revient qui ne mente
pas le jour où le sac de farine augmente.

**Un coût de revient sans détail ne sert à rien.** « 310 F la baguette » ne dit
pas quoi faire. « 310 F, dont 244 de farine » dit où regarder. L'écran montre
donc toujours la décomposition, jamais le seul total.

**Un invendu est une perte, pas un écart de comptage.** Le pain a existé, il a
coûté, il ne sera pas vendu. L'enregistrer en ajustement d'inventaire effacerait
la seule information qui vaille : combien la journée a jeté, et sur quoi.
"""

from decimal import Decimal

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts import permissions as droit
from apps.backoffice.acces import contexte_commun, exige
from apps.backoffice.forms import FicheForm, IngredientForm, InvenduForm, ProductionForm
from apps.catalog.models import LigneRecette, Recette
from apps.inventory.models import MouvementStock
from apps.inventory.services import (
    MouvementInvalide,
    cout_de_revient,
    production_du_jour,
    produire,
    sortir_stock,
)
from apps.marketplace import metiers


def _exiger_le_metier(contexte):
    """Refuse l'écran là où le métier ne fabrique pas.

    404 plutôt qu'un écran vide, comme pour les péremptions : un tableau vide
    dirait « vous n'avez rien produit aujourd'hui » à un quincaillier, ce qui est
    vrai et sans objet — et lui laisserait croire que le logiciel surveille une
    production pour lui.
    """
    metier = contexte["metier"]
    if metier is None or not metier.a(metiers.RECETTE):
        raise Http404("Ce métier ne fabrique pas ce qu'il vend.")
    return metier


def _fiches_actives():
    return (
        Recette.objects.filter(actif=True)
        .select_related("variante__produit")
        .order_by("variante__produit__libelle")
    )


# ---------------------------------------------------------------------------
# Production du jour
# ---------------------------------------------------------------------------
@exige(droit.STOCK_VOIR)
def production(request):
    """Ce qui a été fabriqué aujourd'hui, et de quoi lancer la fournée suivante."""
    contexte = contexte_commun(request, "production")
    _exiger_le_metier(contexte)

    depot = contexte["depot_courant"]
    fiches = list(_fiches_actives())
    mouvements = list(production_du_jour(depot=depot))

    voit_les_couts = droit.COUT_VOIR in contexte["droits"]
    peut_produire = droit.STOCK_MOUVEMENTER in contexte["droits"]
    contexte.update(
        {
            "fiches": fiches,
            "mouvements": mouvements,
            "peut_produire": peut_produire,
            "formulaire": ProductionForm() if peut_produire else None,
            "formulaire_invendu": InvenduForm(recettes=fiches) if peut_produire else None,
            # Un caissier voit ce qui est sorti du four ; il n'a pas à voir ce
            # que la fournée a coûté. Le total n'est donc pas calculé pour lui —
            # pas masqué en CSS, pas calculé (docs/14, §3.6).
            "valeur_produite": (
                sum(
                    (m.quantite * m.cout_unitaire for m in mouvements), Decimal("0")
                ).quantize(Decimal("0.01"))
                if voit_les_couts
                else None
            ),
            "pertes": list(_pertes_du_jour(depot)) if voit_les_couts else None,
        }
    )
    return render(request, "production.html", contexte)


def _pertes_du_jour(depot):
    from django.utils import timezone

    mouvements = MouvementStock.objects.filter(
        type=MouvementStock.PERTE, cree_le__date=timezone.localdate()
    )
    if depot is not None:
        mouvements = mouvements.filter(depot=depot)
    return mouvements.select_related("variante__produit").order_by("-cree_le")


@require_POST
@exige(droit.STOCK_MOUVEMENTER)
def production_lancer(request, recette_id):
    contexte = contexte_commun(request, "production")
    _exiger_le_metier(contexte)

    recette = get_object_or_404(Recette.objects.select_related("variante__produit"), pk=recette_id)
    formulaire = ProductionForm(request.POST)
    if not formulaire.is_valid():
        for erreurs in formulaire.errors.values():
            messages.error(request, erreurs[0])
        return redirect("production")

    try:
        entree, sorties = produire(
            depot=contexte["depot_courant"],
            recette=recette,
            quantite=formulaire.cleaned_data["quantite"],
            commentaire=formulaire.cleaned_data.get("commentaire", ""),
            cree_par=request.user,
        )
    except MouvementInvalide as erreur:
        messages.error(request, str(erreur))
        return redirect("production")

    # Le coût unitaire constaté est rendu au commerçant tout de suite : c'est le
    # chiffre sur lequel il ajustera son prix, et c'est maintenant qu'il y pense.
    if droit.COUT_VOIR in contexte["droits"]:
        messages.success(
            request,
            f"{entree.quantite:.0f} × {recette.variante} produits · "
            f"{len(sorties)} ingrédients consommés · "
            f"revient à {entree.cout_unitaire:.0f} FCFA l'unité.",
        )
    else:
        messages.success(request, f"{entree.quantite:.0f} × {recette.variante} produits.")
    return redirect("production")


@require_POST
@exige(droit.STOCK_MOUVEMENTER)
def production_invendus(request):
    contexte = contexte_commun(request, "production")
    _exiger_le_metier(contexte)

    formulaire = InvenduForm(request.POST, recettes=list(_fiches_actives()))
    if not formulaire.is_valid():
        for erreurs in formulaire.errors.values():
            messages.error(request, erreurs[0])
        return redirect("production")

    sortir_stock(
        depot=contexte["depot_courant"],
        variante=formulaire.cleaned_data["variante"],
        quantite=formulaire.cleaned_data["quantite"],
        type_mouvement=MouvementStock.PERTE,
        origine_type="backoffice.invendus",
        commentaire=formulaire.cleaned_data.get("motif") or "Invendus de la journée",
        cree_par=request.user,
    )
    messages.success(request, "Invendus enregistrés.")
    return redirect("production")


# ---------------------------------------------------------------------------
# Fiches techniques
# ---------------------------------------------------------------------------
@exige(droit.STOCK_VOIR)
def fiches(request):
    contexte = contexte_commun(request, "production")
    metier = _exiger_le_metier(contexte)

    contexte.update(
        {
            "fiches": list(
                Recette.objects.select_related("variante__produit").order_by(
                    "-actif", "variante__produit__libelle"
                )
            ),
            # Le formulaire de création n'est composé que pour qui peut créer :
            # la porte est le décorateur de `fiche_creer`, et l'écran lit le même
            # ensemble de droits qu'elle.
            "formulaire": (
                FicheForm(boutique=contexte["boutique"], metier=metier)
                if droit.STOCK_MOUVEMENTER in contexte["droits"]
                else None
            ),
        }
    )
    return render(request, "fiches.html", contexte)


@require_POST
@exige(droit.STOCK_MOUVEMENTER)
def fiche_creer(request):
    contexte = contexte_commun(request, "production")
    metier = _exiger_le_metier(contexte)
    boutique = contexte["boutique"]

    formulaire = FicheForm(request.POST, boutique=boutique, metier=metier)
    if not formulaire.is_valid():
        for erreurs in formulaire.errors.values():
            messages.error(request, erreurs[0])
        return redirect("fiches")

    recette = Recette.objects.create(
        boutique=boutique,
        variante=formulaire.cleaned_data["variante"],
        rendement=formulaire.cleaned_data["rendement"],
        duree_conservation_jours=formulaire.cleaned_data.get("duree_conservation_jours"),
        note=formulaire.cleaned_data.get("note", ""),
        cree_par=request.user,
    )
    messages.success(request, "Fiche ouverte. Ajoutez maintenant ses ingrédients.")
    return redirect("fiche", recette_id=recette.pk)


@exige(droit.STOCK_VOIR)
def fiche(request, recette_id):
    """Une fiche : ses ingrédients, et ce qu'elle coûte aux prix du jour."""
    contexte = contexte_commun(request, "production")
    _exiger_le_metier(contexte)

    recette = get_object_or_404(Recette.objects.select_related("variante__produit"), pk=recette_id)
    depot = contexte["depot_courant"]

    # Le détail du coût est une donnée d'achat : il suit le droit `cout.voir`,
    # comme le CMP partout ailleurs. Sans ce droit, il n'est pas calculé du tout.
    revient = (
        cout_de_revient(recette, depot=depot)
        if droit.COUT_VOIR in contexte["droits"] and depot is not None
        else None
    )

    contexte.update(
        {
            "recette": recette,
            "formulaire_ingredient": IngredientForm(recette=recette),
            "revient": revient,
            # Ce que la fabrication laisse avant charges. Ce n'est pas la marge
            # commerciale au sens comptable — la TVA et les frais de structure
            # n'y sont pas — et l'écran ne l'appelle donc pas « marge » tout court.
            "marge_production": (
                recette.variante.prix_vente - revient["unitaire"] if revient else None
            ),
            "lignes": list(
                recette.lignes.select_related("ingredient__produit").order_by(
                    "ingredient__produit__libelle"
                )
            ),
        }
    )
    return render(request, "fiche.html", contexte)


@require_POST
@exige(droit.STOCK_MOUVEMENTER)
def fiche_ingredient(request, recette_id):
    contexte = contexte_commun(request, "production")
    _exiger_le_metier(contexte)

    recette = get_object_or_404(Recette.objects, pk=recette_id)
    formulaire = IngredientForm(request.POST, recette=recette)
    if not formulaire.is_valid():
        for erreurs in formulaire.errors.values():
            messages.error(request, erreurs[0])
        return redirect("fiche", recette_id=recette.pk)

    LigneRecette.objects.create(
        boutique=contexte["boutique"],
        recette=recette,
        ingredient=formulaire.cleaned_data["ingredient"],
        quantite=formulaire.cleaned_data["quantite"],
        cree_par=request.user,
    )
    return redirect("fiche", recette_id=recette.pk)


@require_POST
@exige(droit.STOCK_MOUVEMENTER)
def fiche_ingredient_retirer(request, recette_id, ligne_id):
    """Un ingrédient se retire vraiment.

    Contrairement à un lien marketing, une ligne de fiche n'a laissé aucune trace
    dehors : les fabrications déjà faites sont écrites dans le journal du stock,
    avec leurs quantités et leurs coûts. Retirer la ligne ne réécrit donc aucune
    histoire — elle change seulement la prochaine fournée.
    """
    contexte = contexte_commun(request, "production")
    _exiger_le_metier(contexte)

    recette = get_object_or_404(Recette.objects, pk=recette_id)
    LigneRecette.objects.filter(pk=ligne_id, recette=recette).delete()
    return redirect("fiche", recette_id=recette.pk)


@require_POST
@exige(droit.STOCK_MOUVEMENTER)
def fiche_basculer(request, recette_id):
    """Active ou désactive une fiche.

    Une fiche désactivée ne produit plus mais reste lisible : elle explique les
    fabrications passées, qui sont dans le journal du stock. La supprimer rendrait
    ces mouvements orphelins d'explication.
    """
    contexte = contexte_commun(request, "production")
    _exiger_le_metier(contexte)

    recette = get_object_or_404(Recette.objects, pk=recette_id)
    Recette.objects.filter(pk=recette.pk).update(actif=not recette.actif)
    messages.success(
        request,
        "Fiche remise en service." if not recette.actif else "Fiche retirée de la production.",
    )
    return redirect("fiche", recette_id=recette.pk)
