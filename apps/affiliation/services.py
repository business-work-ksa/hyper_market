"""Moteur de commissions d'affiliation.

Trois invariants, testés automatiquement (docs/06, §4.1) :

1. aucune rémunération d'affiliation ne s'ajoute au prix payé par l'acheteur ;
2. le cumul des reversements **financés par la plateforme** (N1 + N2) ne dépasse jamais 35 % de la
   commission plateforme sur une transaction donnée ;
3. une commission n'existe que sur du **chiffre d'affaires encaissé** et sorti du délai de retour.

Deux sources de financement, à ne pas confondre — c'est ce qui rend le plafond calculable :

* **apporteurs N1 et N2** : payés sur la commission de la plateforme. Assiette = commission
  plateforme. C'est à eux, et à eux seuls, que s'applique le plafond de 35 %.
* **revendeur** : payé sur la marge du marchand, que le marchand fixe lui-même produit par produit
  (`Produit.marge_revendeur`). Assiette = montant HT vendu. Son plafond est celui que le marchand
  a consenti ; il ne consomme pas la commission de la plateforme.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.affiliation.models import Apporteur, Attribution, Commission, Revendeur
from django.utils.translation import gettext as _

__all__ = [
    "CommissionInvalide",
    "creer_apporteur",
    "attribuer",
    "resoudre_apporteurs",
    "calculer_commissions",
    "acquerir_commissions",
    "annuler_commissions",
]

CENTIME = Decimal("0.01")


def _reglage(cle: str) -> Decimal:
    return Decimal(settings.AFFILIATION[cle])


class CommissionInvalide(ValueError):
    """Calcul refusé : plafond dépassé, sous-commande non livrée, assiette négative."""


def creer_apporteur(utilisateur, *, parrain: Apporteur | None = None) -> Apporteur:
    """Ouvre un compte d'apporteur. Gratuit, sans droit d'entrée ni achat obligatoire."""
    apporteur, _ = Apporteur.objects.get_or_create(
        utilisateur=utilisateur, defaults={"code": utilisateur.code_apporteur}
    )
    if parrain is not None:
        apporteur.rattacher(parrain)
    return apporteur


def attribuer(*, apporteur: Apporteur, cible_type: str, cible_id, origine: str, preuve=None) -> Attribution:
    """Rattache une cible à un apporteur pour la fenêtre d'attribution.

    Le rattachement est **définitif** : une attribution existante n'est jamais écrasée par un
    apporteur ultérieur (protection contre le vol d'attribution, docs/06, §6).
    """
    existante = Attribution.objects.filter(cible_type=cible_type, cible_id=cible_id).first()
    if existante is not None:
        return existante

    jours = int(settings.AFFILIATION["FENETRE_ATTRIBUTION_JOURS"])
    debut = timezone.now()
    return Attribution.objects.create(
        apporteur=apporteur,
        cible_type=cible_type,
        cible_id=cible_id,
        origine=origine,
        debut=debut,
        fin=debut + timedelta(days=jours),
        preuve=preuve or {},
    )


def resoudre_apporteurs(acheteur) -> tuple[Apporteur | None, Apporteur | None]:
    """Retourne (N1, N2) pour un acheteur, ou (None, None) si aucune attribution valide."""
    attribution = Attribution.objects.filter(
        cible_type=Attribution.ACHETEUR, cible_id=acheteur.pk
    ).select_related("apporteur", "apporteur__parrain_n1").first()

    if attribution is None or not attribution.valide:
        return None, None

    n1 = attribution.apporteur
    if n1.etat != Apporteur.ACTIF:
        return None, None

    n2 = n1.parrain_n1
    if n2 is not None and n2.etat != Apporteur.ACTIF:
        n2 = None
    return n1, n2


@transaction.atomic
def calculer_commissions(sous_commande) -> list[Commission]:
    """Calcule les commissions d'une sous-commande, à l'état `attendue`.

    Deux calculs distincts, parce que les deux rémunérations n'ont ni la même assiette ni la même
    source de financement (voir l'en-tête du module).
    """
    commande = sous_commande.commande
    commissions = []
    commissions += _commissions_apporteurs(sous_commande, commande)
    commissions += _commission_revendeur(sous_commande, commande)
    return commissions


def _commissions_apporteurs(sous_commande, commande) -> list[Commission]:
    """Parts N1 et N2, prélevées sur la commission de la plateforme et plafonnées à 35 %."""
    assiette = Decimal(sous_commande.commission_plateforme)
    if assiette <= 0:
        return []

    plafond = (assiette * _reglage("PLAFOND_REVERSEMENT")).quantize(CENTIME)

    candidats: list[tuple[object, str, Decimal]] = []
    if commande.apporteur_n1_id:
        candidats.append((commande.apporteur_n1.utilisateur, Commission.N1, _reglage("PART_N1")))
    if commande.apporteur_n2_id:
        candidats.append((commande.apporteur_n2.utilisateur, Commission.N2, _reglage("PART_N2")))

    commissions = []
    cumul = Decimal("0")
    for beneficiaire, role, taux in candidats:
        montant = (assiette * taux).quantize(CENTIME)

        # Invariant 2 : le plafond porte sur le cumul, pas sur chaque part prise isolément.
        # Le premier apporteur servi est donc prioritaire — c'est le parrain direct, celui qui a
        # réellement amené la vente.
        if cumul + montant > plafond:
            montant = (plafond - cumul).quantize(CENTIME)
        if montant <= 0:
            continue

        commission, cree = Commission.objects.get_or_create(
            sous_commande=sous_commande,
            beneficiaire=beneficiaire,
            role=role,
            defaults={
                "assiette": assiette,
                "taux": taux,
                "montant": montant,
                "etat": Commission.ATTENDUE,
            },
        )
        cumul += commission.montant
        if cree:
            commissions.append(commission)

    if cumul > plafond:  # pragma: no cover — garde-fou : ne doit jamais se produire
        raise CommissionInvalide(
            _('Cumul de commissions apporteurs %(cumul)s supérieur au plafond (%(plafond)s).') % {"cumul": cumul, "plafond": plafond}
        )

    return commissions


def _commission_revendeur(sous_commande, commande) -> list[Commission]:
    """Marge du revendeur, prélevée sur la marge du marchand.

    Elle ne consomme pas la commission de la plateforme et n'entre donc pas dans le plafond de
    35 %. Son propre plafond est la marge que le marchand a consentie produit par produit.
    """
    if not commande.revendeur_id:
        return []

    from apps.affiliation.models import CatalogueRevendeur
    from apps.orders.models import LigneCommande

    revendeur: Revendeur = commande.revendeur
    lignes = LigneCommande.objects_all_tenants.filter(
        sous_commande=sous_commande
    ).select_related("variante")

    montant = Decimal("0")
    for ligne in lignes:
        entree = CatalogueRevendeur.objects.filter(
            revendeur=revendeur, variante=ligne.variante, actif=True
        ).first()
        if entree is not None:
            montant += ligne.total_ht * entree.marge

    montant = montant.quantize(CENTIME)
    assiette = Decimal(sous_commande.total_ht)
    if montant <= 0 or assiette <= 0:
        return []

    taux = (montant / assiette).quantize(Decimal("0.0001"))
    commission, cree = Commission.objects.get_or_create(
        sous_commande=sous_commande,
        beneficiaire=revendeur.utilisateur,
        role=Commission.REVENDEUR,
        defaults={
            "assiette": assiette,
            "taux": taux,
            "montant": montant,
            "etat": Commission.ATTENDUE,
        },
    )
    return [commission] if cree else []


@transaction.atomic
def acquerir_commissions(sous_commande, *, maintenant=None) -> int:
    """Passe les commissions de `attendue` à `acquise` après le délai de retour.

    Invariant 3 : rien n'est acquis avant l'expiration du délai, même si la livraison est
    confirmée — c'est la fenêtre pendant laquelle une commande fictive se révèle.
    """
    maintenant = maintenant or timezone.now()
    if sous_commande.livree_le is None:
        raise CommissionInvalide(_("La sous-commande n'est pas livrée."))

    delai = timedelta(days=int(settings.AFFILIATION["DELAI_RETOUR_JOURS"]))
    if maintenant < sous_commande.livree_le + delai:
        return 0

    return Commission.objects.filter(
        sous_commande=sous_commande, etat=Commission.ATTENDUE
    ).update(etat=Commission.ACQUISE, acquise_le=maintenant)


@transaction.atomic
def annuler_commissions(sous_commande, *, motif: str = "") -> int:
    """Annule les commissions d'une sous-commande retournée, annulée ou impayée.

    Une commission déjà payée ne peut plus être annulée : elle est **reprise** sur les gains
    futurs du bénéficiaire (docs/06, §4.2).
    """
    non_payees = Commission.objects.filter(
        sous_commande=sous_commande,
        etat__in=[Commission.ATTENDUE, Commission.ACQUISE, Commission.PAYABLE],
    ).update(etat=Commission.ANNULEE)

    deja_payees = Commission.objects.filter(
        sous_commande=sous_commande, etat=Commission.PAYEE
    ).update(etat=Commission.REPRISE)

    return non_payees + deja_payees
