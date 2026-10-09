"""Les emplacements premium sur la vitrine : les montrer, et compter ce qu'ils produisent.

`EmplacementPremium` se vend dans la console depuis le premier jour ; jusqu'ici la vitrine ne
l'affichait pas et rien n'en mesurait l'effet (docs/22, §4.1). Le commerçant payait une semaine de
visibilité sans jamais voir ce qu'il avait acheté — et un emplacement qu'on ne peut pas justifier
ne se renouvelle pas.

Où chaque type apparaît
-----------------------

* **page d'accueil** — le bloc « À la une », jusqu'à trois commerçants, chacun avec quelques articles ;
* **bandeau de rayon** — en tête du rayon, la carte du commerçant ;
* **tête de gondole** — une rangée de ses articles en tête du rayon, avant la grille.

Chaque bloc porte la mention **« Sponsorisé »** : une mise en avant payée qui se ferait passer pour
une recommandation tromperait l'acheteur, et c'est sur la confiance que tient le marché.

Ce qu'on compte, et ce qu'on ne compte pas
------------------------------------------

* un **affichage** par page rendue qui montre l'emplacement — ni les robots d'indexation, ni les
  aperçus de lien (WhatsApp, Facebook), ni le préchargement du navigateur ;
* un **clic** par passage par `/marche/en-avant/<id>/`, l'adresse que portent les liens du bloc ;
* une **commande** quand la session qui a cliqué commande **chez l'occupant** dans les sept jours
  (dernier clic). C'est une attribution, pas une preuve de causalité ; l'écran le dit.

Rien de l'acheteur n'est enregistré : la session garde l'identifiant de l'emplacement cliqué et
l'heure du clic, la base garde des totaux par jour. Un comptage qui échoue n'empêche jamais une
page de s'afficher ni une commande de passer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.db import DatabaseError, connection, transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import contexte_plateforme
from apps.core.uuid7 import uuid7
from apps.marketplace.models import EmplacementPremium, MesureEmplacement

journal = logging.getLogger(__name__)

FENETRE_ATTRIBUTION = timedelta(days=7)
CLE_SESSION = "clics_mise_en_avant"
ARTICLES_PAR_OCCUPANT = 4
# Les visiteurs qui ne sont pas des acheteurs : robots d'indexation, aperçus de liens partagés,
# outils en ligne de commande. Compter leurs passages gonflerait ce que le commerçant croit acheter.
NON_ACHETEURS = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|telegram|curl|wget|"
    r"python-requests|headless|lighthouse",
    re.IGNORECASE,
)


@dataclass
class MiseEnAvant:
    emplacement: EmplacementPremium
    boutique: object
    lien_boutique: str
    articles: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Ce qui est montré
# ---------------------------------------------------------------------------
def emplacements_du_jour(type_: str, *, rayon=None, jour=None) -> list[EmplacementPremium]:
    """Les emplacements de ce type montrés aujourd'hui, dans la limite de sa capacité.

    En cas de surnombre (vendu avant que la capacité soit vérifiée), le premier vendu passe : il
    a été payé le premier.
    """
    jour = jour or timezone.localdate()
    requete = EmplacementPremium.objects.filter(
        type=type_, debut__lte=jour, fin__gte=jour, boutique_occupante__isnull=False
    )
    if type_ != EmplacementPremium.ACCUEIL:
        requete = requete.filter(rayon=rayon)
    capacite = EmplacementPremium.CAPACITES.get(type_, 1)
    return list(requete.order_by("cree_le", "id")[:capacite])


def lien(emplacement, vers: str) -> str:
    """L'adresse d'un lien du bloc : elle passe par le compteur, puis mène à `vers`."""
    return reverse("vitrine_mise_en_avant", args=[emplacement.pk]) + "?" + urlencode({"vers": vers})


def _composer(emplacements, *, rayon=None) -> list[MiseEnAvant]:
    from apps.vitrine.catalogue import _requete_de_base, boutiques_en_vitrine

    if not emplacements:
        return []
    visibles = {b.pk: b for b in boutiques_en_vitrine()}
    mises = []
    for emplacement in emplacements:
        boutique = visibles.get(emplacement.boutique_occupante_id)
        if boutique is None:
            # Suspendue, bail échu : elle ne vend plus, l'emplacement reste vide ce jour-là.
            continue
        with contexte_plateforme():
            articles = _requete_de_base([boutique.pk]).order_by("produit__libelle", "sku")
            if rayon is not None:
                du_rayon = articles.filter(produit__categorie__rayon=rayon)
                if du_rayon.exists():
                    articles = du_rayon
            articles = list(articles[:ARTICLES_PAR_OCCUPANT])
        for article in articles:
            article.lien_mise_en_avant = lien(emplacement, reverse("vitrine_article", args=[article.pk]))
        mises.append(
            MiseEnAvant(
                emplacement=emplacement,
                boutique=boutique,
                lien_boutique=lien(emplacement, reverse("vitrine_boutique", args=[boutique.slug])),
                articles=articles,
            )
        )
    return mises


def pour_accueil() -> list[MiseEnAvant]:
    return _composer(emplacements_du_jour(EmplacementPremium.ACCUEIL))


def pour_rayon(rayon) -> dict:
    """Le bandeau et la tête de gondole d'un rayon — chacun peut manquer."""
    bandeau = _composer(emplacements_du_jour(EmplacementPremium.BANDEAU_RAYON, rayon=rayon), rayon=rayon)
    gondole = _composer(emplacements_du_jour(EmplacementPremium.TETE_DE_GONDOLE, rayon=rayon), rayon=rayon)
    return {"bandeau": bandeau[0] if bandeau else None, "gondole": gondole[0] if gondole else None}


# ---------------------------------------------------------------------------
# Ce qui est compté
# ---------------------------------------------------------------------------
def est_un_acheteur(request) -> bool:
    if NON_ACHETEURS.search(request.headers.get("User-Agent", "")):
        return False
    # Préchargement (Chrome : `Sec-Purpose: prefetch`, ancien `Purpose: prefetch`) : personne ne
    # regarde encore la page.
    intention = (request.headers.get("Sec-Purpose") or request.headers.get("Purpose") or "").lower()
    return "prefetch" not in intention


def _incrementer(emplacement_id, *, affichages=0, clics=0, commandes=0, montant=Decimal("0"), jour=None):
    """Ajoute aux compteurs du jour, en une instruction — deux pages servies au même instant ne
    se marchent pas dessus (`ON CONFLICT … DO UPDATE` additionne au lieu d'écraser)."""
    jour = jour or timezone.localdate()
    table = MesureEmplacement._meta.db_table
    sql = (
        f"INSERT INTO {table} (id, emplacement_id, jour, affichages, clics, commandes, montant) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (emplacement_id, jour) DO UPDATE SET "
        f"affichages = {table}.affichages + EXCLUDED.affichages, "
        f"clics = {table}.clics + EXCLUDED.clics, "
        f"commandes = {table}.commandes + EXCLUDED.commandes, "
        f"montant = {table}.montant + EXCLUDED.montant"
    )
    try:
        with transaction.atomic(), connection.cursor() as curseur:
            curseur.execute(sql, [uuid7(), emplacement_id, jour, affichages, clics, commandes, montant])
    except DatabaseError:
        # Un compteur ne fait jamais échouer une page ni une commande.
        journal.warning("Mesure d'emplacement non enregistrée (%s)", emplacement_id, exc_info=True)


def compter_affichages(request, mises) -> None:
    if not est_un_acheteur(request):
        return
    for mise in mises:
        if mise is not None:
            _incrementer(mise.emplacement.pk, affichages=1)


def compter_clic(request, emplacement) -> None:
    if not est_un_acheteur(request):
        return
    _incrementer(emplacement.pk, clics=1)
    clics = dict(request.session.get(CLE_SESSION) or {})
    clics[str(emplacement.pk)] = timezone.now().isoformat()
    # Les vingt plus récents suffisent : au-delà, ils sont sortis de la fenêtre d'attribution.
    request.session[CLE_SESSION] = dict(sorted(clics.items(), key=lambda c: c[1])[-20:])


def attribuer_commande(request, commande) -> None:
    """Rattache chaque part de la commande au dernier clic sur un emplacement de **son** commerçant.

    Une part chez un commerçant dont l'acheteur n'a cliqué aucun emplacement ne compte pour
    personne : l'emplacement d'un autre commerçant n'y est pour rien.
    """
    clics = request.session.get(CLE_SESSION) or {}
    if not clics:
        return
    limite = timezone.now() - FENETRE_ATTRIBUTION
    recents = {}
    for identifiant, quand in clics.items():
        try:
            moment = datetime.fromisoformat(quand)
        except (TypeError, ValueError):
            continue
        if moment >= limite:
            recents[identifiant] = moment
    if not recents:
        return
    occupants = dict(
        EmplacementPremium.objects.filter(pk__in=list(recents)).values_list("pk", "boutique_occupante_id")
    )
    with contexte_plateforme():
        parts = list(commande.sous_commandes.all())
    for part in parts:
        candidats = [
            (recents[str(pk)], pk) for pk, boutique_id in occupants.items() if boutique_id == part.boutique_id
        ]
        if candidats:
            _, emplacement_id = max(candidats)
            _incrementer(emplacement_id, commandes=1, montant=part.total_ttc)
