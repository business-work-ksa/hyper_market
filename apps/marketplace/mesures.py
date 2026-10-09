"""Le bilan d'un emplacement premium : ce qu'il a coûté, et ce qu'il a produit (docs/22, §4.1).

Lu par le commerçant (back-office, « Mise en avant ») et par l'exploitant (console,
« Emplacements premium ») — les mêmes chiffres des deux côtés, calculés au même endroit.

Deux ratios seulement, et chacun dit ce qu'il est :

* **taux de clic** — clics ÷ affichages : la place attire-t-elle l'œil ?
* **coût par clic** — tarif ÷ clics : combien a coûté chaque visite amenée.

Les commandes attribuées (dernier clic, sept jours) sont montrées **à côté**, jamais converties en
« retour sur investissement » : une partie de ces acheteurs serait venue de toute façon, et un
chiffre qui laisserait croire le contraire ferait renouveler un emplacement pour de mauvaises raisons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.marketplace.models import EmplacementPremium, MesureEmplacement

EN_COURS = "en_cours"
A_VENIR = "a_venir"
TERMINE = "termine"


@dataclass
class Bilan:
    emplacement: EmplacementPremium
    affichages: int = 0
    clics: int = 0
    commandes: int = 0
    montant: Decimal = Decimal("0")
    jours: list = field(default_factory=list)

    @property
    def statut(self) -> str:
        aujourdhui = timezone.localdate()
        if self.emplacement.debut > aujourdhui:
            return A_VENIR
        if self.emplacement.fin < aujourdhui:
            return TERMINE
        return EN_COURS

    @property
    def taux_clic(self) -> Decimal | None:
        """En pour cent, à une décimale ; `None` sans affichage (rien à diviser)."""
        if not self.affichages:
            return None
        return (Decimal(self.clics) * 100 / self.affichages).quantize(Decimal("0.1"), ROUND_HALF_UP)

    @property
    def cout_par_clic(self) -> Decimal | None:
        if not self.clics:
            return None
        return (self.emplacement.tarif / self.clics).quantize(Decimal("1"), ROUND_HALF_UP)


def bilans(emplacements, *, avec_jours: bool = False) -> list[Bilan]:
    """Un bilan par emplacement, dans l'ordre reçu ; une requête pour tous les totaux."""
    emplacements = list(emplacements)
    if not emplacements:
        return []
    ids = [e.pk for e in emplacements]
    totaux = {
        ligne["emplacement_id"]: ligne
        for ligne in MesureEmplacement.objects.filter(emplacement_id__in=ids)
        .values("emplacement_id")
        .annotate(
            affichages=Sum("affichages"), clics=Sum("clics"), commandes=Sum("commandes"), montant=Sum("montant")
        )
    }
    jours: dict = {}
    if avec_jours:
        for mesure in MesureEmplacement.objects.filter(emplacement_id__in=ids).order_by("jour"):
            jours.setdefault(mesure.emplacement_id, []).append(mesure)
    resultat = []
    for emplacement in emplacements:
        t = totaux.get(emplacement.pk, {})
        resultat.append(
            Bilan(
                emplacement=emplacement,
                affichages=t.get("affichages") or 0,
                clics=t.get("clics") or 0,
                commandes=t.get("commandes") or 0,
                montant=t.get("montant") or Decimal("0"),
                jours=jours.get(emplacement.pk, []),
            )
        )
    return resultat


def bilans_de_la_boutique(boutique, *, avec_jours: bool = True) -> list[Bilan]:
    """Les emplacements loués par une boutique : en cours d'abord, puis à venir, puis terminés."""
    emplacements = EmplacementPremium.objects.filter(boutique_occupante=boutique).select_related("rayon")
    rang = {EN_COURS: 0, A_VENIR: 1, TERMINE: 2}
    tries = bilans(emplacements, avec_jours=avec_jours)
    tries.sort(key=lambda b: (rang[b.statut], -b.emplacement.debut.toordinal()))
    return tries
