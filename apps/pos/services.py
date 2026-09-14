"""Clôture d'un ticket de caisse.

La clôture est le point de jonction entre la caisse, le stock et la comptabilité : un seul geste
du caissier produit la sortie de stock au CMP et les écritures comptables. C'est la traduction
concrète de la promesse « zéro double saisie » (docs/07, §1.2).
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.inventory.models import Depot, MouvementStock
from apps.inventory.services import sortir_stock
from apps.pos.models import CENTIME, LigneTicket, ReglementTicket, SessionCaisse, Ticket

__all__ = [
    "TicketInvalide",
    "ouvrir_session",
    "creer_ticket",
    "ajouter_ligne",
    "regler",
    "encaisser",
    "cloturer_ticket",
    "consigner_ordonnance",
    "delivrances_sur_ordonnance",
    "fermer_session",
]


class TicketInvalide(ValueError):
    """Ticket refusé : session fermée, ticket vide, ou règlement incomplet."""


def ouvrir_session(*, depot: Depot, caissier, fonds_ouverture=Decimal("0")) -> SessionCaisse:
    ouverte = SessionCaisse.objects_all_tenants.filter(
        depot=depot, caissier=caissier, etat=SessionCaisse.OUVERTE
    ).first()
    if ouverte is not None:
        return ouverte
    return SessionCaisse.objects_all_tenants.create(
        boutique_id=depot.boutique_id,
        depot=depot,
        caissier=caissier,
        fonds_ouverture=fonds_ouverture,
    )


def _numero_suivant(boutique_id) -> str:
    """Séquence continue par boutique, sans rupture ni doublon (exigence de facturation)."""
    dernier = (
        Ticket.objects_all_tenants.filter(boutique_id=boutique_id)
        .aggregate(m=Max("numero"))["m"]
    )
    prochain = 1 if dernier is None else int(dernier.split("-")[-1]) + 1
    return f"T-{prochain:08d}"


def creer_ticket(*, session: SessionCaisse, operation_id=None, **kwargs) -> Ticket:
    if session.etat != SessionCaisse.OUVERTE:
        raise TicketInvalide("La session de caisse est fermée.")

    if operation_id is not None:
        existant = Ticket.objects_all_tenants.filter(operation_id=operation_id).first()
        if existant is not None:
            return existant

    return Ticket.objects_all_tenants.create(
        boutique_id=session.boutique_id,
        session=session,
        numero=_numero_suivant(session.boutique_id),
        operation_id=operation_id,
        **kwargs,
    )


def ajouter_ligne(*, ticket: Ticket, variante, quantite, remise=Decimal("0")) -> LigneTicket:
    if ticket.etat != Ticket.BROUILLON:
        raise TicketInvalide("Un ticket clôturé ne peut plus être modifié.")

    ligne = LigneTicket.objects_all_tenants.create(
        boutique_id=ticket.boutique_id,
        ticket=ticket,
        variante=variante,
        libelle=str(variante),
        quantite=Decimal(quantite),
        pu_ttc=variante.prix_vente,
        taux_tva=variante.taux_tva,
        remise=Decimal(remise),
        # Figé comme le libellé et le prix. Un médicament que l'autorité reclasse
        # l'an prochain ne doit pas réécrire l'ordonnancier de cette année —
        # c'est un registre, et un registre décrit ce qui était vrai au moment
        # de la délivrance.
        sur_ordonnance=variante.produit.sur_ordonnance,
    )
    _recalculer_totaux(ticket)
    return ligne


def _recalculer_totaux(ticket: Ticket) -> None:
    lignes = list(LigneTicket.objects_all_tenants.filter(ticket=ticket))
    ttc = sum((l.total_ttc for l in lignes), Decimal("0"))
    ht = sum((l.total_ht for l in lignes), Decimal("0"))
    ticket.total_ttc = ttc.quantize(CENTIME)
    ticket.total_ht = ht.quantize(CENTIME)
    ticket.total_tva = (ttc - ht).quantize(CENTIME)
    ticket.save(update_fields=["total_ttc", "total_ht", "total_tva", "modifie_le"])


def regler(*, ticket: Ticket, moyen: str, montant, reference_psp: str = "") -> ReglementTicket:
    return ReglementTicket.objects_all_tenants.create(
        boutique_id=ticket.boutique_id,
        ticket=ticket,
        moyen=moyen,
        montant=Decimal(montant),
        reference_psp=reference_psp,
    )


def encaisser(
    *,
    session: SessionCaisse,
    lignes,
    moyen: str = ReglementTicket.ESPECES,
    operation_id=None,
    client_nom: str = "",
    client_telephone: str = "",
    reference_psp: str = "",
    encaisse_le=None,
    cree_par=None,
    mention_ordonnance: str = "",
) -> tuple[Ticket, bool]:
    """Encaisse un panier complet et retourne `(ticket, rejoue)`.

    Le geste que fait réellement un caissier : un panier entre, un ticket
    clôturé sort — avec sa sortie de stock au CMP et ses écritures comptables.
    Écrit ici et pas dans une vue parce que **deux chemins mènent à ce geste**,
    le comptoir et l'API, et que deux implémentations du même encaissement
    finiraient par diverger sur un détail qui compte : l'arrondi, le moyen de
    règlement par défaut, ou la date portée par les écritures.

    `lignes` est une suite de `(variante, quantite, remise)`, ou de
    `(variante, quantite, remise, numeros)` pour les articles suivis à l'unité.
    C'est à l'appelant de résoudre les variantes : le comptoir ignore une
    référence inconnue, l'API la refuse, et cette différence de politique lui
    appartient.

    **Reprise d'un encaissement interrompu.** Une opération retransmise dont le
    ticket existe déjà et porte déjà ses lignes n'est pas rejouée depuis le
    début : elle est reprise là où elle s'était arrêtée. Sans cela, un client qui
    perd le réseau entre l'ajout des lignes et la clôture doublerait le panier en
    réessayant — la clé d'idempotence protège du doublon de ticket, pas du
    doublon de lignes à l'intérieur d'un même ticket.
    """
    panier = [_normaliser_entree(entree) for entree in lignes]

    ticket = creer_ticket(
        session=session,
        operation_id=operation_id,
        client_nom=client_nom[:180],
        client_telephone=client_telephone[:16],
        mention_ordonnance=mention_ordonnance[:180],
    )
    if ticket.etat == Ticket.CLOTURE:
        # Déjà appliquée : on renvoie le résultat précédent (ADR-004).
        return ticket, True

    if not LigneTicket.objects_all_tenants.filter(ticket=ticket).exists():
        for variante, quantite, remise, _ in panier:
            ajouter_ligne(
                ticket=ticket, variante=variante, quantite=quantite, remise=remise
            )
        ticket.refresh_from_db()

    if ticket.reste_a_payer > 0:
        regler(
            ticket=ticket,
            moyen=moyen,
            montant=ticket.reste_a_payer,
            reference_psp=reference_psp,
        )

    cloturer_ticket(ticket, cree_par=cree_par, cloture_le=encaisse_le)
    _consigner_les_exemplaires(ticket, panier, cree_par=cree_par)
    return ticket, False


def _normaliser_entree(entree):
    """Ramène une ligne de panier à `(variante, quantite, remise, numeros)`.

    La forme à trois éléments reste valide et majoritaire : la plupart des
    métiers ne suivent rien à l'unité, et leur imposer un quatrième élément vide
    aurait touché tous les appelants pour le bénéfice d'un seul.
    """
    variante, quantite, remise = entree[0], entree[1], entree[2]
    numeros = entree[3] if len(entree) > 3 else ()
    return variante, quantite, remise, tuple(numeros or ())


def _consigner_les_exemplaires(ticket: Ticket, panier, *, cree_par=None) -> None:
    """Attache les numéros de série vendus à leurs exemplaires.

    **Après la clôture, et hors de sa transaction.** Un numéro mal saisi ne doit
    pas annuler une vente encaissée : la marchandise est partie, le règlement est
    pris, les écritures sont écrites. C'est la même hiérarchie que l'ordonnancier
    — la vente d'abord, le registre ensuite, et l'incomplet se rattrape.
    """
    numerotees = [(v, n) for v, _, _, n in panier if n]
    if not numerotees:
        return

    from apps.inventory.series import vendre as vendre_exemplaires

    depot = ticket.session.depot
    for variante, numeros in numerotees:
        vendre_exemplaires(
            depot=depot,
            variante=variante,
            numeros=numeros,
            ticket_id=ticket.pk,
            ticket_numero=ticket.numero,
            client=ticket.client_nom,
            vendu_le=ticket.cloture_le,
            cree_par=cree_par,
        )


@transaction.atomic
def cloturer_ticket(ticket: Ticket, *, cree_par=None, cloture_le=None) -> Ticket:
    """Clôt le ticket : sortie de stock au CMP puis génération des écritures comptables.

    `cloture_le` permet de déclarer **quand la vente a réellement eu lieu**, et non
    quand le serveur l'a reçue. C'est la date que porteront les écritures
    comptables, et elle ne pourra plus être corrigée ensuite : le journal est en
    ajout seul, et son trigger refuse de déplacer une écriture validée dans le
    temps. Une vente encaissée hors ligne doit donc arriver avec son heure, pas
    la recevoir après coup.
    """
    if ticket.etat == Ticket.CLOTURE:
        return ticket  # idempotent : une retransmission hors ligne ne double pas la sortie de stock
    if ticket.etat == Ticket.ANNULE:
        raise TicketInvalide("Ce ticket a été annulé.")

    lignes = list(
        LigneTicket.objects_all_tenants.filter(ticket=ticket).select_related("variante")
    )
    if not lignes:
        raise TicketInvalide("Un ticket vide ne peut pas être clôturé.")
    if ticket.reste_a_payer > 0:
        raise TicketInvalide(f"Règlement incomplet : reste {ticket.reste_a_payer} FCFA.")

    depot = ticket.session.depot
    for ligne in lignes:
        sortir_stock(
            depot=depot,
            variante=ligne.variante,
            quantite=ligne.quantite,
            type_mouvement=MouvementStock.SORTIE,
            origine_type="pos.Ticket",
            origine_id=ticket.pk,
            operation_id=ticket.operation_id,
            commentaire=f"Vente comptoir {ticket.numero}",
            cree_par=cree_par,
        )

    ticket.etat = Ticket.CLOTURE
    ticket.cloture_le = cloture_le or timezone.now()
    ticket.save(update_fields=["etat", "cloture_le", "modifie_le"])

    # Import tardif : `pos` ne doit pas dépendre de `accounting` au chargement des modèles
    # (règle de dépendance du docs/09, §2).
    from apps.accounting.services import comptabiliser_ticket

    comptabiliser_ticket(ticket)
    return ticket


# ---------------------------------------------------------------------------
# Ordonnancier
# ---------------------------------------------------------------------------
# Un médicament sur ordonnance délivré doit être consigné : quoi, quand, à qui,
# prescrit par qui. C'est un registre, et un registre incomplet est un registre
# qui ne sert à rien le jour où on le demande.
#
# **La délivrance manquante n'est pas refusée, elle est rendue visible.** C'est
# la même règle que le stock négatif (ADR-005) : la boîte est physiquement partie
# avec le client, et refuser d'enregistrer la vente ne la ferait pas revenir —
# cela ferait seulement disparaître la trace. Le logiciel encaisse, puis réclame.
#
# La caisse, elle, demande la mention **avant** de mettre la vente en file : au
# comptoir, la question se pose pendant que le client est là. Le rattrapage par
# l'ordonnancier est le filet, pas le chemin normal.


def delivrances_sur_ordonnance(*, depuis=None, incompletes_seulement=False):
    """Tickets clôturés portant au moins un médicament sur ordonnance.

    Lit dans le contexte de la boutique courante. Les incomplets d'abord : ce
    sont les seuls sur lesquels il reste quelque chose à faire.
    """
    tickets = Ticket.objects.filter(
        etat=Ticket.CLOTURE, lignes__sur_ordonnance=True
    ).distinct()
    if depuis is not None:
        tickets = tickets.filter(cloture_le__gte=depuis)
    if incompletes_seulement:
        tickets = tickets.filter(mention_ordonnance="")
    return tickets.order_by("mention_ordonnance", "-cloture_le")


def consigner_ordonnance(ticket: Ticket, *, mention: str) -> Ticket:
    """Complète l'ordonnancier après coup.

    Le seul champ d'un ticket clôturé qui reste modifiable, et c'est assumé :
    le registre doit pouvoir être complété, alors que les montants, eux, sont
    figés — ils sont déjà partis en comptabilité, où le journal est en ajout seul.
    """
    mention = (mention or "").strip()[:180]
    if not mention:
        raise TicketInvalide("Une mention d'ordonnance vide ne consigne rien.")

    Ticket.objects_all_tenants.filter(pk=ticket.pk).update(mention_ordonnance=mention)
    ticket.mention_ordonnance = mention
    return ticket


def fermer_session(session: SessionCaisse, *, fonds_compte) -> SessionCaisse:
    session.fonds_compte = Decimal(fonds_compte)
    session.fermee_le = timezone.now()
    session.etat = SessionCaisse.FERMEE
    session.save(update_fields=["fonds_compte", "fermee_le", "etat", "modifie_le"])
    return session
