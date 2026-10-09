"""Référentiel SYSCOHADA révisé et initialisation comptable d'une boutique.

Extrait de travail du plan comptable, limité aux comptes réellement mouvementés par les
automatismes du lot 1 (docs/07, §2.2). Le plan complet sera chargé depuis un fichier de
référence au lot 3, après validation par le cabinet partenaire.
"""

from datetime import date

from django.db import transaction

from apps.accounting.models import (
    CompteBoutique,
    CompteGeneral,
    Exercice,
    Journal,
    PlanComptable,
)
from apps.core.tenancy import contexte_boutique

CODE_PLAN = "SYSCOHADA_REVISE"

ACTIF = CompteGeneral.ACTIF
PASSIF = CompteGeneral.PASSIF
CHARGE = CompteGeneral.CHARGE
PRODUIT = CompteGeneral.PRODUIT

# (numéro, intitulé, classe, type, collectif)
COMPTES = [
    # Classe 1 — Ressources durables
    ("101", "Capital social", 1, PASSIF, False),
    ("120", "Report à nouveau", 1, PASSIF, False),
    ("130", "Résultat net de l'exercice", 1, PASSIF, False),
    # Classe 2 — Actif immobilisé
    ("2441", "Matériel de bureau et informatique", 2, ACTIF, False),
    ("2445", "Matériel et mobilier de magasin", 2, ACTIF, False),
    # Classe 3 — Stocks
    ("311", "Marchandises", 3, ACTIF, False),
    # Classe 4 — Tiers
    ("401", "Fournisseurs, dettes en compte", 4, PASSIF, True),
    ("411", "Clients", 4, ACTIF, True),
    ("422", "Personnel, rémunérations dues", 4, PASSIF, False),
    ("431", "Sécurité sociale (CNPS)", 4, PASSIF, False),
    ("4431", "État, TVA facturée sur ventes", 4, PASSIF, False),
    ("4441", "État, TVA due", 4, PASSIF, False),
    ("4452", "État, TVA récupérable sur achats", 4, ACTIF, False),
    ("447", "État, impôts retenus à la source", 4, PASSIF, False),
    # Classe 5 — Trésorerie
    ("5211", "Banque", 5, ACTIF, False),
    ("5311", "Monnaie électronique — MTN MoMo", 5, ACTIF, False),
    ("5312", "Monnaie électronique — Orange Money", 5, ACTIF, False),
    ("5313", "Compte plateforme HyperMarché", 5, ACTIF, False),
    ("571", "Caisse siège social", 5, ACTIF, False),
    # Classe 6 — Charges
    ("6011", "Achats de marchandises", 6, CHARGE, False),
    ("6031", "Variation des stocks de marchandises", 6, CHARGE, False),
    ("622", "Locations et charges locatives", 6, CHARGE, False),
    ("632", "Rémunérations d'intermédiaires et de conseils", 6, CHARGE, False),
    ("659", "Charges provisionnées d'exploitation", 6, CHARGE, False),
    ("661", "Rémunérations directes versées au personnel", 6, CHARGE, False),
    ("664", "Charges sociales patronales", 6, CHARGE, False),
    # Classe 7 — Produits
    ("701", "Ventes de marchandises", 7, PRODUIT, False),
    ("706", "Services vendus", 7, PRODUIT, False),
]

JOURNAUX = [
    (Journal.VENTES, "Journal des ventes"),
    (Journal.ACHATS, "Journal des achats"),
    (Journal.BANQUE, "Journal de banque"),
    (Journal.CAISSE, "Journal de caisse"),
    (Journal.PAIE, "Journal de paie"),
    (Journal.STOCK, "Journal des stocks"),
    (Journal.OPERATIONS_DIVERSES, "Opérations diverses"),
]


@transaction.atomic
def charger_plan_comptable() -> PlanComptable:
    """Charge le référentiel plateforme. Idempotent."""
    plan, _ = PlanComptable.objects.update_or_create(
        code=CODE_PLAN,
        defaults={"libelle": "SYSCOHADA révisé", "version": "2018"},
    )
    for numero, intitule, classe, type_compte, collectif in COMPTES:
        CompteGeneral.objects.update_or_create(
            plan=plan,
            numero=numero,
            defaults={
                "intitule": intitule,
                "classe": classe,
                "type": type_compte,
                "collectif": collectif,
            },
        )
    return plan


@transaction.atomic
def initialiser_boutique(boutique, *, annee: int | None = None) -> Exercice:
    """Dote une boutique de son plan de comptes, de ses journaux et d'un exercice ouvert.

    Appelée à l'activation du bail, en même temps que l'état des lieux d'entrée. Idempotent :
    on peut la rejouer sans dupliquer ni écraser.

    Le corps s'exécute dans le contexte de la boutique dotée : `objects_all_tenants` contourne le
    gestionnaire, jamais la base, et les politiques de sécurité au niveau ligne refuseraient ces
    écritures sans contexte déclaré (`apps/core/rls.py`).
    """
    plan = charger_plan_comptable()

    with contexte_boutique(boutique):
        for compte_modele in CompteGeneral.objects.filter(plan=plan):
            CompteBoutique.objects_all_tenants.get_or_create(
                boutique=boutique,
                numero=compte_modele.numero,
                defaults={
                    "intitule": compte_modele.intitule,
                    "type": compte_modele.type,
                    "compte_modele": compte_modele,
                },
            )

        for code, libelle in JOURNAUX:
            Journal.objects_all_tenants.get_or_create(
                boutique=boutique, code=code, defaults={"libelle": libelle}
            )

        annee = annee or date.today().year
        exercice, _ = Exercice.objects_all_tenants.get_or_create(
            boutique=boutique,
            debut=date(annee, 1, 1),
            defaults={"fin": date(annee, 12, 31)},
        )
    return exercice
