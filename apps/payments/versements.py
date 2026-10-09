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

Deux façons d'exécuter : **à la main** — le virement est fait hors de l'application, et
l'exécution le constate avec la référence de l'opérateur ; ou **par l'API de MTN** quand la
destination est un compte MTN MoMo et que les clés de versement sont configurées (`envoyer_par_api`,
en bas de ce module). Orange Money n'offre pas de versement par son API de paiement web : il reste
manuel.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.tenancy import contexte_boutique
from apps.payments.models import CENTIME, MouvementPortefeuille, PortefeuilleMarchand, Versement
from apps.payments.services import mouvementer_portefeuille
from django.utils.translation import gettext as _

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
        raise VersementRefuse(_("Un versement se demande par une personne identifiée."))
    # Par un membre de la boutique, jamais par la plateforme : c'est l'argent du marchand, et un
    # administrateur qui pourrait le faire partir à sa place n'aurait plus besoin de complice.
    if not par.appartenances.filter(boutique_id=boutique_id, actif=True).exists():
        raise VersementRefuse(_("Seul un membre de la boutique demande son versement."))

    compte, refus = compte_de_destination(boutique_id, maintenant=maintenant)
    if compte is None:
        raise VersementRefuse(refus)

    with contexte_boutique(boutique_id):
        with transaction.atomic():
            portefeuille = _portefeuille(boutique_id)
            disponible = portefeuille.solde_disponible if portefeuille else Decimal("0")
            disponible = Decimal(disponible).quantize(CENTIME)
            if disponible < 0:
                raise VersementRefuse(
                    _("Rien à verser : les commissions de vos ventes payées à la livraison dépassent "
                    "votre disponible. La différence se règle d'elle-même sur vos prochains "
                    "paiements en ligne.")
                )
            if disponible == 0:
                raise VersementRefuse(_("Rien à verser : votre solde disponible est nul."))
            if Versement.objects.filter(boutique_id=boutique_id, etat=Versement.DEMANDE).exists():
                raise VersementRefuse(
                    _("Un versement est déjà en attente d'exécution. Le suivant pourra être "
                    "demandé dès qu'il sera parti.")
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
        raise VersementRefuse(_("Un versement s'exécute par une personne identifiée."))
    if par.appartenances.filter(boutique_id=versement.boutique_id, actif=True).exists():
        raise VersementRefuse(
            _("Vous êtes membre de cette boutique : son versement doit être exécuté par un autre "
            "administrateur.")
        )
    if versement.compte.verifie_par_id == par.pk:
        raise VersementRefuse(
            _("Vous avez vérifié le compte de destination : le versement doit être exécuté par un "
            "autre administrateur.")
        )
    if versement.demande_par_id == par.pk:
        raise VersementRefuse(_("On n'exécute pas un versement qu'on a soi-même demandé."))


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
            _("Saisissez la référence de l'opération donnée par l'opérateur ou l'agrégateur.")
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
                        _('Ce versement est déjà %(lower)s.') % {"lower": verrouille.get_etat_display().lower()}
                    )
                if verrouille.compte.etat != CompteVersement.VERIFIE:
                    raise VersementRefuse(
                        _("Le compte de destination n'est plus vérifié (%(lower)s) : annulez ce versement, l'argent reviendra au disponible.") % {"lower": verrouille.compte.get_etat_display().lower()}
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
            _("Cette référence d'opérateur justifie déjà un autre versement : une même opération "
            "ne paie pas deux fois.")
        ) from None
    return verrouille


def annuler_versement(versement, *, motif: str, par, maintenant=None) -> Versement:
    """Annule un versement pas encore parti : l'argent revient au disponible, avec la trace."""
    maintenant = maintenant or timezone.now()
    motif = (motif or "").strip()
    if len(motif) < LONGUEUR_MIN_MOTIF:
        raise VersementRefuse(_("Une annulation se motive, en une phrase."))
    if not getattr(par, "is_authenticated", False):
        raise VersementRefuse(_("Une annulation a un auteur identifié."))

    with contexte_boutique(versement.boutique_id):
        with transaction.atomic():
            verrouille = Versement.objects.select_for_update().get(pk=versement.pk)
            if verrouille.etat != Versement.DEMANDE:
                raise VersementRefuse(
                    _("Ce versement est %(lower)s : il ne s'annule plus.") % {"lower": verrouille.get_etat_display().lower()}
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


# ---------------------------------------------------------------------------
# Envoi par l'API de l'opérateur (MTN MoMo)
# ---------------------------------------------------------------------------
# L'exécution manuelle reste la règle générale : un administrateur fait le virement hors de
# l'application et saisit la référence. Quand le compte de destination est un compte MTN MoMo et que
# les clés de versement sont configurées, l'administrateur peut **demander à l'application** de faire
# le virement elle-même. Rien ne change aux garde-fous :
#
# * les mêmes quatre yeux (`_controler_l_executant`) avant tout appel ;
# * **une clé d'idempotence par versement** : `versement-<id>-essai-<n>`, et jamais de second essai
#   tant qu'un envoi est en cours — un double clic ne verse pas deux fois ;
# * le versement n'est **exécuté** qu'une fois l'opérateur relu à « réussi », avec sa référence
#   financière ; un envoi en attente est suivi par la tâche quotidienne.
OPERATEURS_API = ("MTN_MOMO",)


def envoi_par_api_possible(versement) -> bool:
    from django.conf import settings

    from apps.payments.operateurs import AdaptateurMtnMomo

    if versement.operateur not in OPERATEURS_API or versement.etat != Versement.DEMANDE:
        return False
    conf = getattr(settings, "PAIEMENTS_OPERATEURS", {}).get("MTN_MOMO", {})
    return all(conf.get(c) for c in AdaptateurMtnMomo.CHAMPS_VERSEMENT)


def envoi_en_cours(versement):
    from apps.payments.models import Transaction

    return (
        Transaction.objects.filter(
            sens=Transaction.VERSEMENT,
            etat=Transaction.INITIEE,
            cle_idempotence__startswith=f"versement-{versement.pk}-",
        )
        .order_by("cree_le")
        .last()
    )


def envoyer_par_api(versement, *, par):
    """Fait partir le versement par l'API MTN. Renvoie la transaction d'envoi."""
    from apps.payments.adaptateurs import PaiementIndisponible, adaptateur_pour, disjoncteur
    from apps.payments.models import Prestataire, Transaction

    _controler_l_executant(versement, par)
    if not envoi_par_api_possible(versement):
        raise VersementRefuse(
            _("L'envoi automatique n'est possible que vers un compte MTN MoMo, avec les clés de "
            "versement configurées. Exécutez ce versement à la main.")
        )
    en_cours = envoi_en_cours(versement)
    if en_cours is not None:
        return suivre_envoi(en_cours)

    essai = Transaction.objects.filter(cle_idempotence__startswith=f"versement-{versement.pk}-").count() + 1
    try:
        operation = Transaction.objects.create(
            prestataire=Prestataire.objects.get(code=versement.operateur),
            sens=Transaction.VERSEMENT,
            montant=versement.montant,
            numero_payeur=versement.numero[:16],
            cle_idempotence=f"versement-{versement.pk}-essai-{essai}",
            charge_utile_psp={"versement_id": str(versement.pk), "execute_par": str(par.pk)},
        )
    except IntegrityError:
        raise VersementRefuse(_("Un envoi de ce versement vient d'être lancé : relisez la page.")) from None

    try:
        reponse = adaptateur_pour(versement.operateur).verser(
            reference=str(operation.pk), beneficiaire=versement.numero, montant=versement.montant
        )
    except PaiementIndisponible as erreur:
        disjoncteur.echec(versement.operateur)
        operation.etat = Transaction.ECHOUEE
        operation.charge_utile_psp = {**operation.charge_utile_psp, "erreur": str(erreur)}
        operation.save(update_fields=["etat", "charge_utile_psp", "modifie_le"])
        raise VersementRefuse(_("L'opérateur n'a pas pris le versement : %(erreur)s") % {"erreur": erreur}) from erreur

    disjoncteur.succes(versement.operateur)
    operation.reference_externe = reponse.reference_externe
    operation.etat = reponse.etat
    operation.charge_utile_psp = {**operation.charge_utile_psp, **(reponse.charge_utile or {}), "message": reponse.message}
    operation.save(update_fields=["reference_externe", "etat", "charge_utile_psp", "modifie_le"])
    if operation.etat == Transaction.ECHOUEE:
        raise VersementRefuse(reponse.message)
    return suivre_envoi(operation)


def suivre_envoi(operation):
    """Relit un envoi en cours ; s'il a réussi, exécute le versement avec la référence de MTN."""
    from apps.accounts.models import Utilisateur
    from apps.payments.adaptateurs import PaiementIndisponible, adaptateur_pour
    from apps.payments.models import Transaction
    from apps.payments.services import appliquer_statut

    if operation.etat == Transaction.INITIEE:
        try:
            statut = adaptateur_pour(operation.prestataire_id).statut_versement(operation.reference_externe)
        except PaiementIndisponible:
            return operation
        if statut.charge_utile:
            operation.charge_utile_psp = {**operation.charge_utile_psp, **{k: v for k, v in statut.charge_utile.items() if v}}
        operation = appliquer_statut(operation, statut.etat, message=statut.message)

    if operation.etat == Transaction.REUSSIE:
        charge = operation.charge_utile_psp or {}
        versement = Versement.objects.filter(pk=charge.get("versement_id")).select_related("compte").first()
        par = Utilisateur.objects.filter(pk=charge.get("execute_par")).first()
        if versement is not None and versement.etat == Versement.DEMANDE and par is not None:
            reference = charge.get("reference_financiere") or operation.reference_externe
            executer_versement(versement, reference=f"MTN-{reference}", par=par)
    return operation


def suivre_envois_en_cours() -> int:
    """Pour la tâche quotidienne : les envois restés en attente d'une réponse de l'opérateur."""
    from apps.payments.models import Transaction

    n = 0
    for operation in Transaction.objects.filter(sens=Transaction.VERSEMENT, etat=Transaction.INITIEE):
        suivre_envoi(operation)
        n += 1
    return n
