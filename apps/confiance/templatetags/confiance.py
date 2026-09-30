"""Balises de la confiance : ce que la vitrine montre aux acheteurs, et la pastille du rail.

**Des faits, pas des étoiles.** Une note sur cinq se fabrique en une soirée avec dix comptes ; une
livraison confirmée par l'acheteur, non. La vitrine ne montre donc que ce qu'on peut prouver :
l'identité vérifiée (seulement si elle l'est), l'ancienneté, le nombre de livraisons confirmées,
le palier — et la promesse du séquestre.

**Seulement des faits positifs** (docs/23, §2.7). Un taux de litiges affiché sur de petits nombres
— un litige sur trois commandes, « 33 % » — exposerait à une contestation pour dénigrement, et
dirait moins la vérité qu'il n'en a l'air. Les litiges agissent donc à travers le palier, qui les
compte : la vitrine dit « aucun litige perdu » quand c'est vrai, ou le plafond que le palier
garantit (« moins de 10 % de litiges perdus »), jamais un pourcentage brut.

**Sans requête par carte.** Les faits voyagent avec la boutique, dans la requête qui lit déjà les
articles (`apps/vitrine/catalogue.py` : `select_related("mesure_confiance")` et une annotation
pour l'identité). Ces balises ne font que les mettre en forme ; elles ne relisent la base que si
on leur passe une boutique chargée sans ces ajouts.
"""

from __future__ import annotations

from decimal import Decimal

from django import template
from django.core.exceptions import ObjectDoesNotExist

from apps.marketplace.confiance import palier

register = template.Library()

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]


def _mesure(boutique):
    try:
        return boutique.mesure_confiance
    except (ObjectDoesNotExist, AttributeError):
        return None


def _pourcent(fraction: Decimal) -> str:
    valeur = Decimal(fraction) * 100
    return (f"{valeur:.0f}" if valeur == valeur.to_integral() else f"{valeur:.1f}".replace(".", ",")) + " %"


@register.simple_tag
def faits_confiance(boutique, identite=None):
    """Les faits publics d'une boutique, prêts à afficher.

    `identite` : l'annotation déjà calculée (sur la carte d'un article, `vendeur_identite_verifiee`).
    À défaut, on lit celle de la boutique (`identite_verifiee`), et en dernier recours la base.
    """
    if boutique is None:
        return {}
    if identite is None:
        identite = getattr(boutique, "identite_verifiee", None)
    if identite is None:
        from apps.confiance.paliers import identite_verifiee

        identite = identite_verifiee(boutique)

    mesure = _mesure(boutique)
    niveau = boutique.palier_confiance or 0
    p = palier(niveau)
    depuis = mesure.premiere_activation if mesure else None
    if depuis is None and mesure is None:
        from apps.confiance.paliers import premieres_activations

        depuis = premieres_activations([boutique]).get(boutique.pk)

    livraisons = mesure.livraisons_confirmees if mesure else 0
    litiges = None
    if mesure and livraisons and mesure.litiges_perdus == 0:
        litiges = "Aucun litige perdu"
    elif niveau >= 1:
        litiges = f"Moins de {_pourcent(p.taux_litiges_perdus_max)} de litiges perdus"

    return {
        "identite_verifiee": bool(identite),
        "palier": p,
        "depuis": f"{MOIS[depuis.month - 1]} {depuis.year}" if depuis else "",
        "livraisons": livraisons,
        "litiges": litiges,
        "evalue_le": mesure.mesuree_le if mesure else None,
    }


CLE_PASTILLE = "plateforme_signaux_ouverts"
DUREE_PASTILLE = 60  # secondes


@register.simple_tag(takes_context=True)
def signaux_ouverts(context):
    """Le nombre de signaux de risque en attente d'une décision — la pastille du rail.

    `None` plutôt que 0 : une pastille « 0 » apprend à ne plus regarder la pastille.

    Gardé une minute dans la session de l'administrateur : le rail s'affiche sur chaque écran de la
    console, et un décompte par écran serait une requête de plus partout pour un chiffre qui change
    une fois par nuit — et à chaque décision, qui efface cette mémoire (`vues_signaux`).
    """
    import time

    from apps.confiance.models import SignalRisque

    request = context.get("request")
    session = getattr(request, "session", None)
    if session is not None:
        memoire = session.get(CLE_PASTILLE)
        if isinstance(memoire, dict) and memoire.get("jusqua", 0) > time.time():
            return memoire.get("n") or None
    n = SignalRisque.objects.filter(etat=SignalRisque.OUVERT).count()
    if session is not None:
        session[CLE_PASTILLE] = {"n": n, "jusqua": time.time() + DUREE_PASTILLE}
    return n or None
