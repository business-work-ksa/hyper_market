"""Le calcul du palier de confiance d'une boutique — les règles de `apps/marketplace/confiance.py`,
appliquées aux faits.

Ce que chaque palier *permet* est écrit dans `apps/marketplace/confiance.py`. Ce module-ci dit
*comment on y arrive*, et il tient en cinq règles :

1. **Seules les livraisons confirmées comptent.** Une livraison *déclarée* par le marchand
   (`SousCommande.livree_le`) est précisément ce qu'une fausse boutique déclarerait. La
   confirmation vient de l'acheteur (`livraison_confirmee_le`). Et seulement celles d'acheteurs
   **sans lien avec la boutique** : les commandes de son propre gérant ou de ses caissiers ne
   prouvent rien.
2. **Le palier visé est le plus haut dont toutes les conditions sont remplies** : livraisons
   confirmées, acheteurs distincts parmi elles, ancienneté depuis la première activation, taux de
   litiges perdus.
3. **On ne monte que d'un palier à la fois, et pas avant la fin de la fenêtre de litige.** Entre
   deux montées, la boutique reste au moins le délai de libération de son palier courant
   (7 jours au palier 0) : c'est le temps qu'ont ses acheteurs pour contester les livraisons qui
   justifient la montée. Monter avant, c'est récompenser des livraisons qui seront peut-être
   contestées demain. Cette règle rend aussi l'évaluation **idempotente** : la relancer le même
   jour ne change rien.
4. **On descend tout de suite.** Si le taux de litiges perdus dépasse le plafond du palier courant,
   la boutique retombe au palier que ses chiffres justifient, sans délai : la confiance se gagne
   lentement et se perd vite, sinon elle ne protège personne.
5. **Une boutique qui n'est pas active est au palier 0.** Suspendue, elle ne vend plus ; si on la
   réactive, elle recommence à prouver.

Le taux de litiges perdus
-------------------------

« Perdu » veut dire tranché en faveur de l'acheteur, en tout ou partie
(`Litige.PERDUS_PAR_LE_MARCHAND`). Seuls les litiges **clos** comptent : un litige ouvert n'est pas
un jugement, et le compter reviendrait à laisser n'importe quel acheteur rétrograder une boutique
en ouvrant un litige de mauvaise foi.

Le dénominateur est le nombre de sous-commandes **abouties** : livrées et confirmées, ou soldées
par un litige clos. On ne divise pas par le nombre de litiges clos — un marchand qui a livré deux
cents commandes et perdu son seul litige n'a pas « 100 % de litiges perdus » ; il en a perdu un sur
deux cents.

Pourquoi l'ancienneté part de la première activation
----------------------------------------------------

Pas de la création de la fiche : une candidature peut attendre des semaines avant d'être validée,
et ce temps-là n'a rien prouvé. On prend le début du premier bail réellement activé — et jamais
une date antérieure à la création de la boutique, pour qu'un bail antidaté ne fabrique pas
d'ancienneté.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Exists, Max, Min, OuterRef, Q
from django.utils import timezone

from apps.core.tenancy import contexte_plateforme
from apps.marketplace.confiance import PALIERS, Palier, palier

ZERO = Decimal("0")


# ----------------------------------------------------------------------------
# Les faits
# ----------------------------------------------------------------------------
@dataclass
class Mesure:
    livraisons_confirmees: int = 0
    acheteurs_distincts: int = 0
    abouties: int = 0
    litiges_clos: int = 0
    litiges_perdus: int = 0
    premiere_activation: date | None = None
    anciennete_jours: int = 0
    # Le taux tel qu'enregistré par la dernière évaluation, quand on relit une mesure sans son
    # dénominateur (`MesureConfiance`) : il fait alors foi, on ne le recalcule pas.
    taux_enregistre: Decimal | None = None

    @property
    def taux_litiges_perdus(self) -> Decimal:
        if self.taux_enregistre is not None:
            return self.taux_enregistre
        if not self.abouties:
            return ZERO
        return (Decimal(self.litiges_perdus) / Decimal(self.abouties)).quantize(Decimal("0.0001"))

    def en_dict(self) -> dict:
        d = asdict(self)
        d.pop("taux_enregistre", None)
        d["premiere_activation"] = self.premiere_activation.isoformat() if self.premiere_activation else None
        d["taux_litiges_perdus"] = str(self.taux_litiges_perdus)
        return d


def premieres_activations(boutiques) -> dict:
    """Date de première activation de chaque boutique, sans requête par boutique."""
    from apps.marketplace.models import Bail, Boutique

    ids = [b.pk for b in boutiques]
    debuts = dict(
        Bail.objects.filter(boutique_id__in=ids)
        .exclude(etat=Bail.BROUILLON)
        .order_by()
        .values("boutique_id")
        .annotate(d=Min("debut"))
        .values_list("boutique_id", "d")
    )
    resultat = {}
    for b in boutiques:
        plancher = timezone.localdate(b.cree_le) if b.cree_le else None
        debut = debuts.get(b.pk)
        if debut is None:
            # Une boutique active sans bail activé : cas d'exploitation anormal, mais on ne lui
            # invente pas d'ancienneté. Sa fiche fait foi, pas davantage.
            resultat[b.pk] = plancher if b.etat != Boutique.CANDIDATURE else None
        else:
            resultat[b.pk] = max(debut, plancher) if plancher else debut
    return resultat


def mesurer(boutiques, *, aujourdhui: date | None = None) -> dict:
    """Les mesures de plusieurs boutiques, en quatre requêtes quel que soit leur nombre.

    Lit des tables scopées (sous-commandes, litiges) : c'est une tâche technique, sans demandeur
    humain, d'où `contexte_plateforme()` — légitime ici, **jamais** dans la console (ADR-012).
    """
    from apps.accounts.models import Appartenance
    from apps.orders.models import Litige, SousCommande

    boutiques = list(boutiques)
    aujourdhui = aujourdhui or timezone.localdate()
    ids = [b.pk for b in boutiques]
    # Une commande passée par quelqu'un qui travaille dans la boutique ne prouve rien : c'est la
    # façon la plus simple d'acheter un palier (ADR-013, « acheteurs sans lien avec la boutique »).
    maison = Exists(
        Appartenance.objects.filter(
            utilisateur_id=OuterRef("commande__acheteur_id"), boutique_id=OuterRef("boutique_id")
        )
    )
    with contexte_plateforme():
        livraisons = {
            ligne["boutique_id"]: ligne
            for ligne in SousCommande.objects.filter(
                boutique_id__in=ids, livraison_confirmee_le__isnull=False
            )
            .exclude(maison)
            .order_by()
            .values("boutique_id")
            .annotate(n=Count("id"), acheteurs=Count("commande__acheteur_id", distinct=True))
        }
        abouties = dict(
            SousCommande.objects.filter(boutique_id__in=ids)
            .filter(Q(livraison_confirmee_le__isnull=False) | Q(litiges__etat__in=Litige.ETATS_CLOS))
            .order_by()
            .values("boutique_id")
            .annotate(n=Count("id", distinct=True))
            .values_list("boutique_id", "n")
        )
        litiges = {
            ligne["boutique_id"]: ligne
            for ligne in Litige.objects.filter(boutique_id__in=ids, etat__in=Litige.ETATS_CLOS)
            .order_by()
            .values("boutique_id")
            .annotate(
                clos=Count("id"),
                # Une sous-commande perdue compte une fois, même si deux litiges la visaient.
                perdus=Count(
                    "sous_commande_id",
                    distinct=True,
                    filter=Q(etat__in=Litige.PERDUS_PAR_LE_MARCHAND),
                ),
            )
        }
    activations = premieres_activations(boutiques)
    resultat = {}
    for b in boutiques:
        debut = activations.get(b.pk)
        resultat[b.pk] = Mesure(
            livraisons_confirmees=livraisons.get(b.pk, {}).get("n", 0),
            acheteurs_distincts=livraisons.get(b.pk, {}).get("acheteurs", 0),
            abouties=abouties.get(b.pk, 0),
            litiges_clos=litiges.get(b.pk, {}).get("clos", 0),
            litiges_perdus=litiges.get(b.pk, {}).get("perdus", 0),
            premiere_activation=debut,
            anciennete_jours=max((aujourdhui - debut).days, 0) if debut else 0,
        )
    return resultat


def mesurer_une(boutique, *, aujourdhui: date | None = None) -> Mesure:
    return mesurer([boutique], aujourdhui=aujourdhui)[boutique.pk]


# ----------------------------------------------------------------------------
# Les règles
# ----------------------------------------------------------------------------
def _pourcent(fraction: Decimal) -> str:
    valeur = (Decimal(fraction) * 100).quantize(Decimal("0.1"))
    return f"{valeur:.1f}".replace(".", ",").replace(",0", "") + " %"


def manques(p: Palier, mesure: Mesure) -> list[str]:
    """Les conditions de `p` que la boutique ne remplit pas encore — vide si elle y a droit."""
    raisons = []
    if mesure.livraisons_confirmees < p.livraisons_min:
        raisons.append(
            f"{mesure.livraisons_confirmees} livraison(s) confirmée(s) sur {p.livraisons_min} requises"
        )
    requis = getattr(p, "acheteurs_distincts_min", 0)
    if mesure.acheteurs_distincts < requis:
        # Sans cette condition, un palier s'achète : dix auto-commandes depuis deux comptes
        # d'amis, confirmées dans la foulée (ADR-013).
        raisons.append(f"{mesure.acheteurs_distincts} acheteur(s) distinct(s) sur {requis} requis")
    if mesure.anciennete_jours < p.anciennete_jours_min:
        raisons.append(f"{mesure.anciennete_jours} jour(s) d'ancienneté sur {p.anciennete_jours_min} requis")
    if mesure.taux_litiges_perdus > p.taux_litiges_perdus_max:
        raisons.append(
            f"litiges perdus à {_pourcent(mesure.taux_litiges_perdus)}, "
            f"au-delà du plafond de {_pourcent(p.taux_litiges_perdus_max)}"
        )
    return raisons


def palier_merite(mesure: Mesure) -> Palier:
    """Le plus haut palier dont **toutes** les conditions sont remplies.

    Les conditions sont monotones (plus de livraisons, plus d'ancienneté, moins de litiges à
    chaque cran) : remplir celles d'un palier, c'est remplir celles de tous les précédents.
    """
    merite = PALIERS[0]
    for p in PALIERS:
        if not manques(p, mesure):
            merite = p
    return merite


@dataclass
class Decision:
    ancien: int
    nouveau: int
    raisons: list

    @property
    def change(self) -> bool:
        return self.ancien != self.nouveau


def decider(
    *,
    courant: int,
    mesure: Mesure,
    etat_boutique: str,
    dernier_changement: datetime | None,
    maintenant: datetime,
) -> Decision:
    """Le palier que la boutique doit avoir après cette évaluation, et pourquoi. Pure : testable
    sans base."""
    from apps.marketplace.models import Boutique

    courant = palier(courant).niveau  # un niveau inconnu retombe au plus prudent
    if etat_boutique != Boutique.ACTIVE:
        etat = dict(Boutique.ETATS).get(etat_boutique, etat_boutique).lower()
        return Decision(
            courant,
            0,
            [f"Boutique {etat} : le palier retombe à 0 tant qu'elle ne vend pas."] if courant else [],
        )

    merite = palier_merite(mesure)
    actuel = palier(courant)

    if mesure.taux_litiges_perdus > actuel.taux_litiges_perdus_max:
        return Decision(
            courant,
            merite.niveau,
            [
                f"Rétrogradation immédiate : litiges perdus à {_pourcent(mesure.taux_litiges_perdus)} "
                f"({mesure.litiges_perdus} sur {mesure.abouties} commandes abouties), au-delà du "
                f"plafond de {_pourcent(actuel.taux_litiges_perdus_max)} du palier « {actuel.libelle} »."
            ],
        )

    if merite.niveau < courant:
        # Le taux est sous le plafond, donc c'est une autre condition — typiquement un seuil
        # recalibré. Les règles sont le code : on les applique, et on dit laquelle manque.
        return Decision(
            courant,
            merite.niveau,
            [f"Conditions du palier « {actuel.libelle} » non remplies : " + " ; ".join(manques(actuel, mesure)) + "."],
        )

    if merite.niveau > courant:
        suivant = palier(courant + 1)
        depuis = dernier_changement
        attente = timedelta(days=actuel.delai_liberation_jours)
        if depuis is not None and maintenant - depuis < attente:
            reste = attente - (maintenant - depuis)
            return Decision(
                courant,
                courant,
                [
                    f"Conditions du palier « {suivant.libelle} » remplies, montée différée : "
                    f"encore {max(reste.days, 0) + 1} jour(s) de fenêtre de litige au palier courant."
                ],
            )
        raisons = [
            f"Palier « {suivant.libelle} » atteint : {mesure.livraisons_confirmees} livraisons confirmées "
            f"(≥ {suivant.livraisons_min}) auprès de {mesure.acheteurs_distincts} acheteurs distincts "
            f"(≥ {getattr(suivant, 'acheteurs_distincts_min', 0)}), {mesure.anciennete_jours} jours d'ancienneté "
            f"(≥ {suivant.anciennete_jours_min}), litiges perdus à {_pourcent(mesure.taux_litiges_perdus)} "
            f"(≤ {_pourcent(suivant.taux_litiges_perdus_max)})."
        ]
        if merite.niveau > suivant.niveau:
            raisons.append(
                f"Les chiffres justifieraient « {merite.libelle} » ; on monte d'un palier à la fois."
            )
        return Decision(courant, suivant.niveau, raisons)

    return Decision(courant, courant, [])


def progression(niveau: int, mesure: Mesure) -> dict | None:
    """Où en est la boutique vers le palier suivant — pour la carte « Confiance » de la console.

    `None` au dernier palier : il n'y a plus rien à atteindre.
    """
    if niveau >= PALIERS[-1].niveau:
        return None
    cible = palier(niveau + 1)

    def part(valeur, requis):
        return 100 if not requis else min(round(valeur / requis * 100), 100)

    return {
        "palier": cible,
        "criteres": [
            {
                "libelle": "Livraisons confirmées",
                "valeur": mesure.livraisons_confirmees,
                "requis": cible.livraisons_min,
                "part": part(mesure.livraisons_confirmees, cible.livraisons_min),
                "rempli": mesure.livraisons_confirmees >= cible.livraisons_min,
            },
            {
                "libelle": "Acheteurs distincts",
                "valeur": mesure.acheteurs_distincts,
                "requis": getattr(cible, "acheteurs_distincts_min", 0),
                "part": part(mesure.acheteurs_distincts, getattr(cible, "acheteurs_distincts_min", 0)),
                "rempli": mesure.acheteurs_distincts >= getattr(cible, "acheteurs_distincts_min", 0),
            },
            {
                "libelle": "Jours d'ancienneté",
                "valeur": mesure.anciennete_jours,
                "requis": cible.anciennete_jours_min,
                "part": part(mesure.anciennete_jours, cible.anciennete_jours_min),
                "rempli": mesure.anciennete_jours >= cible.anciennete_jours_min,
            },
        ],
        "taux": mesure.taux_litiges_perdus,
        "taux_max": cible.taux_litiges_perdus_max,
        "taux_rempli": mesure.taux_litiges_perdus <= cible.taux_litiges_perdus_max,
        "manques": manques(cible, mesure),
    }


# ----------------------------------------------------------------------------
# L'évaluation
# ----------------------------------------------------------------------------
def evaluer_paliers(*, maintenant: datetime | None = None, boutiques=None) -> dict:
    """Recalcule le palier de chaque boutique, écrit mesures et journal. Idempotente.

    Renvoie un décompte : `{"evaluees": n, "montees": n, "descentes": n}`.
    """
    from apps.confiance.models import ChangementPalier, MesureConfiance
    from apps.marketplace.models import Boutique

    maintenant = maintenant or timezone.now()
    aujourdhui = timezone.localdate(maintenant)
    boutiques = list(boutiques if boutiques is not None else Boutique.objects.all())
    mesures = mesurer(boutiques, aujourdhui=aujourdhui)
    derniers = dict(
        ChangementPalier.objects.filter(boutique__in=boutiques)
        .order_by()
        .values("boutique_id")
        .annotate(d=Max("decide_le"))
        .values_list("boutique_id", "d")
    )

    bilan = {"evaluees": 0, "montees": 0, "descentes": 0}
    for b in boutiques:
        mesure = mesures[b.pk]
        # Sans changement passé, la fenêtre court depuis la première activation : l'entrée au
        # palier 0.
        repere = derniers.get(b.pk)
        if repere is None and mesure.premiere_activation:
            repere = timezone.make_aware(datetime.combine(mesure.premiere_activation, datetime.min.time()))
        decision = decider(
            courant=b.palier_confiance,
            mesure=mesure,
            etat_boutique=b.etat,
            dernier_changement=repere,
            maintenant=maintenant,
        )
        with transaction.atomic():
            MesureConfiance.objects.update_or_create(
                boutique=b,
                defaults={
                    "livraisons_confirmees": mesure.livraisons_confirmees,
                    "acheteurs_distincts": mesure.acheteurs_distincts,
                    "litiges_clos": mesure.litiges_clos,
                    "litiges_perdus": mesure.litiges_perdus,
                    "taux_litiges_perdus": mesure.taux_litiges_perdus,
                    "premiere_activation": mesure.premiere_activation,
                    "mesuree_le": maintenant,
                },
            )
            # `update()` et non `save()` : on n'écrit que les deux champs qui nous appartiennent,
            # sans réécrire une fiche qu'un administrateur modifie peut-être au même instant.
            Boutique.objects.filter(pk=b.pk).update(
                palier_confiance=decision.nouveau, palier_evalue_le=maintenant
            )
            if decision.change:
                ChangementPalier.objects.create(
                    boutique=b,
                    ancien=decision.ancien,
                    nouveau=decision.nouveau,
                    raisons=decision.raisons,
                    mesures=mesure.en_dict(),
                    decide_le=maintenant,
                )
                bilan["montees" if decision.nouveau > decision.ancien else "descentes"] += 1
        b.palier_confiance, b.palier_evalue_le = decision.nouveau, maintenant
        bilan["evaluees"] += 1
    return bilan


# ----------------------------------------------------------------------------
# Les faits publics — ce que la vitrine montre, et rien qu'elle ne puisse prouver
# ----------------------------------------------------------------------------
def condition_identite_verifiee(reference: str = "pk"):
    """Expression SQL : « l'identité de chaque gérant en exercice a été vérifiée, et n'a pas expiré ».

    Faite pour une **annotation** (`Boutique` avec `reference="pk"`, `Variante` avec
    `reference="boutique_id"`) : la vitrine l'obtient dans la requête qui lit déjà les articles, sans
    une requête de plus par carte.

    Deux conditions, parce qu'une seule mentirait : il faut **au moins un** gérant — une boutique
    sans gérant n'a personne dont l'identité soit vérifiée — et **aucun** gérant sans pièce valide —
    un associé non vérifié a les mêmes droits que celui qui l'est. La règle est celle de
    `apps/confiance/verification.py` (contrôle « identite ») ; elle est répétée ici en SQL parce
    que la vitrine ne peut pas se permettre de l'appeler boutique par boutique.
    """
    from apps.accounts.models import Appartenance, DossierKyc, Role
    from apps.marketplace.cemac import PAYS

    pieces = getattr(DossierKyc, "PIECES_IDENTITE", None) or {c for p in PAYS.values() for c in p.pieces}
    valides = DossierKyc.objects.filter(
        utilisateur_id=OuterRef("utilisateur_id"), type_piece__in=list(pieces), etat=DossierKyc.VALIDE
    )
    if any(f.name == "expire_le" for f in DossierKyc._meta.get_fields()):
        valides = valides.filter(Q(expire_le__isnull=True) | Q(expire_le__gte=timezone.localdate()))
    gerants = Appartenance.objects.filter(boutique_id=OuterRef(reference), role_id=Role.GERANT, actif=True)
    return Exists(gerants) & ~Exists(gerants.exclude(Exists(valides)))


def identite_verifiee(boutique) -> bool:
    """La même règle, pour une seule boutique déjà chargée."""
    from apps.marketplace.models import Boutique

    return Boutique.objects.filter(pk=boutique.pk).filter(condition_identite_verifiee()).exists()


def expression_identite_verifiee(reference: str = "pk"):
    """La condition ci-dessus, prête pour `annotate()`."""
    from django.db.models import BooleanField, ExpressionWrapper

    return ExpressionWrapper(condition_identite_verifiee(reference), output_field=BooleanField())


# ----------------------------------------------------------------------------
# La carte « Confiance » de la console
# ----------------------------------------------------------------------------
def carte_confiance(boutique, *, aujourdhui: date | None = None) -> dict:
    """Palier, progression vers le suivant, derniers changements, signaux ouverts.

    Ne lit **aucune** table scopée : la dernière mesure écrite par la tâche de nuit suffit. La fiche
    d'une boutique s'ouvre sans motif de suivi (ADR-012) ; relire ici ses commandes l'obligerait à
    en demander un pour afficher trois chiffres que la vitrine publie déjà.
    """
    from apps.confiance.models import ChangementPalier, MesureConfiance, SignalRisque

    aujourdhui = aujourdhui or timezone.localdate()
    niveau = boutique.palier_confiance or 0
    enregistree = MesureConfiance.objects.filter(boutique=boutique).first()
    mesure = None
    if enregistree is not None:
        mesure = Mesure(
            livraisons_confirmees=enregistree.livraisons_confirmees,
            acheteurs_distincts=enregistree.acheteurs_distincts,
            litiges_clos=enregistree.litiges_clos,
            litiges_perdus=enregistree.litiges_perdus,
            premiere_activation=enregistree.premiere_activation,
            anciennete_jours=(
                max((aujourdhui - enregistree.premiere_activation).days, 0)
                if enregistree.premiere_activation
                else 0
            ),
            taux_enregistre=enregistree.taux_litiges_perdus,
        )
    return {
        "palier": palier(niveau),
        "evalue_le": boutique.palier_evalue_le,
        "mesure": mesure,
        "mesuree_le": enregistree.mesuree_le if enregistree else None,
        "progression": progression(niveau, mesure) if mesure else None,
        "changements": list(ChangementPalier.objects.filter(boutique=boutique)[:4]),
        "signaux": list(
            SignalRisque.objects.filter(boutique=boutique, etat=SignalRisque.OUVERT).order_by(
                "-gravite", "-score"
            )
        ),
        "dernier_palier": niveau >= PALIERS[-1].niveau,
    }
