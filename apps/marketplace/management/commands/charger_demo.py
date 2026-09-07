"""Jeu de démonstration : deux boutiques de Douala, du stock, des ventes, une filiation.

Sert aux démonstrations commerciales et à la recette. Les données sont volontairement réalistes
(prix, assortiment, marges) : une démonstration avec des « Produit A » à 100 F ne convainc aucun
commerçant.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounting.referentiel import initialiser_boutique
from apps.accounts.models import Appartenance, Role, Utilisateur
from apps.affiliation.services import attribuer, creer_apporteur
from apps.catalog.models import Categorie, Produit, Variante
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import Depot
from apps.inventory.services import entrer_stock
from apps.marketplace.models import Bail, Boutique, Rayon, TypeEmplacement
from apps.pos import services as caisse

BOUTIQUES = [
    {
        "raison_sociale": "Ateba & Fils SARL",
        "enseigne": "Quincaillerie Ateba",
        "slug": "quincaillerie-ateba",
        "rayon": "quincaillerie",
        "offre": TypeEmplacement.BOUTIQUE,
        "rccm": "RC/DLA/2019/B/1842",
        "niu": "M031912345678A",
        "ville": "Douala",
        "gerant": ("+237699110011", "Jean-Pierre Ateba"),
        "produits": [
            ("QUI-CIM-50", "Ciment CIMENCAM 50 kg", "6500", "5200", 40),
            ("QUI-PEIN-20", "Peinture acrylique blanche 20 L", "28000", "21500", 12),
            ("QUI-TUB-PVC", "Tube PVC 110 mm — 3 m", "4800", "3600", 60),
            ("QUI-CAD-IND", "Cadenas industriel 60 mm", "3500", "2100", 25),
        ],
    },
    {
        "raison_sociale": "Ngo Bell Distribution SARL",
        "enseigne": "Bella Cosmétiques",
        "slug": "bella-cosmetiques",
        "rayon": "cosmetique-beaute",
        "offre": TypeEmplacement.GRANDE_SURFACE,
        "rccm": "RC/YAO/2021/B/0917",
        "niu": "M032187654321B",
        "ville": "Yaoundé",
        "gerant": ("+237677220022", "Élisabeth Ngo Bell"),
        "produits": [
            ("COS-KAR-500", "Beurre de karité brut 500 g", "4500", "2400", 120),
            ("COS-HUI-COC", "Huile de coco vierge 250 ml", "3200", "1600", 90),
            ("COS-SAV-NOI", "Savon noir africain 200 g", "1500", "700", 200),
            ("COS-CRE-VIS", "Crème hydratante visage 100 ml", "8900", "5100", 45),
        ],
    },
]


class Command(BaseCommand):
    help = "Charge un jeu de démonstration (boutiques, stock, ventes, affiliation)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reinitialiser",
            action="store_true",
            help="Supprime les boutiques de démonstration avant de recharger.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not Rayon.objects.exists():
            self.stderr.write(
                self.style.ERROR(
                    "Référentiels absents. Lancez d'abord : "
                    "python manage.py initialiser_referentiels"
                )
            )
            return

        if options["reinitialiser"]:
            Boutique.objects.filter(slug__in=[b["slug"] for b in BOUTIQUES]).delete()

        role_gerant = Role.objects.get(code=Role.GERANT)

        for donnees in BOUTIQUES:
            boutique = self._creer_boutique(donnees, role_gerant)
            self.stdout.write(self.style.SUCCESS(f"  {boutique.enseigne} ({boutique.ville})"))

        self._creer_reseau_affiliation()
        self.stdout.write(self.style.SUCCESS("Jeu de démonstration chargé."))

    def _creer_boutique(self, donnees, role_gerant) -> Boutique:
        telephone, nom = donnees["gerant"]
        gerant, cree = Utilisateur.objects.get_or_create(
            telephone=telephone, defaults={"nom_complet": nom, "telephone_verifie": True}
        )
        if cree:
            gerant.set_password("demo1234")
            gerant.save(update_fields=["password"])

        rayon = Rayon.objects.get(code=donnees["rayon"])
        offre = TypeEmplacement.objects.get(code=donnees["offre"])

        boutique, _ = Boutique.objects.get_or_create(
            slug=donnees["slug"],
            defaults={
                "raison_sociale": donnees["raison_sociale"],
                "enseigne": donnees["enseigne"],
                "rccm": donnees["rccm"],
                "niu": donnees["niu"],
                "ville": donnees["ville"],
                "rayon_principal": rayon,
                "etat": Boutique.ACTIVE,
                "regime_fiscal": Boutique.SIMPLIFIE,
            },
        )

        Bail.objects.get_or_create(
            boutique=boutique,
            type_emplacement=offre,
            defaults={
                "loyer_mensuel": offre.loyer_mensuel,
                "depot_garantie": offre.loyer_mensuel * 2,
                "taux_commission": rayon.taux_commission,
                "etat": Bail.ACTIF,
            },
        )

        Appartenance.objects.get_or_create(
            utilisateur=gerant, boutique=boutique, role=role_gerant
        )

        initialiser_boutique(boutique)

        with contexte_boutique(boutique):
            self._garnir_boutique(boutique, rayon, gerant, donnees["produits"])

        return boutique

    def _garnir_boutique(self, boutique, rayon, gerant, produits):
        categorie, _ = Categorie.objects.get_or_create(
            rayon=rayon,
            slug=f"general-{rayon.code}",
            defaults={"libelle": f"{rayon.libelle} — général"},
        )

        depot, _ = Depot.objects.get_or_create(
            boutique=boutique,
            libelle="Magasin principal",
            defaults={"type": Depot.BOUTIQUE, "principal": True},
        )

        variantes = []
        for sku, libelle, prix_ttc, cout, quantite in produits:
            produit, _ = Produit.objects.get_or_create(
                boutique=boutique,
                sku=sku,
                defaults={
                    "libelle": libelle,
                    "categorie": categorie,
                    "revente_autorisee": True,
                    "marge_revendeur": Decimal("0.10"),
                },
            )
            variante, cree = Variante.objects.get_or_create(
                boutique=boutique,
                sku=sku,
                defaults={"produit": produit, "prix_vente": Decimal(prix_ttc)},
            )
            if cree:
                entrer_stock(
                    depot=depot,
                    variante=variante,
                    quantite=Decimal(quantite),
                    cout_unitaire=Decimal(cout),
                    origine_type="demo",
                    commentaire="Stock initial (état des lieux d'entrée)",
                    cree_par=gerant,
                )
            variantes.append(variante)

        self._passer_une_vente(boutique, depot, gerant, variantes)

    def _passer_une_vente(self, boutique, depot, gerant, variantes):
        session = caisse.ouvrir_session(
            depot=depot, caissier=gerant, fonds_ouverture=Decimal("50000")
        )
        ticket = caisse.creer_ticket(session=session, client_nom="Client comptoir")
        caisse.ajouter_ligne(ticket=ticket, variante=variantes[0], quantite=Decimal("2"))
        caisse.ajouter_ligne(ticket=ticket, variante=variantes[1], quantite=Decimal("1"))
        ticket.refresh_from_db()
        caisse.regler(ticket=ticket, moyen="especes", montant=ticket.total_ttc)
        caisse.cloturer_ticket(ticket, cree_par=gerant)

    def _creer_reseau_affiliation(self):
        """Awa parraine Junior, Junior parraine Sandrine — la chaîne s'arrête à 2 niveaux."""
        profils = [
            ("+237690330033", "Awa Moussa"),
            ("+237690440044", "Junior Tchoumi"),
            ("+237690550055", "Sandrine Eyenga"),
        ]
        utilisateurs = []
        for telephone, nom in profils:
            utilisateur, cree = Utilisateur.objects.get_or_create(
                telephone=telephone, defaults={"nom_complet": nom}
            )
            if cree:
                utilisateur.set_password("demo1234")
                utilisateur.save(update_fields=["password"])
            utilisateurs.append(utilisateur)

        awa = creer_apporteur(utilisateurs[0])
        junior = creer_apporteur(utilisateurs[1], parrain=awa)
        sandrine = creer_apporteur(utilisateurs[2], parrain=junior)

        acheteur, cree = Utilisateur.objects.get_or_create(
            telephone="+237690660066", defaults={"nom_complet": "Client démonstration"}
        )
        if cree:
            acheteur.set_password("demo1234")
            acheteur.save(update_fields=["password"])

        from apps.affiliation.models import Attribution

        attribuer(
            apporteur=sandrine,
            cible_type=Attribution.ACHETEUR,
            cible_id=acheteur.pk,
            origine=Attribution.CODE,
            preuve={"saisi_le": timezone.now().isoformat()},
        )

        self.stdout.write(
            f"  filiation : {awa.code} → {junior.code} → {sandrine.code} "
            f"(N2 de Sandrine = {sandrine.parrain_n2.code if sandrine.parrain_n2 else '—'})"
        )
