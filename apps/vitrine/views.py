"""Vitrine publique : catalogue, panier, tunnel de commande.

C'est le seul endroit du produit qui s'adresse à quelqu'un qui n'a pas de
compte, et cela change tout. Un acheteur qui doit s'inscrire pour voir un prix
s'en va ; un acheteur qui doit s'inscrire pour poser un article dans un panier
s'en va aussi. **On ne demande son identité qu'au moment où elle devient
nécessaire** — c'est-à-dire quand il faut livrer quelque part.

Ce que la vitrine ne fait pas
-----------------------------

**Elle n'encaisse pas.** La commande est enregistrée, éclatée entre les
marchands, et arrive immédiatement sur leur écran de traitement. Le paiement est
constaté hors ligne, comme au comptoir. C'est la même frontière que pour les
appels d'opérateur (docs/18, §8.8) : tant que la couche Mobile Money n'est pas
écrite contre un bac à sable, un bouton « Payer » ici serait un mensonge.

**Elle n'ouvre pas de session.** Passer commande crée un compte acheteur si le
numéro est inconnu, mais ne connecte personne : un numéro de téléphone non
vérifié ne doit pas donner accès à l'historique de son propriétaire. Il faudra
un code à usage unique pour cela, et il n'existe pas encore.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import Utilisateur
from apps.core.tenancy import contexte_plateforme
from apps.orders.models import Commande, SousCommande
from apps.orders.services import CommandeInvalide, passer_commande
from apps.vitrine import panier as panier_service
from apps.vitrine.catalogue import (
    article_par_identifiant,
    articles_en_vitrine,
    boutique_par_slug,
    boutiques_en_vitrine,
    rayons_ouverts,
)
from apps.vitrine.forms import CommandeForm

CLE_COMMANDES = "commandes_de_la_session"


# ---------------------------------------------------------------------------
# Contexte commun
# ---------------------------------------------------------------------------
def _contexte(request, page: str, **extra) -> dict:
    """Socle de toutes les pages publiques, et capture du parrainage.

    Le code d'apporteur arrive en paramètre d'URL (`?ref=`) sur **n'importe
    quelle** page : un revendeur partage le lien d'un produit, pas celui de la
    page d'accueil. Il est rangé en session et ne sera lu qu'à la commande —
    c'est là seulement que l'attribution se fige, et une attribution existante
    ne se laisse pas écraser (docs/06, §6).
    """
    reference = (request.GET.get("ref") or "").strip()
    if reference:
        request.session[panier_service.CLE_PARRAINAGE] = reference[:12]

    contexte = {
        "page": page,
        "rayons": rayons_ouverts(),
        "articles_au_panier": panier_service.nombre_articles(request.session),
        "recherche": (request.GET.get("q") or "").strip(),
    }
    contexte.update(extra)
    return contexte


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
def accueil(request):
    articles = articles_en_vitrine(limite=12)
    return render(
        request,
        "vitrine/accueil.html",
        _contexte(
            request,
            "accueil",
            articles=articles,
            boutiques=boutiques_en_vitrine()[:6],
        ),
    )


def catalogue(request):
    recherche = (request.GET.get("q") or "").strip()
    code_rayon = request.GET.get("rayon") or ""

    rayons = rayons_ouverts()
    rayon = next((r for r in rayons if r.code == code_rayon), None)

    articles = articles_en_vitrine(recherche=recherche, rayon=rayon, limite=120)
    return render(
        request,
        "vitrine/catalogue.html",
        _contexte(
            request,
            "catalogue",
            articles=articles,
            rayon_courant=rayon,
            nombre=len(articles),
        ),
    )


def article(request, identifiant):
    vendu = article_par_identifiant(identifiant)
    if vendu is None:
        return render(request, "vitrine/introuvable.html", _contexte(request, "catalogue"), status=404)

    voisins = [
        a
        for a in articles_en_vitrine(boutique=vendu.boutique, limite=8)
        if a.pk != vendu.pk
    ][:4]
    return render(
        request,
        "vitrine/article.html",
        _contexte(request, "catalogue", article=vendu, voisins=voisins),
    )


def boutique(request, slug):
    vue = boutique_par_slug(slug)
    if vue is None:
        return render(request, "vitrine/introuvable.html", _contexte(request, "catalogue"), status=404)

    articles = articles_en_vitrine(boutique=vue, limite=120)
    return render(
        request,
        "vitrine/boutique.html",
        _contexte(
            request,
            "catalogue",
            boutique=vue,
            articles=articles,
            nombre=len(articles),
            # Sur **sa** page, le commerçant est chez lui : ses couleurs, son
            # logo. Sur le catalogue de tout le marché, non — mélanger dix
            # chartes sur une même grille ne servirait personne.
            identite=identite_de_la_boutique(vue),
        ),
    )


def identite_de_la_boutique(boutique):
    from apps.marketplace.models import IdentiteVisuelle

    with contexte_plateforme():
        return IdentiteVisuelle.objects.filter(boutique=boutique).first()


# ---------------------------------------------------------------------------
# Panier
# ---------------------------------------------------------------------------
@require_POST
def panier_ajouter(request, identifiant):
    if article_par_identifiant(identifiant) is None:
        messages.error(request, "Cet article n'est plus disponible.")
        return redirect("vitrine_catalogue")

    panier_service.ajouter(request.session, identifiant, request.POST.get("quantite") or 1)
    messages.success(request, "Ajouté à votre panier.")
    return redirect(_suite_sure(request.POST.get("suite")))


def _suite_sure(cible: str | None) -> str:
    """Retour après ajout, borné au site.

    Le formulaire dit où revenir pour que l'acheteur reprenne sa navigation là
    où il l'a laissée. C'est une valeur venue du client : renvoyer dessus sans
    contrôle offrirait une redirection ouverte, c'est-à-dire un lien
    d'apparence légitime menant ailleurs. Seul un chemin relatif est accepté —
    et `//ailleurs.example` est une adresse absolue déguisée, pas un chemin.
    """
    cible = (cible or "").strip()
    if cible.startswith("/") and not cible.startswith("//"):
        return cible
    return "vitrine_panier"


@require_POST
def panier_modifier(request, identifiant):
    panier_service.definir_quantite(request.session, identifiant, request.POST.get("quantite") or 0)
    return redirect("vitrine_panier")


def panier(request):
    lignes = panier_service.lignes(request.session)
    return render(
        request,
        "vitrine/panier.html",
        _contexte(
            request,
            "panier",
            lignes=lignes,
            groupes=panier_service.par_boutique(lignes),
            total=panier_service.total(lignes),
        ),
    )


# ---------------------------------------------------------------------------
# Tunnel de commande
# ---------------------------------------------------------------------------
def commander(request):
    lignes = panier_service.lignes(request.session)
    if not lignes:
        messages.error(request, "Votre panier est vide.")
        return redirect("vitrine_catalogue")

    formulaire = CommandeForm(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        try:
            commande = _enregistrer(request, lignes, formulaire.cleaned_data)
        except CommandeInvalide as erreur:
            messages.error(request, str(erreur))
        else:
            panier_service.vider(request.session)
            _memoriser(request, commande)
            return redirect("vitrine_commande", identifiant=commande.pk)

    return render(
        request,
        "vitrine/commander.html",
        _contexte(
            request,
            "panier",
            formulaire=formulaire,
            lignes=lignes,
            groupes=panier_service.par_boutique(lignes),
            total=panier_service.total(lignes),
        ),
    )


def _enregistrer(request, lignes, donnees) -> Commande:
    acheteur = _acheteur(donnees["telephone"], donnees["nom_complet"])
    commande = passer_commande(
        acheteur=acheteur,
        lignes=[(l["article"], l["quantite"]) for l in lignes],
        code_apporteur=request.session.get(panier_service.CLE_PARRAINAGE, ""),
    )
    Commande.objects.filter(pk=commande.pk).update(
        adresse_livraison=donnees["adresse_livraison"][:255],
        note=donnees.get("note", ""),
    )
    commande.refresh_from_db()
    return commande


def _acheteur(telephone: str, nom_complet: str) -> Utilisateur:
    """Retrouve le compte du numéro, ou en crée un — sans jamais connecter.

    Le nom n'est renseigné qu'à la création. Un numéro déjà connu appartient
    peut-être à un gérant ou à un salarié : laisser un formulaire public
    renommer un compte existant serait une prise de contrôle discrète.

    Le compte est créé sans mot de passe utilisable. Il devient utilisable le
    jour où son propriétaire en définit un, par un chemin qui vérifie le numéro.
    """
    existant = Utilisateur.objects.filter(telephone=telephone).first()
    if existant is not None:
        return existant
    return Utilisateur.objects.create_user(telephone=telephone, nom_complet=nom_complet[:150])


def _memoriser(request, commande) -> None:
    """Garde la commande accessible pour la session qui vient de la passer."""
    connues = list(request.session.get(CLE_COMMANDES) or [])
    connues.append(str(commande.pk))
    request.session[CLE_COMMANDES] = connues[-20:]
    request.session.modified = True


def commande(request, identifiant):
    """Suivi d'une commande, adressé par son identifiant et non par son numéro.

    `CMD-00000042` s'incrémente : quiconque en connaît un les connaît tous. Un
    UUIDv7 ne se devine pas, et c'est lui qui sert d'adresse. Le numéro reste
    affiché — c'est ce que l'acheteur dira au marchand au téléphone.
    """
    with contexte_plateforme():
        commande_vue = (
            Commande.objects.filter(pk=identifiant).select_related("acheteur").first()
        )
        if commande_vue is None:
            return render(
                request, "vitrine/introuvable.html", _contexte(request, "panier"), status=404
            )
        parts = list(
            SousCommande.objects.filter(commande=commande_vue)
            .select_related("boutique")
            .prefetch_related("lignes")
        )

    return render(
        request,
        "vitrine/commande.html",
        _contexte(request, "panier", commande=commande_vue, parts=parts),
    )
