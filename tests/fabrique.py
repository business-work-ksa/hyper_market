"""Fabriques de données pour les tests.

Les fabriques de données scopées posent elles-mêmes le contexte de la boutique
qu'elles peuplent. Ce n'est pas une commodité : depuis la barrière 3, une
insertion faite dans le mauvais contexte est **rejetée par PostgreSQL**, et un
test qui prépare deux boutiques doit dire à chaque ligne à laquelle elle
appartient. Autant que la fabrique s'en charge — c'est du code de test, pas du
code de production, et l'isolation reste prouvée par les tests dédiés.
"""

from decimal import Decimal

from apps.accounting.referentiel import initialiser_boutique
from apps.accounts.models import Utilisateur
from apps.catalog.models import Produit, Variante
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import Depot
from apps.marketplace.models import Bail, Boutique, Rayon, TypeEmplacement

_compteur = {"n": 0}


def _suivant() -> int:
    _compteur["n"] += 1
    return _compteur["n"]


def creer_utilisateur(nom="Testeur", telephone=None) -> Utilisateur:
    return Utilisateur.objects.create_user(
        telephone=telephone or f"+2376991{_suivant():05d}",
        password="motdepasse",
        nom_complet=nom,
    )


def creer_rayon(taux="0.0500") -> Rayon:
    n = _suivant()
    return Rayon.objects.create(
        code=f"rayon-{n}", libelle=f"Rayon {n}", taux_commission=Decimal(taux)
    )


def creer_offre(*, quota_depots=1) -> TypeEmplacement:
    return TypeEmplacement.objects.create(
        code=f"OFFRE_{_suivant()}",
        libelle="Boutique",
        loyer_mensuel=Decimal("45000"),
        taux_commission_defaut=Decimal("0.0500"),
        quota_depots=quota_depots,
    )


def creer_boutique(enseigne=None, *, avec_comptabilite=True, quota_depots=1) -> Boutique:
    n = _suivant()
    enseigne = enseigne or f"Boutique {n}"
    boutique = Boutique.objects.create(
        raison_sociale=f"{enseigne} SARL",
        enseigne=enseigne,
        slug=f"boutique-{n}",
        rayon_principal=creer_rayon(),
        etat=Boutique.ACTIVE,
    )
    offre = creer_offre(quota_depots=quota_depots)
    Bail.objects.create(
        boutique=boutique,
        type_emplacement=offre,
        loyer_mensuel=offre.loyer_mensuel,
        taux_commission=offre.taux_commission_defaut,
        etat=Bail.ACTIF,
    )
    if avec_comptabilite:
        initialiser_boutique(boutique)
    return boutique


def creer_depot(boutique, libelle="Magasin", *, principal=True) -> Depot:
    with contexte_boutique(boutique):
        return creer_depot_sans_contexte(boutique, libelle, principal=principal)


def creer_depot_sans_contexte(boutique, libelle="Magasin", *, principal=True) -> Depot:
    """Insertion volontairement non contextualisée, pour éprouver la barrière 3."""
    return Depot.objects.create(
        boutique=boutique,
        libelle=libelle,
        type=Depot.BOUTIQUE if principal else Depot.RESERVE,
        principal=principal,
    )


def creer_variante(boutique, *, prix="11925", sku=None) -> Variante:
    n = _suivant()
    sku = sku or f"SKU-{n}"
    with contexte_boutique(boutique):
        produit = Produit.objects.create(
            boutique=boutique, sku=sku, libelle=f"Produit {n}"
        )
        return Variante.objects.create(
            boutique=boutique, produit=produit, sku=sku, prix_vente=Decimal(prix)
        )
