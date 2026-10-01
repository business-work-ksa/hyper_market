"""Suivi des boutiques : liste, fiche, activité, loyers, rayons, emplacements.

Deux sortes d'écrans vivent ici, et la différence est toute l'ADR-012 :

* les **contrats du bailleur** — la boutique, son bail, ses loyers, ses emplacements, le rayon où
  elle vend. Non scopés : les lire ne franchit aucune barrière, n'exige aucun motif, n'écrit rien
  au journal ;
* l'**activité** d'une boutique — son chiffre d'affaires, ses ventes. Scopée : on la lit sous un
  motif de suivi ouvert, à l'intérieur de `lecture_journalisee()`, et chaque affichage laisse une
  ligne que le commerçant pourra lire. On n'en lit que des agrégats.

Les gestes (valider, suspendre, encaisser, fixer un taux, vendre un emplacement) ne sont pas ici :
ces écrans y mènent par des liens, les assistants les accomplissent.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.accounts.models import Appartenance, DossierKyc
from apps.confiance.paliers import carte_confiance
from apps.core.models import AccesPlateforme
from apps.marketplace.gouvernance import boutiques_de
from apps.marketplace.metiers import metier_de
from apps.marketplace.models import (
    Bail,
    Boutique,
    EmplacementPremium,
    FactureLoyer,
    Rayon,
    TypeEmplacement,
)
from apps.plateforme import indicateurs as ind
from apps.plateforme.acces import contexte_console, exige_console, lecture_journalisee

PAR_PAGE = 25

# Les tris proposés. Chacun répond à une question qu'on se pose vraiment : « qui vient
# d'arriver ? », « qui paie le plus ? », « quel bail finit bientôt ? ». `nulls_last` parce
# qu'une candidature sans bail ne doit pas encombrer le haut d'un tri par loyer.
TRIS_BOUTIQUES = {
    "enseigne": ("Nom", [F("enseigne").asc()]),
    "recentes": ("Ouverture récente", [F("ouverture").desc(nulls_last=True), F("cree_le").desc()]),
    "loyer": ("Loyer décroissant", [F("loyer").desc(nulls_last=True), F("enseigne").asc()]),
    "ville": ("Ville", [F("ville").asc(), F("enseigne").asc()]),
    "fin_bail": ("Fin de bail proche", [F("fin_bail").asc(nulls_last=True), F("enseigne").asc()]),
}

# Les gestes possibles selon l'état — les mêmes transitions que l'assistant accepte. Afficher un
# bouton qu'on refuserait ensuite apprend à cliquer sans lire.
ACTIONS_PAR_ETAT = {
    Boutique.CANDIDATURE: [("valider", "Valider la boutique", "primaire")],
    Boutique.ACTIVE: [("suspendre", "Suspendre", ""), ("resilier", "Résilier le bail", "danger")],
    Boutique.SUSPENDUE: [("reactiver", "Réactiver", "primaire"), ("resilier", "Résilier le bail", "danger")],
    Boutique.RESILIEE: [],
}

LIBELLES_ETATS = dict(Boutique.ETATS)


def _parametres_sans(request, *cles) -> str:
    """La requête courante sans certaines clés — pour les liens d'onglet et de page, qui
    conservent la recherche et les filtres posés."""
    parametres = request.GET.copy()
    for cle in cles:
        parametres.pop(cle, None)
    return parametres.urlencode()


# ----------------------------------------------------------------------------
# La liste des boutiques
# ----------------------------------------------------------------------------
@exige_console()
def boutiques(request):
    texte = request.GET.get("q", "").strip()
    etat = request.GET.get("etat", "")
    if etat not in LIBELLES_ETATS:
        etat = ""
    filtres = {
        "rayon": request.GET.get("rayon", ""),
        "ville": request.GET.get("ville", ""),
        "offre": request.GET.get("offre", ""),
    }
    tri = request.GET.get("tri", "enseigne")
    if tri not in TRIS_BOUTIQUES:
        tri = "enseigne"

    qs = ind.rechercher_boutiques(ind.boutiques_annotees(), texte)
    if filtres["rayon"] == "aucun":
        qs = qs.filter(rayon_principal__isnull=True)
    elif filtres["rayon"]:
        qs = qs.filter(rayon_principal__code=filtres["rayon"])
    if filtres["ville"]:
        qs = qs.filter(ville=filtres["ville"])
    if filtres["offre"]:
        qs = qs.filter(offre_code=filtres["offre"])

    # Les compteurs d'onglet suivent la recherche et les filtres, pas l'onglet : « 3 suspendues »
    # doit vouloir dire « 3 suspendues parmi ce que je cherche ».
    compteurs = {e: 0 for e in LIBELLES_ETATS}
    for ligne in qs.order_by().values("etat").annotate(n=Count("id")):
        compteurs[ligne["etat"]] = ligne["n"]
    onglets = [{"code": "", "libelle": "Toutes", "nombre": sum(compteurs.values())}] + [
        {"code": code, "libelle": f"{libelle}s", "nombre": compteurs[code]}
        for code, libelle in Boutique.ETATS
    ]

    if etat:
        qs = qs.filter(etat=etat)
    page = Paginator(qs.order_by(*TRIS_BOUTIQUES[tri][1]), PAR_PAGE).get_page(request.GET.get("page"))
    for b in page.object_list:
        b.metier_libelle = metier_de(b.metier).libelle

    return render(
        request,
        "plateforme/boutiques.html",
        contexte_console(
            request,
            page="plateforme:boutiques",
            page_obj=page,
            texte=texte,
            etat=etat,
            filtres=filtres,
            nb_filtres=sum(1 for v in filtres.values() if v),
            tri=tri,
            tris=[(code, libelle) for code, (libelle, _) in TRIS_BOUTIQUES.items()],
            onglets=onglets,
            rayons=Rayon.objects.order_by("ordre", "libelle").values_list("code", "libelle"),
            villes=Boutique.objects.order_by("ville").values_list("ville", flat=True).distinct(),
            offres=TypeEmplacement.objects.values_list("code", "libelle"),
            parametres_onglet=_parametres_sans(request, "etat", "page"),
            parametres_page=_parametres_sans(request, "page"),
        ),
    )


# ----------------------------------------------------------------------------
# La fiche d'une boutique
# ----------------------------------------------------------------------------
@exige_console()
def boutique(request, boutique_id):
    b = get_object_or_404(Boutique.objects.select_related("rayon_principal"), pk=boutique_id)
    aujourdhui = timezone.localdate()

    baux = list(b.baux.select_related("type_emplacement").order_by("-debut"))
    bail = next((x for x in baux if x.etat == Bail.ACTIF), None)
    derogation = None
    if bail is not None:
        reference = bail.type_emplacement.taux_commission_defaut
        if reference is not None and bail.taux_commission != reference:
            derogation = {"reference": reference * 100, "ecart": (bail.taux_commission - reference) * 100}

    factures = list(
        FactureLoyer.objects.filter(bail__boutique=b).select_related("bail").order_by("-periode")[:12]
    )
    for f in factures:
        f.statut, f.statut_libelle = ind.statut_facture(f, aujourdhui)

    emplacements = list(b.emplacements_premium.select_related("rayon").order_by("-debut"))
    for e in emplacements:
        e.statut = ind.etat_emplacement(e, aujourdhui)

    journal = AccesPlateforme.objects.filter(boutique_id=b.pk).select_related("utilisateur")

    return render(
        request,
        "plateforme/boutique.html",
        contexte_console(
            request,
            page="plateforme:boutiques",
            b=b,
            metier=metier_de(b.metier),
            bail=bail,
            anciens_baux=[x for x in baux if x is not bail],
            derogation=derogation,
            taux_pourcent=bail.taux_commission * 100 if bail else None,
            factures=factures,
            synthese=ind.synthese_factures(FactureLoyer.objects.filter(bail__boutique=b)),
            impayes=ind.factures_echues(aujourdhui).filter(bail__boutique=b).count(),
            emplacements=emplacements,
            equipe=Appartenance.objects.filter(boutique=b)
            .select_related("utilisateur", "role")
            .order_by("-actif", "role__code", "utilisateur__nom_complet"),
            kyc=DossierKyc.objects.filter(boutique=b).order_by("-cree_le"),
            journal=journal[:8],
            nb_journal=journal.count(),
            actions=ACTIONS_PAR_ETAT.get(b.etat, []),
            # Palier, progression, signaux : la dernière mesure de la tâche de nuit, pas les
            # commandes elles-mêmes — la fiche s'ouvre sans motif de suivi (ADR-012).
            confiance=carte_confiance(b),
        ),
    )


# ----------------------------------------------------------------------------
# L'activité — lecture journalisée
# ----------------------------------------------------------------------------
def _ligne_activite(b, donnees, aujourdhui) -> dict:
    d = donnees.get(b.pk, {})
    jours = ind.jours_sans_vente(d.get("derniere"), aujourdhui)
    return {
        "b": b,
        "ca": d.get("ca", ind.ZERO),
        "tickets": d.get("tickets", 0),
        "commandes": d.get("commandes", 0),
        "derniere": d.get("derniere"),
        "jours": jours,
        # Une boutique suspendue ne vend plus sur la vitrine : la dire « endormie » serait
        # confondre une décision du marché avec un signal de désintérêt.
        "endormie": b.etat == Boutique.ACTIVE and ind.est_endormie(jours),
    }


TRIS_ACTIVITE = {
    "ca": ("Chiffre d'affaires", lambda l: (-l["ca"], l["b"].enseigne.lower())),
    "silence": ("Jours sans vente", lambda l: (-(l["jours"] if l["jours"] is not None else 10**6), l["b"].enseigne.lower())),
    "enseigne": ("Nom", lambda l: l["b"].enseigne.lower()),
}


@exige_console(suivi=True)
def activite(request):
    """Vue d'ensemble de l'activité du marché : une ligne de journal par affichage.

    La lecture des tables scopées est **la seule chose** faite dans le bloc journalisé : la liste
    des boutiques (non scopée) se lit dehors. Le bloc reste ainsi court et lisible — on voit d'un
    coup d'œil ce qui franchit la barrière.
    """
    aujourdhui = timezone.localdate()
    with lecture_journalisee(request, ecran="plateforme:activite", boutique_id=None):
        donnees = ind.activite_par_boutique(aujourdhui)

    lignes = [
        _ligne_activite(b, donnees, aujourdhui)
        for b in Boutique.objects.filter(etat__in=[Boutique.ACTIVE, Boutique.SUSPENDUE])
        .select_related("rayon_principal")
    ]
    endormies = [l for l in lignes if l["endormie"]]
    vue = request.GET.get("vue", "")
    tri = request.GET.get("tri", "ca")
    if tri not in TRIS_ACTIVITE:
        tri = "ca"
    affichees = endormies if vue == "endormies" else lignes
    affichees = sorted(affichees, key=TRIS_ACTIVITE[tri][1])
    maximum = max((l["ca"] for l in lignes), default=ind.ZERO)
    for l in affichees:
        l["largeur"] = round(float(l["ca"]) / float(maximum) * 100, 1) if maximum else 0

    return render(
        request,
        "plateforme/activite.html",
        contexte_console(
            request,
            page="plateforme:activite",
            lignes=affichees,
            vue=vue,
            tri=tri,
            tris=[(c, lib) for c, (lib, _) in TRIS_ACTIVITE.items()],
            nb_boutiques=len(lignes),
            nb_endormies=len(endormies),
            total_ca=sum((l["ca"] for l in lignes), ind.ZERO),
            total_tickets=sum(l["tickets"] for l in lignes),
            total_commandes=sum(l["commandes"] for l in lignes),
            fenetre=ind.FENETRE_ACTIVITE,
            seuil=ind.SEUIL_ENDORMIE,
        ),
    )


@exige_console(suivi=True)
def boutique_activite(request, boutique_id):
    b = get_object_or_404(Boutique.objects.select_related("rayon_principal"), pk=boutique_id)
    aujourdhui = timezone.localdate()
    with lecture_journalisee(request, ecran="plateforme:boutique_activite", boutique_id=b.pk):
        donnees = ind.activite_par_boutique(aujourdhui, boutique_id=b.pk)
        serie = ind.ca_quotidien(b.pk, aujourdhui)

    ligne = _ligne_activite(b, donnees, aujourdhui)
    jours_actifs = sum(1 for p in serie if p["valeur"])
    return render(
        request,
        "plateforme/boutique_activite.html",
        contexte_console(
            request,
            page="plateforme:activite",
            b=b,
            ligne=ligne,
            graphe=ind.graphe_de(serie, etiquette=44, largeur=1100, hauteur=250),
            jours_actifs=jours_actifs,
            panier_moyen=(
                (ligne["ca"] / (ligne["tickets"] + ligne["commandes"])).quantize(Decimal("1"))
                if ligne["tickets"] + ligne["commandes"]
                else None
            ),
            fenetre=ind.FENETRE_ACTIVITE,
            seuil=ind.SEUIL_ENDORMIE,
        ),
    )


# ----------------------------------------------------------------------------
# Les loyers
# ----------------------------------------------------------------------------
ONGLETS_LOYERS = [
    ("", "Toutes"),
    ("emises", "Émises"),
    ("payees", "Payées"),
    ("impayees", "Impayées"),
    ("echues", "Échues"),
]


@exige_console()
def loyers(request):
    aujourdhui = timezone.localdate()
    courant = ind.debut_du_mois(aujourdhui)
    tous = request.GET.get("mois") == "tous"
    mois = None if tous else ind.lire_mois(request.GET.get("mois"), courant)
    etat = request.GET.get("etat", "")
    if etat not in dict(ONGLETS_LOYERS):
        etat = ""

    base = FactureLoyer.objects.all() if tous else FactureLoyer.objects.filter(periode=mois)
    # Venu de la fiche d'une boutique : ses seules factures. Un identifiant illisible est ignoré.
    boutique_filtree = None
    if request.GET.get("boutique"):
        try:
            boutique_filtree = Boutique.objects.filter(pk=request.GET["boutique"]).first()
        except (ValueError, ValidationError):
            boutique_filtree = None
        if boutique_filtree:
            base = base.filter(bail__boutique=boutique_filtree)
    echue = Q(etat__in=[FactureLoyer.EMISE, FactureLoyer.IMPAYEE], echeance__lt=aujourdhui)
    filtres_onglets = {
        "": Q(),
        "emises": Q(etat=FactureLoyer.EMISE),
        "payees": Q(etat=FactureLoyer.PAYEE),
        "impayees": Q(etat=FactureLoyer.IMPAYEE),
        "echues": echue,
    }
    comptes = base.aggregate(**{f"n_{code or 'tout'}": Count("id", filter=f) for code, f in filtres_onglets.items()})
    onglets = [
        {"code": code, "libelle": libelle, "nombre": comptes[f"n_{code or 'tout'}"]}
        for code, libelle in ONGLETS_LOYERS
    ]

    # Les échues se lisent par ancienneté du retard : la plus vieille dette d'abord.
    ordre = ["echeance"] if etat == "echues" else ["-periode"]
    qs = (
        base.filter(filtres_onglets[etat])
        .select_related("bail__boutique", "bail__type_emplacement")
        .order_by(*ordre, "bail__boutique__enseigne")
    )
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    for f in page.object_list:
        f.statut, f.statut_libelle = ind.statut_facture(f, aujourdhui)
        f.retard = (aujourdhui - f.echeance).days if f.statut == "echue" else 0

    # Le sélecteur de mois propose les mois où il existe des factures, plus le mois courant :
    # proposer « mars 2019 » à un marché ouvert en 2026 serait une fausse promesse.
    periodes = set(FactureLoyer.objects.order_by().values_list("periode", flat=True).distinct())
    periodes.add(courant)
    choix_mois = [
        {"valeur": f"{p:%Y-%m}", "libelle": ind.libelle_mois(p, long=True).capitalize()}
        for p in sorted(periodes, reverse=True)
    ]

    return render(
        request,
        "plateforme/loyers.html",
        contexte_console(
            request,
            page="plateforme:loyers",
            tous=tous,
            mois=mois,
            mois_valeur="tous" if tous else f"{mois:%Y-%m}",
            libelle_periode="Tous les mois" if tous else ind.libelle_mois(mois, long=True).capitalize(),
            precedent=None if tous else f"{ind.decaler_mois(mois, -1):%Y-%m}",
            suivant=None if tous else f"{ind.decaler_mois(mois, 1):%Y-%m}",
            choix_mois=choix_mois,
            etat=etat,
            onglets=onglets,
            boutique_filtree=boutique_filtree,
            synthese=ind.synthese_factures(base),
            echues=ind.synthese_factures(base.filter(echue)),
            page_obj=page,
            parametres_onglet=_parametres_sans(request, "etat", "page"),
            parametres_page=_parametres_sans(request, "page"),
        ),
    )


# ----------------------------------------------------------------------------
# Les rayons et les offres
# ----------------------------------------------------------------------------
@exige_console()
def rayons(request):
    liste = list(
        Rayon.objects.select_related("parent", "responsable")
        .annotate(
            nb_actives=Count("boutiques", filter=Q(boutiques__etat=Boutique.ACTIVE)),
            nb_candidatures=Count("boutiques", filter=Q(boutiques__etat=Boutique.CANDIDATURE)),
        )
        .order_by("ordre", "libelle")
    )
    total = sum(r.nb_actives for r in liste)
    maximum = max((r.nb_actives for r in liste), default=0)
    # Le garde-fou du juge et partie, rendu visible avant le clic : un lien « Modifier le taux »
    # qu'on refuserait à l'étape suivante apprend seulement que la console est capricieuse.
    mes_rayons = set(
        Boutique.objects.filter(pk__in=boutiques_de(request.user))
        .exclude(rayon_principal__isnull=True)
        .values_list("rayon_principal_id", flat=True)
    )
    for r in liste:
        r.part = ind.pourcentage(r.nb_actives, total) or 0
        r.largeur = round(r.nb_actives / maximum * 100, 1) if maximum else 0
        r.taux_pourcent = r.taux_commission * 100
        r.en_conflit = r.pk in mes_rayons

    offres = list(
        TypeEmplacement.objects.annotate(nb_baux=Count("bail", filter=Q(bail__etat=Bail.ACTIF)))
        .order_by("ordre")
    )
    for o in offres:
        o.taux_pourcent = o.taux_commission_defaut * 100

    return render(
        request,
        "plateforme/rayons.html",
        contexte_console(
            request,
            page="plateforme:rayons",
            rayons=liste,
            nb_ouverts=sum(1 for r in liste if r.ouvert),
            total_actives=total,
            taux_moyen=(
                sum((r.taux_commission * r.nb_actives for r in liste), Decimal("0")) / total * 100
                if total
                else None
            ),
            offres=offres,
            conflit_personnel=bool(mes_rayons),
        ),
    )


# ----------------------------------------------------------------------------
# Les emplacements premium
# ----------------------------------------------------------------------------
ONGLETS_EMPLACEMENTS = [
    ("en_cours", "En cours"),
    ("a_venir", "À venir"),
    ("termines", "Terminés"),
]


@exige_console()
def emplacements(request):
    aujourdhui = timezone.localdate()
    mois = ind.debut_du_mois(aujourdhui)
    vue = request.GET.get("vue", "en_cours")
    if vue not in dict(ONGLETS_EMPLACEMENTS):
        vue = "en_cours"
    compteurs = ind.compteurs_emplacements(aujourdhui)
    filtres = {
        "en_cours": Q(debut__lte=aujourdhui, fin__gte=aujourdhui),
        "a_venir": Q(debut__gt=aujourdhui),
        "termines": Q(fin__lt=aujourdhui),
    }
    ordre = {"en_cours": ["fin"], "a_venir": ["debut"], "termines": ["-fin"]}[vue]
    page = Paginator(
        EmplacementPremium.objects.filter(filtres[vue])
        .select_related("rayon", "boutique_occupante")
        .order_by(*ordre),
        PAR_PAGE,
    ).get_page(request.GET.get("page"))
    for e in page.object_list:
        e.statut = ind.etat_emplacement(e, aujourdhui)
        e.duree = (e.fin - e.debut).days + 1
        e.restant = (e.fin - aujourdhui).days if e.statut == "en_cours" else None
        e.dans = (e.debut - aujourdhui).days if e.statut == "a_venir" else None

    a_venir_30 = EmplacementPremium.objects.filter(
        debut__gt=aujourdhui, debut__lte=aujourdhui + timedelta(days=30)
    ).count()
    return render(
        request,
        "plateforme/emplacements.html",
        contexte_console(
            request,
            page="plateforme:emplacements",
            vue=vue,
            onglets=[
                {"code": c, "libelle": lib, "nombre": compteurs[c]}
                for c, lib in ONGLETS_EMPLACEMENTS
            ],
            compteurs=compteurs,
            revenu_mois=ind.revenu_premium(mois),
            revenu_mois_precedent=ind.revenu_premium(ind.decaler_mois(mois, -1)),
            libelle_mois=ind.libelle_mois(mois, long=True),
            a_venir_30=a_venir_30,
            page_obj=page,
        ),
    )
