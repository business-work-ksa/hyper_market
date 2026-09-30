"""Versements : le chemin de l'argent du `solde_disponible` jusqu'au compte du marchand.

C'est ici que se loge l'**abus de confiance interne**, bien plus que la fraude externe : un
séquestre bien gardé ne sert à rien si le dernier mètre — « verser à tel numéro » — se laisse
détourner. Les parades, dans l'ordre où l'argent les traverse :

1. **Demande par le marchand**, jamais par la plateforme : c'est son argent, c'est lui qui le
   réclame. La demande porte sur tout le disponible, et le retire aussitôt du disponible — deux
   demandes ne peuvent pas porter sur le même franc.
2. **Destination unique et prouvée** : le `CompteVersement` vérifié de la boutique, sorti de son
   délai de carence. Aucun autre numéro n'est proposable, aucun champ ne permet d'en saisir un.
3. **Destination figée** sur le versement au moment de la demande. Changer le compte ensuite ne
   déroute pas un versement déjà demandé.
4. **Exécution tracée** par un administrateur de la plateforme qui saisit la référence de
   l'opérateur — unique, pour qu'une même opération réelle ne justifie pas deux versements. Il ne
   peut pas exécuter le versement d'une boutique dont il est membre, ni vers un compte qu'il a
   lui-même vérifié : quatre yeux, au moins, entre une déclaration de compte et l'argent qui y part.
5. **Rien ne se supprime.** Un versement s'annule, avec un motif et un auteur, et l'argent revient
   au disponible par une ligne de journal.

Ce qui n'est **pas** fait ici : l'appel à l'API de l'agrégateur. Il viendra se brancher à la place
de la saisie manuelle de la référence ; en attendant, l'exécution constate un virement fait hors
de l'application, et ne prétend jamais l'avoir fait elle-même.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.tenancy import contexte_boutique
from apps.payments.models import CENTIME, MouvementPortefeuille, PortefeuilleMarchand, Versement
from apps.payments.services import mouvementer_portefeuille

journal = logging.getLogger(__name__)

__all__ = [
    "VersementRefuse",
    "compte_de_destination",
    "demander_versement",
    "executer_versement",
    "annuler_versement",
]

LONGUEUR_MIN_MOTIF = 10


class VersementRefuse(ValueError):
    """Versement refusé : pas de compte utilisable, rien à verser, geste interdit."""


def compte_de_destination(boutique, *, maintenant=None):
    """Le compte où verser, et à défaut la raison — dite au marchand telle quelle.

    Renvoie `(compte, None)` ou `(None, message)`.
    """
    from apps.marketplace.models import CompteVersement

    maintenant = maintenant or timezone.now()
    boutique_id = getattr(boutique, "pk", boutique)
    compte = CompteVersement.objects.filter(
        boutique_id=boutique_id, etat=CompteVersement.VERIFIE
    ).first()
    if compte is None:
        en_attente = CompteVersement.objects.filter(
            boutique_id=boutique_id, etat=CompteVersement.EN_ATTENTE
        ).exists()
        if en_attente:
            return None, (
                "Votre compte de versement attend sa vérification par la plateforme. "
                "Aucun versement ne part vers un compte qui n'a pas été vérifié."
            )
        return None, (
            "Aucun compte de versement vérifié : déclarez le numéro Mobile Money ou le compte "
            "bancaire de la boutique, à son titulaire vérifié."
        )
    if compte.utilisable_le is None:
        return None, (
            "Votre compte est vérifié, mais sa fin de délai de carence n'est pas fixée : "
            "contactez la plateforme."
        )
    if compte.utilisable_le > maintenant:
        return None, (
            "Compte en délai de carence jusqu'au "
            f"{timezone.localtime(compte.utilisable_le):%d/%m/%Y à %H:%M}. Ce délai protège "
            "contre un changement de numéro juste avant un versement : aucun versement ne part "
            "vers un compte tout juste déclaré."
        )
    return compte, None


def _portefeuille(boutique_id):
    return (
        PortefeuilleMarchand.objects_all_tenants.select_for_update()
        .filter(boutique_id=boutique_id)
        .first()
    )


def demander_versement(boutique, *, par, maintenant=None) -> Versement:
    """Le marchand demande que son disponible lui soit versé.

    Tout le disponible, vers le seul compte possible, avec la destination recopiée — figée —
    sur le versement. Le disponible est débité **à la demande** : l'argent n'est plus disponible
    puisqu'il est en route, et une seconde demande ne peut pas le réclamer une seconde fois.
    """
    maintenant = maintenant or timezone.now()
    boutique_id = getattr(boutique, "pk", boutique)
    if not getattr(par, "is_authenticated", False):
        raise VersementRefuse("Un versement se demande par une personne identifiée.")
    # Par un membre de la boutique, jamais par la plateforme : c'est l'argent du marchand, et un
    # administrateur qui pourrait le faire partir à sa place n'aurait plus besoin de complice.
    if not par.appartenances.filter(boutique_id=boutique_id, actif=True).exists():
        raise VersementRefuse("Seul un membre de la boutique demande son versement.")

    compte, refus = compte_de_destination(boutique_id, maintenant=maintenant)
    if compte is None:
        raise VersementRefuse(refus)

    with contexte_boutique(boutique_id):
        with transaction.atomic():
            portefeuille = _portefeuille(boutique_id)
            disponible = portefeuille.solde_disponible if portefeuille else Decimal("0")
            disponible = Decimal(disponible).quantize(CENTIME)
            if disponible <= 0:
                raise VersementRefuse("Rien à verser : votre solde disponible est nul.")
            if Versement.objects.filter(boutique_id=boutique_id, etat=Versement.DEMANDE).exists():
                raise VersementRefuse(
                    "Un versement est déjà en attente d'exécution. Le suivant pourra être "
                    "demandé dès qu'il sera parti."
                )
            versement = Versement.objects.create(
                boutique_id=boutique_id,
                montant=disponible,
                compte=compte,
                pays=compte.pays,
                operateur=compte.operateur,
                numero=compte.numero,
                titulaire=compte.titulaire,
                demande_par=par,
                cree_par=par,
            )
            mouvementer_portefeuille(
                boutique=boutique_id,
                compartiment=MouvementPortefeuille.DISPONIBLE,
                montant=-disponible,
                type_mouvement=MouvementPortefeuille.VERSEMENT,
                origine_type="payments.Versement",
                origine_id=versement.pk,
            )
    return versement


def _controler_l_executant(versement, par) -> None:
    """Quatre yeux au moins entre la déclaration d'un compte et l'argent qui y part."""
    if not getattr(par, "is_authenticated", False):
        raise VersementRefuse("Un versement s'exécute par une personne identifiée.")
    if par.appartenances.filter(boutique_id=versement.boutique_id, actif=True).exists():
        raise VersementRefuse(
            "Vous êtes membre de cette boutique : son versement doit être exécuté par un autre "
            "administrateur."
        )
    if versement.compte.verifie_par_id == par.pk:
        raise VersementRefuse(
            "Vous avez vérifié le compte de destination : le versement doit être exécuté par un "
            "autre administrateur."
        )
    if versement.demande_par_id == par.pk:
        raise VersementRefuse("On n'exécute pas un versement qu'on a soi-même demandé.")


def executer_versement(versement, *, reference: str, par, maintenant=None) -> Versement:
    """Constate que le virement est parti, sous la référence que l'opérateur lui a donnée.

    Le compte de destination est revérifié : s'il a été retiré ou rejeté depuis la demande — un
    numéro compromis, un titulaire contesté —, le versement ne part pas, il s'annule.
    """
    from apps.accounting.services import EcritureInvalide, comptabiliser_versement
    from apps.marketplace.models import CompteVersement

    maintenant = maintenant or timezone.now()
    reference = (reference or "").strip()
    if len(reference) < 4:
        raise VersementRefuse(
            "Saisissez la référence de l'opération donnée par l'opérateur ou l'agrégateur."
        )
    _controler_l_executant(versement, par)

    try:
        with contexte_boutique(versement.boutique_id):
            with transaction.atomic():
                verrouille = (
                    Versement.objects.select_for_update().select_related("compte").get(
                        pk=versement.pk
                    )
                )
                if verrouille.etat != Versement.DEMANDE:
                    raise VersementRefuse(
                        f"Ce versement est déjà {verrouille.get_etat_display().lower()}."
                    )
                if verrouille.compte.etat != CompteVersement.VERIFIE:
                    raise VersementRefuse(
                        "Le compte de destination n'est plus vérifié "
                        f"({verrouille.compte.get_etat_display().lower()}) : annulez ce "
                        "versement, l'argent reviendra au disponible."
                    )
                verrouille.etat = Versement.EXECUTE
                verrouille.reference_operateur = reference[:120]
                verrouille.execute_par = par
                verrouille.execute_le = maintenant
                verrouille.save(
                    update_fields=[
                        "etat",
                        "reference_operateur",
                        "execute_par",
                        "execute_le",
                        "modifie_le",
                    ]
                )
                try:
                    with transaction.atomic():
                        comptabiliser_versement(
                            verrouille, date_ecriture=timezone.localdate(maintenant)
                        )
                except EcritureInvalide as erreur:
                    # Le virement est parti : le refuser ici ne le ferait pas revenir. On garde
                    # la trace du versement, et on signale l'écriture à passer à la main.
                    journal.error(
                        "Versement %s exécuté sans écriture comptable (%s).", verrouille.pk, erreur
                    )
    except IntegrityError:
        raise VersementRefuse(
            "Cette référence d'opérateur justifie déjà un autre versement : une même opération "
            "ne paie pas deux fois."
        ) from None
    return verrouille


def annuler_versement(versement, *, motif: str, par, maintenant=None) -> Versement:
    """Annule un versement pas encore parti : l'argent revient au disponible, avec la trace."""
    maintenant = maintenant or timezone.now()
    motif = (motif or "").strip()
    if len(motif) < LONGUEUR_MIN_MOTIF:
        raise VersementRefuse("Une annulation se motive, en une phrase.")
    if not getattr(par, "is_authenticated", False):
        raise VersementRefuse("Une annulation a un auteur identifié.")

    with contexte_boutique(versement.boutique_id):
        with transaction.atomic():
            verrouille = Versement.objects.select_for_update().get(pk=versement.pk)
            if verrouille.etat != Versement.DEMANDE:
                raise VersementRefuse(
                    f"Ce versement est {verrouille.get_etat_display().lower()} : "
                    "il ne s'annule plus."
                )
            verrouille.etat = Versement.ANNULE
            verrouille.annule_par = par
            verrouille.annule_le = maintenant
            verrouille.motif_annulation = motif[:300]
            verrouille.save(
                update_fields=["etat", "annule_par", "annule_le", "motif_annulation", "modifie_le"]
            )
            mouvementer_portefeuille(
                boutique=verrouille.boutique_id,
                compartiment=MouvementPortefeuille.DISPONIBLE,
                montant=verrouille.montant,
                type_mouvement=MouvementPortefeuille.VERSEMENT_ANNULE,
                origine_type="payments.Versement",
                origine_id=verrouille.pk,
            )
    return verrouille
