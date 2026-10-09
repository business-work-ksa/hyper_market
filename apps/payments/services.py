"""Cycle de vie d'un paiement : routage, idempotence, transitions d'état.

C'est la partie qui nous appartient, et c'est la partie difficile. Les appels
HTTP vers les opérateurs viendront s'y brancher (`apps/payments/adaptateurs.py`) ;
ils ne changeront rien à ce qui suit.

Deux invariants gouvernent tout le module :

1. **Une clé d'idempotence, une transaction.** Un double débit Mobile Money est
   l'incident le plus grave possible sur ce marché : le client perd de l'argent,
   et il le raconte. La clé est unique en base — c'est la protection principale,
   pas un contrôle applicatif.
2. **Un état terminal ne change plus.** Une transaction réussie ne redevient
   jamais initiée, une transaction échouée ne devient jamais réussie. Les
   notifications d'opérateur arrivent en désordre, en double, et parfois après
   une interrogation manuelle : sans cette règle, la dernière reçue gagnerait.
"""

from decimal import Decimal

from django.db import IntegrityError
from django.db import transaction as transaction_bd
from django.utils import timezone

from apps.core.tenancy import contexte_boutique
from apps.payments.adaptateurs import (
    PaiementIndisponible,
    adaptateur_pour,
    disjoncteur,
)
from apps.payments.models import (
    CENTIME,
    MouvementPortefeuille,
    PortefeuilleMarchand,
    Prestataire,
    Transaction,
)

__all__ = [
    "AucunPrestataireDisponible",
    "TransitionInterdite",
    "normaliser_numero",
    "choisir_prestataire",
    "initier_encaissement",
    "appliquer_statut",
    "rafraichir_statut",
    "crediter_portefeuille",
    "mouvementer_portefeuille",
]

# États depuis lesquels plus rien ne bouge.
ETATS_TERMINAUX = frozenset({Transaction.REUSSIE, Transaction.ECHOUEE, Transaction.EXPIREE})

INDICATIF_CAMEROUN = "237"


class AucunPrestataireDisponible(RuntimeError):
    """Aucun prestataire ne peut servir ce numéro en ce moment."""


class TransitionInterdite(ValueError):
    """Tentative de faire reculer une transaction déjà tranchée."""


def normaliser_numero(numero: str) -> str:
    """Ramène un numéro à ses chiffres nationaux.

    Un même client écrit son numéro de quatre façons — `+237 6 99 11 00 11`,
    `00237699110011`, `699110011`, `6 99 11 00 11`. Le routage se fait sur des
    préfixes : il faut donc une forme unique avant toute comparaison.
    """
    chiffres = "".join(c for c in (numero or "") if c.isdigit())
    if chiffres.startswith("00" + INDICATIF_CAMEROUN):
        chiffres = chiffres[2 + len(INDICATIF_CAMEROUN) :]
    elif chiffres.startswith(INDICATIF_CAMEROUN) and len(chiffres) > 9:
        chiffres = chiffres[len(INDICATIF_CAMEROUN) :]
    return chiffres


def choisir_prestataire(numero: str) -> Prestataire:
    """Prestataire qui doit encaisser ce numéro.

    **Le numéro décide de l'opérateur, et cela ne se contourne pas.** On ne
    bascule pas un numéro MTN vers Orange : ce n'est pas un choix de routage,
    c'est une impossibilité technique. Le document 09 §6 annonçait une « bascule
    automatique en cas d'indisponibilité d'un opérateur » : cette formulation
    était fausse, et elle est corrigée là-bas.

    Ce qui bascule réellement, c'est le **généraliste** — un agrégateur ou une
    passerelle carte, reconnaissable à sa liste de préfixes vide, qui accepte
    n'importe quel numéro. À défaut, on refuse franchement plutôt que d'envoyer
    un paiement chez le mauvais opérateur.
    """
    national = normaliser_numero(numero)
    actifs = list(Prestataire.objects.filter(actif=True))

    # Préfixe le plus long d'abord : « 650 » doit l'emporter sur « 65 ».
    specialistes = sorted(
        (
            (prefixe, prestataire)
            for prestataire in actifs
            for prefixe in (prestataire.prefixes_numero or [])
            if national.startswith(prefixe)
        ),
        key=lambda couple: len(couple[0]),
        reverse=True,
    )

    for _, prestataire in specialistes:
        if disjoncteur.disponible(prestataire.code):
            return prestataire

    # Le paiement à la livraison et le simulateur n'ont pas de préfixe, mais ce ne sont pas des
    # passerelles : le premier ne débite rien, le second ne débite pas pour de vrai. Sans cette
    # exclusion, le paiement à la livraison — frais nuls, donc premier au tri — recevait tout numéro
    # dont l'opérateur était en panne, et un prépaiement devenait une promesse sans argent.
    NON_PASSERELLES = {Prestataire.PAIEMENT_LIVRAISON, Prestataire.FAUX}
    generalistes = sorted(
        (
            p
            for p in actifs
            if not p.prefixes_numero
            and p.code not in NON_PASSERELLES
            and disjoncteur.disponible(p.code)
        ),
        key=lambda p: p.taux_frais,
    )
    if generalistes:
        return generalistes[0]

    if specialistes:
        raise AucunPrestataireDisponible(
            f"L'opérateur de ce numéro ne répond pas, et aucun autre ne peut le servir. "
            f"Encaissez en espèces et régularisez ensuite."
        )
    raise AucunPrestataireDisponible(f"Aucun prestataire ne couvre le numéro {numero}.")


def initier_encaissement(
    *,
    cle_idempotence: str,
    montant: Decimal,
    numero_payeur: str,
    commande=None,
    prestataire: Prestataire | None = None,
    url_retour: str = "",
) -> Transaction:
    """Demande un débit, **au plus une fois**.

    La clé d'idempotence est fournie par l'appelant — la caisse hors ligne réutilise
    la sienne. Une clé déjà connue renvoie la transaction existante sans rien
    retenter : c'est ce qui rend la retransmission sûre.

    Deux points de structure qui ont chacun leur raison :

    * **La transaction est enregistrée et validée en base avant l'appel réseau.**
      Garder une transaction SQL ouverte pendant un appel d'opérateur la ferait
      durer le temps d'un délai réseau — et, à l'échec, annulerait la trace de
      cet échec avec le reste. Une transaction dont on ne sait plus qu'elle a
      été tentée est une enquête impossible, et potentiellement un débit fantôme.
    * **C'est la contrainte d'unicité qui arbitre**, pas la lecture préalable.
      Deux caisses qui retransmettent la même vente au même instant passent
      toutes deux le `filter()` ; seule l'une des deux insère.
    """
    montant = Decimal(montant).quantize(CENTIME)
    if montant <= 0:
        raise ValueError("Un encaissement de montant nul ou négatif n'a pas de sens.")

    existante = Transaction.objects.filter(cle_idempotence=cle_idempotence).first()
    if existante is not None:
        return existante

    prestataire = prestataire or choisir_prestataire(numero_payeur)
    try:
        with transaction_bd.atomic():
            operation = Transaction.objects.create(
                commande=commande,
                prestataire=prestataire,
                sens=Transaction.ENCAISSEMENT,
                montant=montant,
                numero_payeur=numero_payeur,
                cle_idempotence=cle_idempotence,
            )
    except IntegrityError:
        # Course perdue : l'autre appel a inséré. Sa transaction fait foi.
        return Transaction.objects.get(cle_idempotence=cle_idempotence)

    adaptateur = adaptateur_pour(prestataire.code)
    try:
        reponse = adaptateur.initier(
            reference=str(operation.pk), montant=montant, numero=numero_payeur, url_retour=url_retour
        )
    except PaiementIndisponible as erreur:
        # Le disjoncteur apprend la panne, et la transaction porte le motif :
        # une transaction sans trace de son échec est une enquête pour plus tard.
        disjoncteur.echec(prestataire.code)
        operation.etat = Transaction.ECHOUEE
        operation.charge_utile_psp = {"erreur": str(erreur)}
        operation.save(update_fields=["etat", "charge_utile_psp", "modifie_le"])
        raise

    disjoncteur.succes(prestataire.code)
    operation.reference_externe = reponse.reference_externe
    operation.charge_utile_psp = reponse.charge_utile or {"message": reponse.message}
    operation.etat = reponse.etat
    operation.save(
        update_fields=["reference_externe", "charge_utile_psp", "etat", "modifie_le"]
    )
    return operation


def appliquer_statut(operation: Transaction, etat: str, *, message: str = "") -> Transaction:
    """Fait avancer une transaction, jamais reculer.

    Les notifications d'opérateur arrivent en double, en désordre, et parfois
    après qu'on a interrogé le statut soi-même. Sans cette règle, la dernière
    reçue ferait loi — et une transaction réussie pourrait « échouer » une minute
    plus tard sur une notification en retard.
    """
    if operation.etat == etat:
        return operation
    if operation.etat in ETATS_TERMINAUX:
        raise TransitionInterdite(
            f"Transaction déjà {operation.get_etat_display().lower()} : "
            f"elle ne peut pas devenir « {etat} »."
        )
    if etat not in dict(Transaction.ETATS):
        raise TransitionInterdite(f"État inconnu : {etat}.")

    operation.etat = etat
    charge = dict(operation.charge_utile_psp or {})
    charge["dernier_message"] = message
    charge["tranche_le"] = timezone.now().isoformat(timespec="seconds")
    operation.charge_utile_psp = charge
    operation.save(update_fields=["etat", "charge_utile_psp", "modifie_le"])
    return operation


def rafraichir_statut(operation: Transaction) -> Transaction:
    """Interroge le prestataire et applique ce qu'il répond.

    Utile quand la notification n'est jamais arrivée — cas fréquent : les
    rappels d'opérateur se perdent, et une caisse ne peut pas rester en attente
    indéfiniment.
    """
    if operation.etat in ETATS_TERMINAUX:
        return operation

    adaptateur = adaptateur_pour(operation.prestataire_id)
    try:
        statut = adaptateur.statut(
            operation.reference_externe, charge_utile=dict(operation.charge_utile_psp or {})
        )
    except PaiementIndisponible:
        disjoncteur.echec(operation.prestataire_id)
        raise

    disjoncteur.succes(operation.prestataire_id)
    if statut.charge_utile:
        # La référence financière de l'opérateur est ce qu'un client cite au service client :
        # elle doit rester sur la transaction, pas seulement dans un journal.
        charge = dict(operation.charge_utile_psp or {})
        charge.update({k: v for k, v in statut.charge_utile.items() if v})
        operation.charge_utile_psp = charge
    return appliquer_statut(operation, statut.etat, message=statut.message)


def crediter_portefeuille(
    *, boutique, montant: Decimal, type_mouvement: str, origine_type: str = "", origine_id=None
) -> MouvementPortefeuille:
    """Écrit une ligne au journal du portefeuille marchand, compartiment disponible.

    Le portefeuille est un **compte de suivi**, pas un dépôt de monnaie
    électronique (docs/08, §5.2) : il retrace une créance du marchand sur la
    plateforme. Comme le stock et la comptabilité, il est tenu en journal — le
    solde est un agrégat, jamais une valeur qu'on écrit directement.
    """
    with contexte_boutique(boutique):
        with transaction_bd.atomic():
            return mouvementer_portefeuille(
                boutique=boutique,
                compartiment=MouvementPortefeuille.DISPONIBLE,
                montant=montant,
                type_mouvement=type_mouvement,
                origine_type=origine_type,
                origine_id=origine_id,
            )


def mouvementer_portefeuille(
    *,
    boutique,
    compartiment: str,
    montant: Decimal,
    type_mouvement: str,
    origine_type: str = "",
    origine_id=None,
) -> MouvementPortefeuille:
    """Une ligne de journal, et le solde du compartiment qui la suit.

    **À appeler dans le contexte de la boutique et dans une transaction** : le séquestre et les
    versements écrivent leur état et leurs lignes de journal ensemble, ou pas du tout. Un séquestre
    libéré sans la ligne qui crédite le disponible serait de l'argent disparu ; la ligne sans le
    séquestre, de l'argent inventé.

    Idempotent par origine : la ligne de portefeuille verrouillée sérialise les écritures d'une même
    boutique, et une origine déjà journalisée pour ce type et ce compartiment renvoie sa ligne sans
    toucher au solde. La contrainte d'unicité reste le dernier mot si ce raisonnement est un jour
    contourné.
    """
    montant = Decimal(montant).quantize(CENTIME)
    if montant == 0:
        raise ValueError("Un mouvement de portefeuille nul n'a pas de sens.")
    if compartiment not in dict(MouvementPortefeuille.COMPARTIMENTS):
        raise ValueError(f"Compartiment inconnu : {compartiment}.")

    boutique_id = getattr(boutique, "pk", boutique)
    portefeuille = (
        PortefeuilleMarchand.objects_all_tenants.select_for_update()
        .filter(boutique_id=boutique_id)
        .first()
    )
    if portefeuille is None:
        portefeuille = PortefeuilleMarchand.objects_all_tenants.create(boutique_id=boutique_id)
        portefeuille = PortefeuilleMarchand.objects_all_tenants.select_for_update().get(
            pk=portefeuille.pk
        )

    if origine_id is not None:
        deja = MouvementPortefeuille.objects_all_tenants.filter(
            boutique_id=boutique_id,
            type=type_mouvement,
            compartiment=compartiment,
            origine_id=origine_id,
        ).first()
        if deja is not None:
            return deja

    champ = "solde_bloque" if compartiment == MouvementPortefeuille.BLOQUE else "solde_disponible"
    solde = (getattr(portefeuille, champ) + montant).quantize(CENTIME)
    setattr(portefeuille, champ, solde)
    portefeuille.save(update_fields=[champ, "modifie_le"])

    return MouvementPortefeuille.objects_all_tenants.create(
        boutique_id=boutique_id,
        portefeuille=portefeuille,
        type=type_mouvement,
        compartiment=compartiment,
        montant=montant,
        solde_apres=solde,
        origine_type=origine_type,
        origine_id=origine_id,
    )
