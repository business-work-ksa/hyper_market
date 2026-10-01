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
    "comptabiliser_vente_en_ligne",
    "comptabiliser_expedition",
    "comptabiliser_liberation_sequestre",
    "comptabiliser_versement",
    "comptabiliser_remboursement",
    "comptabiliser_vente_a_la_livraison",
    "comptabiliser_compensation_commission",
    "comptabiliser_reglement_cahier",
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


# ---------------------------------------------------------------------------
# Vente en ligne
# ---------------------------------------------------------------------------
def comptabiliser_vente_en_ligne(sous_commande, *, date_ecriture=None) -> list[EcritureComptable]:
    """Vente en ligne encaissée : vente, séquestre, commission de place (docs/07, §3.2).

    Trois écritures, et une différence de fond avec la vente au comptoir : **l'argent
    n'arrive pas chez le marchand.** Il arrive sur le compte de séquestre de la
    plateforme (`5313`), qui reversera plus tard, net de sa commission. Le marchand
    voit donc une créance sur la plateforme, pas de la trésorerie — et c'est
    exactement ce qui doit apparaître dans ses comptes.

    La commission de place est une **charge du marchand** (`632`), pas une réduction
    de son chiffre d'affaires : le prix payé par l'acheteur est intégralement du
    chiffre d'affaires, et la place de marché facture son service par-dessus. La
    confusion des deux fausserait le chiffre d'affaires déclaré, donc la TVA.

    Ce qui n'est **pas** écrit ici : le reversement (`5311` / `401` / `5313`). Il a
    lieu quand la plateforme paie effectivement, ce que le palier 1 ne fait pas
    encore — écrire l'écriture d'un virement qui n'existe pas mettrait de la
    trésorerie fictive dans les comptes du marchand.
    """
    with contexte_boutique(sous_commande.boutique_id):
        return _comptabiliser_vente_en_ligne(sous_commande, date_ecriture=date_ecriture)


def _comptabiliser_vente_en_ligne(sous_commande, *, date_ecriture=None) -> list[EcritureComptable]:
    from django.conf import settings
    from django.utils import timezone

    boutique_id = sous_commande.boutique_id
    date = date_ecriture or timezone.localdate()
    numero = sous_commande.commande.numero
    reference = {"origine_type": "orders.SousCommande", "origine_id": sous_commande.pk}
    ecritures = []

    # 1. Vente et TVA collectée
    lignes_vente = [
        (C_CLIENTS, sous_commande.total_ttc, Decimal("0")),
        (C_VENTES_MARCHANDISES, Decimal("0"), sous_commande.total_ht),
    ]
    if sous_commande.total_tva > 0:
        lignes_vente.append((C_TVA_FACTUREE, Decimal("0"), sous_commande.total_tva))
    ecritures.append(
        passer_ecriture(
            boutique_id=boutique_id,
            code_journal=Journal.VENTES,
            date_ecriture=date,
            libelle=f"Vente en ligne {numero}",
            lignes=lignes_vente,
            **reference,
        )
    )

    # 2. Encaissement par la plateforme : la créance client devient une créance
    #    sur la plateforme, pas de la trésorerie disponible.
    ecritures.append(
        passer_ecriture(
            boutique_id=boutique_id,
            code_journal=Journal.BANQUE,
            date_ecriture=date,
            libelle=f"Séquestre plateforme {numero}",
            lignes=[
                (C_COMPTE_PLATEFORME, sous_commande.total_ttc, Decimal("0")),
                (C_CLIENTS, Decimal("0"), sous_commande.total_ttc),
            ],
            **reference,
        )
    )

    # 3. Commission de place, TVA récupérable comprise
    commission = Decimal(sous_commande.commission_plateforme)
    if commission > 0:
        tva = (commission * Decimal(settings.TAUX_TVA_DEFAUT) / 100).quantize(CENTIME)
        ecritures.append(
            passer_ecriture(
                boutique_id=boutique_id,
                code_journal=Journal.ACHATS,
                date_ecriture=date,
                libelle=f"Commission de place {numero}",
                lignes=[
                    (C_COMMISSIONS, commission, Decimal("0")),
                    (C_TVA_DEDUCTIBLE, tva, Decimal("0")),
                    (C_FOURNISSEURS, Decimal("0"), commission + tva),
                ],
                **reference,
            )
        )

    return ecritures


def comptabiliser_vente_a_la_livraison(sous_commande, *, date_ecriture=None) -> list[EcritureComptable]:
    """Vente en ligne **payée à la livraison** : l'argent passe de la main de l'acheteur à celle du
    livreur du marchand, jamais par la plateforme.

    Elle n'était comptabilisée nulle part : `marquer_payee` ne voit que les parts prépayées. Un
    marchand qui vend surtout à la livraison — le cas le plus courant ici — avait donc un chiffre
    d'affaires en ligne absent de ses livres.

    Trois écritures, comme au comptoir, écrites **à la livraison** parce que c'est là que l'argent
    change de main :

    1. la vente et sa TVA collectée (`411` / `701`, `4431`) ;
    2. l'encaissement en caisse (`571` / `411`) — le livreur rapporte des espèces ; un règlement par
       Mobile Money au livreur se reclasse à la main, faute de savoir comment il a été fait ;
    3. la commission de place, due à la plateforme même sans séquestre (`632`, `4452` / `401`) :
       elle sera facturée avec le loyer, pas retenue sur un versement.

    Idempotent : une part déjà comptabilisée ne l'est pas deux fois.
    """
    with contexte_boutique(sous_commande.boutique_id):
        return _comptabiliser_vente_a_la_livraison(sous_commande, date_ecriture=date_ecriture)


def _comptabiliser_vente_a_la_livraison(sous_commande, *, date_ecriture=None) -> list[EcritureComptable]:
    from django.conf import settings
    from django.utils import timezone

    reference = {"origine_type": "orders.SousCommande", "origine_id": sous_commande.pk}
    if EcritureComptable.objects_all_tenants.filter(
        boutique_id=sous_commande.boutique_id, journal__code=Journal.VENTES, **reference
    ).exists():
        return []

    boutique_id = sous_commande.boutique_id
    date = date_ecriture or timezone.localdate()
    numero = sous_commande.commande.numero
    ttc = Decimal(sous_commande.total_ttc)
    if ttc <= 0:
        return []

    lignes_vente = [
        (C_CLIENTS, ttc, Decimal("0")),
        (C_VENTES_MARCHANDISES, Decimal("0"), sous_commande.total_ht),
    ]
    if sous_commande.total_tva > 0:
        lignes_vente.append((C_TVA_FACTUREE, Decimal("0"), sous_commande.total_tva))
    ecritures = [
        passer_ecriture(
            boutique_id=boutique_id,
            code_journal=Journal.VENTES,
            date_ecriture=date,
            libelle=f"Vente en ligne à la livraison {numero}",
            lignes=lignes_vente,
            **reference,
        ),
        passer_ecriture(
            boutique_id=boutique_id,
            code_journal=Journal.CAISSE,
            date_ecriture=date,
            libelle=f"Encaissement à la livraison {numero}",
            lignes=[(C_CAISSE, ttc, Decimal("0")), (C_CLIENTS, Decimal("0"), ttc)],
            **reference,
        ),
    ]
    commission = Decimal(sous_commande.commission_plateforme)
    if commission > 0:
        tva = (commission * Decimal(settings.TAUX_TVA_DEFAUT) / 100).quantize(CENTIME)
        ecritures.append(
            passer_ecriture(
                boutique_id=boutique_id,
                code_journal=Journal.ACHATS,
                date_ecriture=date,
                libelle=f"Commission de place {numero}",
                lignes=[
                    (C_COMMISSIONS, commission, Decimal("0")),
                    (C_TVA_DEDUCTIBLE, tva, Decimal("0")),
                    (C_FOURNISSEURS, Decimal("0"), commission + tva),
                ],
                **reference,
            )
        )
    return ecritures


def comptabiliser_liberation_sequestre(sequestre, *, date_ecriture=None) -> list[EcritureComptable]:
    """La plateforme se paie sa commission sur la créance du marchand, à la libération.

    À la vente, le marchand a enregistré deux choses : une créance sur la plateforme (`5313`, le
    TTC encaissé) et une dette envers elle (`401`, la commission de place TVA comprise). Tant que le
    séquestre peut encore être remboursé, les deux restent face à face — un litige gagné par
    l'acheteur annulerait la commission. À la libération, elle est acquise : la plateforme la
    retient sur ce qu'elle doit, et les deux comptes se compensent (débit `401`, crédit `5313`).

    Ce qui reste au `5313` est alors exactement la part nette du marchand, que le versement
    soldera (`comptabiliser_versement`).
    """
    retenue = Decimal(sequestre.commission).quantize(CENTIME)
    if retenue <= 0:
        return []
    from django.utils import timezone

    numero = sequestre.commande.numero
    return [
        passer_ecriture(
            boutique_id=sequestre.boutique_id,
            code_journal=Journal.OPERATIONS_DIVERSES,
            date_ecriture=date_ecriture or timezone.localdate(),
            libelle=f"Commission retenue sur séquestre {numero}",
            lignes=[
                (C_FOURNISSEURS, retenue, Decimal("0")),
                (C_COMPTE_PLATEFORME, Decimal("0"), retenue),
            ],
            origine_type="payments.Sequestre",
            origine_id=sequestre.pk,
        )
    ]


def comptabiliser_remboursement(sequestre, *, date_ecriture=None) -> list[EcritureComptable]:
    """L'acheteur est remboursé : la vente est défaite, en tout ou en partie, dans les livres.

    Sans ces écritures, un marchand remboursé gardait dans ses comptes un chiffre d'affaires et une
    TVA collectée qu'il n'a jamais encaissés — et il les déclarait.

    * **Remboursement total** : les trois écritures de la vente en ligne (vente et TVA, séquestre,
      commission de place) sont **contre-passées**. C'est la seule correction qu'admet un journal en
      ajout seul, et elle rend exactement ce que la vente avait mis : le `5313` retombe à zéro, la
      commission disparaît avec la vente, la TVA collectée aussi. La sortie de stock n'est pas
      touchée — une marchandise non rendue n'est pas rentrée.
    * **Remboursement partiel** : un **avoir** au prorata de la vente (le HT et la TVA dans la
      proportion du TTC rendu), puis la sortie du `5313` vers l'acheteur. La commission subsiste,
      la vente aussi : c'est une réduction consentie, pas une annulation.

    Idempotent : une vente déjà contre-passée ne l'est pas deux fois ; un avoir déjà passé n'est pas
    repassé.
    """
    with contexte_boutique(sequestre.boutique_id):
        return _comptabiliser_remboursement(sequestre, date_ecriture=date_ecriture)


def _comptabiliser_remboursement(sequestre, *, date_ecriture=None) -> list[EcritureComptable]:
    from django.utils import timezone

    from apps.payments.models import Sequestre

    date = date_ecriture or timezone.localdate()
    part = sequestre.sous_commande
    numero = part.commande.numero

    if sequestre.etat == Sequestre.REMBOURSE:
        originales = EcritureComptable.objects_all_tenants.filter(
            boutique_id=sequestre.boutique_id,
            origine_type="orders.SousCommande",
            origine_id=part.pk,
            journal__code__in=[Journal.VENTES, Journal.BANQUE, Journal.ACHATS],
            contrepassee_par__isnull=True,
        )
        # Une contre-passation porte la même origine que ce qu'elle annule : on écarte les inverses,
        # sans quoi un second appel « annulerait l'annulation ».
        inverses = EcritureComptable.objects_all_tenants.filter(
            boutique_id=sequestre.boutique_id, contrepassee_par__isnull=False
        ).values_list("contrepassee_par_id", flat=True)
        return [
            contrepasser(e, date_ecriture=date, motif=f"Avoir — remboursement total {numero}"[:255])
            for e in originales.exclude(pk__in=inverses).order_by("cree_le")
        ]

    rendu = Decimal(sequestre.rembourse_acheteur or 0).quantize(CENTIME)
    if sequestre.etat != Sequestre.PARTAGE or rendu <= 0:
        return []
    deja = EcritureComptable.objects_all_tenants.filter(
        boutique_id=sequestre.boutique_id,
        origine_type="payments.Sequestre",
        origine_id=sequestre.pk,
        libelle__startswith="Avoir partiel",
    ).exists()
    if deja:
        return []

    total_ttc = Decimal(part.total_ttc)
    ht = (rendu * Decimal(part.total_ht) / total_ttc).quantize(CENTIME) if total_ttc else rendu
    tva = rendu - ht
    lignes_avoir = [(C_VENTES_MARCHANDISES, ht, Decimal("0"))]
    if tva > 0:
        lignes_avoir.append((C_TVA_FACTUREE, tva, Decimal("0")))
    lignes_avoir.append((C_CLIENTS, Decimal("0"), rendu))
    reference = {"origine_type": "payments.Sequestre", "origine_id": sequestre.pk}
    return [
        passer_ecriture(
            boutique_id=sequestre.boutique_id,
            code_journal=Journal.VENTES,
            date_ecriture=date,
            libelle=f"Avoir partiel {numero}",
            lignes=lignes_avoir,
            **reference,
        ),
        passer_ecriture(
            boutique_id=sequestre.boutique_id,
            code_journal=Journal.BANQUE,
            date_ecriture=date,
            libelle=f"Avoir partiel {numero} — remboursé par le séquestre",
            lignes=[(C_CLIENTS, rendu, Decimal("0")), (C_COMPTE_PLATEFORME, Decimal("0"), rendu)],
            **reference,
        ),
    ]


def comptabiliser_compensation_commission(sous_commande, montant, *, date_ecriture=None) -> list[EcritureComptable]:
    """La commission d'une vente à la livraison, retenue par la plateforme sur ce qu'elle doit.

    Même écriture qu'à la libération d'un séquestre : la dette `401` (commission due, passée à la
    remise) est soldée contre le compte de la plateforme `5313`. Idempotent par part.
    """
    from django.utils import timezone

    montant = Decimal(montant).quantize(CENTIME)
    if montant <= 0:
        return []
    reference = {"origine_type": "orders.SousCommande", "origine_id": sous_commande.pk}
    with contexte_boutique(sous_commande.boutique_id):
        if EcritureComptable.objects_all_tenants.filter(
            boutique_id=sous_commande.boutique_id,
            journal__code=Journal.OPERATIONS_DIVERSES,
            libelle__startswith="Commission compensée",
            **reference,
        ).exists():
            return []
        return [
            passer_ecriture(
                boutique_id=sous_commande.boutique_id,
                code_journal=Journal.OPERATIONS_DIVERSES,
                date_ecriture=date_ecriture or timezone.localdate(),
                libelle=f"Commission compensée {sous_commande.commande.numero}",
                lignes=[
                    (C_FOURNISSEURS, montant, Decimal("0")),
                    (C_COMPTE_PLATEFORME, Decimal("0"), montant),
                ],
                **reference,
            )
        ]


# Compte de trésorerie qui reçoit un versement, selon l'opérateur figé sur le versement.
COMPTE_DE_TRESORERIE = {
    "MTN_MOMO": C_MOMO_MTN,
    "ORANGE_MONEY": C_MOMO_ORANGE,
    "VIREMENT_BANCAIRE": C_BANQUE,
}


def comptabiliser_versement(versement, *, date_ecriture=None) -> list[EcritureComptable]:
    """Le versement exécuté : la créance sur la plateforme devient de la trésorerie.

    C'est l'écriture que `comptabiliser_vente_en_ligne` annonçait sans l'écrire, parce qu'aucun
    virement n'existait encore. Elle est passée **à l'exécution**, pas à la demande : tant que
    l'opérateur n'a pas donné sa référence, rien n'est arrivé sur le compte du marchand, et
    l'écrire plus tôt mettrait de la trésorerie fictive dans ses livres.
    """
    from django.utils import timezone

    compte = COMPTE_DE_TRESORERIE.get(versement.operateur)
    if compte is None:
        raise EcritureInvalide(
            f"Aucun compte de trésorerie n'est prévu pour l'opérateur {versement.operateur} : "
            "complétez le plan comptable avant d'ouvrir ce pays."
        )
    montant = Decimal(versement.montant).quantize(CENTIME)
    return [
        passer_ecriture(
            boutique_id=versement.boutique_id,
            code_journal=Journal.BANQUE,
            date_ecriture=date_ecriture or timezone.localdate(),
            libelle=f"Versement plateforme {versement.reference_operateur}"[:255],
            lignes=[
                (compte, montant, Decimal("0")),
                (C_COMPTE_PLATEFORME, Decimal("0"), montant),
            ],
            origine_type="payments.Versement",
            origine_id=versement.pk,
        )
    ]


def comptabiliser_expedition(sous_commande, *, date_ecriture=None) -> list[EcritureComptable]:
    """Sortie de stock d'une sous-commande expédiée, valorisée au CMP réellement appliqué.

    Écrite à l'expédition et non à la commande, parce que c'est à l'expédition que
    la marchandise quitte le dépôt. Une écriture de stock antérieure au mouvement
    qu'elle décrit ne serait pas rattrapable : le journal est en ajout seul.
    """
    with contexte_boutique(sous_commande.boutique_id):
        return _comptabiliser_expedition(sous_commande, date_ecriture=date_ecriture)


def _comptabiliser_expedition(sous_commande, *, date_ecriture=None) -> list[EcritureComptable]:
    from django.utils import timezone

    from apps.inventory.models import MouvementStock

    mouvements = MouvementStock.objects_all_tenants.filter(
        boutique_id=sous_commande.boutique_id,
        origine_type="orders.SousCommande",
        origine_id=sous_commande.pk,
    )
    cout = sum((abs(m.quantite) * m.cout_unitaire for m in mouvements), Decimal("0")).quantize(
        CENTIME
    )
    if cout <= 0:
        return []

    return [
        passer_ecriture(
            boutique_id=sous_commande.boutique_id,
            code_journal=Journal.STOCK,
            date_ecriture=date_ecriture or timezone.localdate(),
            libelle=f"Sortie de stock {sous_commande.commande.numero}",
            lignes=[
                (C_VARIATION_STOCKS, cout, Decimal("0")),
                (C_STOCK_MARCHANDISES, Decimal("0"), cout),
            ],
            origine_type="orders.SousCommande",
            origine_id=sous_commande.pk,
        )
    ]


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


def comptabiliser_reglement_cahier(reglement):
    """Écriture d'un paiement reçu sur le cahier de crédit d'un client (docs/22, §2.1).

    L'écriture est la plus simple du module, et c'est précisément ce qui la rend juste : la vente au
    cahier a **déjà** débité le 411 pour la totalité, au moment de la vente — `comptabiliser_ticket`
    saute les règlements à crédit en le disant (« la créance reste au 411 jusqu'au règlement »).

    Il ne reste donc qu'à solder cette créance quand l'argent arrive :

        débit   trésorerie (caisse, Mobile Money ou banque selon le moyen)
        crédit  411 Clients

    Rien d'autre. **Pas de produit** : la vente a été constatée en son temps, la reconstater ici
    doublerait le chiffre d'affaires — c'est l'erreur classique du rapprochement d'encaissements, et
    elle gonfle le résultat de tout ce qui a été vendu à crédit.

    **Aucun intérêt, aucune pénalité, aucun escompte.** Un cahier est une facilité de paiement ;
    facturer le temps en ferait une activité réglementée. Voir `apps/pos/cahier.py` et docs/08.
    """
    from django.utils import timezone

    from apps.pos.models import ReglementCahier

    if not isinstance(reglement, ReglementCahier):
        raise EcritureInvalide("comptabiliser_reglement_cahier attend un règlement de cahier.")

    comptes_par_moyen = {
        ReglementCahier.ESPECES: (Journal.CAISSE, C_CAISSE),
        ReglementCahier.MOBILE_MONEY: (Journal.BANQUE, C_MOMO_MTN),
        ReglementCahier.CARTE: (Journal.BANQUE, C_BANQUE),
    }
    try:
        code_journal, compte = comptes_par_moyen[reglement.moyen]
    except KeyError:
        raise EcritureInvalide(
            f"Moyen de règlement « {reglement.moyen} » sans compte de trésorerie associé."
        ) from None

    return passer_ecriture(
        boutique_id=reglement.boutique_id,
        code_journal=code_journal,
        date_ecriture=timezone.localdate(reglement.recu_le),
        libelle=f"Règlement cahier · {reglement.client.nom}",
        lignes=[
            (compte, reglement.montant, Decimal("0")),
            (C_CLIENTS, Decimal("0"), reglement.montant),
        ],
        origine_type="pos.ReglementCahier",
        origine_id=reglement.pk,
    )
