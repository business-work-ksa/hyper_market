"""Le cahier de crédit client (docs/22, §2.1).

Dans le commerce de quartier camerounais, le cahier est universel : on note ce que le client
habituel emporte et paiera « à la fin du mois ». Il est en papier, il se perd, il se conteste — et
**c'est là que le commerçant perd réellement de l'argent.** Pas sur sa marge, sur ses créances.

Ce que ce module calcule et ce qu'il refuse
-------------------------------------------

Le solde d'un client est une **différence**, jamais un champ stocké :

    solde = Σ(règlements à crédit de ses tickets clôturés) − Σ(ses règlements sur le cahier)

Un champ `solde` sur `ClientCahier` serait plus rapide à lire et faux au premier incident : une
annulation de ticket, une écriture concurrente, une reprise de sauvegarde, et il dérive sans que
personne ne le voie. Un solde calculé ne peut pas mentir sur ce qu'il additionne. Si le nombre de
lignes devient un problème un jour, la réponse sera un cache ou une vue matérialisée — pas un champ
que deux chemins d'écriture peuvent désynchroniser.

Les tickets **annulés** ne comptent pas, et les **brouillons** non plus : une vente au cahier
existe quand elle est clôturée, comme toute vente.

La limite juridique, qui n'est pas une précaution de style
---------------------------------------------------------

Un cahier est une **facilité de paiement**, pas un prêt. Ce module ne calcule aucun intérêt, aucun
frais de retard, aucune pénalité, et il ne doit jamais en calculer : facturer le temps rend
l'activité réglementée (agrément COBAC, microfinance), c'est-à-dire un autre métier avec un autre
capital. Voir docs/08 avant d'ajouter quoi que ce soit ici qui ressemble à un taux.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction

from apps.pos.models import ClientCahier, ReglementCahier, ReglementTicket, Ticket
from django.utils.translation import gettext as _

__all__ = [
    "CENTIME",
    "PlafondDepasse",
    "solde_de",
    "avec_soldes",
    "verifier_plafond",
    "enregistrer_reglement",
    "releve_de",
]

CENTIME = Decimal("0.01")


class PlafondDepasse(ValidationError):
    """Refus d'une vente au cahier qui ferait passer l'encours au-dessus du plafond.

    Une `ValidationError` et non une `PermissionDenied` : le caissier a le droit de faire cette
    vente, c'est le montant qui ne passe pas. La nuance change le message affiché et le code HTTP.
    """


def _credit_du_client():
    """Somme des règlements à crédit, par client, sur les tickets clôturés uniquement."""
    return (
        ReglementTicket.objects.filter(
            moyen=ReglementTicket.CREDIT,
            ticket__etat=Ticket.CLOTURE,
            ticket__client__isnull=False,
        )
        .values("ticket__client")
        .annotate(total=models.Sum("montant"))
    )


def solde_de(client) -> Decimal:
    """Ce que ce client doit, à cet instant. Positif = il doit ; zéro = à jour.

    Ne peut pas être négatif dans les faits, mais **n'est pas borné à zéro** : un solde négatif
    signalerait un trop-perçu, et l'écraser silencieusement cacherait une erreur de caisse. Mieux
    vaut l'afficher et qu'on se demande pourquoi.
    """
    client_id = getattr(client, "pk", client)

    du = ReglementTicket.objects.filter(
        moyen=ReglementTicket.CREDIT,
        ticket__etat=Ticket.CLOTURE,
        ticket__client_id=client_id,
    ).aggregate(total=models.Sum("montant"))["total"] or Decimal("0")

    rendu = ReglementCahier.objects.filter(client_id=client_id).aggregate(
        total=models.Sum("montant")
    )["total"] or Decimal("0")

    return (du - rendu).quantize(CENTIME)


def avec_soldes(queryset=None):
    """Les clients, annotés de leur encours — **en une requête, quel que soit leur nombre**.

    Deux sous-requêtes corrélées plutôt qu'une boucle sur `solde_de()`. C'est la différence entre
    un écran qui s'affiche et un écran qui s'écroule à deux cents clients ; un test compte les
    requêtes pour que la régression ne passe pas inaperçue.

    `Coalesce` est indispensable : sans elle, un client qui n'a jamais rien pris à crédit obtient
    `NULL` et non zéro, et tri comme classement s'en trouvent faux.
    """
    from django.db.models.functions import Coalesce

    base = queryset if queryset is not None else ClientCahier.objects.all()

    du = models.Subquery(
        ReglementTicket.objects.filter(
            moyen=ReglementTicket.CREDIT,
            ticket__etat=Ticket.CLOTURE,
            ticket__client_id=models.OuterRef("pk"),
        )
        .values("ticket__client_id")
        .annotate(t=models.Sum("montant"))
        .values("t")[:1],
        output_field=models.DecimalField(max_digits=14, decimal_places=2),
    )
    rendu = models.Subquery(
        ReglementCahier.objects.filter(client_id=models.OuterRef("pk"))
        .values("client_id")
        .annotate(t=models.Sum("montant"))
        .values("t")[:1],
        output_field=models.DecimalField(max_digits=14, decimal_places=2),
    )
    zero = models.Value(Decimal("0"), output_field=models.DecimalField(max_digits=14, decimal_places=2))

    return base.annotate(
        total_pris=Coalesce(du, zero),
        total_rendu=Coalesce(rendu, zero),
        encours=Coalesce(du, zero) - Coalesce(rendu, zero),
    )


def verifier_plafond(client, montant) -> Decimal:
    """Refuse une vente au cahier qui dépasserait le plafond. Renvoie l'encours après vente.

    **Ce contrôle est ici, au service, et non à l'écran.** C'est la règle posée par le projet : un
    droit refusé n'est pas grisé, il n'est pas calculé. Un plafond qui ne vit que dans le
    formulaire est contourné par la première requête qui ne passe pas par ce formulaire — et le
    mode hors ligne de la caisse est précisément un chemin qui ne passe pas par lui.

    Un plafond à zéro signifie **pas de crédit**, pas « illimité ». C'est le défaut du modèle, et
    c'est le bon sens : un plafond qu'on a oublié de remplir ne doit pas ouvrir un crédit sans
    limite.
    """
    montant = Decimal(montant)
    if montant <= 0:
        raise ValidationError({"montant": _("Un montant porté au cahier est strictement positif.")})

    if not client.actif:
        raise PlafondDepasse(
            {
                "client": (
                    f"Le cahier de {client.nom} est clos. Rouvrez-le avant d'y porter une vente."
                )
            }
        )

    apres = (solde_de(client) + montant).quantize(CENTIME)
    if apres > client.plafond_credit:
        reste = (client.plafond_credit - solde_de(client)).quantize(CENTIME)
        if reste <= 0:
            detail = f"son plafond de {client.plafond_credit:.0f} FCFA est déjà atteint"
        else:
            detail = f"il reste {reste:.0f} FCFA disponibles sur {client.plafond_credit:.0f}"
        raise PlafondDepasse(
            {"montant": f"Cette vente porterait {client.nom} à {apres:.0f} FCFA : {detail}."}
        )
    return apres


@transaction.atomic
def enregistrer_reglement(
    *, client, moyen: str, montant, recu_par, reference_psp: str = "", note: str = ""
) -> ReglementCahier:
    """Encaisse un paiement sur le cahier, et passe l'écriture comptable correspondante.

    L'atomicité n'est pas décorative : sans elle, un règlement pourrait exister sans son écriture,
    et le 411 resterait débiteur d'un argent déjà dans la caisse. C'est exactement le genre d'écart
    qu'un commerçant découvre trois mois plus tard, sans pouvoir le reconstituer.

    **On n'interdit pas de payer plus que le solde.** Un client peut déposer une avance, et refuser
    l'avance obligerait le caissier à mentir sur le montant reçu. Le solde devient négatif et se
    voit — ce qui est le comportement souhaitable.
    """
    from apps.accounts.permissions import CAHIER_ENCAISSER, droits_de

    montant = Decimal(montant)
    if montant <= 0:
        raise ValidationError({"montant": _("Un règlement est strictement positif.")})
    if moyen == ReglementTicket.CREDIT or moyen not in dict(ReglementCahier.MOYENS):
        raise ValidationError(
            {"moyen": _("Moyen de règlement inconnu. Payer un crédit à crédit n'est rien.")}
        )
    if CAHIER_ENCAISSER not in droits_de(recu_par, client.boutique_id):
        raise PermissionDenied("Encaisser sur le cahier demande le droit correspondant.")

    reglement = ReglementCahier.objects.create(
        boutique_id=client.boutique_id,
        client=client,
        moyen=moyen,
        montant=montant,
        reference_psp=reference_psp,
        note=note,
        cree_par=recu_par,
    )

    # L'écriture vit dans `accounting`, qui dépend de `pos` et non l'inverse : c'est le sens du
    # graphe de dépendances imposé par l'ordre de `LOCAL_APPS`.
    from apps.accounting.services import comptabiliser_reglement_cahier

    comptabiliser_reglement_cahier(reglement)
    return reglement


def releve_de(client, *, depuis=None):
    """Le relevé d'un client : ce qu'il a pris, ce qu'il a payé, dans l'ordre où c'est arrivé.

    C'est la pièce que le commerçant montre quand le client conteste — donc elle mêle les deux
    natures d'événement dans une seule chronologie, plutôt que deux listes à rapprocher de tête.
    """
    client_id = getattr(client, "pk", client)

    tickets = ReglementTicket.objects.filter(
        moyen=ReglementTicket.CREDIT,
        ticket__etat=Ticket.CLOTURE,
        ticket__client_id=client_id,
    ).select_related("ticket")
    if depuis:
        tickets = tickets.filter(ticket__cloture_le__gte=depuis)

    reglements = ReglementCahier.objects.filter(client_id=client_id)
    if depuis:
        reglements = reglements.filter(recu_le__gte=depuis)

    lignes = [
        {
            "date": r.ticket.cloture_le,
            "nature": "achat",
            "libelle": _('Ticket %(numero)s') % {"numero": r.ticket.numero},
            "debit": r.montant,
            "credit": Decimal("0"),
        }
        for r in tickets
    ] + [
        {
            "date": r.recu_le,
            "nature": "paiement",
            "libelle": r.get_moyen_display() + (f" · {r.note}" if r.note else ""),
            "debit": Decimal("0"),
            "credit": r.montant,
        }
        for r in reglements
    ]
    lignes.sort(key=lambda ligne: ligne["date"])

    courant = Decimal("0")
    for ligne in lignes:
        courant += ligne["debit"] - ligne["credit"]
        ligne["solde"] = courant.quantize(CENTIME)
    return lignes
