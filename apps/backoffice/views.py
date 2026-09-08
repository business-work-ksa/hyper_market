"""Vues du back-office marchand.

Périmètre du palier 1 (docs/18-produit-palier-1.md) : tableau de bord, caisse,
stock, ventes, lecture comptable. Ni marketplace, ni logistique, ni paiement en
ligne — ils viendront quand ils seront financés.

Toutes les vues s'exécutent dans le contexte de la boutique courante, posé par
`BoutiqueCouranteMiddleware` à partir de la session (docs/09, §3.2).
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounting.services import balance, solde_compte
from apps.catalog.models import Variante
from apps.inventory.models import Depot, MouvementStock, NiveauStock
from apps.marketplace.models import Boutique
from apps.pos import services as caisse_service
from apps.pos.models import LigneTicket, Ticket

JOURS_HISTORIQUE = 14


# ----------------------------------------------------------------------------
# Session et boutique courante
# ----------------------------------------------------------------------------
def _boutique_courante(request) -> Boutique | None:
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


def _contexte_commun(request, page: str) -> dict:
    boutique = _boutique_courante(request)
    alertes = 0
    if boutique is not None:
        alertes = _niveaux_en_alerte().count()
    return {"page": page, "boutique": boutique, "alertes": alertes or None}


def _niveaux_en_alerte():
    """Articles en rupture ou sous leur seuil de réapprovisionnement."""
    from django.db.models import F, Q

    return NiveauStock.objects.filter(
        Q(quantite__lte=0) | Q(quantite__lte=F("seuil_alerte"))
    ).select_related("variante__produit", "depot")


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
        return redirect("tableau_de_bord")

    return render(request, "connexion.html")


def deconnexion(request):
    logout(request)
    return redirect("connexion")


# ----------------------------------------------------------------------------
# Tableau de bord
# ----------------------------------------------------------------------------
@login_required(login_url="connexion")
def tableau_de_bord(request):
    contexte = _contexte_commun(request, "tableau_de_bord")
    if contexte["boutique"] is None:
        return redirect("connexion")

    aujourdhui = timezone.localdate()
    hier = aujourdhui - timedelta(days=1)

    ca_jour = _chiffre_affaires(aujourdhui, aujourdhui)
    ca_hier = _chiffre_affaires(hier, hier)
    cout_jour = _cout_des_ventes(aujourdhui, aujourdhui)

    marge_jour = ca_jour - cout_jour
    taux_marge = (marge_jour / ca_jour * 100) if ca_jour else Decimal("0")
    evolution = ((ca_jour - ca_hier) / ca_hier * 100) if ca_hier else None

    serie = _serie_ventes(JOURS_HISTORIQUE)
    niveaux = list(NiveauStock.objects.select_related("variante__produit"))
    valeur_stock = sum((n.quantite * n.cmp for n in niveaux), Decimal("0"))
    ruptures = [n for n in niveaux if n.quantite <= 0]
    sous_seuil = [n for n in niveaux if 0 < n.quantite <= n.seuil_alerte]
    sains = [n for n in niveaux if n.quantite > n.seuil_alerte]

    contexte.update(
        {
            "ca_jour": ca_jour,
            "marge_jour": marge_jour,
            "taux_marge": taux_marge,
            "evolution": evolution,
            "valeur_stock": valeur_stock,
            "nb_references": len(niveaux),
            "nb_ruptures": len(ruptures),
            "nb_sous_seuil": len(sous_seuil),
            "nb_sains": len(sains),
            "part_sains": _part(len(sains), len(niveaux)),
            "part_sous_seuil": _part(len(sous_seuil), len(niveaux)),
            "part_ruptures": _part(len(ruptures), len(niveaux)),
            "serie": serie,
            "graphe": geometrie_graphe(serie),
            "alertes_stock": (ruptures + sous_seuil)[:6],
            "derniers_tickets": Ticket.objects.filter(etat=Ticket.CLOTURE).select_related(
                "session__caissier"
            )[:6],
            "meilleurs": _meilleurs_articles(7),
        }
    )
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
@login_required(login_url="connexion")
def caisse(request):
    contexte = _contexte_commun(request, "caisse")
    if contexte["boutique"] is None:
        return redirect("connexion")

    variantes = (
        Variante.objects.filter(actif=True)
        .select_related("produit", "produit__categorie")
        .order_by("produit__libelle")
    )
    niveaux = {n.variante_id: n for n in NiveauStock.objects.all()}

    articles = []
    for variante in variantes:
        niveau = niveaux.get(variante.id)
        articles.append(
            {
                "id": str(variante.id),
                "libelle": variante.produit.libelle,
                "sku": variante.sku,
                "prix": float(variante.prix_vente),
                "taux_tva": float(variante.taux_tva),
                "stock": float(niveau.quantite) if niveau else 0.0,
                "categorie": variante.produit.categorie.libelle if variante.produit.categorie else "",
            }
        )

    session = _session_ouverte(request)
    contexte.update(
        {
            "articles": articles,
            "articles_json": json.dumps(articles),
            "session_caisse": session,
            "tickets_session": (
                Ticket.objects.filter(session=session, etat=Ticket.CLOTURE).count()
                if session
                else 0
            ),
        }
    )
    return render(request, "caisse.html", contexte)


def _session_ouverte(request):
    from apps.pos.models import SessionCaisse

    return SessionCaisse.objects.filter(
        caissier=request.user, etat=SessionCaisse.OUVERTE
    ).select_related("depot").first()


@login_required(login_url="connexion")
@require_POST
def caisse_encaisser(request):
    """Encaisse un panier : ticket, sortie de stock au CMP, écritures comptables.

    Un seul appel déclenche toute la chaîne — c'est la promesse « zéro double
    saisie » (docs/07, §1.2).
    """
    boutique = _boutique_courante(request)
    if boutique is None:
        return JsonResponse({"ok": False, "erreur": "Aucune boutique active."}, status=403)

    try:
        charge = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "erreur": "Requête illisible."}, status=400)

    lignes = charge.get("lignes") or []
    if not lignes:
        return JsonResponse({"ok": False, "erreur": "Le panier est vide."}, status=400)

    depot = Depot.objects.filter(principal=True).first() or Depot.objects.first()
    if depot is None:
        return JsonResponse({"ok": False, "erreur": "Aucun dépôt configuré."}, status=400)

    session = _session_ouverte(request) or caisse_service.ouvrir_session(
        depot=depot, caissier=request.user, fonds_ouverture=Decimal("0")
    )

    try:
        ticket = caisse_service.creer_ticket(
            session=session,
            operation_id=charge.get("operation_id") or None,
            client_nom=(charge.get("client") or "")[:180],
        )
        if ticket.etat == Ticket.CLOTURE:
            # Retransmission d'une opération déjà appliquée : on renvoie le résultat
            # précédent plutôt que de rejouer la vente (ADR-004).
            return JsonResponse(
                {"ok": True, "numero": ticket.numero, "total": float(ticket.total_ttc), "rejoue": True}
            )

        for ligne in lignes:
            variante = Variante.objects.filter(pk=ligne.get("variante")).first()
            if variante is None:
                continue
            caisse_service.ajouter_ligne(
                ticket=ticket,
                variante=variante,
                quantite=Decimal(str(ligne.get("quantite", 1))),
            )

        ticket.refresh_from_db()
        caisse_service.regler(
            ticket=ticket,
            moyen=charge.get("moyen") or "especes",
            montant=ticket.total_ttc,
        )
        caisse_service.cloturer_ticket(ticket, cree_par=request.user)
    except caisse_service.TicketInvalide as erreur:
        return JsonResponse({"ok": False, "erreur": str(erreur)}, status=400)

    return JsonResponse(
        {"ok": True, "numero": ticket.numero, "total": float(ticket.total_ttc), "rejoue": False}
    )


# ----------------------------------------------------------------------------
# Stock
# ----------------------------------------------------------------------------
@login_required(login_url="connexion")
def stock(request):
    contexte = _contexte_commun(request, "stock")
    if contexte["boutique"] is None:
        return redirect("connexion")

    recherche = (request.GET.get("q") or "").strip()
    filtre = request.GET.get("etat") or "tous"

    niveaux = NiveauStock.objects.select_related(
        "variante__produit", "variante__produit__categorie", "depot"
    ).order_by("variante__produit__libelle")

    if recherche:
        from django.db.models import Q

        niveaux = niveaux.filter(
            Q(variante__produit__libelle__icontains=recherche)
            | Q(variante__sku__icontains=recherche)
        )

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
            "valeur_totale": sum((n.quantite * n.cmp for n in niveaux), Decimal("0")),
        }
    )
    return render(request, "stock.html", contexte)


@login_required(login_url="connexion")
def article(request, variante_id):
    contexte = _contexte_commun(request, "stock")
    if contexte["boutique"] is None:
        return redirect("connexion")

    variante = Variante.objects.filter(pk=variante_id).select_related("produit").first()
    if variante is None:
        return redirect("stock")

    contexte.update(
        {
            "variante": variante,
            "niveaux": NiveauStock.objects.filter(variante=variante).select_related("depot"),
            "mouvements": MouvementStock.objects.filter(variante=variante).select_related("depot")[:30],
        }
    )
    return render(request, "article.html", contexte)


# ----------------------------------------------------------------------------
# Ventes
# ----------------------------------------------------------------------------
@login_required(login_url="connexion")
def ventes(request):
    contexte = _contexte_commun(request, "ventes")
    if contexte["boutique"] is None:
        return redirect("connexion")

    tickets = list(
        Ticket.objects.filter(etat=Ticket.CLOTURE)
        .select_related("session__caissier", "session__depot")[:60]
    )
    lignes_par_ticket = {}
    for ligne in LigneTicket.objects.filter(ticket__in=tickets):
        lignes_par_ticket.setdefault(ligne.ticket_id, []).append(ligne)
    for ticket in tickets:
        ticket.lignes_affichees = lignes_par_ticket.get(ticket.id, [])

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
@login_required(login_url="connexion")
def comptabilite(request):
    contexte = _contexte_commun(request, "comptabilite")
    boutique = contexte["boutique"]
    if boutique is None:
        return redirect("connexion")

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
@login_required(login_url="connexion")
def boutique(request):
    contexte = _contexte_commun(request, "boutique")
    fiche = contexte["boutique"]
    if fiche is None:
        return redirect("connexion")

    contexte.update(
        {
            "bail": fiche.bail_actif,
            "depots": Depot.objects.all(),
            "equipe": fiche.appartenances.filter(actif=True).select_related("utilisateur", "role"),
        }
    )
    return render(request, "boutique.html", contexte)
