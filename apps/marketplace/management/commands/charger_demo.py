"""Jeu de démonstration : deux boutiques de Douala, du stock, des ventes, une filiation.

Sert aux démonstrations commerciales et à la recette. Les données sont volontairement réalistes
(prix, assortiment, marges) : une démonstration avec des « Produit A » à 100 F ne convainc aucun
commerçant.
"""

import random
from datetime import datetime
from datetime import time as dtime
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounting.referentiel import initialiser_boutique
from apps.accounts.models import Appartenance, Role, Utilisateur
from apps.affiliation.services import attribuer, creer_apporteur
from apps.catalog.models import Categorie, Produit, Variante
from apps.core.tenancy import contexte_boutique
from apps.accounting.models import EcritureComptable
from apps.inventory.models import Depot, MouvementStock, NiveauStock
from apps.inventory.services import enregistrer_mouvement, entrer_stock, transferer_stock
from apps.marketplace.models import Bail, Boutique, Rayon, TypeEmplacement
from apps.payments.models import Prestataire
from apps.pos import services as caisse
from apps.pos.models import Ticket

JOURS_HISTORIQUE = 20

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
        # Une équipe aux rôles distincts : c'est ce qui rend visible le fait que
        # tout le monde ne voit pas la même chose (apps/accounts/permissions.py).
        "equipe": [
            ("+237699110022", "Marie Ekedi", Role.CAISSIER),
            ("+237699110033", "Salomon Bidzogo", Role.MAGASINIER),
        ],
        "reserve": "Réserve Bonabéri",
        "produits": [
            # (sku, libellé, prix TTC, coût, quantité initiale, seuil d'alerte)
            ("QUI-CIM-50", "Ciment CIMENCAM 50 kg", "6500", "5200", 900, 120),
            ("QUI-PEIN-20", "Peinture acrylique blanche 20 L", "28000", "21500", 260, 45),
            ("QUI-TUB-PVC", "Tube PVC 110 mm — 3 m", "4800", "3600", 640, 90),
            ("QUI-CAD-IND", "Cadenas industriel 60 mm", "3500", "2100", 410, 60),
            ("QUI-BRO-ELE", "Brouette galvanisée renforcée", "34500", "26000", 180, 30),
            ("QUI-FER-12", "Fer à béton 12 mm — barre 12 m", "9800", "7400", 520, 80),
            ("QUI-DIS-230", "Disque à tronçonner 230 mm", "2200", "1250", 700, 100),
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
        "equipe": [("+237677220033", "Nadège Fotso", Role.COMPTABLE)],
        "reserve": None,
        "produits": [
            ("COS-KAR-500", "Beurre de karité brut 500 g", "4500", "2400", 820, 110),
            ("COS-HUI-COC", "Huile de coco vierge 250 ml", "3200", "1600", 760, 100),
            ("COS-SAV-NOI", "Savon noir africain 200 g", "1500", "700", 980, 140),
            ("COS-CRE-VIS", "Crème hydratante visage 100 ml", "8900", "5100", 340, 50),
            ("COS-HUI-ARG", "Huile d'argan pressée à froid 100 ml", "12500", "7900", 280, 40),
            ("COS-MAS-ARG", "Masque à l'argile verte 150 g", "3800", "2050", 520, 70),
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

        # Prestataire simulé : réservé aux démonstrations. Il n'est pas chargé par
        # `initialiser_referentiels` — un faux prestataire n'a rien à faire dans
        # les référentiels d'une plateforme qui encaisse de l'argent réel.
        Prestataire.objects.update_or_create(
            code=Prestataire.FAUX,
            defaults={
                "libelle": "Prestataire simulé (démonstration)",
                "taux_frais": Decimal("0.0160"),
                "prefixes_numero": [],
            },
        )

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
                "regime_fiscal": Boutique.REEL_SIMPLIFIE,
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
        self._creer_equipe(boutique, donnees.get("equipe") or [])

        initialiser_boutique(boutique)

        with contexte_boutique(boutique):
            self._garnir_boutique(boutique, rayon, gerant, donnees)

        return boutique

    def _creer_equipe(self, boutique, equipe):
        for telephone, nom, code_role in equipe:
            employe, cree = Utilisateur.objects.get_or_create(
                telephone=telephone, defaults={"nom_complet": nom, "telephone_verifie": True}
            )
            if cree:
                employe.set_password("demo1234")
                employe.save(update_fields=["password"])
            Appartenance.objects.get_or_create(
                utilisateur=employe,
                boutique=boutique,
                role=Role.objects.get(code=code_role),
            )

    def _garnir_boutique(self, boutique, rayon, gerant, donnees):
        produits = donnees["produits"]
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
        for sku, libelle, prix_ttc, cout, quantite, seuil in produits:
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
                NiveauStock.objects.create(
                    boutique=boutique, depot=depot, variante=variante, seuil_alerte=Decimal(seuil)
                )
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

        self._generer_historique(boutique, depot, gerant, variantes)
        self._creer_etats_de_stock(depot, gerant, variantes)
        self._ouvrir_reserve(boutique, depot, gerant, variantes, donnees.get("reserve"))

    def _ouvrir_reserve(self, boutique, principal, gerant, variantes, libelle):
        """Second dépôt et transferts, pour que le multi-dépôts soit visible.

        Une quincaillerie tient rarement tout son ciment derrière le comptoir :
        la réserve est le cas normal, pas une option de configuration.
        """
        if not libelle:
            return

        reserve, cree = Depot.objects.get_or_create(
            boutique=boutique,
            libelle=libelle,
            defaults={"type": Depot.RESERVE, "principal": False},
        )
        if not cree:
            return

        for variante in variantes[:3]:
            niveau = NiveauStock.objects.filter(depot=principal, variante=variante).first()
            if niveau is None or niveau.quantite <= 10:
                continue
            transferer_stock(
                depot_source=principal,
                depot_cible=reserve,
                variante=variante,
                quantite=(niveau.quantite / 3).quantize(Decimal("1")),
                origine_type="demo",
                commentaire="Mise en réserve à l'installation",
                cree_par=gerant,
            )

    def _generer_historique(self, boutique, depot, gerant, variantes):
        """Vingt jours de ventes comptoir, pour que le tableau de bord ait du sens.

        Le tirage est déterministe (graine fixe) : deux exécutions produisent le
        même jeu, ce qui rend les captures d'écran et les démonstrations
        reproductibles.
        """
        alea = random.Random(f"hypermarche-{boutique.slug}")
        vendables = [v for v in variantes if v.niveaux.filter(quantite__gt=0).exists()]
        if not vendables:
            return

        session = caisse.ouvrir_session(
            depot=depot, caissier=gerant, fonds_ouverture=Decimal("50000")
        )
        moyens = ["especes"] * 6 + ["mobile_money"] * 3 + ["carte"]
        aujourdhui = timezone.localdate()

        for recul in range(JOURS_HISTORIQUE, -1, -1):
            jour = aujourdhui - timedelta(days=recul)
            # Les dimanches sont creux, les samedis chargés : une courbe plate
            # ne ressemble à aucun commerce réel.
            if jour.weekday() == 6:
                nb_tickets = alea.randint(0, 2)
            elif jour.weekday() == 5:
                nb_tickets = alea.randint(5, 9)
            else:
                nb_tickets = alea.randint(2, 6)

            for _ in range(nb_tickets):
                horodatage = timezone.make_aware(
                    datetime.combine(jour, dtime(alea.randint(8, 18), alea.randint(0, 59)))
                )
                ticket = caisse.creer_ticket(session=session)
                for variante in alea.sample(vendables, alea.randint(1, min(3, len(vendables)))):
                    caisse.ajouter_ligne(
                        ticket=ticket, variante=variante, quantite=Decimal(alea.randint(1, 3))
                    )
                ticket.refresh_from_db()
                if ticket.total_ttc <= 0:
                    continue
                caisse.regler(ticket=ticket, moyen=alea.choice(moyens), montant=ticket.total_ttc)
                # La date de clôture est **déclarée avant** la comptabilisation :
                # elle devient la date des écritures, et le journal en ajout seul
                # refuse ensuite de la déplacer. Antidater après coup ne marchait
                # que sur SQLite, faute de trigger.
                caisse.cloturer_ticket(ticket, cree_par=gerant, cloture_le=horodatage)
                self._antidater(ticket, horodatage)

    def _creer_etats_de_stock(self, depot, gerant, variantes):
        """Met en scène les trois états du stock, par ajustement d'inventaire.

        Un jeu de démonstration où tout est vert ne montre pas ce que le produit
        sert à voir. On provoque donc deux alertes et une rupture — non pas en
        truquant les compteurs, mais en passant de vrais mouvements
        d'ajustement, comme le ferait un inventaire physique.
        """
        cibles = variantes[-3:]
        if len(cibles) < 3:
            return

        scenarios = [
            (cibles[0], Decimal("0.55"), "Écart d'inventaire — casse non déclarée"),
            (cibles[1], Decimal("0.70"), "Écart d'inventaire — comptage du mois"),
            (cibles[2], None, "Rupture constatée à l'inventaire"),
        ]

        for variante, part_du_seuil, motif in scenarios:
            niveau = NiveauStock.objects.get(depot=depot, variante=variante)
            cible = Decimal("0") if part_du_seuil is None else (
                niveau.seuil_alerte * part_du_seuil
            ).quantize(Decimal("1"))
            ecart = cible - niveau.quantite
            if ecart == 0:
                continue
            enregistrer_mouvement(
                depot=depot,
                variante=variante,
                type_mouvement=MouvementStock.AJUSTEMENT,
                quantite=ecart,
                origine_type="demo",
                commentaire=motif,
                cree_par=gerant,
            )

    @staticmethod
    def _antidater(ticket, horodatage):
        """Repositionne les horodatages techniques dans le passé.

        `cree_le` est posé automatiquement par `auto_now_add` : seul un `update()`
        peut le corriger. On ne touche **que** cet horodatage technique.

        La date comptable, elle, n'est pas corrigeable : le trigger du journal
        refuse de déplacer une écriture validée dans le temps, et il a raison.
        Elle est donc déclarée à la clôture du ticket, avant que la
        comptabilisation ne s'exécute.
        """
        Ticket.objects_all_tenants.filter(pk=ticket.pk).update(cree_le=horodatage)
        MouvementStock.objects_all_tenants.filter(
            origine_type="pos.Ticket", origine_id=ticket.pk
        ).update(cree_le=horodatage)
        EcritureComptable.objects_all_tenants.filter(
            origine_type="pos.Ticket", origine_id=ticket.pk
        ).update(cree_le=horodatage)

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
