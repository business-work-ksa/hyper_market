"""Payer une commande en ligne par Mobile Money, et constater le paiement.

Le chemin, de bout en bout :

1. l'acheteur passe commande ; ses parts prépayées attendent leur paiement (`Commande.CONFIRMEE`) ;
2. `payer_commande` demande le débit à l'opérateur de son numéro — MTN pousse une demande sur son
   téléphone, Orange le renvoie vers sa page de paiement ;
3. l'issue arrive par une notification de l'opérateur, par la page de l'acheteur qui interroge, ou
   par la tâche quotidienne — et dans les trois cas, **le statut est relu auprès de l'opérateur**
   avant d'être appliqué (`actualiser`) ;
4. un paiement réussi, du bon montant, est **constaté** : `marquer_payee` ouvre le séquestre de
   chaque part prépayée. Rien ne part au commerçant avant la livraison confirmée.

Deux garde-fous que ce module porte seul :

* **Une seule tentative vivante par commande.** Tant qu'une demande est en attente, on n'en lance pas
  une seconde : un acheteur qui tape deux fois « Payer » recevrait deux demandes sur son téléphone,
  et les validerait peut-être toutes les deux. Après un échec, une nouvelle tentative a sa propre
  clé d'idempotence.
* **Le montant constaté doit être le montant dû.** Un paiement réussi d'un autre montant n'ouvre pas
  de séquestre : il est signalé, et un humain tranche. Un opérateur qui se trompe d'un zéro ne doit
  pas se transformer en livraison.

Le montage est celui du document 08, §5 : l'argent est encaissé par l'opérateur pour le compte de
cantonnement chez le partenaire agréé ; la plateforme **constate** et **ordonne**, elle ne détient pas.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.tenancy import contexte_plateforme
from apps.orders.models import Commande, SousCommande
from apps.payments.adaptateurs import PaiementIndisponible, PrestataireNonConfigure
from apps.payments.models import CENTIME, Prestataire, Transaction
from apps.payments.services import (
    AucunPrestataireDisponible,
    choisir_prestataire,
    initier_encaissement,
    rafraichir_statut,
)
from django.utils.translation import gettext as _

journal = logging.getLogger(__name__)

# Une demande Mobile Money que personne n'a validée au bout d'une journée ne le sera plus.
EXPIRATION = timedelta(hours=24)
# Les opérateurs par lesquels la vitrine accepte un paiement en ligne.
OPERATEURS_EN_LIGNE = (Prestataire.MTN_MOMO, Prestataire.ORANGE_MONEY)


class PaiementImpossible(ValueError):
    """Le paiement ne peut pas être lancé : le message dit pourquoi, et quoi faire à la place."""


def paiements_simules() -> bool:
    return bool(getattr(settings, "PAIEMENTS_SIMULES", False))


def operateurs_ouverts() -> list[str]:
    """Les moyens de paiement en ligne réellement utilisables, en toutes lettres.

    La vitrine ne propose le prépaiement que si cette liste n'est pas vide : proposer de payer
    d'avance quand rien ne permet de payer, c'est engager l'acheteur dans une commande qu'il ne
    pourra pas régler.
    """
    if paiements_simules():
        return ["paiement simulé (démonstration)"]
    from apps.payments.operateurs import AdaptateurMtnMomo, AdaptateurOrangeMoney

    conf = getattr(settings, "PAIEMENTS_OPERATEURS", {})
    actifs = set(Prestataire.objects.filter(actif=True).values_list("code", flat=True))
    ouverts = []
    mtn = conf.get(Prestataire.MTN_MOMO, {})
    if Prestataire.MTN_MOMO in actifs and all(mtn.get(c) for c in AdaptateurMtnMomo.CHAMPS_COLLECTE):
        ouverts.append("MTN Mobile Money")
    orange = conf.get(Prestataire.ORANGE_MONEY, {})
    if (
        Prestataire.ORANGE_MONEY in actifs
        and all(orange.get(c) for c in AdaptateurOrangeMoney.CHAMPS)
        and getattr(settings, "URL_PUBLIQUE", "")
    ):
        ouverts.append("Orange Money")
    return ouverts


def montant_a_payer(commande) -> Decimal:
    """Ce que l'acheteur paie d'avance : ses parts prépayées non annulées.

    Les parts payées à la livraison ne passent jamais par ici — l'argent va de sa main à celle du
    livreur. Les frais de livraison ne sont pas encore répartis entre les parts : ils se règlent à
    la livraison (docs/24, §5).
    """
    with contexte_plateforme():
        parts = SousCommande.objects.filter(
            commande=commande, mode_paiement=SousCommande.PREPAYE
        ).exclude(etat=SousCommande.ANNULEE)
        total = sum((p.total_ttc for p in parts), Decimal("0"))
    return Decimal(total).quantize(CENTIME)


def transactions_de(commande):
    return Transaction.objects.filter(commande=commande, sens=Transaction.ENCAISSEMENT).order_by("cree_le")


def tentative_en_cours(commande) -> Transaction | None:
    return transactions_de(commande).filter(etat=Transaction.INITIEE).last()


def _prestataire_simule() -> Prestataire:
    prestataire, _cree = Prestataire.objects.get_or_create(
        code=Prestataire.FAUX,
        defaults={
            "libelle": "Paiement simulé (démonstration)",  # i18n: non (enregistré en base)
            "taux_frais": Decimal("0"),
            "prefixes_numero": [],
        },
    )
    return prestataire


def _prestataire_pour(numero: str) -> Prestataire:
    if paiements_simules():
        return _prestataire_simule()
    try:
        prestataire = choisir_prestataire(numero)
    except AucunPrestataireDisponible as exc:
        raise PaiementImpossible(str(exc)) from exc
    if prestataire.code not in OPERATEURS_EN_LIGNE:
        raise PaiementImpossible(
            _("Ce numéro n'est ni un numéro MTN ni un numéro Orange : le paiement en ligne n'est "
            "possible qu'avec MTN Mobile Money ou Orange Money. Choisissez le paiement à la livraison.")
        )
    return prestataire


def payer_commande(commande, *, numero: str, url_retour: str = "") -> Transaction:
    """Lance le débit du montant dû, **au plus une demande vivante à la fois**."""
    with transaction.atomic():
        commande = Commande.objects.select_for_update().get(pk=commande.pk)
        if commande.etat != Commande.CONFIRMEE:
            raise PaiementImpossible(_("Cette commande n'attend plus de paiement."))
        montant = montant_a_payer(commande)
        if montant <= 0:
            raise PaiementImpossible(_("Cette commande se paie à la livraison : rien à payer en ligne."))
        en_cours = tentative_en_cours(commande)
        if en_cours is not None:
            return en_cours
        essai = transactions_de(commande).count() + 1

    prestataire = _prestataire_pour(numero)
    try:
        return initier_encaissement(
            cle_idempotence=f"commande-{commande.pk}-essai-{essai}",
            montant=montant,
            numero_payeur=numero,
            commande=commande,
            prestataire=prestataire,
            url_retour=url_retour,
        )
    except PrestataireNonConfigure as exc:
        journal.error("Paiement en ligne impossible : %s", exc)
        raise PaiementImpossible(
            _("Le paiement %(libelle)s n'est pas encore ouvert sur HyperMarché. Choisissez le paiement à la livraison, ou réessayez plus tard.") % {"libelle": prestataire.libelle_affiche}
        ) from exc
    except PaiementIndisponible as exc:
        raise PaiementImpossible(
            _('%(libelle)s ne répond pas en ce moment. Réessayez dans quelques minutes.') % {"libelle": prestataire.libelle_affiche}
        ) from exc


def constater(operation: Transaction) -> bool:
    """Ouvre le séquestre si le paiement a réussi, du bon montant. Idempotent. Renvoie `True` si
    la commande est (ou était déjà) payée."""
    from apps.orders.services import CommandeInvalide, marquer_payee

    if operation.sens != Transaction.ENCAISSEMENT or operation.commande_id is None:
        return False
    if operation.etat != Transaction.REUSSIE:
        return False
    commande = Commande.objects.get(pk=operation.commande_id)
    if commande.etat == Commande.PAYEE:
        return True
    du = montant_a_payer(commande)
    if operation.montant != du:
        journal.error(
            "Paiement %s de %s FCFA pour la commande %s qui en doit %s : constat refusé.",
            operation.pk,
            operation.montant,
            commande.numero,
            du,
        )
        charge = dict(operation.charge_utile_psp or {})
        charge["anomalie"] = f"montant encaissé {operation.montant} ≠ montant dû {du}"
        Transaction.objects.filter(pk=operation.pk).update(charge_utile_psp=charge)
        return False
    try:
        marquer_payee(commande)
    except CommandeInvalide as exc:
        journal.error("Constat du paiement %s refusé : %s", operation.pk, exc)
        return False
    return True


def actualiser(operation: Transaction, *, maintenant=None) -> Transaction:
    """Relit le statut auprès de l'opérateur, puis constate. Ce qu'on fait de toute notification."""
    maintenant = maintenant or timezone.now()
    if operation.etat == Transaction.INITIEE:
        try:
            operation = rafraichir_statut(operation)
        except PaiementIndisponible:
            journal.warning("Statut du paiement %s illisible pour l'instant.", operation.pk)
        except PrestataireNonConfigure:
            pass
        if operation.etat == Transaction.INITIEE and maintenant - operation.cree_le > EXPIRATION:
            from apps.payments.services import appliquer_statut

            operation = appliquer_statut(
                operation, Transaction.EXPIREE, message="Demande non validée au bout de 24 heures."
            )
    constater(operation)
    return operation


def actualiser_en_attente(*, maintenant=None) -> dict:
    """Pour la tâche quotidienne : les demandes restées en attente, et les paiements réussis que
    rien n'aurait encore constatés (une notification perdue, une page fermée trop tôt)."""
    bilan = {"relus": 0, "constates": 0}
    for operation in Transaction.objects.filter(
        sens=Transaction.ENCAISSEMENT, commande__isnull=False, etat=Transaction.INITIEE
    ):
        actualiser(operation, maintenant=maintenant)
        bilan["relus"] += 1
    for operation in Transaction.objects.filter(
        sens=Transaction.ENCAISSEMENT,
        etat=Transaction.REUSSIE,
        commande__etat=Commande.CONFIRMEE,
    ):
        if constater(operation):
            bilan["constates"] += 1
    return bilan
