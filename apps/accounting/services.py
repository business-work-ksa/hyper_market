"""Moteur d'écritures automatiques.

Traduit un événement métier en écritures SYSCOHADA selon la table de correspondance du
docs/07-comptabilite-paie-syscohada.md, §3.4. C'est ce module qui matérialise la promesse
« zéro double saisie » : le comptable ne saisit rien de ce que le système sait déjà.
"""

from contextlib import contextmanager
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, Sum

from apps.core.tenancy import contexte_boutique
from apps.accounting.models import (
    CENTIME,
    CompteBoutique,
    EcritureComptable,
    Exercice,
    Journal,
    LigneEcriture,
)

__all__ = [
    "EcritureInvalide",
    "passer_ecriture",
    "contrepasser",
    "comptabiliser_ticket",
    "balance",
    "solde_compte",
]

# Comptes SYSCOHADA utilisés par les automatismes (docs/07, §2.2).
C_STOCK_MARCHANDISES = "311"
C_FOURNISSEURS = "401"
C_CLIENTS = "411"
C_TVA_FACTUREE = "4431"
C_TVA_DEDUCTIBLE = "4452"
C_BANQUE = "5211"
C_MOMO_MTN = "5311"
C_MOMO_ORANGE = "5312"
C_COMPTE_PLATEFORME = "5313"
C_CAISSE = "571"
C_ACHATS_MARCHANDISES = "6011"
C_VARIATION_STOCKS = "6031"
C_LOCATIONS = "622"
C_COMMISSIONS = "632"
C_VENTES_MARCHANDISES = "701"


class EcritureInvalide(ValueError):
    """Écriture refusée : déséquilibrée, sans ligne, ou sur un exercice clôturé."""


def _exercice_courant(boutique_id, date_ecriture) -> Exercice:
    exercice = (
        Exercice.objects_all_tenants.filter(
            boutique_id=boutique_id, debut__lte=date_ecriture, fin__gte=date_ecriture
        )
        .first()
    )
    if exercice is None:
        raise EcritureInvalide(f"Aucun exercice ouvert ne couvre le {date_ecriture}.")
    if exercice.etat == Exercice.CLOTURE:
        raise EcritureInvalide("L'exercice est clôturé : passez l'écriture sur l'exercice suivant.")
    return exercice


def _compte(boutique_id, numero: str) -> CompteBoutique:
    compte = CompteBoutique.objects_all_tenants.filter(
        boutique_id=boutique_id, numero=numero
    ).first()
    if compte is None:
        raise EcritureInvalide(
            f"Le compte {numero} n'existe pas dans le plan de cette boutique. "
            "Initialisez le plan comptable (commande `initialiser_plan_comptable`)."
        )
    return compte


def _piece_suivante(boutique_id, exercice, journal) -> str:
    dernier = EcritureComptable.objects_all_tenants.filter(
        boutique_id=boutique_id, exercice=exercice, journal=journal
    ).aggregate(m=Max("piece"))["m"]
    prochain = 1 if dernier is None else int(dernier.split("-")[-1]) + 1
    return f"{journal.code}-{prochain:06d}"


def passer_ecriture(*, boutique_id, **arguments) -> EcritureComptable:
    """Passe une écriture en partie double, dans le contexte de sa boutique.

    Le contexte est établi **autour** de la transaction, pas dedans : un `SET`
    PostgreSQL est transactionnel, et le poser à l'intérieur d'un bloc qui peut
    échouer laisserait la restauration se heurter à une transaction en erreur
    (`apps/core/rls.py`).
    """
    with contexte_boutique(boutique_id):
        return _passer_ecriture(boutique_id=boutique_id, **arguments)


@transaction.atomic
def _passer_ecriture(
    *,
    boutique_id,
    code_journal: str,
    date_ecriture,
    libelle: str,
    lignes: list[tuple[str, Decimal, Decimal]],
    origine_type: str = "",
    origine_id=None,
    valider: bool = True,
    cree_par=None,
) -> EcritureComptable:
    """Corps de `passer_ecriture`.

    `lignes` est une liste de triplets `(numero_compte, debit, credit)`.
    L'écriture est refusée si elle est déséquilibrée : c'est la garantie que le grand livre reste
    exploitable, quelle que soit l'origine de l'opération.
    """
    if not lignes:
        raise EcritureInvalide("Une écriture sans ligne n'a pas de sens.")

    total_debit = sum((Decimal(d) for _, d, _ in lignes), Decimal("0")).quantize(CENTIME)
    total_credit = sum((Decimal(c) for _, _, c in lignes), Decimal("0")).quantize(CENTIME)
    if total_debit != total_credit:
        raise EcritureInvalide(
            f"Écriture déséquilibrée : débit {total_debit} ≠ crédit {total_credit}."
        )
    if total_debit == 0:
        raise EcritureInvalide("Une écriture de montant nul n'a pas de sens.")

    exercice = _exercice_courant(boutique_id, date_ecriture)
    journal = Journal.objects_all_tenants.filter(
        boutique_id=boutique_id, code=code_journal
    ).first()
    if journal is None:
        raise EcritureInvalide(f"Le journal {code_journal} n'existe pas pour cette boutique.")

    ecriture = EcritureComptable(
        boutique_id=boutique_id,
        journal=journal,
        exercice=exercice,
        date_ecriture=date_ecriture,
        piece=_piece_suivante(boutique_id, exercice, journal),
        libelle=libelle,
        origine_type=origine_type,
        origine_id=origine_id,
        cree_par=cree_par,
    )
    ecriture.save()

    for numero, debit, credit in lignes:
        LigneEcriture.objects_all_tenants.create(
            boutique_id=boutique_id,
            ecriture=ecriture,
            compte=_compte(boutique_id, numero),
            libelle=libelle[:255],
            debit=Decimal(debit).quantize(CENTIME),
            credit=Decimal(credit).quantize(CENTIME),
        )

    if valider:
        ecriture.validee = True
        ecriture.save(update_fields=["validee", "modifie_le"])

    return ecriture


def contrepasser(ecriture: EcritureComptable, *, date_ecriture=None, motif: str = "") -> EcritureComptable:
    """Annule une écriture validée par son inverse. **Seule correction possible.**"""
    with contexte_boutique(ecriture.boutique_id):
        return _contrepasser(ecriture, date_ecriture=date_ecriture, motif=motif)


@transaction.atomic
def _contrepasser(ecriture: EcritureComptable, *, date_ecriture=None, motif: str = "") -> EcritureComptable:
    if ecriture.contrepassee_par_id is not None:
        raise EcritureInvalide("Cette écriture a déjà été contre-passée.")

    from django.utils import timezone

    lignes = [
        (ligne.compte.numero, ligne.credit, ligne.debit)  # inversion débit/crédit
        for ligne in LigneEcriture.objects_all_tenants.filter(ecriture=ecriture).select_related(
            "compte"
        )
    ]
    inverse = passer_ecriture(
        boutique_id=ecriture.boutique_id,
        code_journal=ecriture.journal.code,
        date_ecriture=date_ecriture or timezone.localdate(),
        libelle=motif or f"Contre-passation de {ecriture.piece}",
        lignes=lignes,
        origine_type=ecriture.origine_type,
        origine_id=ecriture.origine_id,
    )

    # `contrepassee_par` est un champ de suivi, pas une donnée comptable : sa mise à jour ne
    # touche ni les lignes ni les montants de l'écriture d'origine.
    EcritureComptable.objects_all_tenants.filter(pk=ecriture.pk).update(contrepassee_par=inverse)
    return inverse


def comptabiliser_ticket(ticket) -> list[EcritureComptable]:
    """Vente au comptoir : vente + TVA, encaissement, sortie de stock au CMP (docs/07, §3.1)."""
    with contexte_boutique(ticket.boutique_id):
        return _comptabiliser_ticket(ticket)


def _comptabiliser_ticket(ticket) -> list[EcritureComptable]:
    from apps.inventory.models import MouvementStock

    boutique_id = ticket.boutique_id
    date = ticket.cloture_le.date() if ticket.cloture_le else ticket.cree_le.date()
    ecritures = []

    # 1. Vente et TVA collectée
    lignes_vente = [
        (C_CLIENTS, ticket.total_ttc, Decimal("0")),
        (C_VENTES_MARCHANDISES, Decimal("0"), ticket.total_ht),
    ]
    if ticket.total_tva > 0:
        lignes_vente.append((C_TVA_FACTUREE, Decimal("0"), ticket.total_tva))
    ecritures.append(
        passer_ecriture(
            boutique_id=boutique_id,
            code_journal=Journal.VENTES,
            date_ecriture=date,
            libelle=f"Vente comptoir {ticket.numero}",
            lignes=lignes_vente,
            origine_type="pos.Ticket",
            origine_id=ticket.pk,
        )
    )

    # 2. Encaissement, ventilé par moyen de paiement
    comptes_par_moyen = {
        "especes": (Journal.CAISSE, C_CAISSE),
        "mobile_money": (Journal.BANQUE, C_MOMO_MTN),
        "carte": (Journal.BANQUE, C_BANQUE),
    }
    from apps.pos.models import ReglementTicket

    for reglement in ReglementTicket.objects_all_tenants.filter(ticket=ticket):
        if reglement.moyen == "credit":
            continue  # la créance reste au 411 jusqu'au règlement
        code_journal, compte = comptes_par_moyen[reglement.moyen]
        ecritures.append(
            passer_ecriture(
                boutique_id=boutique_id,
                code_journal=code_journal,
                date_ecriture=date,
                libelle=f"Encaissement {ticket.numero}",
                lignes=[
                    (compte, reglement.montant, Decimal("0")),
                    (C_CLIENTS, Decimal("0"), reglement.montant),
                ],
                origine_type="pos.Ticket",
                origine_id=ticket.pk,
            )
        )

    # 3. Sortie de stock, valorisée au CMP effectivement appliqué par le moteur de stock
    cout_sorti = _cout_sorti(ticket, MouvementStock)
    if cout_sorti > 0:
        ecritures.append(
            passer_ecriture(
                boutique_id=boutique_id,
                code_journal=Journal.STOCK,
                date_ecriture=date,
                libelle=f"Sortie de stock {ticket.numero}",
                lignes=[
                    (C_VARIATION_STOCKS, cout_sorti, Decimal("0")),
                    (C_STOCK_MARCHANDISES, Decimal("0"), cout_sorti),
                ],
                origine_type="pos.Ticket",
                origine_id=ticket.pk,
            )
        )

    return ecritures


def _cout_sorti(ticket, modele_mouvement) -> Decimal:
    """Coût des marchandises vendues, lu sur les mouvements de stock réellement écrits."""
    mouvements = modele_mouvement.objects_all_tenants.filter(
        boutique_id=ticket.boutique_id, origine_type="pos.Ticket", origine_id=ticket.pk
    )
    total = sum((abs(m.quantite) * m.cout_unitaire for m in mouvements), Decimal("0"))
    return total.quantize(CENTIME)


def solde_compte(numero: str, *, boutique_id=None, jusqu_au=None) -> Decimal:
    """Solde d'un compte (débit − crédit) pour la boutique courante ou désignée."""
    with _contexte_de_lecture(boutique_id):
        lignes = LigneEcriture.objects_all_tenants.filter(compte__numero=numero)
        if boutique_id is not None:
            lignes = lignes.filter(boutique_id=boutique_id)
        if jusqu_au is not None:
            lignes = lignes.filter(ecriture__date_ecriture__lte=jusqu_au)
        agg = lignes.aggregate(d=Sum("debit"), c=Sum("credit"))
    return ((agg["d"] or Decimal("0")) - (agg["c"] or Decimal("0"))).quantize(CENTIME)


@contextmanager
def _contexte_de_lecture(boutique_id):
    """Établit le contexte quand la boutique est désignée, le laisse tel quel sinon.

    Une lecture qui nomme sa boutique doit l'annoncer à la base : sans cela, les
    politiques de sécurité au niveau ligne ne renverraient rien. Une lecture qui
    ne la nomme pas s'appuie sur le contexte de l'appelant, comme avant.
    """
    if boutique_id is None:
        yield
    else:
        with contexte_boutique(boutique_id):
            yield


def balance(*, boutique_id=None, jusqu_au=None) -> list[dict]:
    """Balance générale : un enregistrement par compte mouvementé, trié par numéro."""
    with _contexte_de_lecture(boutique_id):
        return _balance(boutique_id=boutique_id, jusqu_au=jusqu_au)


def _balance(*, boutique_id=None, jusqu_au=None) -> list[dict]:
    lignes = LigneEcriture.objects_all_tenants.all()
    if boutique_id is not None:
        lignes = lignes.filter(boutique_id=boutique_id)
    if jusqu_au is not None:
        lignes = lignes.filter(ecriture__date_ecriture__lte=jusqu_au)

    agrege = (
        lignes.values("compte__numero", "compte__intitule")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("compte__numero")
    )
    return [
        {
            "numero": ligne["compte__numero"],
            "intitule": ligne["compte__intitule"],
            "debit": ligne["debit"] or Decimal("0"),
            "credit": ligne["credit"] or Decimal("0"),
            "solde": (ligne["debit"] or Decimal("0")) - (ligne["credit"] or Decimal("0")),
        }
        for ligne in agrege
    ]
