"""Charge les référentiels plateforme : rôles, rayons, offres, prestataires, plan comptable.

Idempotent : la commande peut être rejouée à chaque déploiement.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounting.referentiel import charger_plan_comptable
from apps.accounts.models import Role
from apps.marketplace.models import Rayon, TypeEmplacement
from apps.payments.models import Prestataire

ROLES = [
    (Role.GERANT, "Gérant de boutique", Role.BOUTIQUE),
    (Role.VENDEUR, "Vendeur", Role.BOUTIQUE),
    (Role.CAISSIER, "Caissier", Role.BOUTIQUE),
    (Role.MAGASINIER, "Magasinier", Role.BOUTIQUE),
    (Role.COMPTABLE, "Comptable", Role.BOUTIQUE),
    (Role.RH, "Responsable RH", Role.BOUTIQUE),
    (Role.RESP_RAYON, "Responsable de rayon", Role.PLATEFORME),
    (Role.ADMIN_MARCHE, "Gestionnaire du marché", Role.PLATEFORME),
    (Role.CABINET, "Cabinet comptable partenaire", Role.PLATEFORME),
]

# Barème du docs/06, §4.3. Arbitrage A8 : l'alimentaire frais reste fermé jusqu'au lot 4.
RAYONS = [
    ("cosmetique-beaute", "Cosmétique & beauté", "0.0800", True, 10),
    ("mode-accessoires", "Mode & accessoires", "0.0800", True, 20),
    ("quincaillerie", "Quincaillerie & bricolage", "0.0600", True, 30),
    ("pieces-detachees", "Pièces détachées", "0.0600", True, 40),
    ("maison-decoration", "Maison & décoration", "0.0600", True, 50),
    ("petit-electronique", "Petit électronique", "0.0400", True, 60),
    ("electromenager", "Électroménager", "0.0300", True, 70),
    ("alimentaire", "Alimentaire", "0.0300", False, 80),
]

# Grille du docs/03, §1.1.
OFFRES = [
    (
        TypeEmplacement.ETAL,
        "Étal",
        "15000",
        "0.0800",
        1,
        1,
        ["catalogue", "stock", "caisse"],
        10,
    ),
    (
        TypeEmplacement.BOUTIQUE,
        "Boutique",
        "45000",
        "0.0500",
        5,
        3,
        ["catalogue", "stock", "caisse", "comptabilite", "statistiques"],
        20,
    ),
    (
        TypeEmplacement.GRANDE_SURFACE,
        "Grande surface",
        "120000",
        "0.0300",
        20,
        10,
        ["catalogue", "stock", "caisse", "comptabilite", "statistiques", "paie", "api", "b2b"],
        30,
    ),
]

# Aucune dépendance à un opérateur unique : le routage bascule par préfixe (docs/02, §3.3).
PRESTATAIRES = [
    (Prestataire.MTN_MOMO, "MTN Mobile Money", "0.0160", ["67", "650", "651", "652", "653", "654"]),
    (Prestataire.ORANGE_MONEY, "Orange Money", "0.0160", ["69", "655", "656", "657", "658", "659"]),
    (Prestataire.CAMTEL, "Camtel Blue Mobile Money", "0.0150", ["62", "242"]),
    (Prestataire.CARTE, "Carte bancaire", "0.0280", []),
    (Prestataire.PAIEMENT_LIVRAISON, "Paiement à la livraison", "0.0000", []),
]


class Command(BaseCommand):
    help = "Charge les référentiels plateforme (rôles, rayons, offres, prestataires, plan comptable)."

    @transaction.atomic
    def handle(self, *args, **options):
        for code, libelle, portee in ROLES:
            Role.objects.update_or_create(
                code=code, defaults={"libelle": libelle, "portee": portee}
            )
        self.stdout.write(f"  {len(ROLES)} rôles")

        for code, libelle, taux, ouvert, ordre in RAYONS:
            Rayon.objects.update_or_create(
                code=code,
                defaults={
                    "libelle": libelle,
                    "taux_commission": Decimal(taux),
                    "ouvert": ouvert,
                    "ordre": ordre,
                },
            )
        self.stdout.write(f"  {len(RAYONS)} rayons")

        for code, libelle, loyer, taux, utilisateurs, depots, modules, ordre in OFFRES:
            TypeEmplacement.objects.update_or_create(
                code=code,
                defaults={
                    "libelle": libelle,
                    "loyer_mensuel": Decimal(loyer),
                    "taux_commission_defaut": Decimal(taux),
                    "quota_utilisateurs": utilisateurs,
                    "quota_depots": depots,
                    "modules_inclus": modules,
                    "ordre": ordre,
                },
            )
        self.stdout.write(f"  {len(OFFRES)} types d'emplacement")

        for code, libelle, frais, prefixes in PRESTATAIRES:
            Prestataire.objects.update_or_create(
                code=code,
                defaults={
                    "libelle": libelle,
                    "taux_frais": Decimal(frais),
                    "prefixes_numero": prefixes,
                },
            )
        self.stdout.write(f"  {len(PRESTATAIRES)} prestataires de paiement")

        plan = charger_plan_comptable()
        self.stdout.write(f"  plan comptable {plan.libelle} ({plan.comptes.count()} comptes)")

        self.stdout.write(self.style.SUCCESS("Référentiels chargés."))
