"""Les calculs de la console : ce que les tableaux affichent, sans les tableaux.

Séparés des vues pour deux raisons. La première est la vérifiabilité : un taux de recouvrement
faux se lit mal dans un gabarit et très bien dans un test qui appelle une fonction. La seconde est
la frontière de l'ADR-012 : tout ce qui touche une table **scopée** est rangé en bas de ce fichier,
sous un titre qui le dit, et n'est appelé que depuis l'intérieur de `lecture_journalisee()`. Le
reste ne lit que les contrats du bailleur — boutiques, baux, loyers, rayons, emplacements — qui ne
franchissent aucune barrière.

Conventions de montant, fixées une fois ici pour que deux écrans ne se contredisent jamais :

* un **loyer dû ou encaissé** se compte TTC — c'est ce que le commerçant paie ;
* un **revenu de la plateforme** se compte HT — la TVA collectée n'est pas un revenu, elle est
  reversée. Additionner les deux ferait mentir le compte de résultat.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
)
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.marketplace.models import Bail, Boutique, EmplacementPremium, FactureLoyer
from django.utils.translation import gettext as _
from django.utils.translation import pgettext_lazy

ZERO = Decimal("0")

# Au-delà de ce nombre de jours sans une vente, une boutique active est dite « endormie ». Deux
# semaines : assez pour absorber un congé ou une rupture d'approvisionnement, assez court pour
# qu'un appel du marché arrive avant la résiliation plutôt qu'après.
SEUIL_ENDORMIE = 14

# Fenêtre de l'activité agrégée. Trente jours lissent le jour de marché hebdomadaire.
FENETRE_ACTIVITE = 30

# Traduits selon la langue de la page ; le contexte sépare « mars » court de « mars » long.
MOIS_COURTS = [
    pgettext_lazy("mois court", "janv."),
    pgettext_lazy("mois court", "févr."),
    pgettext_lazy("mois court", "mars"),
    pgettext_lazy("mois court", "avr."),
    pgettext_lazy("mois court", "mai"),
    pgettext_lazy("mois court", "juin"),
    pgettext_lazy("mois court", "juil."),
    pgettext_lazy("mois court", "août"),
    pgettext_lazy("mois court", "sept."),
    pgettext_lazy("mois court", "oct."),
    pgettext_lazy("mois court", "nov."),
    pgettext_lazy("mois court", "déc."),
]
MOIS_LONGS = [
    pgettext_lazy("mois long", "janvier"),
    pgettext_lazy("mois long", "février"),
    pgettext_lazy("mois long", "mars"),
    pgettext_lazy("mois long", "avril"),
    pgettext_lazy("mois long", "mai"),
    pgettext_lazy("mois long", "juin"),
    pgettext_lazy("mois long", "juillet"),
    pgettext_lazy("mois long", "août"),
    pgettext_lazy("mois long", "septembre"),
    pgettext_lazy("mois long", "octobre"),
    pgettext_lazy("mois long", "novembre"),
    pgettext_lazy("mois long", "décembre"),
]

# Le TTC d'une facture, calculé en base : `montant_ttc` est une propriété Python, et l'agréger
# ligne à ligne en Python coûterait une requête par écran et une boucle par facture.
TTC = ExpressionWrapper(
    F("montant_ht") + F("montant_ht") * F("taux_tva"),
    output_field=DecimalField(max_digits=16, decimal_places=4),
)


# ----------------------------------------------------------------------------
# Le calendrier
# ----------------------------------------------------------------------------
def debut_du_mois(jour: date) -> date:
    return jour.replace(day=1)


def decaler_mois(mois: date, n: int) -> date:
    """Premier jour du mois situé `n` mois avant (n < 0) ou après (n > 0)."""
    rang = mois.year * 12 + (mois.month - 1) + n
    return date(rang // 12, rang % 12 + 1, 1)


def fin_du_mois(mois: date) -> date:
    return mois.replace(day=calendar.monthrange(mois.year, mois.month)[1])


def libelle_mois(mois: date, *, long: bool = False) -> str:
    noms = MOIS_LONGS if long else MOIS_COURTS
    return f"{noms[mois.month - 1]} {mois.year}"


def lire_mois(texte: str | None, defaut: date) -> date:
    """`2026-09` → 1er septembre 2026. Une saisie illisible retombe sur le défaut, sans erreur :
    c'est un paramètre d'adresse, et une adresse mal recopiée ne mérite pas une page d'erreur."""
    try:
        annee, mois = (int(p) for p in (texte or "").split("-")[:2])
        return date(annee, mois, 1)
    except (TypeError, ValueError):
        return defaut


def pourcentage(part, total) -> float | None:
    """Une part en pour-cent, ou `None` quand le total est nul — « 0 % » mentirait."""
    if not total:
        return None
    return round(float(part) / float(total) * 100, 1)


# ----------------------------------------------------------------------------
# Les boutiques
# ----------------------------------------------------------------------------
def compteurs_boutiques() -> dict[str, int]:
    """Nombre de boutiques par état, en une requête. Tous les états sont présents, même à zéro."""
    compteurs = {etat: 0 for etat, _ in Boutique.ETATS}
    for ligne in Boutique.objects.order_by().values("etat").annotate(n=Count("id")):
        compteurs[ligne["etat"]] = ligne["n"]
    compteurs["total"] = sum(compteurs.values())
    return compteurs


def boutiques_annotees():
    """Les boutiques, chacune avec son bail actif aplati en colonnes.

    Des sous-requêtes plutôt que `prefetch_related` : la liste trie et filtre sur le loyer et
    l'offre, ce qu'un préchargement ne sait pas faire en base. Une seule requête SQL quelle que
    soit la taille de la page.
    """
    bail = Bail.objects.filter(boutique=OuterRef("pk"), etat=Bail.ACTIF).order_by("-debut")
    return Boutique.objects.select_related("rayon_principal").annotate(
        offre_code=Subquery(bail.values("type_emplacement_id")[:1]),
        offre_libelle=Subquery(bail.values("type_emplacement__libelle")[:1]),
        loyer=Subquery(bail.values("loyer_mensuel")[:1]),
        ouverture=Subquery(bail.values("debut")[:1]),
        fin_bail=Subquery(bail.values("fin")[:1]),
    )


def rechercher_boutiques(qs, texte: str):
    """Recherche plein texte « de guichet » : ce qu'un administrateur a sous les yeux quand un
    commerçant appelle — son nom, sa ville, son numéro, son RCCM ou son NIU."""
    texte = (texte or "").strip()
    if not texte:
        return qs
    filtre = Q()
    for champ in ("enseigne", "raison_sociale", "ville", "telephone", "rccm", "niu"):
        filtre |= Q(**{f"{champ}__icontains": texte})
    # Un numéro se tape de dix façons : « 699 11 00 11 », « +237699110011 ». On compare aussi
    # sans espaces, faute de quoi la recherche la plus fréquente échouerait.
    compact = texte.replace(" ", "")
    if compact != texte:
        filtre |= Q(telephone__icontains=compact)
    return qs.filter(filtre)


def repartition(qs, champ: str, *, limite: int = 6, vide: str = "Non renseigné") -> list[dict]:
    """Effectifs par valeur d'un champ, les plus gros d'abord, le reste replié en « Autres ».

    Replier plutôt que tout montrer : au-delà de six barres, on ne compare plus, on lit une liste.
    """
    lignes = list(
        qs.order_by().values(champ).annotate(n=Count("id")).order_by("-n", champ)
    )
    total = sum(l["n"] for l in lignes)
    tete, queue = lignes[:limite], lignes[limite:]
    resultat = [{"libelle": l[champ] or vide, "nombre": l["n"]} for l in tete]
    if queue:
        resultat.append(
            {"libelle": _('Autres (%(len)s)') % {"len": len(queue)}, "nombre": sum(l["n"] for l in queue), "autres": True}
        )
    maximum = max((r["nombre"] for r in resultat), default=0)
    for r in resultat:
        r["part"] = pourcentage(r["nombre"], total) or 0
        # La barre se lit relativement à la plus grande, pas au total : sinon, avec dix rayons,
        # toutes les barres sont courtes et plus rien ne se compare.
        r["largeur"] = round(r["nombre"] / maximum * 100, 1) if maximum else 0
    return resultat


# ----------------------------------------------------------------------------
# Les loyers
# ----------------------------------------------------------------------------
def factures_echues(aujourdhui: date):
    """Factures dont l'échéance est passée sans paiement. Même définition que le rail."""
    return FactureLoyer.objects.filter(
        etat__in=[FactureLoyer.EMISE, FactureLoyer.IMPAYEE], echeance__lt=aujourdhui
    )


def statut_facture(facture, aujourdhui: date) -> tuple[str, str]:
    """(classe, mot) d'une facture. « Échue » n'est pas un état stocké : c'est une émise ou une
    impayée dont l'échéance est passée — la seule qui appelle un geste aujourd'hui."""
    if facture.etat == FactureLoyer.PAYEE:
        return "payee", "Payée"
    if facture.etat == FactureLoyer.ANNULEE:
        return "annulee", "Annulée"
    if facture.echeance < aujourdhui:
        return "echue", "Échue"
    if facture.etat == FactureLoyer.IMPAYEE:
        return "impayee", "Impayée"
    return "emise", "Émise"


def synthese_loyers(mois: date) -> dict:
    """Émis, encaissé et taux de recouvrement d'un mois facturé, TTC, en une requête."""
    return synthese_factures(FactureLoyer.objects.filter(periode=mois))


def synthese_factures(qs) -> dict:
    """Émis, encaissé, reste et taux de recouvrement d'un ensemble de factures, TTC.

    Une facture annulée n'est ni due ni encaissée : elle sort du calcul, sans quoi une erreur
    de facturation corrigée ferait baisser le taux de recouvrement pour toujours.
    """
    totaux = (
        qs.exclude(etat=FactureLoyer.ANNULEE)
        .aggregate(
            emis=Sum(TTC),
            encaisse=Sum(TTC, filter=Q(etat=FactureLoyer.PAYEE)),
            nb=Count("id"),
            nb_payees=Count("id", filter=Q(etat=FactureLoyer.PAYEE)),
        )
    )
    emis = totaux["emis"] or ZERO
    encaisse = totaux["encaisse"] or ZERO
    return {
        "emis": emis,
        "encaisse": encaisse,
        "reste": emis - encaisse,
        "nb": totaux["nb"],
        "nb_payees": totaux["nb_payees"],
        "nb_restantes": totaux["nb"] - totaux["nb_payees"],
        "taux": pourcentage(encaisse, emis),
    }


def synthese_impayes(aujourdhui: date) -> dict:
    totaux = factures_echues(aujourdhui).aggregate(
        montant=Sum(TTC), nombre=Count("id"), boutiques=Count("bail__boutique", distinct=True)
    )
    return {
        "montant": totaux["montant"] or ZERO,
        "nombre": totaux["nombre"],
        "boutiques": totaux["boutiques"],
    }


# ----------------------------------------------------------------------------
# Les emplacements premium
# ----------------------------------------------------------------------------
def etat_emplacement(emplacement, aujourdhui: date) -> str:
    if emplacement.debut > aujourdhui:
        return "a_venir"
    if emplacement.fin < aujourdhui:
        return "termine"
    return "en_cours"


def revenu_premium(mois: date) -> Decimal:
    """Recette HT des emplacements premium imputable à un mois, **au prorata des jours**.

    Un emplacement de trois semaines à cheval sur deux mois ne compte pas deux fois son tarif —
    ni zéro dans le second mois. Le prorata est la seule lecture qui additionne juste d'un mois à
    l'autre.
    """
    fin = fin_du_mois(mois)
    total = ZERO
    for debut_e, fin_e, tarif in EmplacementPremium.objects.filter(
        debut__lte=fin, fin__gte=mois
    ).values_list("debut", "fin", "tarif"):
        duree = (fin_e - debut_e).days + 1
        recouvre = (min(fin_e, fin) - max(debut_e, mois)).days + 1
        if duree > 0 and recouvre > 0:
            total += tarif * recouvre / duree
    return total.quantize(Decimal("1"))


def compteurs_emplacements(aujourdhui: date) -> dict[str, int]:
    return EmplacementPremium.objects.aggregate(
        en_cours=Count("id", filter=Q(debut__lte=aujourdhui, fin__gte=aujourdhui)),
        a_venir=Count("id", filter=Q(debut__gt=aujourdhui)),
        termines=Count("id", filter=Q(fin__lt=aujourdhui)),
    )


# ----------------------------------------------------------------------------
# Les revenus de la plateforme, dans le temps
# ----------------------------------------------------------------------------
def loyers_encaisses_par_mois(dernier_mois: date, nb_mois: int) -> list[dict]:
    """Loyers encaissés HT, par mois **facturé**, sur `nb_mois` mois glissants.

    Par mois facturé et non par date d'encaissement : un loyer de juillet payé en septembre est
    un revenu de juillet. C'est la lecture comptable, et c'est aussi celle qui ne fait pas
    « bondir » un mois parce qu'un retardataire a régularisé.

    Tous les mois sont présents, même vides : une série trouée décale les barres et fait croire
    à une tendance qui n'existe pas.
    """
    premier = decaler_mois(dernier_mois, -(nb_mois - 1))
    montants = {
        ligne["periode"]: ligne["total"]
        for ligne in FactureLoyer.objects.filter(
            etat=FactureLoyer.PAYEE, periode__gte=premier, periode__lte=dernier_mois
        )
        .order_by()
        .values("periode")
        .annotate(total=Sum("montant_ht"))
    }
    serie = []
    for rang in range(nb_mois):
        mois = decaler_mois(premier, rang)
        serie.append(
            {
                "mois": mois,
                "valeur": (montants.get(mois) or ZERO).quantize(Decimal("1")),
                "libelle": str(MOIS_COURTS[mois.month - 1]).rstrip("."),
                "libelle_long": libelle_mois(mois, long=True).capitalize(),
            }
        )
    return serie


# ----------------------------------------------------------------------------
# La géométrie des graphes
# ----------------------------------------------------------------------------
@dataclass
class Graphe:
    """Deux rendus d'une même série : large pour le bureau, compact pour le téléphone.

    Un seul SVG réduit à 390 px ramènerait les étiquettes à 5 px de corps. Deux géométries
    calculées côté serveur coûtent quelques centaines d'octets et restent lisibles sans script ;
    la feuille de style montre l'une ou l'autre.
    """

    large: dict
    compact: dict
    serie: list = field(default_factory=list)
    total: Decimal = ZERO

    @property
    def vide(self) -> bool:
        return not self.serie or not any(p["valeur"] for p in self.serie)


def _espacer_les_ticks(geometrie: dict, *, largeur_etiquette: float) -> dict:
    """Montre une étiquette d'abscisse sur `k`, la dernière toujours comprise.

    Ancré sur la **dernière** barre : c'est le mois en cours, ou aujourd'hui — l'étiquette qu'on
    cherche en premier.
    """
    barres = geometrie["barres"]
    if not barres:
        return geometrie
    creneau = barres[0]["creneau_l"] or 1
    pas = max(1, math.ceil(largeur_etiquette / creneau))
    dernier = len(barres) - 1
    for rang, barre in enumerate(barres):
        barre["tick_visible"] = (dernier - rang) % pas == 0
    return geometrie


def graphe_de(
    serie: list[dict], *, etiquette: float = 34, largeur: int = 740, hauteur: int = 220
) -> Graphe:
    """La série → deux géométries, au modèle de `geometrie_graphe` du back-office.

    `serie` : une liste de `{"valeur", "libelle", "libelle_long"}`. `largeur` : celle de la carte
    qui l'accueille, à peu près — le SVG s'étire, et une géométrie trop étroite pour une carte
    pleine largeur grossirait les étiquettes d'une fois et demie. Une série vide ou nulle
    produit une géométrie valide (grille et échelle par défaut, aucune barre) : le gabarit
    superpose alors un état vide plutôt qu'un axe muet.
    """
    # Import différé : le module des vues du back-office charge beaucoup, et seules les pages
    # qui dessinent un graphe en ont besoin.
    from apps.backoffice.views import geometrie_graphe

    large = _espacer_les_ticks(
        geometrie_graphe(serie, largeur, hauteur), largeur_etiquette=etiquette
    )
    compact = _espacer_les_ticks(geometrie_graphe(serie, 360, 200), largeur_etiquette=etiquette)
    return Graphe(
        large=large,
        compact=compact,
        serie=serie,
        total=sum((Decimal(p["valeur"]) for p in serie), ZERO),
    )


def trace(serie: list[dict], largeur: int = 92, hauteur: int = 30) -> str:
    """Les points d'une petite courbe de tendance, pour le coin d'un indicateur.

    Pas d'axe, pas d'échelle : elle dit « ça monte » ou « ça baisse », rien de plus. Vide si la
    série est nulle, pour ne pas dessiner un plat trompeur.
    """
    valeurs = [float(p["valeur"]) for p in serie]
    if len(valeurs) < 2 or not any(valeurs):
        return ""
    plafond = max(valeurs) or 1
    pas = largeur / (len(valeurs) - 1)
    return " ".join(
        f"{rang * pas:.1f},{hauteur - 2 - v / plafond * (hauteur - 4):.1f}"
        for rang, v in enumerate(valeurs)
    )


# ============================================================================
# Lectures dans les tables SCOPÉES
#
# Tout ce qui suit lit l'activité d'un commerçant. Ces fonctions ne posent aucun contexte
# elles-mêmes : elles s'appellent **exclusivement** à l'intérieur de `lecture_journalisee()`, qui
# ouvre l'accès transverse et écrit la ligne de journal. Hors de ce bloc, le gestionnaire filtrant
# renvoie un résultat vide — un oubli se voit, il ne fuit pas.
#
# Ce qu'elles lisent est borné à dessein : des totaux TTC, des nombres et des dates. Jamais une
# ligne de ticket, un article, un prix d'achat, un niveau de stock, un client ni une écriture.
# L'administrateur du marché n'en a pas besoin pour faire son métier (ADR-012, §3) — et ce qu'on ne
# lit pas ne peut pas fuir.
# ============================================================================
def _minuit(jour: date) -> datetime:
    """Minuit à Douala, et non en UTC : la journée d'un commerçant commence chez lui."""
    return timezone.make_aware(datetime.combine(jour, time.min))


def activite_par_boutique(
    aujourdhui: date, jours: int = FENETRE_ACTIVITE, *, boutique_id=None
) -> dict:
    """Pour chaque boutique ayant vendu : CA TTC et volumes sur la fenêtre, dernière vente.

    Deux requêtes agrégées, quelle que soit la taille du marché. `boutique_id` borne la lecture à
    une seule boutique : l'écran d'une fiche ne lit pas le marché entier pour en garder une ligne.
    """
    from apps.orders.models import SousCommande
    from apps.pos.models import Ticket

    depuis = _minuit(aujourdhui - timedelta(days=jours - 1))
    resultat: dict = {}

    def entree(boutique_id):
        return resultat.setdefault(
            boutique_id,
            {"ca": ZERO, "tickets": 0, "commandes": 0, "derniere": None},
        )

    borne = {"boutique_id": boutique_id} if boutique_id else {}
    dans_fenetre = Q(cloture_le__gte=depuis)
    for ligne in (
        Ticket.objects.filter(etat=Ticket.CLOTURE, **borne)
        .order_by()
        .values("boutique_id")
        .annotate(
            ca=Sum("total_ttc", filter=dans_fenetre),
            n=Count("id", filter=dans_fenetre),
            derniere=Max("cloture_le"),
        )
    ):
        e = entree(ligne["boutique_id"])
        e["ca"] += ligne["ca"] or ZERO
        e["tickets"] = ligne["n"]
        e["derniere"] = ligne["derniere"]

    dans_fenetre = Q(cree_le__gte=depuis)
    for ligne in (
        SousCommande.objects.filter(**borne)
        .exclude(etat=SousCommande.ANNULEE)
        .order_by()
        .values("boutique_id")
        .annotate(
            ca=Sum("total_ttc", filter=dans_fenetre),
            n=Count("id", filter=dans_fenetre),
            derniere=Max("cree_le"),
        )
    ):
        e = entree(ligne["boutique_id"])
        e["ca"] += ligne["ca"] or ZERO
        e["commandes"] = ligne["n"]
        if ligne["derniere"] and (e["derniere"] is None or ligne["derniere"] > e["derniere"]):
            e["derniere"] = ligne["derniere"]

    return resultat


def jours_sans_vente(derniere, aujourdhui: date) -> int | None:
    """Jours écoulés depuis la dernière vente ; `None` pour une boutique qui n'a jamais vendu."""
    if derniere is None:
        return None
    return (aujourdhui - timezone.localtime(derniere).date()).days


def est_endormie(jours: int | None) -> bool:
    return jours is None or jours >= SEUIL_ENDORMIE


def ca_quotidien(boutique_id, aujourdhui: date, jours: int = FENETRE_ACTIVITE) -> list[dict]:
    """CA TTC jour par jour d'une boutique — caisse et en ligne confondus. Deux requêtes."""
    from apps.orders.models import SousCommande
    from apps.pos.models import Ticket

    premier = aujourdhui - timedelta(days=jours - 1)
    depuis = _minuit(premier)
    parts: dict[date, Decimal] = {}
    for ligne in (
        Ticket.objects.filter(boutique_id=boutique_id, etat=Ticket.CLOTURE, cloture_le__gte=depuis)
        .annotate(jour=TruncDate("cloture_le"))
        .order_by()
        .values("jour")
        .annotate(total=Sum("total_ttc"))
    ):
        parts[ligne["jour"]] = parts.get(ligne["jour"], ZERO) + (ligne["total"] or ZERO)
    for ligne in (
        SousCommande.objects.filter(boutique_id=boutique_id, cree_le__gte=depuis)
        .exclude(etat=SousCommande.ANNULEE)
        .annotate(jour=TruncDate("cree_le"))
        .order_by()
        .values("jour")
        .annotate(total=Sum("total_ttc"))
    ):
        parts[ligne["jour"]] = parts.get(ligne["jour"], ZERO) + (ligne["total"] or ZERO)

    serie = []
    for rang in range(jours):
        jour = premier + timedelta(days=rang)
        serie.append(
            {
                "jour": jour,
                "valeur": parts.get(jour, ZERO).quantize(Decimal("1")),
                "libelle": f"{jour.day}/{jour.month}",
                "libelle_long": f"{jour.day} {MOIS_LONGS[jour.month - 1]} {jour.year}",
            }
        )
    return serie
