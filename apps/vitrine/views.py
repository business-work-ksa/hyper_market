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

L'acheteur choisit en revanche **comment** il paiera : d'avance — l'argent reste
en séquestre chez le partenaire agréé jusqu'à ce qu'il confirme la réception —
ou à la livraison. Le prépaiement est refusé, boutique par boutique, quand il
ferait dépasser le plafond de séquestre d'une boutique qui n'a pas encore fait
ses preuves ; la page le dit avant l'envoi, et propose la livraison.

**Ce que seule la session de l'acheteur voit.** La page de suivi est adressée
par un identifiant qu'on ne devine pas, mais **le marchand le connaît** : c'est
celui de la commande qu'il traite. Le code de remise, la confirmation de
réception et l'ouverture d'un litige ne sont donc offerts qu'à la session qui a
passé la commande — sinon une fausse boutique lirait le code, ou confirmerait
elle-même la réception qu'elle n'a jamais faite.

**Elle n'ouvre pas de session.** Passer commande crée un compte acheteur si le
numéro est inconnu, mais ne connecte personne : un numéro de téléphone non
vérifié ne doit pas donner accès à l'historique de son propriétaire. Il faudra
un code à usage unique pour cela, et il n'existe pas encore.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.utils.functional import SimpleLazyObject
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.models import Utilisateur
from apps.core.tenancy import contexte_plateforme
from apps.marketplace.confiance import palier_de
from apps.orders.models import Commande, Litige, SousCommande
from apps.orders.services import CommandeInvalide, PrepaiementRefuse, passer_commande
from apps.payments import paiement_en_ligne
from apps.payments import sequestre as sequestre_service
from apps.payments.models import Sequestre, Transaction
from apps.marketplace.models import EmplacementPremium
from apps.vitrine import mise_en_avant
from apps.vitrine import panier as panier_service
from apps.vitrine.catalogue import (
    Filtres,
    article_par_identifiant,
    articles_en_vitrine,
    boutique_par_slug,
    boutiques_en_vitrine,
    compatibilites_de,
    menu_rayons,
    rayons_ouverts,
    rechercher,
)
from apps.vitrine.design_system import contexte as jetons_du_marche
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
        # Le mégamenu : calculé au premier accès du gabarit, une seule fois — et jamais pour un
        # fragment, qui ne l'affiche pas.
        "menu": SimpleLazyObject(menu_rayons),
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
    a_la_une = mise_en_avant.pour_accueil()
    mise_en_avant.compter_affichages(request, a_la_une)
    return render(
        request,
        "vitrine/accueil.html",
        _contexte(
            request,
            "accueil",
            articles=articles,
            boutiques=boutiques_en_vitrine()[:6],
            a_la_une=a_la_une,
        ),
    )


def catalogue(request):
    filtres = Filtres(request.GET, rayons_ouverts())
    resultat = rechercher(filtres)
    contexte = _contexte(
        request,
        "catalogue",
        articles=resultat.articles,
        resultat=resultat,
        filtres=filtres,
        facettes=resultat.facettes,
        puces=_puces_actives(request, filtres, resultat.facettes),
        rayon_courant=filtres.rayon,
        nombre=resultat.total,
        tris=_libelles_tris(),
        url_suivante=_url_page(request, resultat.suivante) if resultat.suivante else "",
    )
    # Rechargement de la seule grille (filtres, rayon, recherche) par static/js/marche.js : un
    # fragment, pas la page ; « suite » ne rend que les cartes de la page suivante. `Vary`
    # empêche un cache de servir le fragment à qui demande la page.
    fragment = request.headers.get("X-Fragment")
    # Bandeau et tête de gondole du rayon : en tête de la première page d'un rayon parcouru, pas
    # dans une recherche (l'acheteur a dit ce qu'il voulait) ni dans la suite d'une liste.
    if filtres.rayon is not None and filtres.page == 1 and not filtres.recherche and fragment != "suite":
        en_avant = mise_en_avant.pour_rayon(filtres.rayon)
        mise_en_avant.compter_affichages(request, en_avant.values())
        contexte["en_avant"] = en_avant
        # Les articles de la tête de gondole ne se répètent pas juste en dessous, dans la grille.
        if en_avant["gondole"]:
            deja = {a.pk for a in en_avant["gondole"].articles}
            contexte["articles"] = [a for a in contexte["articles"] if a.pk not in deja]
    gabarit = {
        "1": "vitrine/partials/catalogue_corps.html",
        "suite": "vitrine/partials/cartes.html",
    }.get(fragment, "vitrine/catalogue.html")
    reponse = render(request, gabarit, contexte)
    patch_vary_headers(reponse, ["X-Fragment"])
    return reponse


def _libelles_tris():
    return [
        ("pertinence", _("Pertinence")),
        ("prix-croissant", _("Prix croissant")),
        ("prix-decroissant", _("Prix décroissant")),
        ("nouveautes", _("Nouveautés")),
    ]


def _url_sans(request, *cles) -> str:
    params = request.GET.copy()
    for cle in (*cles, "page"):
        params.pop(cle, None)
    chaine = params.urlencode()
    return f"{request.path}?{chaine}" if chaine else request.path


def _url_page(request, page) -> str:
    params = request.GET.copy()
    params["page"] = str(page)
    return f"{request.path}?{params.urlencode()}"


def mise_en_avant_clic(request, emplacement_id):
    """Compte le clic sur un lien d'emplacement premium, puis mène à la page visée.

    `vers` ne peut viser que la vitrine elle-même : une adresse de redirection ouverte sur
    l'extérieur servirait à maquiller des liens d'hameçonnage derrière le nom du marché.
    """
    vers = request.GET.get("vers") or ""
    if not (
        vers.startswith("/marche/")
        and url_has_allowed_host_and_scheme(vers, allowed_hosts={request.get_host()})
    ):
        vers = reverse("vitrine_accueil")
    emplacement = EmplacementPremium.objects.filter(pk=emplacement_id).first()
    if emplacement is not None:
        mise_en_avant.compter_clic(request, emplacement)
    return redirect(vers)


def _puces_actives(request, filtres, facettes) -> list[dict]:
    """Une puce par filtre posé, avec l'adresse qui l'enlève : on retire un filtre d'un geste."""
    from apps.backoffice.templatetags.hm import fcfa

    puces = []
    if filtres.categorie:
        libelle = next((c["libelle"] for c in facettes["categories"] if c["slug"] == filtres.categorie), filtres.categorie)
        puces.append({"libelle": libelle, "url": _url_sans(request, "categorie")})
    if filtres.boutique:
        libelle = next((b["libelle"] for b in facettes["boutiques"] if b["slug"] == filtres.boutique), filtres.boutique)
        puces.append({"libelle": libelle, "url": _url_sans(request, "boutique")})
    if filtres.ville:
        puces.append({"libelle": filtres.ville, "url": _url_sans(request, "ville")})
    if filtres.prix_min is not None:
        puces.append({"libelle": _("Dès %(prix)s FCFA") % {"prix": fcfa(filtres.prix_min)}, "url": _url_sans(request, "prix_min")})
    if filtres.prix_max is not None:
        puces.append({"libelle": _("Jusqu'à %(prix)s FCFA") % {"prix": fcfa(filtres.prix_max)}, "url": _url_sans(request, "prix_max")})
    if filtres.verifie:
        puces.append({"libelle": _("Identité vérifiée"), "url": _url_sans(request, "verifie")})
    return puces


def design_system(request):
    """La référence vivante du système de design du marché (docs/26).

    Chaque composant, dans tous ses états, rendu par la même feuille que les pages : ce qu'on y
    voit est ce que l'acheteur verra. Hors index des moteurs de recherche.
    """
    exemples = articles_en_vitrine(limite=4)
    reponse = render(
        request,
        "marche/design_system.html",
        _contexte(request, "design_system", exemples=exemples, **jetons_du_marche()),
    )
    reponse.headers["X-Robots-Tag"] = "noindex"
    return reponse


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
        _contexte(
            request,
            "catalogue",
            article=vendu,
            voisins=voisins,
            compatibilites=compatibilites_de(vendu),
        ),
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
        messages.error(request, _("Cet article n'est plus disponible."))
        return redirect("vitrine_catalogue")

    panier_service.ajouter(request.session, identifiant, request.POST.get("quantite") or 1)
    messages.success(request, _("Ajouté à votre panier."))
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
        messages.error(request, _("Votre panier est vide."))
        return redirect("vitrine_catalogue")

    groupes = panier_service.par_boutique(lignes)
    refus = _refus_de_prepaiement(groupes)
    ouverts = paiement_en_ligne.operateurs_ouverts()
    formulaire = CommandeForm(request.POST or None, prepaiement_ouvert=bool(ouverts))
    if request.method == "POST" and formulaire.is_valid():
        try:
            commande = _enregistrer(request, lignes, formulaire.cleaned_data)
        except PrepaiementRefuse as erreur:
            # Le plafond a changé entre l'affichage et l'envoi : on le redit, on n'impose pas.
            refus.update(erreur.refus)
            messages.error(
                request,
                _(
                    "Le prépaiement n'est plus possible chez une boutique de votre panier : "
                    "relisez la commande, puis envoyez-la à nouveau."
                ),
            )
        except CommandeInvalide as erreur:
            messages.error(request, str(erreur))
        else:
            panier_service.vider(request.session)
            _memoriser(request, commande)
            mise_en_avant.attribuer_commande(request, commande)
            return redirect("vitrine_commande", identifiant=commande.pk)

    for groupe in groupes:
        groupe["refus_prepaiement"] = refus.get(str(groupe["boutique"].pk))
    return render(
        request,
        "vitrine/commander.html",
        _contexte(
            request,
            "panier",
            formulaire=formulaire,
            lignes=lignes,
            groupes=groupes,
            total=panier_service.total(lignes),
            refus=refus,
            a_la_livraison=",".join(sorted(refus)),
            tout_refuse=bool(groupes) and len(refus) == len(groupes),
            operateurs_ouverts=ouverts,
        ),
    )


def _refus_de_prepaiement(groupes) -> dict:
    """Pour chaque boutique du panier, le message qui y refuse le prépaiement, s'il y en a un."""
    refus = {}
    for groupe in groupes:
        message = sequestre_service.refus_de_prepaiement(groupe["boutique"], groupe["total"])
        if message:
            refus[str(groupe["boutique"].pk)] = message
    return refus


def _enregistrer(request, lignes, donnees) -> Commande:
    acheteur = _acheteur(donnees["telephone"], donnees["nom_complet"])
    commande = passer_commande(
        acheteur=acheteur,
        lignes=[(l["article"], l["quantite"]) for l in lignes],
        code_apporteur=request.session.get(panier_service.CLE_PARRAINAGE, ""),
        mode_paiement=(
            SousCommande.A_LA_LIVRAISON
            if donnees.get("mode_paiement") == "livraison"
            else SousCommande.PREPAYE
        ),
        # Seules les boutiques que la page a annoncées : une boutique refusée entre-temps fait
        # échouer l'envoi (`PrepaiementRefuse`) plutôt que de basculer sans le dire.
        a_la_livraison=donnees.get("a_la_livraison") or (),
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


def _acheteur_reconnu(request, commande) -> bool:
    """La requête vient-elle de l'acheteur ? Sa session a passé la commande, ou il est connecté.

    Connaître l'adresse de la page ne suffit pas : le marchand la connaît.
    """
    if str(commande.pk) in (request.session.get(CLE_COMMANDES) or []):
        return True
    utilisateur = getattr(request, "user", None)
    return bool(
        utilisateur is not None
        and utilisateur.is_authenticated
        and utilisateur.pk == commande.acheteur_id
    )


def _lire_commande(identifiant):
    """La commande et ses parts, lues par la façade publique du marché (ADR-012)."""
    with contexte_plateforme():
        commande_vue = Commande.objects.filter(pk=identifiant).select_related("acheteur").first()
        if commande_vue is None:
            return None, []
        parts = list(
            SousCommande.objects.filter(commande=commande_vue)
            .select_related("boutique")
            .prefetch_related("lignes")
            .order_by("cree_le")
        )
        litiges = {}
        for litige in Litige.objects.filter(sous_commande__in=parts).order_by("cree_le"):
            litiges[litige.sous_commande_id] = litige  # le plus récent l'emporte
    sequestres = {
        s.sous_commande_id: s for s in Sequestre.objects.filter(sous_commande__in=parts)
    }
    for part in parts:
        part.sequestre_vu = sequestres.get(part.pk)
        if part.sequestre_vu is not None:
            # La part est déjà lue : on la rattache, plutôt que de la relire hors contexte.
            part.sequestre_vu.sous_commande = part
        part.litige_vu = litiges.get(part.pk)
    return commande_vue, parts


def _decorer_pour_l_acheteur(parts, reconnu: bool) -> None:
    """Ce que l'acheteur peut voir et faire, part par part."""
    for part in parts:
        sequestre = part.sequestre_vu
        litige = part.litige_vu
        en_litige = litige is not None and litige.en_cours
        bloque = sequestre is not None and sequestre.etat == Sequestre.BLOQUE
        livrable = part.etat in (SousCommande.EXPEDIEE, SousCommande.LIVREE)
        part.en_litige = en_litige
        part.code_affiche = (
            sequestre_service.code_de_remise(part)
            if reconnu and bloque and part.livraison_confirmee_le is None and not en_litige
            else None
        )
        part.peut_confirmer = (
            reconnu
            and livrable
            and part.livraison_confirmee_le is None
            and not en_litige
            and (sequestre is None or bloque)
        )
        part.peut_contester = reconnu and bloque and not en_litige
        part.echeance_liberation = (
            sequestre_service.echeance_de_liberation(sequestre) if bloque else None
        )


def commande(request, identifiant):
    """Suivi d'une commande, adressé par son identifiant et non par son numéro.

    `CMD-00000042` s'incrémente : quiconque en connaît un les connaît tous. Un
    UUIDv7 ne se devine pas, et c'est lui qui sert d'adresse. Le numéro reste
    affiché — c'est ce que l'acheteur dira au marchand au téléphone.
    """
    commande_vue, parts = _lire_commande(identifiant)
    if commande_vue is None:
        return render(
            request, "vitrine/introuvable.html", _contexte(request, "panier"), status=404
        )
    reconnu = _acheteur_reconnu(request, commande_vue)
    paiement = _paiement_de(commande_vue) if reconnu else None
    if paiement and paiement["en_cours"] is not None:
        # Retour de la page Orange, ou acheteur qui revient : on relit l'opérateur avant d'afficher.
        paiement["en_cours"] = paiement_en_ligne.actualiser(paiement["en_cours"])
        commande_vue, parts = _lire_commande(identifiant)
        paiement = _paiement_de(commande_vue)
    _decorer_pour_l_acheteur(parts, reconnu)

    return render(
        request,
        "vitrine/commande.html",
        _contexte(
            request,
            "panier",
            commande=commande_vue,
            parts=parts,
            reconnu=reconnu,
            prepayee=any(p.prepayee for p in parts),
            delai_implicite=sequestre_service.DELAI_CONFIRMATION_IMPLICITE.days,
            paiement=paiement,
        ),
    )


# ---------------------------------------------------------------------------
# Paiement en ligne (MTN MoMo, Orange Money)
# ---------------------------------------------------------------------------
def _paiement_de(commande_vue) -> dict | None:
    """Ce que la page de commande doit dire du paiement d'avance, s'il en reste un à faire."""
    if commande_vue.etat != Commande.CONFIRMEE:
        return None
    du = paiement_en_ligne.montant_a_payer(commande_vue)
    if du <= 0:
        return None
    tentatives = list(paiement_en_ligne.transactions_de(commande_vue))
    en_cours = next((t for t in reversed(tentatives) if t.etat == Transaction.INITIEE), None)
    dernier_echec = next(
        (t for t in reversed(tentatives) if t.etat in (Transaction.ECHOUEE, Transaction.EXPIREE)),
        None,
    )
    return {
        "montant": du,
        "en_cours": en_cours,
        "dernier_echec": dernier_echec if en_cours is None else None,
        "operateurs": paiement_en_ligne.operateurs_ouverts(),
        "simule": paiement_en_ligne.paiements_simules(),
        "numero": commande_vue.acheteur.telephone if commande_vue.acheteur_id else "",
    }


@require_POST
def payer(request, identifiant):
    """Lance le paiement d'avance. Réservé à la session qui a passé la commande."""
    commande_vue, _parts = _lire_commande(identifiant)
    if commande_vue is None or not _acheteur_reconnu(request, commande_vue):
        return render(request, "vitrine/introuvable.html", _contexte(request, "panier"), status=404)

    numero = (request.POST.get("numero") or "").strip().replace(" ", "")
    retour = request.build_absolute_uri(reverse("vitrine_commande", args=[commande_vue.pk]))
    try:
        operation = paiement_en_ligne.payer_commande(commande_vue, numero=numero, url_retour=retour)
    except paiement_en_ligne.PaiementImpossible as erreur:
        messages.error(request, str(erreur))
        return redirect("vitrine_commande", identifiant=commande_vue.pk)

    # Orange : le paiement se fait chez lui. On n'y envoie que vers l'adresse qu'il nous a rendue,
    # enregistrée sur la transaction — jamais vers une adresse lue dans la requête.
    adresse = (operation.charge_utile_psp or {}).get("payment_url", "")
    if operation.etat == Transaction.INITIEE and adresse.startswith("https://"):
        return redirect(adresse)
    paiement_en_ligne.constater(operation)
    if operation.etat == Transaction.ECHOUEE:
        messages.error(request, _("Le paiement n'a pas abouti : %(motif)s") % {"motif": _message_de(operation)})
    return redirect("vitrine_commande", identifiant=commande_vue.pk)


def paiement_etat(request, identifiant):
    """Où en est le paiement : relu auprès de l'opérateur. JSON pour la page qui attend, sinon retour."""
    from django.http import JsonResponse

    commande_vue, _parts = _lire_commande(identifiant)
    if commande_vue is None or not _acheteur_reconnu(request, commande_vue):
        return JsonResponse({"etat": "inconnu"}, status=404)
    en_cours = paiement_en_ligne.tentative_en_cours(commande_vue)
    if en_cours is not None:
        en_cours = paiement_en_ligne.actualiser(en_cours)
    commande_vue.refresh_from_db()
    etat = "payee" if commande_vue.etat != Commande.CONFIRMEE else (en_cours.etat if en_cours else "aucun")
    if request.method == "POST" or "application/json" not in request.headers.get("Accept", ""):
        return redirect("vitrine_commande", identifiant=commande_vue.pk)
    return JsonResponse({"etat": etat})


def _message_de(operation) -> str:
    charge = operation.charge_utile_psp or {}
    return charge.get("dernier_message") or charge.get("message") or charge.get("refus") or "refusé par l'opérateur."


def _part_de_l_acheteur(request, identifiant, part_id):
    """La commande et la part visées, **si la requête vient de l'acheteur** ; sinon `None`."""
    commande_vue, parts = _lire_commande(identifiant)
    if commande_vue is None or not _acheteur_reconnu(request, commande_vue):
        return commande_vue, None
    part = next((p for p in parts if p.pk == part_id), None)
    if part is not None:
        _decorer_pour_l_acheteur([part], True)
    return commande_vue, part


def confirmer_reception(request, identifiant, part_id):
    """L'acheteur confirme avoir reçu sa part. Une page, puis un bouton : pas de clic accidentel.

    Le geste compte : il ouvre le délai au terme duquel l'argent part chez le marchand. Il
    mérite une page qui dit ce qu'il déclenche, plutôt qu'un bouton perdu dans le suivi.
    """
    commande_vue, part = _part_de_l_acheteur(request, identifiant, part_id)
    if part is None:
        return render(
            request, "vitrine/introuvable.html", _contexte(request, "panier"), status=404
        )

    if request.method == "POST":
        try:
            sequestre_service.confirmer_par_acheteur(part)
        except sequestre_service.SequestreRefuse as refus:
            messages.error(request, str(refus))
        else:
            messages.success(
                request,
                _("Merci : la réception de votre commande chez %(boutique)s est confirmée.")
                % {"boutique": part.boutique.enseigne},
            )
        return redirect("vitrine_commande", identifiant=commande_vue.pk)

    return render(
        request,
        "vitrine/confirmer_reception.html",
        _contexte(
            request,
            "panier",
            commande=commande_vue,
            part=part,
            delai=palier_de(part.boutique).delai_liberation_jours,
        ),
    )


def ouvrir_litige(request, identifiant, part_id):
    """L'acheteur conteste sa part : motif, description, et l'argent est gelé."""
    commande_vue, part = _part_de_l_acheteur(request, identifiant, part_id)
    if part is None:
        return render(
            request, "vitrine/introuvable.html", _contexte(request, "panier"), status=404
        )

    erreur = None
    motif = request.POST.get("motif") or ""
    description = request.POST.get("description") or ""
    if request.method == "POST":
        try:
            sequestre_service.ouvrir_litige(
                part, motif=motif, description=description, par=request.user
            )
        except sequestre_service.SequestreRefuse as refus:
            erreur = str(refus)
        else:
            messages.success(
                request,
                _(
                    "Votre réclamation est enregistrée. L'argent de cette commande reste en "
                    "séquestre, et la plateforme l'examine sous 72 heures."
                ),
            )
            return redirect("vitrine_commande", identifiant=commande_vue.pk)

    return render(
        request,
        "vitrine/litige.html",
        _contexte(
            request,
            "panier",
            commande=commande_vue,
            part=part,
            motifs=Litige.MOTIFS,
            motif=motif,
            description=description,
            erreur=erreur,
        ),
        status=400 if erreur else 200,
    )
