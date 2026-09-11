"""Vues du back-office marchand.

Périmètre du palier 1 (docs/18-produit-palier-1.md) : tableau de bord, caisse,
stock, ventes, lecture comptable. Ni marketplace, ni logistique, ni paiement en
ligne — ils viendront quand ils seront financés.

Toutes les vues s'exécutent dans le contexte de la boutique courante, posé par
`BoutiqueCouranteMiddleware` à partir de la session (docs/09, §3.2), et derrière
le décorateur `exige` qui vérifie les droits du rôle (`apps.backoffice.acces`).
Une vue décorée peut supposer que la boutique existe et que le droit est acquis.
"""

import csv
import io
import json
import zipfile
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.staticfiles import finders
from django.db import transaction
from django.db.models import Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounting.services import balance, solde_compte
from apps.accounts import permissions as droit
from apps.accounts.permissions import droits_de
from apps.backoffice.acces import (
    boutique_courante,
    contexte_commun,
    depot_courant,
    depots_disponibles,
    exige,
    exige_json,
    page_d_accueil,
)
from apps.backoffice.forms import (
    ArticleForm,
    CompatibiliteForm,
    DepotForm,
    EntreeStockForm,
    FermetureCaisseForm,
    OuvertureCaisseForm,
    TransfertStockForm,
)
from apps.catalog import vehicules
from apps.catalog.models import CompatibiliteVehicule, Produit, Variante
from apps.inventory.models import (
    Depot,
    Inventaire,
    LigneInventaire,
    MouvementStock,
    NiveauStock,
)
from apps.inventory.services import (
    MouvementInvalide,
    entrer_stock,
    lots_a_surveiller,
    regulariser_inventaire,
    transferer_stock,
)
from apps.marketplace import metiers
from apps.marketplace.models import Boutique
from apps.pos import services as caisse_service
from apps.pos.models import LigneTicket, ReglementTicket, Ticket

JOURS_HISTORIQUE = 14

# Horizon de l'écran des péremptions. Un mois est le délai à partir duquel un
# commerçant peut encore agir : écouler, remiser, retourner au grossiste.
JOURS_PEREMPTION = 30


# ----------------------------------------------------------------------------
# Authentification
# ----------------------------------------------------------------------------
def connexion(request):
    if request.method == "POST":
        telephone = (request.POST.get("telephone") or "").strip()
        utilisateur = authenticate(
            request, telephone=telephone, password=request.POST.get("mot_de_passe")
        )
        if utilisateur is None:
            return render(
                request,
                "connexion.html",
                {"erreur": "Numéro ou mot de passe incorrect.", "telephone": telephone},
                status=401,
            )

        login(request, utilisateur)
        appartenance = utilisateur.appartenances.filter(actif=True).first()
        if appartenance is None:
            logout(request)
            return render(
                request,
                "connexion.html",
                {"erreur": "Ce compte n'est rattaché à aucune boutique active."},
                status=403,
            )
        request.session["boutique_id"] = str(appartenance.boutique_id)
        request.session.pop("depot_id", None)

        # Chacun ouvre sur l'écran qu'il peut réellement utiliser : un caissier
        # arrive sur sa caisse, pas sur un tableau de bord dont toutes les tuiles
        # lui sont fermées.
        droits = droits_de(utilisateur, appartenance.boutique)
        return redirect(page_d_accueil(droits))

    return render(request, "connexion.html")


def deconnexion(request):
    logout(request)
    return redirect("connexion")


# ----------------------------------------------------------------------------
# Dépôt d'exploitation
# ----------------------------------------------------------------------------
@exige()
@require_POST
def choisir_depot(request):
    """Change le dépôt sur lequel portent caisse, réception et comptage."""
    depot = Depot.objects.filter(pk=request.POST.get("depot"), actif=True).first()
    if depot is not None:
        request.session["depot_id"] = str(depot.pk)

    suite = request.POST.get("suite") or ""
    if not url_has_allowed_host_and_scheme(suite, allowed_hosts={request.get_host()}):
        suite = "/"
    return redirect(suite)


# ----------------------------------------------------------------------------
# Tableau de bord
# ----------------------------------------------------------------------------
@exige(droit.TABLEAU_DE_BORD)
def tableau_de_bord(request):
    """Le tableau de bord n'est pas le même écran pour tous les rôles.

    Les tuiles sont composées à partir des droits, pas masquées après coup : un
    magasinier n'a pas une version grisée du tableau du gérant, il a le sien —
    mouvements du jour, valeur du stock, réapprovisionnement.
    """
    contexte = contexte_commun(request, "tableau_de_bord")
    droits = contexte["droits"]

    aujourdhui = timezone.localdate()
    hier = aujourdhui - timedelta(days=1)

    if droit.VENTES_VOIR in droits:
        ca_jour = _chiffre_affaires(aujourdhui, aujourdhui)
        ca_hier = _chiffre_affaires(hier, hier)
        serie = _serie_ventes(JOURS_HISTORIQUE)
        contexte.update(
            {
                "ca_jour": ca_jour,
                "evolution": ((ca_jour - ca_hier) / ca_hier * 100) if ca_hier else None,
                "serie": serie,
                "graphe": geometrie_graphe(serie),
                "derniers_tickets": Ticket.objects.filter(etat=Ticket.CLOTURE).select_related(
                    "session__caissier"
                )[:6],
                "meilleurs": _meilleurs_articles(7),
            }
        )

        if droit.MARGE_VOIR in droits:
            marge_jour = ca_jour - _cout_des_ventes(aujourdhui, aujourdhui)
            contexte.update(
                {
                    "marge_jour": marge_jour,
                    "taux_marge": (marge_jour / ca_jour * 100) if ca_jour else Decimal("0"),
                }
            )

    if droit.STOCK_VOIR in droits:
        niveaux = list(NiveauStock.objects.select_related("variante__produit"))
        ruptures = [n for n in niveaux if n.quantite <= 0]
        sous_seuil = [n for n in niveaux if 0 < n.quantite <= n.seuil_alerte]
        sains = [n for n in niveaux if n.quantite > n.seuil_alerte]
        contexte.update(
            {
                "nb_references": len(niveaux),
                "nb_ruptures": len(ruptures),
                "nb_sous_seuil": len(sous_seuil),
                "nb_sains": len(sains),
                "part_sains": _part(len(sains), len(niveaux)),
                "part_sous_seuil": _part(len(sous_seuil), len(niveaux)),
                "part_ruptures": _part(len(ruptures), len(niveaux)),
                "alertes_stock": (ruptures + sous_seuil)[:6],
                "mouvements_jour": MouvementStock.objects.filter(
                    cree_le__date=aujourdhui
                ).count(),
            }
        )
        if droit.COUT_VOIR in droits:
            contexte["valeur_stock"] = sum(
                (n.quantite * n.cmp for n in niveaux), Decimal("0")
            )

    if droit.COMPTABILITE_VOIR in droits:
        contexte["tresorerie"] = solde_compte(
            "571", boutique_id=contexte["boutique"].pk
        ) + solde_compte("5311", boutique_id=contexte["boutique"].pk)

    return render(request, "tableau_de_bord.html", contexte)


def _part(valeur: int, total: int) -> float:
    return round(valeur / total * 100, 1) if total else 0.0


def _chiffre_affaires(debut, fin) -> Decimal:
    agg = Ticket.objects.filter(
        etat=Ticket.CLOTURE, cloture_le__date__gte=debut, cloture_le__date__lte=fin
    ).aggregate(total=Sum("total_ttc"))
    return agg["total"] or Decimal("0")


def _cout_des_ventes(debut, fin) -> Decimal:
    """Coût des marchandises vendues, lu sur les mouvements de stock réels.

    On ne recalcule pas la marge à partir d'un prix d'achat théorique : on la lit
    sur le CMP effectivement appliqué à la sortie. C'est la seule valeur qui
    correspond à ce que le commerçant a réellement payé.
    """
    mouvements = MouvementStock.objects.filter(
        origine_type="pos.Ticket",
        type=MouvementStock.SORTIE,
        cree_le__date__gte=debut,
        cree_le__date__lte=fin,
    )
    return sum((abs(m.quantite) * m.cout_unitaire for m in mouvements), Decimal("0"))


def _serie_ventes(jours: int) -> list[dict]:
    """Série journalière du chiffre d'affaires — une seule série, pas de légende."""
    fin = timezone.localdate()
    debut = fin - timedelta(days=jours - 1)

    par_jour = {}
    tickets = Ticket.objects.filter(
        etat=Ticket.CLOTURE, cloture_le__date__gte=debut, cloture_le__date__lte=fin
    ).values_list("cloture_le", "total_ttc")
    for cloture_le, total in tickets:
        cle = timezone.localtime(cloture_le).date()
        par_jour[cle] = par_jour.get(cle, Decimal("0")) + total

    jours_fr = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    serie = []
    for decalage in range(jours):
        jour = debut + timedelta(days=decalage)
        serie.append(
            {
                "date": jour,
                "libelle": f"{jours_fr[jour.weekday()]} {jour.day:02d}",
                "libelle_long": jour.strftime("%d/%m/%Y"),
                "valeur": par_jour.get(jour, Decimal("0")),
            }
        )
    return serie


def geometrie_graphe(serie: list[dict], largeur: int = 740, hauteur: int = 210) -> dict:
    """Prépare la géométrie SVG du graphe de ventes.

    Calculée côté serveur plutôt qu'en JavaScript : la page reste lisible sans script,
    et le premier rendu n'attend rien (contrainte de frugalité, docs/19, §5).

    Conventions imposées par le système de visualisation :
    — une seule série, donc pas de légende : le titre nomme la mesure ;
    — marques fines, extrémité haute arrondie à 4 px, ancrée sur la ligne de base ;
    — écart de 2 px minimum entre deux remplissages voisins ;
    — étiquette directe sur le seul maximum, jamais sur chaque barre.
    """
    # La marge gauche doit loger l'étiquette la plus large (« 400 000 ») sans
    # la coller au bord : 64 px laissent une respiration à 10,5 px de corps.
    marge = {"haut": 18, "droite": 8, "bas": 26, "gauche": 64}
    aire_l = largeur - marge["gauche"] - marge["droite"]
    aire_h = hauteur - marge["haut"] - marge["bas"]
    base_y = marge["haut"] + aire_h

    valeurs = [float(point["valeur"]) for point in serie]
    plafond = _plafond_agreable(max(valeurs) if valeurs else 0)

    creneau = aire_l / len(serie) if serie else aire_l
    largeur_barre = min(creneau - 6, 24)  # marque fine ; l'écart dépasse les 2 px requis

    barres = []
    indice_max = valeurs.index(max(valeurs)) if valeurs and max(valeurs) > 0 else -1
    for rang, point in enumerate(serie):
        valeur = float(point["valeur"])
        h = (valeur / plafond * aire_h) if plafond else 0
        h = max(h, 2) if valeur > 0 else 0
        x = marge["gauche"] + creneau * rang + (creneau - largeur_barre) / 2
        y = base_y - h
        rayon = min(4, h / 2) if h else 0

        barres.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "largeur": round(largeur_barre, 2),
                "hauteur": round(h, 2),
                "centre": round(x + largeur_barre / 2, 2),
                "creneau_x": round(marge["gauche"] + creneau * rang, 2),
                "creneau_l": round(creneau, 2),
                "chemin": _chemin_barre(x, y, largeur_barre, h, rayon),
                "y_etiquette": round(y - 7, 2),
                "libelle": point["libelle"],
                "libelle_long": point["libelle_long"],
                "valeur": point["valeur"],
                "est_max": rang == indice_max,
                "tick_visible": rang % 2 == 1,
            }
        )

    lignes = []
    for part in (0, 0.25, 0.5, 0.75, 1):
        y = base_y - aire_h * part
        lignes.append(
            {
                "y": round(y, 2),
                # Décalage de la ligne de base du texte, calculé ici : le filtre
                # `add` de Django ne sait pas additionner un flottant et « 3.5 »,
                # il renvoie une chaîne vide et l'étiquette retombe à y=0.
                "y_texte": round(y + 3.5, 2),
                "valeur": Decimal(str(plafond * part)),
                "base": part == 0,
            }
        )

    return {
        "largeur": largeur,
        "hauteur": hauteur,
        "barres": barres,
        "lignes": lignes,
        "x_gauche": marge["gauche"],
        "x_droite": largeur - marge["droite"],
        "x_etiquettes": marge["gauche"] - 10,
        "y_haut": marge["haut"],
        "y_base": base_y,
        "y_ticks": base_y + 16,
        "hauteur_survol": aire_h,
    }


def _plafond_agreable(maximum: float) -> float:
    """Arrondit l'échelle à une graduation lisible plutôt qu'au maximum brut."""
    if maximum <= 0:
        return 1000.0
    import math

    magnitude = 10 ** math.floor(math.log10(maximum))
    for facteur in (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
        if maximum <= magnitude * facteur:
            return magnitude * facteur
    return magnitude * 10


def _chemin_barre(x: float, y: float, largeur: float, hauteur: float, rayon: float) -> str:
    """Barre à extrémité haute arrondie, pied carré sur la ligne de base."""
    if hauteur <= 0:
        return ""
    bas = y + hauteur
    r = min(rayon, largeur / 2)
    return (
        f"M{x:.2f},{bas:.2f} L{x:.2f},{y + r:.2f} Q{x:.2f},{y:.2f} {x + r:.2f},{y:.2f} "
        f"L{x + largeur - r:.2f},{y:.2f} Q{x + largeur:.2f},{y:.2f} "
        f"{x + largeur:.2f},{y + r:.2f} L{x + largeur:.2f},{bas:.2f} Z"
    )


def _meilleurs_articles(limite: int) -> list[dict]:
    """Articles les plus vendus sur la période d'historique, par chiffre d'affaires."""
    depuis = timezone.now() - timedelta(days=JOURS_HISTORIQUE)
    lignes = LigneTicket.objects.filter(
        ticket__etat=Ticket.CLOTURE, ticket__cloture_le__gte=depuis
    ).select_related("variante__produit")

    cumul: dict[str, dict] = {}
    for ligne in lignes:
        cle = str(ligne.variante_id)
        entree = cumul.setdefault(
            cle,
            {"libelle": ligne.libelle, "quantite": Decimal("0"), "montant": Decimal("0")},
        )
        entree["quantite"] += ligne.quantite
        entree["montant"] += ligne.total_ttc

    classement = sorted(cumul.values(), key=lambda e: e["montant"], reverse=True)[:limite]
    maximum = classement[0]["montant"] if classement else Decimal("1")
    for entree in classement:
        entree["part"] = round(entree["montant"] / maximum * 100, 1) if maximum else 0
    return classement


# ----------------------------------------------------------------------------
# Caisse
# ----------------------------------------------------------------------------
def _articles_caisse(depot) -> list[dict]:
    """Catalogue vendable du dépôt, sous la forme consommée par la caisse.

    Une seule construction, servie à deux endroits : le gabarit de la caisse et
    le point d'entrée JSON qui alimente le catalogue hors ligne. Deux
    représentations divergentes du même catalogue produiraient, tôt ou tard, une
    tuile qui vend un prix que le serveur ne connaît pas.
    """
    variantes = (
        Variante.objects.filter(actif=True)
        .select_related("produit", "produit__categorie")
        .order_by("produit__libelle")
    )
    niveaux = {}
    if depot is not None:
        niveaux = {n.variante_id: n for n in NiveauStock.objects.filter(depot=depot)}

    articles = []
    for variante in variantes:
        niveau = niveaux.get(variante.id)
        articles.append(
            {
                "id": str(variante.id),
                "libelle": variante.produit.libelle,
                "sku": variante.sku,
                "code_barres": variante.code_barres or "",
                "prix": float(variante.prix_vente),
                "taux_tva": float(variante.taux_tva),
                "stock": float(niveau.quantite) if niveau else 0.0,
                "categorie": (
                    variante.produit.categorie.libelle if variante.produit.categorie else ""
                ),
                # Porté jusque dans le catalogue hors ligne : c'est la caisse
                # qui doit réclamer l'ordonnance pendant que le client est là,
                # réseau ou pas.
                "sur_ordonnance": variante.produit.sur_ordonnance,
            }
        )
    return articles


@exige(droit.CAISSE_ENCAISSER)
def caisse(request):
    contexte = contexte_commun(request, "caisse")
    depot = contexte["depot_courant"]
    session = _session_ouverte(request)

    articles = _articles_caisse(session.depot if session else depot)
    contexte.update(
        {
            "articles": articles,
            "session_caisse": session,
            "tickets_session": (
                Ticket.objects.filter(session=session, etat=Ticket.CLOTURE).count()
                if session
                else 0
            ),
        }
    )
    return render(request, "caisse.html", contexte)


@exige_json(droit.CAISSE_ENCAISSER)
def catalogue_json(request):
    """Catalogue du dépôt, pour le cache hors ligne de la caisse.

    Le service worker sert la page de caisse depuis son cache quand le réseau
    manque — mais une page en cache fige aussi son catalogue. Un article créé ce
    matin serait invisible cet après-midi sur un poste hors ligne. La grille est
    donc reconstruite à partir de ce point d'entrée, rangé dans IndexedDB à
    chaque passage en ligne : l'écran est au pire aussi frais que la dernière
    connexion, jamais aussi vieux que la page.
    """
    session = _session_ouverte(request)
    depot = session.depot if session else depot_courant(request)
    return JsonResponse(
        {
            "ok": True,
            "genere_le": timezone.localtime().isoformat(timespec="seconds"),
            "depot": str(depot.pk) if depot else None,
            "articles": _articles_caisse(depot),
        }
    )


def _session_ouverte(request):
    from apps.pos.models import SessionCaisse

    return (
        SessionCaisse.objects.filter(caissier=request.user, etat=SessionCaisse.OUVERTE)
        .select_related("depot")
        .first()
    )


@exige_json(droit.CAISSE_ENCAISSER)
@require_POST
def caisse_encaisser(request):
    """Encaisse un panier : ticket, sortie de stock au CMP, écritures comptables.

    Un seul appel déclenche toute la chaîne — c'est la promesse « zéro double
    saisie » (docs/07, §1.2).
    """
    try:
        charge = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "erreur": "Requête illisible."}, status=400)

    lignes = charge.get("lignes") or []
    if not lignes:
        return JsonResponse({"ok": False, "erreur": "Le panier est vide."}, status=400)

    # Une session ouverte est liée à son dépôt : elle l'emporte sur le dépôt
    # choisi dans l'en-tête, sinon une vente sortirait le stock d'une réserve
    # pendant qu'on encaisse au comptoir.
    session = _session_ouverte(request)
    depot = session.depot if session else depot_courant(request)
    if depot is None:
        return JsonResponse({"ok": False, "erreur": "Aucun dépôt configuré."}, status=400)

    if session is None:
        session = caisse_service.ouvrir_session(
            depot=depot, caissier=request.user, fonds_ouverture=Decimal("0")
        )

    # Au comptoir, une référence inconnue est ignorée plutôt que de faire échouer
    # la vente entière : le caissier a le client devant lui. L'API, elle, refuse
    # — c'est la même opération, ce n'est pas la même situation.
    panier = []
    for ligne in lignes:
        variante = Variante.objects.filter(pk=ligne.get("variante")).first()
        if variante is None:
            continue
        panier.append((variante, Decimal(str(ligne.get("quantite", 1))), Decimal("0")))

    try:
        ticket, rejoue = caisse_service.encaisser(
            session=session,
            lignes=panier,
            moyen=charge.get("moyen") or "especes",
            operation_id=charge.get("operation_id") or None,
            client_nom=charge.get("client") or "",
            cree_par=request.user,
            # Absente, elle ne bloque pas la vente : la boîte est partie avec le
            # client. Le ticket ressort dans l'ordonnancier, à compléter.
            mention_ordonnance=charge.get("mention_ordonnance") or "",
        )
    except caisse_service.TicketInvalide as erreur:
        return JsonResponse({"ok": False, "erreur": str(erreur)}, status=400)

    return JsonResponse(
        {
            "ok": True,
            "numero": ticket.numero,
            "total": float(ticket.total_ttc),
            "ticket_id": str(ticket.pk),
            "rejoue": rejoue,
        }
    )


# ----------------------------------------------------------------------------
# Stock
# ----------------------------------------------------------------------------
@exige(droit.STOCK_VOIR)
def stock(request):
    contexte = contexte_commun(request, "stock")

    recherche = (request.GET.get("q") or "").strip()
    filtre = request.GET.get("etat") or "tous"

    # Le filtre de dépôt est confronté à la liste réelle plutôt qu'injecté tel
    # quel : un identifiant fantaisiste dans l'URL doit produire « tous », pas
    # une erreur de conversion.
    connus = {str(d.pk) for d in contexte["depots"]}
    depot_filtre = request.GET.get("depot") or "tous"
    if depot_filtre not in connus:
        depot_filtre = "tous"

    niveaux = NiveauStock.objects.select_related(
        "variante__produit", "variante__produit__categorie", "depot"
    ).order_by("variante__produit__libelle")

    if depot_filtre != "tous":
        niveaux = niveaux.filter(depot_id=depot_filtre)

    if recherche:
        from django.db.models import Q

        niveaux = niveaux.filter(
            Q(variante__produit__libelle__icontains=recherche)
            | Q(variante__sku__icontains=recherche)
            # La référence du constructeur est celle qui est gravée sur la pièce :
            # c'est souvent la seule chose que le client apporte.
            | Q(variante__reference_constructeur__icontains=recherche)
        )

    metier = contexte["metier"]
    vehicule = _vehicule_demande(request) if metier and metier.a(metiers.COMPATIBILITE) else None
    if vehicule:
        niveaux = niveaux.filter(variante__in=vehicules.compatibles(**vehicule))

    niveaux = list(niveaux)
    if filtre == "rupture":
        niveaux = [n for n in niveaux if n.quantite <= 0]
    elif filtre == "alerte":
        niveaux = [n for n in niveaux if 0 < n.quantite <= n.seuil_alerte]

    contexte.update(
        {
            "niveaux": niveaux,
            "recherche": recherche,
            "filtre": filtre,
            "depot_filtre": depot_filtre,
            "valeur_totale": sum((n.quantite * n.cmp for n in niveaux), Decimal("0")),
            "vehicule": vehicule,
            # Le nombre de **pièces**, pas de lignes : un article présent dans
            # deux dépôts fait deux lignes et reste une seule pièce, et annoncer
            # « 5 pièces compatibles » pour quatre références est un mensonge que
            # le vendeur repère au premier coup d'œil.
            "nb_compatibles": len({n.variante_id for n in niveaux}) if vehicule else None,
            "marques_connues": (
                vehicules.marques_connues()
                if metier and metier.a(metiers.COMPATIBILITE)
                else []
            ),
            "modeles_connus": (
                vehicules.modeles_connus(vehicule["marque"] if vehicule else "")
                if metier and metier.a(metiers.COMPATIBILITE)
                else []
            ),
        }
    )
    return render(request, "stock.html", contexte)


def _vehicule_demande(request) -> dict | None:
    """Véhicule décrit dans l'URL, ou rien.

    L'année illisible est **ignorée**, jamais une erreur : un client qui dit
    « une Corolla, dans les 2015 » et un vendeur qui tape « 15 » ne doivent pas
    tomber sur un message d'erreur mais sur la liste des filtres Corolla. Une
    recherche au comptoir se fait en parlant à quelqu'un, pas en remplissant un
    formulaire.
    """
    marque = (request.GET.get("marque") or "").strip()
    modele = (request.GET.get("modele") or "").strip()
    brut = (request.GET.get("annee") or "").strip()

    annee = None
    if brut.isdigit() and 1950 <= int(brut) <= 2100:
        annee = int(brut)

    if not marque and not modele and annee is None:
        return None
    return {"marque": marque, "modele": modele, "annee": annee}


@exige(droit.STOCK_VOIR)
def article(request, variante_id):
    contexte = contexte_commun(request, "stock")

    variante = Variante.objects.filter(pk=variante_id).select_related("produit").first()
    if variante is None:
        return redirect("stock")

    metier = contexte["metier"]
    suit_les_vehicules = metier is not None and metier.a(metiers.COMPATIBILITE)

    contexte.update(
        {
            "variante": variante,
            "niveaux": NiveauStock.objects.filter(variante=variante).select_related("depot"),
            "mouvements": MouvementStock.objects.filter(variante=variante).select_related(
                "depot"
            )[:30],
            # Ni la liste ni le formulaire ne sont composés là où le métier
            # n'active pas la fonction : une quincaillerie n'a pas de véhicules.
            "compatibilites": (
                list(variante.compatibilites.all()) if suit_les_vehicules else None
            ),
            "formulaire_compatibilite": (
                CompatibiliteForm(variante=variante)
                if suit_les_vehicules and droit.STOCK_MOUVEMENTER in contexte["droits"]
                else None
            ),
            "marques_connues": vehicules.marques_connues() if suit_les_vehicules else [],
            "modeles_connus": vehicules.modeles_connus() if suit_les_vehicules else [],
        }
    )
    return render(request, "article.html", contexte)


@require_POST
@exige(droit.STOCK_MOUVEMENTER)
def compatibilite_ajouter(request, variante_id):
    contexte = contexte_commun(request, "stock")
    metier = contexte["metier"]
    if metier is None or not metier.a(metiers.COMPATIBILITE):
        raise Http404("Ce métier ne suit pas les compatibilités véhicule.")

    variante = get_object_or_404(Variante.objects, pk=variante_id)
    formulaire = CompatibiliteForm(request.POST, variante=variante)
    if not formulaire.is_valid():
        for erreurs in formulaire.errors.values():
            messages.error(request, erreurs[0])
        return redirect("article", variante_id=variante.pk)

    CompatibiliteVehicule.objects.create(
        boutique=contexte["boutique"],
        variante=variante,
        marque=formulaire.cleaned_data["marque"],
        modele=formulaire.cleaned_data.get("modele", ""),
        motorisation=formulaire.cleaned_data.get("motorisation", "").strip(),
        annee_debut=formulaire.cleaned_data.get("annee_debut"),
        annee_fin=formulaire.cleaned_data.get("annee_fin"),
        cree_par=request.user,
    )
    return redirect("article", variante_id=variante.pk)


@require_POST
@exige(droit.STOCK_MOUVEMENTER)
def compatibilite_retirer(request, variante_id, compatibilite_id):
    """Une compatibilité fausse se retire vraiment.

    Contrairement à un lien marketing, elle n'a rien laissé dehors : c'est une
    affirmation sur le montage d'une pièce, et une affirmation fausse ne se
    conserve pas « pour l'historique ». La garder ferait repartir un client avec
    la mauvaise pièce.
    """
    contexte_commun(request, "stock")
    CompatibiliteVehicule.objects.filter(
        pk=compatibilite_id, variante_id=variante_id
    ).delete()
    return redirect("article", variante_id=variante_id)


# ----------------------------------------------------------------------------
# Reprise et mouvements de stock
# ----------------------------------------------------------------------------
@exige(droit.STOCK_MOUVEMENTER)
def nouvel_article(request):
    """Création d'un article avec son stock initial.

    C'est l'écran de l'installation : pendant un comptage debout dans une
    réserve, on ne remplit pas quatre écrans par référence.
    """
    contexte = contexte_commun(request, "stock")
    boutique = contexte["boutique"]

    depot = contexte["depot_courant"]
    if depot is None:
        depot = Depot.objects.create(
            boutique=boutique, libelle="Magasin principal", type=Depot.BOUTIQUE, principal=True
        )
        request.session["depot_id"] = str(depot.pk)

    if request.method == "POST":
        formulaire = ArticleForm(request.POST, boutique=boutique)
        if formulaire.is_valid():
            variante = _creer_article(formulaire.cleaned_data, boutique, depot, request.user)
            messages.success(request, f"« {variante.produit.libelle} » ajouté à votre stock.")
            suite = "nouvel_article" if request.POST.get("enchainer") else "stock"
            return redirect(suite)
    else:
        formulaire = ArticleForm(boutique=boutique)

    contexte.update({"formulaire": formulaire, "depot": depot})
    return render(request, "article_nouveau.html", contexte)


@transaction.atomic
def _creer_article(donnees, boutique, depot, utilisateur) -> Variante:
    """Produit, variante, seuil et entrée de stock valorisée, en une transaction."""
    produit = Produit.objects.create(
        boutique=boutique,
        sku=donnees["sku"],
        libelle=donnees["libelle"],
        regime_tva=donnees["regime_tva"],
        unite=donnees.get("unite") or boutique.metier_choisi.unite_defaut,
        # Faux partout sauf en officine : la case n'y est même pas affichée
        # ailleurs (`ArticleForm._composer`).
        sur_ordonnance=bool(donnees.get("sur_ordonnance")),
        cree_par=utilisateur,
    )
    variante = Variante.objects.create(
        boutique=boutique,
        produit=produit,
        sku=donnees["sku"],
        code_barres=donnees.get("code_barres") or "",
        prix_vente=donnees["prix_vente"],
        # Vide partout sauf en pièces détachées : le champ n'y est même pas
        # affiché ailleurs (`ArticleForm._composer`).
        reference_constructeur=(donnees.get("reference_constructeur") or "").strip(),
        cree_par=utilisateur,
    )
    NiveauStock.objects.create(
        boutique=boutique,
        depot=depot,
        variante=variante,
        seuil_alerte=donnees["seuil_alerte"],
    )
    if donnees["quantite"] > 0:
        entrer_stock(
            depot=depot,
            variante=variante,
            quantite=donnees["quantite"],
            cout_unitaire=donnees["cout_unitaire"],
            origine_type="backoffice.reprise",
            commentaire="Reprise de stock à l'installation",
            cree_par=utilisateur,
            # Vides pour les métiers qui n'activent pas la fonction : le suivi
            # par lot reste alors entièrement inerte.
            date_peremption=donnees.get("date_peremption"),
            numero_lot=donnees.get("numero_lot") or "",
        )
    return variante


@exige(droit.STOCK_MOUVEMENTER)
def entree_stock(request, variante_id):
    """Réception fournisseur : le CMP est recalculé par le moteur de stock."""
    contexte = contexte_commun(request, "stock")

    variante = Variante.objects.filter(pk=variante_id).select_related("produit").first()
    if variante is None:
        return redirect("stock")

    depot = contexte["depot_courant"]
    niveau = NiveauStock.objects.filter(variante=variante, depot=depot).first()

    if request.method == "POST":
        formulaire = EntreeStockForm(request.POST)
        if formulaire.is_valid():
            mouvement = entrer_stock(
                depot=depot,
                variante=variante,
                quantite=formulaire.cleaned_data["quantite"],
                cout_unitaire=formulaire.cleaned_data["cout_unitaire"],
                origine_type="backoffice.reception",
                commentaire=formulaire.cleaned_data["commentaire"] or "Réception fournisseur",
                cree_par=request.user,
            )
            messages.success(
                request,
                f"Entrée enregistrée. Nouveau coût moyen : {mouvement.cmp_apres:.0f} FCFA.",
            )
            return redirect("article", variante_id=variante.pk)
    else:
        initial = {"cout_unitaire": niveau.cmp.quantize(Decimal("1"))} if niveau else {}
        formulaire = EntreeStockForm(initial=initial)

    contexte.update({"formulaire": formulaire, "variante": variante, "niveau": niveau})
    return render(request, "stock_entree.html", contexte)


@exige_json(droit.STOCK_MOUVEMENTER)
@require_POST
def entree_stock_json(request, variante_id):
    """Même réception, en JSON et **idempotente** — pour la file hors ligne.

    Jusqu'ici, seules les ventes survivaient à une coupure. Une réception saisie
    au moment où le réseau tombe était simplement perdue, et le camion reparti :
    la marchandise était en réserve et absente du système. Le mouvement porte
    désormais la même clé d'idempotence qu'un ticket, ce qui rend son rejeu sûr.
    """
    try:
        charge = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "erreur": "Requête illisible."}, status=400)

    variante = Variante.objects.filter(pk=variante_id).first()
    if variante is None:
        return JsonResponse({"ok": False, "erreur": "Article introuvable."}, status=400)

    depot = Depot.objects.filter(pk=charge.get("depot"), actif=True).first() or depot_courant(
        request
    )
    if depot is None:
        return JsonResponse({"ok": False, "erreur": "Aucun dépôt configuré."}, status=400)

    formulaire = EntreeStockForm(
        {
            "quantite": charge.get("quantite"),
            "cout_unitaire": charge.get("cout_unitaire"),
            "commentaire": charge.get("commentaire") or "",
        }
    )
    if not formulaire.is_valid():
        return JsonResponse(
            {"ok": False, "erreur": _premiere_erreur(formulaire), "erreurs": formulaire.errors},
            status=400,
        )

    try:
        mouvement = entrer_stock(
            depot=depot,
            variante=variante,
            quantite=formulaire.cleaned_data["quantite"],
            cout_unitaire=formulaire.cleaned_data["cout_unitaire"],
            origine_type="backoffice.reception",
            operation_id=charge.get("operation_id") or None,
            commentaire=formulaire.cleaned_data["commentaire"] or "Réception fournisseur",
            cree_par=request.user,
        )
    except MouvementInvalide as erreur:
        return JsonResponse({"ok": False, "erreur": str(erreur)}, status=400)

    return JsonResponse(
        {
            "ok": True,
            "variante": str(variante.pk),
            "quantite_apres": float(mouvement.quantite_apres),
            "cmp_apres": float(mouvement.cmp_apres),
            "url": f"/stock/{variante.pk}/",
        }
    )


def _premiere_erreur(formulaire) -> str:
    for erreurs in formulaire.errors.values():
        if erreurs:
            return erreurs[0]
    return "Saisie refusée."


@exige(droit.STOCK_MOUVEMENTER)
def transfert_stock(request, variante_id):
    """Transfert d'un article entre deux dépôts de la boutique.

    Un transfert interne ne crée ni ne détruit de valeur : la marchandise sort au
    CMP du dépôt d'origine et entre au même coût dans le dépôt de destination.
    C'est le seul écran par lequel un stock peut se déplacer sans passer par une
    vente ou un inventaire.
    """
    contexte = contexte_commun(request, "stock")

    variante = Variante.objects.filter(pk=variante_id).select_related("produit").first()
    if variante is None:
        return redirect("stock")

    depots = depots_disponibles()
    source = contexte["depot_courant"]
    if source is None or len(depots) < 2:
        messages.error(request, "Un transfert demande au moins deux dépôts.")
        return redirect("article", variante_id=variante.pk)

    niveau = NiveauStock.objects.filter(variante=variante, depot=source).first()

    if request.method == "POST":
        formulaire = TransfertStockForm(request.POST, depots=depots, source=source)
        if formulaire.is_valid():
            try:
                transferer_stock(
                    depot_source=source,
                    depot_cible=formulaire.cleaned_data["cible"],
                    variante=variante,
                    quantite=formulaire.cleaned_data["quantite"],
                    origine_type="backoffice.transfert",
                    commentaire=formulaire.cleaned_data["commentaire"] or "Transfert interne",
                    cree_par=request.user,
                )
            except MouvementInvalide as erreur:
                formulaire.add_error(None, str(erreur))
            else:
                messages.success(
                    request,
                    f"{formulaire.cleaned_data['quantite']:.0f} unité(s) transférée(s) "
                    f"vers « {formulaire.cleaned_data['cible'].libelle} ».",
                )
                return redirect("article", variante_id=variante.pk)
    else:
        formulaire = TransfertStockForm(depots=depots, source=source)

    contexte.update(
        {
            "formulaire": formulaire,
            "variante": variante,
            "source": source,
            "niveau": niveau,
        }
    )
    return render(request, "stock_transfert.html", contexte)


@exige(droit.STOCK_MOUVEMENTER)
def inventaire(request):
    """Comptage physique du dépôt, puis régularisation par mouvements d'ajustement.

    Les écarts ne sont jamais écrits directement sur le niveau de stock : ils
    passent par le journal, comme tout le reste.
    """
    contexte = contexte_commun(request, "stock")
    boutique = contexte["boutique"]

    depot = contexte["depot_courant"]
    if depot is None:
        return redirect("stock")

    niveaux = list(
        NiveauStock.objects.filter(depot=depot)
        .select_related("variante__produit")
        .order_by("variante__produit__libelle")
    )

    if request.method == "POST":
        inventaire_en_cours = Inventaire.objects.create(
            boutique=boutique, depot=depot, cree_par=request.user
        )
        comptees = 0
        for niveau in niveaux:
            brut = (request.POST.get(f"qte_{niveau.variante_id}") or "").strip()
            if brut == "":
                continue  # non compté : on ne suppose rien
            try:
                valeur = Decimal(brut.replace(",", "."))
            except (InvalidOperation, ArithmeticError, ValueError):
                continue
            LigneInventaire.objects.create(
                boutique=boutique,
                inventaire=inventaire_en_cours,
                variante=niveau.variante,
                qte_theorique=niveau.quantite,
                qte_comptee=valeur,
                motif=(request.POST.get(f"motif_{niveau.variante_id}") or "")[:255],
            )
            comptees += 1

        if comptees == 0:
            inventaire_en_cours.delete()
            messages.error(request, "Aucune quantité saisie : l'inventaire n'a pas été enregistré.")
            return redirect("inventaire")

        mouvements = regulariser_inventaire(inventaire_en_cours, cree_par=request.user)
        messages.success(
            request,
            f"Inventaire validé : {comptees} article(s) comptés, "
            f"{len(mouvements)} écart(s) régularisé(s).",
        )
        return redirect("stock")

    contexte.update(
        {
            "depot": depot,
            "niveaux": niveaux,
            "derniers": Inventaire.objects.filter(etat=Inventaire.VALIDE)[:5],
        }
    )
    return render(request, "inventaire.html", contexte)


# ----------------------------------------------------------------------------
# Session de caisse
# ----------------------------------------------------------------------------
@exige(droit.CAISSE_ENCAISSER)
def session_caisse(request):
    """Ouverture et fermeture de caisse.

    Sans fermeture comptée, il n'y a pas d'écart de caisse — donc aucun contrôle
    du caissier. C'est la raison d'être de cet écran.
    """
    contexte = contexte_commun(request, "caisse")

    session = _session_ouverte(request)
    depot = session.depot if session else contexte["depot_courant"]
    if depot is None:
        messages.error(request, "Aucun dépôt n'est ouvert : créez-en un avant d'encaisser.")
        return redirect("boutique")

    if request.method == "POST":
        if session is None:
            formulaire = OuvertureCaisseForm(request.POST)
            if formulaire.is_valid():
                caisse_service.ouvrir_session(
                    depot=depot,
                    caissier=request.user,
                    fonds_ouverture=formulaire.cleaned_data["fonds_ouverture"],
                )
                messages.success(request, f"Caisse ouverte sur « {depot.libelle} ».")
                return redirect("caisse")
        else:
            formulaire = FermetureCaisseForm(request.POST)
            if formulaire.is_valid():
                fermee = caisse_service.fermer_session(
                    session, fonds_compte=formulaire.cleaned_data["fonds_compte"]
                )
                ecart = fermee.ecart
                if ecart == 0:
                    messages.success(request, "Caisse fermée, aucun écart.")
                else:
                    signe = "manquant" if ecart < 0 else "excédent"
                    messages.error(
                        request, f"Caisse fermée avec un {signe} de {abs(ecart):.0f} FCFA."
                    )
                return redirect("caisse")
    else:
        formulaire = OuvertureCaisseForm() if session is None else FermetureCaisseForm()

    contexte.update(
        {
            "formulaire": formulaire,
            "session_caisse": session,
            "depot": depot,
            "tickets_session": (
                Ticket.objects.filter(session=session, etat=Ticket.CLOTURE).count()
                if session
                else 0
            ),
        }
    )
    return render(request, "caisse_session.html", contexte)


# ----------------------------------------------------------------------------
# Ticket imprimable
# ----------------------------------------------------------------------------
@exige(droit.VENTES_VOIR)
def ticket(request, ticket_id):
    """Ticket au format bande 80 mm, imprimable ou partageable.

    Un client qui repart sans rien doute. À défaut d'imprimante, la page se
    partage par WhatsApp ; si l'appareil sait parler Bluetooth, elle part
    directement sur la bobine (`static/js/imprimante.js`).
    """
    contexte = contexte_commun(request, "ventes")
    boutique = contexte["boutique"]

    ticket_vendu = Ticket.objects.filter(pk=ticket_id).select_related("session__caissier").first()
    if ticket_vendu is None:
        return redirect("ventes")

    lignes = list(LigneTicket.objects.filter(ticket=ticket_vendu))
    reglements = list(ReglementTicket.objects.filter(ticket=ticket_vendu))
    assujetti = boutique.regime_fiscal != Boutique.IGS

    contexte.update(
        {
            "ticket": ticket_vendu,
            "lignes": lignes,
            "reglements": reglements,
            "assujetti_tva": assujetti,
            "ticket_json": json.dumps(
                _ticket_pour_impression(boutique, ticket_vendu, lignes, reglements, assujetti)
            ),
        }
    )
    return render(request, "ticket.html", contexte)


def _ticket_pour_impression(boutique, ticket_vendu, lignes, reglements, assujetti) -> dict:
    """Modèle de données du ticket, indépendant de sa mise en page HTML.

    L'imprimante thermique ne lit pas le DOM : elle reçoit du texte et des
    commandes ESC/POS. Construire le ruban à partir de cette structure plutôt
    qu'en grattant la page évite qu'un changement de gabarit casse silencieusement
    l'impression.
    """
    return {
        "enseigne": boutique.enseigne,
        "raison_sociale": boutique.raison_sociale,
        "rccm": boutique.rccm,
        "niu": boutique.niu,
        "ville": boutique.ville,
        "telephone": boutique.telephone,
        "numero": ticket_vendu.numero,
        "date": timezone.localtime(ticket_vendu.cloture_le).strftime("%d/%m/%Y %H:%M")
        if ticket_vendu.cloture_le
        else "",
        "caissier": ticket_vendu.session.caissier.nom_complet,
        "client": ticket_vendu.client_nom,
        "lignes": [
            {
                "libelle": ligne.libelle,
                "quantite": float(ligne.quantite),
                "pu": float(ligne.pu_ttc),
                "total": float(ligne.total_ttc),
                "remise": float(ligne.remise),
            }
            for ligne in lignes
        ],
        "total_ht": float(ticket_vendu.total_ht),
        "total_tva": float(ticket_vendu.total_tva),
        "total_ttc": float(ticket_vendu.total_ttc),
        "assujetti_tva": assujetti,
        "reglements": [
            {"moyen": r.get_moyen_display(), "montant": float(r.montant)} for r in reglements
        ],
    }


# ----------------------------------------------------------------------------
# Application installable et mode hors ligne
# ----------------------------------------------------------------------------
def service_worker(request):
    """Sert le service worker depuis la racine.

    La portée d'un service worker est celle de son URL : servi depuis
    `/static/js/`, il ne pourrait intercepter que `/static/js/`. Il doit donc
    être exposé à la racine pour couvrir toute l'application.
    """
    chemin = finders.find("js/service-worker.js")
    if chemin is None:  # pragma: no cover — fichier statique manquant
        return HttpResponse("// service worker introuvable", content_type="text/javascript")

    with open(chemin, encoding="utf-8") as fichier:
        reponse = HttpResponse(fichier.read(), content_type="text/javascript")
    reponse["Service-Worker-Allowed"] = "/"
    reponse["Cache-Control"] = "no-cache"
    return reponse


# ----------------------------------------------------------------------------
# Export des données
# ----------------------------------------------------------------------------
@exige(droit.EXPORTER)
def export_donnees(request):
    """Export intégral, gratuit, en CSV — la promesse de réversibilité tenue.

    Elle est écrite dans l'interface et dans le contrat de bail : elle doit être
    vraie avant le premier client payant (docs/01, §4.1 et docs/08, §8).
    """
    boutique = boutique_courante(request)

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        for nom, entetes, lignes in _tables_export(boutique):
            archive.writestr(f"{nom}.csv", _en_csv(entetes, lignes))
        archive.writestr("LISEZ-MOI.txt", _notice_export(boutique))

    horodatage = timezone.localtime().strftime("%Y%m%d-%H%M")
    reponse = HttpResponse(tampon.getvalue(), content_type="application/zip")
    reponse["Content-Disposition"] = (
        f'attachment; filename="hypermarche-{boutique.slug}-{horodatage}.zip"'
    )
    return reponse


def _en_csv(entetes: list[str], lignes) -> str:
    sortie = io.StringIO()
    graveur = csv.writer(sortie, delimiter=";")
    graveur.writerow(entetes)
    graveur.writerows(lignes)
    # BOM : sans lui, Excel en français ouvre les accents en mojibake.
    return "﻿" + sortie.getvalue()


def _tables_export(boutique) -> list[tuple]:
    from apps.accounting.models import LigneEcriture

    produits = Variante.objects.select_related("produit").order_by("sku")
    niveaux = NiveauStock.objects.select_related("variante", "depot")
    mouvements = MouvementStock.objects.select_related("variante", "depot").order_by("cree_le")
    tickets = Ticket.objects.select_related("session__caissier").order_by("cree_le")
    lignes_ticket = LigneTicket.objects.select_related("ticket").order_by("cree_le")
    ecritures = LigneEcriture.objects.select_related("ecriture__journal", "compte").order_by(
        "ecriture__date_ecriture"
    )

    return [
        (
            "articles",
            ["sku", "libelle", "code_barres", "prix_vente_ttc", "regime_tva", "actif"],
            [
                [v.sku, v.produit.libelle, v.code_barres, v.prix_vente, v.produit.regime_tva, v.actif]
                for v in produits
            ],
        ),
        (
            "stock",
            ["depot", "sku", "quantite", "cout_moyen_pondere", "valeur", "seuil_alerte"],
            [
                [n.depot.libelle, n.variante.sku, n.quantite, n.cmp, n.valeur, n.seuil_alerte]
                for n in niveaux
            ],
        ),
        (
            "mouvements_stock",
            ["date", "depot", "sku", "type", "quantite", "cout_unitaire", "stock_apres", "cmp_apres", "commentaire"],
            [
                [
                    timezone.localtime(m.cree_le).isoformat(timespec="seconds"),
                    m.depot.libelle, m.variante.sku, m.type, m.quantite,
                    m.cout_unitaire, m.quantite_apres, m.cmp_apres, m.commentaire,
                ]
                for m in mouvements
            ],
        ),
        (
            "tickets",
            ["numero", "date", "caissier", "total_ht", "total_tva", "total_ttc", "etat"],
            [
                [
                    t.numero,
                    timezone.localtime(t.cloture_le).isoformat(timespec="seconds") if t.cloture_le else "",
                    t.session.caissier.nom_complet, t.total_ht, t.total_tva, t.total_ttc, t.etat,
                ]
                for t in tickets
            ],
        ),
        (
            "lignes_ticket",
            ["ticket", "libelle", "quantite", "pu_ttc", "taux_tva", "remise", "total_ttc"],
            [
                [l.ticket.numero, l.libelle, l.quantite, l.pu_ttc, l.taux_tva, l.remise, l.total_ttc]
                for l in lignes_ticket
            ],
        ),
        (
            "ecritures_comptables",
            ["date", "journal", "piece", "libelle", "compte", "intitule", "debit", "credit"],
            [
                [
                    l.ecriture.date_ecriture.isoformat(), l.ecriture.journal.code,
                    l.ecriture.piece, l.ecriture.libelle, l.compte.numero,
                    l.compte.intitule, l.debit, l.credit,
                ]
                for l in ecritures
            ],
        ),
    ]


def _notice_export(boutique) -> str:
    return (
        f"Export des données de « {boutique.enseigne} » ({boutique.raison_sociale})\r\n"
        f"Généré le {timezone.localtime():%d/%m/%Y à %H:%M}.\r\n\r\n"
        "Fichiers CSV, séparateur point-virgule, encodage UTF-8 avec BOM.\r\n\r\n"
        "Ces données vous appartiennent. Cet export est intégral et gratuit, à tout\r\n"
        "moment, y compris en cas de résiliation de votre emplacement.\r\n\r\n"
        "  articles.csv             votre catalogue et vos prix\r\n"
        "  stock.csv                l'état actuel, valorisé au coût moyen pondéré\r\n"
        "  mouvements_stock.csv     chaque entrée et sortie, avec le coût appliqué\r\n"
        "  tickets.csv              vos ventes\r\n"
        "  lignes_ticket.csv        le détail de chaque vente\r\n"
        "  ecritures_comptables.csv votre journal en partie double (SYSCOHADA)\r\n"
    )


# ----------------------------------------------------------------------------
# Ventes
# ----------------------------------------------------------------------------
@exige(droit.VENTES_VOIR)
def ventes(request):
    contexte = contexte_commun(request, "ventes")

    tickets = list(
        Ticket.objects.filter(etat=Ticket.CLOTURE).select_related(
            "session__caissier", "session__depot"
        )[:60]
    )
    lignes_par_ticket = {}
    for ligne in LigneTicket.objects.filter(ticket__in=tickets):
        lignes_par_ticket.setdefault(ligne.ticket_id, []).append(ligne)
    for ticket_vendu in tickets:
        ticket_vendu.lignes_affichees = lignes_par_ticket.get(ticket_vendu.id, [])

    contexte.update(
        {
            "tickets": tickets,
            "total_periode": sum((t.total_ttc for t in tickets), Decimal("0")),
            "tva_periode": sum((t.total_tva for t in tickets), Decimal("0")),
        }
    )
    return render(request, "ventes.html", contexte)


# ----------------------------------------------------------------------------
# Comptabilité
# ----------------------------------------------------------------------------
@exige(droit.COMPTABILITE_VOIR)
def comptabilite(request):
    contexte = contexte_commun(request, "comptabilite")
    boutique = contexte["boutique"]

    lignes = balance(boutique_id=boutique.pk)
    total_debit = sum((l["debit"] for l in lignes), Decimal("0"))
    total_credit = sum((l["credit"] for l in lignes), Decimal("0"))

    chiffre_affaires = -solde_compte("701", boutique_id=boutique.pk)
    cout_ventes = solde_compte("6031", boutique_id=boutique.pk)
    tva_collectee = -solde_compte("4431", boutique_id=boutique.pk)
    tresorerie = solde_compte("571", boutique_id=boutique.pk) + solde_compte(
        "5311", boutique_id=boutique.pk
    )

    from apps.accounting.models import EcritureComptable

    contexte.update(
        {
            "lignes": lignes,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "equilibree": total_debit == total_credit,
            "chiffre_affaires": chiffre_affaires,
            "cout_ventes": cout_ventes,
            "marge_brute": chiffre_affaires - cout_ventes,
            "tva_collectee": tva_collectee,
            "tresorerie": tresorerie,
            "ecritures": EcritureComptable.objects.select_related("journal")[:12],
            "assujetti_tva": boutique.regime_fiscal != Boutique.IGS,
        }
    )
    return render(request, "comptabilite.html", contexte)


# ----------------------------------------------------------------------------
# Boutique
# ----------------------------------------------------------------------------
@exige(droit.BOUTIQUE_VOIR)
def boutique(request):
    contexte = contexte_commun(request, "boutique")
    fiche = contexte["boutique"]

    bail = fiche.bail_actif
    depots = list(Depot.objects.all())
    quota = bail.type_emplacement.quota_depots if bail else 1

    contexte.update(
        {
            "bail": bail,
            "depots": depots,
            "quota_depots": quota,
            "depots_restants": max(quota - len(depots), 0),
            "equipe": fiche.appartenances.filter(actif=True).select_related("utilisateur", "role"),
            "droits_par_role": _droits_par_role(fiche),
        }
    )
    return render(request, "boutique.html", contexte)


def _droits_par_role(fiche) -> list[dict]:
    """Ce que chaque rôle présent dans l'équipe peut réellement faire.

    Écrit à l'écran plutôt que laissé dans le code : un gérant qui confie sa
    caisse doit pouvoir vérifier lui-même ce que son caissier voit, sans avoir à
    croire sur parole que la marge lui est fermée.
    """
    from apps.accounts.permissions import LIBELLES, droits_du_role

    vus = []
    codes = []
    for appartenance in fiche.appartenances.filter(actif=True).select_related("role"):
        if appartenance.role_id in codes:
            continue
        codes.append(appartenance.role_id)
        vus.append(
            {
                "libelle": appartenance.role.libelle,
                "droits": [LIBELLES[d] for d in sorted(droits_du_role(appartenance.role_id))],
            }
        )
    return vus


@exige(droit.BOUTIQUE_ADMINISTRER)
def nouveau_depot(request):
    """Ajout d'un dépôt, dans la limite du quota de l'emplacement loué.

    Le quota n'est pas une contrainte technique mais commerciale : il fait partie
    de la grille tarifaire (docs/03, §1.1). Il est donc annoncé, pas seulement
    appliqué.
    """
    contexte = contexte_commun(request, "boutique")
    fiche = contexte["boutique"]

    bail = fiche.bail_actif
    quota = bail.type_emplacement.quota_depots if bail else 1
    existants = Depot.objects.count()

    if existants >= quota:
        messages.error(
            request,
            f"Votre emplacement autorise {quota} dépôt(s). "
            "Passez à une offre supérieure pour en ouvrir un de plus.",
        )
        return redirect("boutique")

    if request.method == "POST":
        formulaire = DepotForm(request.POST)
        if formulaire.is_valid():
            depot = Depot.objects.create(
                boutique=fiche,
                libelle=formulaire.cleaned_data["libelle"],
                type=formulaire.cleaned_data["type"],
                adresse=formulaire.cleaned_data["adresse"],
                principal=existants == 0,
                cree_par=request.user,
            )
            messages.success(request, f"Dépôt « {depot.libelle} » ouvert.")
            return redirect("boutique")
    else:
        formulaire = DepotForm()

    contexte.update({"formulaire": formulaire, "quota_depots": quota, "existants": existants})
    return render(request, "depot_nouveau.html", contexte)


# ----------------------------------------------------------------------------
# Péremptions — métiers qui suivent les dates (pharmacie, cosmétique, frais…)
# ----------------------------------------------------------------------------
@exige(droit.STOCK_VOIR)
def peremptions(request):
    """Ce qui périme, et dans quel ordre s'en occuper.

    L'écran n'existe que pour les métiers qui activent la fonction : ailleurs il
    répond 404, et non un tableau vide. Un tableau vide dirait « vous n'avez rien
    qui périme » à un quincaillier, ce qui est vrai mais sans objet — et lui
    laisserait croire que le logiciel surveille quelque chose pour lui.

    Périmés et bientôt périmés sont dans le même écran, séparés en deux blocs :
    ce sont deux gestes différents — retirer d'un côté, écouler de l'autre — mais
    c'est la même tournée de rayon.
    """
    contexte = contexte_commun(request, "peremptions")
    metier = contexte["metier"]
    if metier is None or not metier.a(metiers.PEREMPTION):
        raise Http404("Ce métier ne suit pas les dates de péremption.")

    aujourd_hui = timezone.localdate()
    lots = list(lots_a_surveiller(jours=JOURS_PEREMPTION))
    for lot in lots:
        lot.etat_calcule = lot.etat(aujourd_hui)
        lot.jours = lot.jours_restants(aujourd_hui)

    perimes = [l for l in lots if l.etat_calcule == "perime"]
    bientot = [l for l in lots if l.etat_calcule == "bientot"]

    contexte.update(
        {
            "perimes": perimes,
            "bientot": bientot,
            "horizon": JOURS_PEREMPTION,
            # La valeur de ce qui périme n'a de sens que pour qui voit les coûts.
            "valeur_perimee": (
                sum(
                    (l.quantite * _cmp_du_lot(l) for l in perimes), Decimal("0")
                ).quantize(Decimal("0.01"))
                if droit.COUT_VOIR in contexte["droits"]
                else None
            ),
        }
    )
    return render(request, "peremptions.html", contexte)


def _cmp_du_lot(lot) -> Decimal:
    """Coût moyen pondéré du couple (dépôt, variante) auquel appartient le lot.

    Le lot ne porte pas de coût — c'est la décision de conception du modèle : la
    valorisation reste globale, le lot ne répond qu'à « quoi périme quand ». La
    valeur affichée est donc une **estimation au CMP courant**, ce que le gabarit
    dit explicitement plutôt que de la présenter comme un chiffre comptable.
    """
    niveau = NiveauStock.objects.filter(depot_id=lot.depot_id, variante_id=lot.variante_id).first()
    return niveau.cmp if niveau else Decimal("0")
