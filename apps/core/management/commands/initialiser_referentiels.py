"""Charge les référentiels plateforme : rôles, rayons, offres, prestataires, plan comptable.

Chaque libellé a sa forme anglaise (`libelle_en`, `apps/core/bilingue.py`).

Idempotent : la commande peut être rejouée à chaque déploiement.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounting.referentiel import charger_plan_comptable
from apps.accounts.models import Role
from apps.accounts.permissions import droits_du_role
from apps.marketplace.models import Rayon, TypeEmplacement
from apps.payments.models import Prestataire

ROLES = [
    (Role.GERANT, "Gérant de boutique", "Shop manager", Role.BOUTIQUE),
    (Role.VENDEUR, "Vendeur", "Salesperson", Role.BOUTIQUE),
    (Role.CAISSIER, "Caissier", "Cashier", Role.BOUTIQUE),
    (Role.MAGASINIER, "Magasinier", "Storekeeper", Role.BOUTIQUE),
    (Role.COMPTABLE, "Comptable", "Accountant", Role.BOUTIQUE),
    (Role.RH, "Responsable RH", "HR manager", Role.BOUTIQUE),
    (Role.RESP_RAYON, "Responsable de rayon", "Aisle manager", Role.PLATEFORME),
    (Role.ADMIN_MARCHE, "Gestionnaire du marché", "Market manager", Role.PLATEFORME),
    (Role.CABINET, "Cabinet comptable partenaire", "Partner accounting firm", Role.PLATEFORME),
]

# Barème du docs/06, §4.3. Arbitrage A8 : l'alimentaire frais reste fermé jusqu'au lot 4.
RAYONS = [
    ("cosmetique-beaute", "Cosmétique & beauté", "Cosmetics & beauty", "0.0800", True, 10),
    ("mode-accessoires", "Mode & accessoires", "Fashion & accessories", "0.0800", True, 20),
    ("quincaillerie", "Quincaillerie & bricolage", "Hardware & DIY", "0.0600", True, 30),
    ("pieces-detachees", "Pièces détachées", "Spare parts", "0.0600", True, 40),
    ("maison-decoration", "Maison & décoration", "Home & decor", "0.0600", True, 50),
    ("petit-electronique", "Petit électronique", "Small electronics", "0.0400", True, 60),
    ("electromenager", "Électroménager", "Home appliances", "0.0300", True, 70),
    ("alimentaire", "Alimentaire", "Food", "0.0300", False, 80),
]

# Grille du docs/03, §1.1.
OFFRES = [
    (
        TypeEmplacement.ETAL,
        "Étal",
        "Stall",
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
        "Shop",
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
        "Superstore",
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
    (Prestataire.MTN_MOMO, "MTN Mobile Money", "MTN Mobile Money", "0.0160", ["67", "650", "651", "652", "653", "654"]),
    (Prestataire.ORANGE_MONEY, "Orange Money", "Orange Money", "0.0160", ["69", "655", "656", "657", "658", "659"]),
    (Prestataire.CAMTEL, "Camtel Blue Mobile Money", "Camtel Blue Mobile Money", "0.0150", ["62", "242"]),
    (Prestataire.CARTE, "Carte bancaire", "Bank card", "0.0280", []),
    (Prestataire.PAIEMENT_LIVRAISON, "Paiement à la livraison", "Cash on delivery", "0.0000", []),
]


class Command(BaseCommand):
    help = "Charge les référentiels plateforme (rôles, rayons, offres, prestataires, plan comptable)."

    @transaction.atomic
    def handle(self, *args, **options):
        for code, libelle, libelle_en, portee in ROLES:
            # `permissions` est un **miroir** de `apps.accounts.permissions` :
            # écrit ici pour que l'administration affiche ce qu'un rôle ouvre,
            # jamais relu pour décider. La décision reste en code — une table
            # modifiable à chaud n'a pas à pouvoir ouvrir la marge à un caissier.
            Role.objects.update_or_create(
                code=code,
                defaults={
                    "libelle": libelle,
                    "libelle_en": libelle_en,
                    "portee": portee,
                    "permissions": sorted(droits_du_role(code)),
                },
            )
        self.stdout.write(f"  {len(ROLES)} rôles")

        for code, libelle, libelle_en, taux, ouvert, ordre in RAYONS:
            Rayon.objects.update_or_create(
                code=code,
                defaults={
                    "libelle": libelle,
                    "libelle_en": libelle_en,
                    "taux_commission": Decimal(taux),
                    "ouvert": ouvert,
                    "ordre": ordre,
                },
            )
        self.stdout.write(f"  {len(RAYONS)} rayons")

        for code, libelle, libelle_en, loyer, taux, utilisateurs, depots, modules, ordre in OFFRES:
            TypeEmplacement.objects.update_or_create(
                code=code,
                defaults={
                    "libelle": libelle,
                    "libelle_en": libelle_en,
                    "loyer_mensuel": Decimal(loyer),
                    "taux_commission_defaut": Decimal(taux),
                    "quota_utilisateurs": utilisateurs,
                    "quota_depots": depots,
                    "modules_inclus": modules,
                    "ordre": ordre,
                },
            )
        self.stdout.write(f"  {len(OFFRES)} types d'emplacement")

        for code, libelle, libelle_en, frais, prefixes in PRESTATAIRES:
            Prestataire.objects.update_or_create(
                code=code,
                defaults={
                    "libelle": libelle,
                    "libelle_en": libelle_en,
                    "taux_frais": Decimal(frais),
                    "prefixes_numero": prefixes,
                },
            )
        self.stdout.write(f"  {len(PRESTATAIRES)} prestataires de paiement")

        plan = charger_plan_comptable()
        self.stdout.write(f"  plan comptable {plan.libelle} ({plan.comptes.count()} comptes)")

        self.stdout.write(self.style.SUCCESS("Référentiels chargés."))
