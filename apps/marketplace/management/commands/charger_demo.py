"""Jeu de démonstration : six boutiques de Douala et Yaoundé, du stock, des ventes, une filiation.

Sert aux démonstrations commerciales et à la recette. Les données sont volontairement réalistes
(prix, assortiment, marges) : une démonstration avec des « Produit A » à 100 F ne convainc aucun
commerçant.

Chaque métier représenté l'est pour une raison : la pharmacie est le seul endroit
où les lots, les péremptions et l'ordonnancier se vérifient à l'écran ; la
boulangerie le seul où l'on fabrique ; les pièces détachées le seul où l'on
cherche par la voiture du client ; l'électronique le seul où un appareil se suit
exemplaire par exemplaire, avec sa garantie et son atelier.
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

# Identifiants du jeu de démonstration, nommés une fois. La page de connexion les
# affiche (`AFFICHER_COMPTE_DEMO`) et doit pouvoir **vérifier qu'ils existent** avant
# de les promettre : recopier « demo1234 » à quatre endroits garantissait qu'ils
# divergeraient le jour où l'un changerait.
TELEPHONE_DEMO = "+237699110011"
MOT_DE_PASSE_DEMO = "demo1234"

BOUTIQUES = [
    {
        "raison_sociale": "Ateba & Fils SARL",
        "enseigne": "Quincaillerie Ateba",
        "slug": "quincaillerie-ateba",
        "metier": "QUINCAILLERIE",
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
        "metier": "COSMETIQUE",
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
    {
        # Une pharmacie dans le jeu de démonstration n'est pas un décor : c'est
        # le seul métier où le suivi des lots et des péremptions se voit
        # réellement à l'écran, et donc le seul où l'on peut vérifier qu'il
        # fonctionne sans lire le code.
        "raison_sociale": "Officine du Wouri SARL",
        "enseigne": "Pharmacie du Wouri",
        "slug": "pharmacie-du-wouri",
        "metier": "PHARMACIE",
        "rayon": "cosmetique-beaute",
        "offre": TypeEmplacement.BOUTIQUE,
        "rccm": "RC/DLA/2022/B/3310",
        "niu": "M032298765432C",
        "ville": "Douala",
        "gerant": ("+237655330011", "Dr Estelle Manga"),
        "equipe": [("+237655330022", "Cédric Ondoa", Role.VENDEUR)],
        "reserve": None,
        # Les péremptions sont exprimées en jours à partir d'aujourd'hui : le jeu
        # de démonstration doit montrer un périmé et un « bientôt » quel que soit
        # le jour où on le charge.
        "produits": [
            ("PHA-PARA-500", "Paracétamol 500 mg — boîte de 20", "600", "380", 420, 60, "L24A118", 240),
            ("PHA-AMOX-1G", "Amoxicilline 1 g — boîte de 12", "3200", "2100", 180, 30, "L24B072", 18),
            ("PHA-SERU-PH", "Sérum physiologique 5 ml — 20 doses", "1500", "900", 260, 40, "L23K455", -6),
            ("PHA-IBUP-400", "Ibuprofène 400 mg — boîte de 20", "900", "540", 300, 45, "L25C201", 400),
            ("PHA-VITC-1G", "Vitamine C 1 g — 10 comprimés", "1200", "700", 210, 35, "L24D019", 25),
            # Deuxième paracétamol, sous une autre marque : sans lui, la DCI
            # n'aurait personne à rapprocher, et l'écran des équivalents
            # n'afficherait jamais que « aucun équivalent en rayon ».
            ("PHA-EFFE-500", "Efferalgan 500 mg — 16 comprimés", "1800", "1150", 90, 15, "L24E077", 300),
        ],
        # (sku, nature, désignation, employée par)
        # La DCI est ce qui rapproche deux boîtes différentes ; le nom commercial
        # est ce qui permet de retrouver la même boîte quand le client la demande
        # par la marque qu'il connaît. Les deux sont saisis ici pour que la
        # distinction se vérifie à l'écran : chercher « Doliprane » trouve une
        # boîte, chercher « paracétamol » en trouve deux, et les équivalents de
        # l'une citent l'autre.
        "designations": [
            ("PHA-PARA-500", "dci", "Paracétamol 500 mg", "OMS"),
            ("PHA-PARA-500", "commercial", "Doliprane 500 mg", "Sanofi"),
            ("PHA-EFFE-500", "dci", "Paracétamol 500 mg", "OMS"),
            ("PHA-AMOX-1G", "dci", "Amoxicilline 1 g", "OMS"),
            # Sans confrère en rayon : c'est le cas qui montre qu'une DCI saisie
            # ne fabrique pas un équivalent de complaisance.
            ("PHA-IBUP-400", "dci", "Ibuprofène 400 mg", "OMS"),
        ],
        # Un antibiotique ne se délivre pas sans ordonnance, et ne se vend pas
        # en ligne. Le marquer ici est ce qui rend l'ordonnancier et le retrait
        # de la vitrine vérifiables sans lire le code.
        "sur_ordonnance": ["PHA-AMOX-1G"],
    },
    {
        # Une boulangerie non plus n'est pas un décor : c'est le seul métier du
        # jeu où l'on **fabrique**, et donc le seul où l'écran de production, le
        # coût de revient et les invendus se vérifient sans lire le code.
        "raison_sociale": "Fournil de Bonapriso SARL",
        "enseigne": "Boulangerie Bonapriso",
        "slug": "boulangerie-bonapriso",
        "metier": "BOULANGERIE",
        "rayon": "alimentaire",
        "offre": TypeEmplacement.BOUTIQUE,
        "rccm": "RC/DLA/2020/B/2471",
        "niu": "M032011223344D",
        "ville": "Douala",
        "gerant": ("+237691440011", "Rachel Mbappé"),
        "equipe": [("+237691440022", "Ibrahim Sali", Role.VENDEUR)],
        "reserve": None,
        # Matières premières et produits finis entrent tous à l'état des lieux :
        # une boulangerie qui installe le logiciel un mardi a du pain en rayon,
        # et il vaut ce qu'il a coûté à cuire. Ce qui change ensuite, c'est que
        # le pain se **refait** — les fournées ci-dessous — quand la farine, elle,
        # se rachète.
        "produits": [
            ("BOU-FAR-T55", "Farine de blé T55 — sac de 50 kg", "32000", "26000", 40, 8),
            ("BOU-LEV-1KG", "Levure boulangère — 1 kg", "4500", "3200", 25, 5),
            ("BOU-SEL-25", "Sel fin — sac de 25 kg", "6000", "4200", 12, 3),
            ("BOU-BEU-1KG", "Beurre de tourage — 1 kg", "7500", "5600", 30, 6),
            ("BOU-BAG-250", "Baguette 250 g", "150", "102", 900, 60),
            ("BOU-CRO-BEU", "Croissant au beurre", "300", "141", 400, 40),
        ],
        # (produit fini, rendement, jours de conservation, [(ingrédient, quantité)])
        # Les quantités sont exprimées dans l'unité d'achat : la farine s'achète
        # au sac, une fournée de 40 baguettes en consomme 0,15.
        "fiches": [
            (
                "BOU-BAG-250", "40", 2,
                [("BOU-FAR-T55", "0.15"), ("BOU-LEV-1KG", "0.05"), ("BOU-SEL-25", "0.008")],
            ),
            (
                "BOU-CRO-BEU", "60", 2,
                [("BOU-FAR-T55", "0.06"), ("BOU-BEU-1KG", "1.2"), ("BOU-LEV-1KG", "0.05")],
            ),
        ],
        # Fournées du matin, pour que l'écran ne s'ouvre pas sur du vide.
        "productions": [("BOU-BAG-250", "120"), ("BOU-CRO-BEU", "60")],
    },
    {
        # Même raison que la pharmacie et la boulangerie : c'est le seul métier
        # du jeu où l'on cherche une pièce par la voiture du client, et donc le
        # seul endroit où cette recherche se vérifie sans lire le code.
        "raison_sociale": "Ndokoti Auto Pièces SARL",
        "enseigne": "Auto Pièces Ndokoti",
        "slug": "auto-pieces-ndokoti",
        "metier": "PIECES_AUTO",
        "rayon": "pieces-detachees",
        "offre": TypeEmplacement.BOUTIQUE,
        "rccm": "RC/DLA/2018/B/0994",
        "niu": "M031855667788E",
        "ville": "Douala",
        "gerant": ("+237677550011", "Blaise Nkoulou"),
        "equipe": [("+237677550022", "Aline Tchoumi", Role.VENDEUR)],
        "reserve": "Réserve Ndokoti",
        "produits": [
            ("PAU-FIL-HUI", "Filtre à huile", "3500", "2100", 140, 20),
            ("PAU-PLA-AVA", "Plaquettes de frein avant — jeu", "18500", "13000", 60, 10),
            ("PAU-FIL-AIR", "Filtre à air", "4800", "2900", 95, 15),
            ("PAU-AMO-ARR", "Amortisseur arrière", "34000", "25000", 24, 4),
            ("PAU-HUI-15W40", "Huile moteur 15W40 — bidon 5 L", "12500", "9200", 180, 25),
            # Même filtre, autre fabricant : sans lui, la référence croisée
            # n'aurait personne à rapprocher. C'est aussi le cas réel du
            # comptoir — l'origine à 3 500, l'adaptable à 2 200.
            ("PAU-FIL-HUI-AD", "Filtre à huile adaptable", "2200", "1300", 60, 10),
        ],
        # (sku, nature, désignation, employée par)
        # Le client pose un carton sur le comptoir et lit ce qui est écrit
        # dessus : « W 68/3 ». Sans ces lignes, la boutique a la pièce en rayon
        # et le vendeur ne la trouve pas.
        "designations": [
            ("PAU-FIL-HUI", "reference", "W 68/3", "Mann"),
            ("PAU-FIL-HUI", "reference", "OC 195", "Knecht"),
            ("PAU-FIL-HUI-AD", "reference", "W 68/3", "Mann"),
            ("PAU-FIL-AIR", "reference", "C 26 168", "Mann"),
        ],
        # (sku, référence constructeur, [(marque, modèle, motorisation, de, à)])
        # Les vides sont volontaires : un vendeur sait « ça va sur les Hilux », il
        # ne sait presque jamais en quelle année la pièce a changé.
        "vehicules": [
            ("PAU-FIL-HUI", "90915-YZZD4", [
                ("Toyota", "Corolla", "1.4 D-4D", 2007, 2018),
                ("Toyota", "Yaris", "", 2006, None),
                ("Toyota", "Hilux", "", None, None),
            ]),
            ("PAU-PLA-AVA", "04465-0K090", [
                ("Toyota", "Hilux", "", 2005, 2015),
                ("Toyota", "Fortuner", "", 2005, 2015),
            ]),
            ("PAU-FIL-AIR", "17801-0C010", [
                ("Toyota", "Hilux", "2.5 D-4D", 2005, 2015),
                ("Nissan", "Navara", "", 2005, 2014),
            ]),
            ("PAU-AMO-ARR", "", [
                ("Nissan", "Navara", "", 2005, 2014),
            ]),
            # Une huile va sur tout : aucune borne, aucun modèle. C'est
            # exactement le cas que la recherche ne doit pas faire disparaître.
            ("PAU-HUI-15W40", "", [("Toyota", "", "", None, None), ("Nissan", "", "", None, None)]),
        ],
    },
    {
        # Même raison que les trois précédentes : c'est le seul métier du jeu où
        # un appareil se suit exemplaire par exemplaire. Sans cette boutique, la
        # garantie, l'atelier et la recherche par IMEI ne se vérifient qu'en
        # lisant le code.
        "raison_sociale": "Nkolo Télécom SARL",
        "enseigne": "Nkolo Électronique",
        "slug": "nkolo-electronique",
        "metier": "ELECTRONIQUE",
        "rayon": "petit-electronique",
        "offre": TypeEmplacement.BOUTIQUE,
        "rccm": "RC/DLA/2021/B/5127",
        "niu": "M032166778899F",
        "ville": "Douala",
        "gerant": ("+237698660011", "Armand Nkolo"),
        "equipe": [("+237698660022", "Chantal Mvondo", Role.VENDEUR)],
        "reserve": None,
        "produits": [
            ("ELE-TEL-128", "Téléphone 128 Go — double SIM", "185000", "148000", 5, 2),
            ("ELE-TEL-64", "Téléphone 64 Go — double SIM", "119000", "92000", 4, 2),
            ("ELE-TEL-REC", "Téléphone reconditionné 64 Go", "62000", "44000", 3, 1),
            ("ELE-ORD-15", "Ordinateur portable 15 pouces", "425000", "352000", 3, 1),
            ("ELE-CHA-25W", "Chargeur rapide 25 W", "6500", "3400", 140, 20),
            ("ELE-ECO-BLU", "Écouteurs sans fil", "12500", "7200", 85, 15),
            ("ELE-CAR-64", "Carte mémoire 64 Go", "7500", "4300", 120, 20),
        ],
        # (sku, garantie en mois, numéros reçus)
        # Les accessoires n'y sont pas : un chargeur n'a pas de numéro de série,
        # et en réclamer un à chaque réception ferait abandonner le suivi. Le
        # téléphone reconditionné, lui, est garanti un mois — c'est l'usage, et
        # c'est ce qui met une garantie expirée dans le jeu sans antidater une
        # vente hors de l'exercice comptable.
        "appareils": [
            ("ELE-TEL-128", 12, [
                "356938035643809", "356938035643810", "356938035643811",
                "356938035643812", "356938035643813",
            ]),
            # Trois numéros pour quatre téléphones en stock : l'écart est
            # **voulu**. C'est la livraison saisie un jour de presse, sans
            # relever le dernier IMEI — le cas que l'écran de garantie doit
            # savoir montrer, et qu'un jeu de démonstration parfait cacherait.
            ("ELE-TEL-64", 12, [
                "351756051523999", "351756051524000", "351756051524001",
            ]),
            ("ELE-TEL-REC", 1, [
                "862011048873210", "862011048873211", "862011048873212",
            ]),
            ("ELE-ORD-15", 24, ["5CD9482KJ7", "5CD9482KJ8", "5CD9482KJ9"]),
        ],
        # (sku, numéro, jours de recul, nom du client)
        "ventes_appareils": [
            ("ELE-TEL-128", "356938035643809", 9, "Marthe Ngo Bisseck"),
            ("ELE-TEL-128", "356938035643810", 3, "Serge Owona"),
            ("ELE-ORD-15", "5CD9482KJ7", 12, "Cabinet Mballa & Associés"),
            # Vendu il y a six semaines avec un mois de garantie : échue, et
            # l'écran doit le dire sans ambiguïté au client qui revient.
            ("ELE-TEL-REC", "862011048873210", 44, "Patrick Essomba"),
        ],
        # (numéro, motif, jours de recul, rendu ou non)
        "atelier": [
            ("356938035643809", "Ne charge plus — nappe de charge suspectée", 2, False),
            ("862011048873210", "Écran fissuré, tactile mort en bas", 20, True),
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
        parser.add_argument(
            "--jours",
            type=int,
            default=JOURS_HISTORIQUE,
            help=(
                "Jours de ventes simulées (défaut : %(default)s). Le volume est un "
                "paramètre parce qu'il décide du temps de chargement : contre une base "
                "gratuite au CPU bridé, vingt jours peuvent dépasser le délai maximal "
                "d'une construction sans serveur, et une démonstration qu'on ne peut pas "
                "charger ne démontre rien. Voir docs/20, §2 bis."
            ),
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

        self._jours = max(0, options["jours"])

        if options["reinitialiser"] and not self._reinitialiser():
            return

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

        boutiques = []
        for donnees in BOUTIQUES:
            boutique = self._creer_boutique(donnees, role_gerant)
            boutiques.append(boutique)
            self.stdout.write(self.style.SUCCESS(f"  {boutique.enseigne} ({boutique.ville})"))

        acheteur = self._creer_reseau_affiliation()
        self._creer_commandes_en_ligne(boutiques, acheteur)
        self.stdout.write(self.style.SUCCESS("Jeu de démonstration chargé."))

    def _reinitialiser(self) -> bool:
        """Efface les boutiques de démonstration, **si c'est encore possible**.

        Ce n'est pas toujours le cas, et le refus est une bonne nouvelle : une
        boutique qui a vendu porte des **écritures comptables validées**, que le
        trigger d'ajout seul refuse de supprimer (ADR-003). C'est exactement ce
        qu'on lui demande de faire, et le contourner ici — désactiver le trigger,
        supprimer, le remettre — reviendrait à livrer dans le dépôt l'outil qui
        sait effacer un journal comptable.

        Sur une base de développement, la remise à zéro se fait donc au niveau de
        la base, pas de l'application.
        """
        from django.db.models import ProtectedError

        from apps.core.tenancy import contexte_plateforme

        slugs = [b["slug"] for b in BOUTIQUES]
        cibles = list(Boutique.objects.filter(slug__in=slugs))
        if not cibles:
            return True

        # Le contexte plateforme est indispensable ici : `objects_all_tenants` ne
        # contourne que le gestionnaire, pas les politiques d'isolation. Sans
        # lui, ce contrôle ne verrait aucune écriture et conclurait à tort que la
        # suppression est possible.
        with contexte_plateforme():
            validees = EcritureComptable.objects_all_tenants.filter(
                boutique__in=cibles, validee=True
            ).exists()

        if validees:
            self.stderr.write(
                self.style.ERROR(
                    "Ces boutiques de démonstration ont un journal comptable validé : "
                    "il est en ajout seul et ne se supprime pas."
                )
            )
            self.stderr.write(
                "Pour repartir de zéro en développement, recréez la base :\n"
                "  docker compose down -v && docker compose up -d db\n"
                "  make migrer && make demo"
            )
            return False

        # Le bail protège sa boutique : c'est un contrat, il ne disparaît pas
        # parce qu'on efface le locataire. Il part donc explicitement, d'abord.
        try:
            with contexte_plateforme():
                Bail.objects.filter(boutique__in=cibles).delete()
                Boutique.objects.filter(slug__in=slugs).delete()
        except ProtectedError as erreur:
            self.stderr.write(
                self.style.ERROR(f"Suppression impossible : {erreur.args[0]}")
            )
            self.stderr.write(
                "Ces boutiques portent des données que le modèle protège. "
                "Recréez la base plutôt que de forcer :\n"
                "  docker compose down -v && docker compose up -d db\n"
                "  make migrer && make demo"
            )
            return False
        return True

    def _creer_boutique(self, donnees, role_gerant) -> Boutique:
        telephone, nom = donnees["gerant"]
        gerant, cree = Utilisateur.objects.get_or_create(
            telephone=telephone, defaults={"nom_complet": nom, "telephone_verifie": True}
        )
        if cree:
            gerant.set_password(MOT_DE_PASSE_DEMO)
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
                "metier": donnees.get("metier", "COMMERCE_GENERAL"),
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
                employe.set_password(MOT_DE_PASSE_DEMO)
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

        # Les métiers qui suivent les péremptions apportent deux colonnes de
        # plus : le numéro de lot et l'échéance, en jours à partir d'aujourd'hui.
        metier = boutique.metier_choisi
        variantes = []
        for ligne in produits:
            sku, libelle, prix_ttc, cout, quantite, seuil = ligne[:6]
            numero_lot, jours = (ligne[6], ligne[7]) if len(ligne) > 6 else ("", None)
            peremption = (
                timezone.localdate() + timedelta(days=jours) if jours is not None else None
            )
            produit, _ = Produit.objects.get_or_create(
                boutique=boutique,
                sku=sku,
                defaults={
                    "libelle": libelle,
                    "categorie": categorie,
                    "unite": metier.unite_defaut,
                    "regime_tva": metier.regime_tva_defaut,
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
                # Une quantité nulle ne produit pas de mouvement : un article
                # peut légitimement entrer au catalogue sans stock, et un
                # mouvement de zéro serait refusé par le moteur — à raison.
                if Decimal(quantite) > 0:
                    entrer_stock(
                        depot=depot,
                        variante=variante,
                        quantite=Decimal(quantite),
                        cout_unitaire=Decimal(cout),
                        origine_type="demo",
                        commentaire="Stock initial (état des lieux d'entrée)",
                        cree_par=gerant,
                        date_peremption=peremption,
                        numero_lot=numero_lot,
                    )
            variantes.append(variante)

        self._marquer_les_ordonnances(boutique, variantes, donnees)
        self._nommer_autrement(boutique, gerant, variantes, donnees)
        self._declarer_les_vehicules(boutique, gerant, variantes, donnees)
        suivis = self._suivre_les_appareils(boutique, depot, gerant, variantes, donnees)

        # Les fiches et les fournées viennent **avant** l'historique de ventes :
        # on ne vend pas des baguettes qui n'ont pas été cuites.
        ingredients = self._composer_les_fiches(boutique, depot, gerant, variantes, donnees)

        # Une matière première ne passe pas en caisse. Un boulanger ne vend pas
        # son sac de farine au comptoir, et l'y faire passer creuserait un stock
        # négatif qui ne raconterait rien — sinon que le jeu de démonstration
        # ignore ce qu'est un ingrédient.
        #
        # Un appareil suivi à l'unité en est écarté pour une raison voisine : le
        # tirage aléatoire de l'historique vendrait des téléphones sans leur
        # IMEI, et laisserait des exemplaires « en stock » qui ne sont plus là.
        # Ces ventes-là sont écrites nommément, plus bas.
        au_comptoir = [v for v in variantes if v.pk not in ingredients and v.pk not in suivis]
        self._generer_historique(boutique, depot, gerant, au_comptoir)
        self._consigner_quelques_ordonnances(boutique)
        self._vendre_quelques_appareils(boutique, depot, gerant, variantes, donnees)
        self._creer_etats_de_stock(depot, gerant, au_comptoir)
        self._ouvrir_reserve(boutique, depot, gerant, variantes, donnees.get("reserve"))

    def _marquer_les_ordonnances(self, boutique, variantes, donnees) -> None:
        """Médicaments délivrés sur ordonnance. Inerte ailleurs."""
        skus = set(donnees.get("sur_ordonnance") or [])
        if not skus:
            return
        Produit.objects.filter(boutique=boutique, sku__in=skus).update(sur_ordonnance=True)

        # Et sur les objets déjà en mémoire : l'historique de ventes qui suit lit
        # `variante.produit.sur_ordonnance` pour figer le drapeau sur la ligne de
        # ticket. Un `UPDATE` en base ne rafraîchit pas un objet Python déjà
        # chargé, et l'ordonnancier de démonstration serait resté vide sans que
        # rien ne le signale.
        for variante in variantes:
            if variante.sku in skus:
                variante.produit.sur_ordonnance = True

    def _consigner_quelques_ordonnances(self, boutique) -> None:
        """Consigne le registre, **sauf les deux dernières délivrances**.

        Un ordonnancier de démonstration entièrement rempli ne montrerait pas le
        cas qui compte : celui où il reste quelque chose à faire. Deux lignes en
        attente, c'est ce qu'un pharmacien trouve un lundi matin.
        """
        from apps.pos.services import consigner_ordonnance, delivrances_sur_ordonnance

        delivrances = list(delivrances_sur_ordonnance())
        for numero, ticket in enumerate(delivrances[2:], start=1):
            consigner_ordonnance(
                ticket,
                mention=f"Dr Manga — ordonnance n° {numero:03d}",
            )

    def _nommer_autrement(self, boutique, gerant, variantes, donnees) -> None:
        """Désignations alternatives : DCI en officine, références croisées en pièces.

        Inerte ailleurs : la clé `designations` est absente et rien n'est écrit.

        Aucune paire d'équivalents n'est déclarée, et c'est tout l'intérêt : les
        deux paracétamols se rapprochent parce qu'ils portent la même DCI, pas
        parce que quelqu'un a écrit qu'ils se ressemblent.
        """
        from apps.catalog.models import Designation

        lignes = donnees.get("designations") or []
        if not lignes:
            return

        par_sku = {v.sku: v for v in variantes}
        for sku, type_designation, valeur, source in lignes:
            Designation.objects.get_or_create(
                boutique=boutique,
                variante=par_sku[sku],
                type=type_designation,
                valeur=Designation.normaliser(valeur),
                defaults={"source": source, "cree_par": gerant},
            )

    def _declarer_les_vehicules(self, boutique, gerant, variantes, donnees) -> None:
        """Références constructeur et compatibilités, pour les pièces détachées.

        Inerte ailleurs : la clé `vehicules` est absente et rien n'est écrit.
        """
        from apps.catalog.models import CompatibiliteVehicule

        lignes = donnees.get("vehicules") or []
        if not lignes:
            return

        par_sku = {v.sku: v for v in variantes}
        for sku, reference, compatibilites in lignes:
            variante = par_sku[sku]
            if reference and not variante.reference_constructeur:
                Variante.objects.filter(pk=variante.pk).update(reference_constructeur=reference)
            for marque, modele, motorisation, debut, fin in compatibilites:
                CompatibiliteVehicule.objects.get_or_create(
                    boutique=boutique,
                    variante=variante,
                    marque=marque,
                    modele=modele,
                    motorisation=motorisation,
                    annee_debut=debut,
                    annee_fin=fin,
                    defaults={"cree_par": gerant},
                )

    def _suivre_les_appareils(self, boutique, depot, gerant, variantes, donnees) -> set:
        """Marque les articles suivis à l'unité et nomme les exemplaires reçus.

        Inerte ailleurs : la clé `appareils` est absente et rien n'est écrit.
        Renvoie les variantes suivies, que l'historique de ventes doit éviter.
        """
        from apps.inventory import series

        lignes = donnees.get("appareils") or []
        if not lignes:
            return set()

        par_sku = {v.sku: v for v in variantes}
        suivis = set()
        for sku, garantie, numeros in lignes:
            variante = par_sku[sku]
            Variante.objects.filter(pk=variante.pk).update(
                suivi_unitaire=True, garantie_mois=garantie
            )
            # Et sur l'objet en mémoire : `declarer` refuse un article qui n'est
            # pas suivi, et un `UPDATE` ne rafraîchit pas un objet déjà chargé.
            variante.suivi_unitaire = True
            variante.garantie_mois = garantie

            series.declarer(
                depot=depot,
                variante=variante,
                numeros=numeros,
                # Reçus avant d'être vendus, sinon l'écran de garantie
                # afficherait un appareil vendu six semaines avant son arrivée —
                # une incohérence qu'un commerçant remarque tout de suite.
                recu_le=self._recul(60).date(),
                cree_par=gerant,
                commentaire="Réception à l'installation",
            )
            suivis.add(variante.pk)
        return suivis

    def _vendre_quelques_appareils(self, boutique, depot, gerant, variantes, donnees) -> None:
        """Ventes nommées d'appareils, puis leurs passages à l'atelier.

        Écrites une par une plutôt que tirées au sort : chacune illustre un cas
        que l'écran de garantie doit savoir dire — sous garantie, échue, en
        réparation. Un tirage aléatoire ne garantirait aucun des trois.
        """
        from apps.inventory import series

        ventes = donnees.get("ventes_appareils") or []
        if not ventes:
            return

        par_sku = {v.sku: v for v in variantes}
        session = caisse.ouvrir_session(
            depot=depot, caissier=gerant, fonds_ouverture=Decimal("50000")
        )

        for sku, numero, recul, client in ventes:
            horodatage = self._recul(recul)
            ticket, _ = caisse.encaisser(
                session=session,
                lignes=[(par_sku[sku], Decimal("1"), Decimal("0"), [numero])],
                moyen="especes",
                client_nom=client,
                encaisse_le=horodatage,
                cree_par=gerant,
            )
            self._antidater(ticket, horodatage)

        for numero, motif, recul, rendu in donnees.get("atelier") or []:
            exemplaire = series.rechercher(numero)
            if exemplaire is None:
                continue
            passage = series.entrer_a_l_atelier(exemplaire, motif=motif, cree_par=gerant)
            from apps.inventory.models import PassageAtelier

            PassageAtelier.objects.filter(pk=passage.pk).update(entre_le=self._recul(recul))
            if rendu:
                series.sortir_de_l_atelier(exemplaire, resultat="Écran remplacé, testé au comptoir")

    @staticmethod
    def _recul(jours: int):
        """Horodatage à `jours` en arrière, sans sortir de l'exercice comptable.

        Le plan comptable d'une boutique ouvre un exercice sur l'année civile
        courante (`apps/accounting/referentiel.py`). Une vente antidatée avant le
        1er janvier n'aurait aucun exercice pour la recevoir, et le chargement
        échouerait — un jour de janvier seulement, ce qui est la pire façon de
        découvrir un défaut.
        """
        jour = max(
            timezone.localdate() - timedelta(days=jours),
            timezone.localdate().replace(month=1, day=1),
        )
        return timezone.make_aware(datetime.combine(jour, dtime(11, 30)))

    def _composer_les_fiches(self, boutique, depot, gerant, variantes, donnees) -> set:
        """Fiches techniques et fournées du matin, pour les métiers qui fabriquent.

        Rien n'est écrit ici pour les autres : la clé `fiches` est absente, la
        méthode ne fait rien, et une quincaillerie de démonstration reste une
        quincaillerie.

        Renvoie les variantes qui servent d'ingrédient : l'appelant s'en sert
        pour les tenir hors des ventes comptoir.
        """
        from apps.catalog.models import LigneRecette, Recette
        from apps.inventory.services import produire

        fiches = donnees.get("fiches") or []
        if not fiches:
            return set()

        par_sku = {v.sku: v for v in variantes}
        utilises = {
            par_sku[sku_ingredient].pk
            for _, _, _, ingredients in fiches
            for sku_ingredient, _quantite in ingredients
        }
        recettes = {}
        for sku, rendement, conservation, ingredients in fiches:
            recette, cree = Recette.objects.get_or_create(
                boutique=boutique,
                variante=par_sku[sku],
                defaults={
                    "rendement": Decimal(rendement),
                    "duree_conservation_jours": conservation,
                    "cree_par": gerant,
                },
            )
            recettes[sku] = recette
            if not cree:
                continue
            for sku_ingredient, quantite in ingredients:
                LigneRecette.objects.create(
                    boutique=boutique,
                    recette=recette,
                    ingredient=par_sku[sku_ingredient],
                    quantite=Decimal(quantite),
                    cree_par=gerant,
                )

        for sku, quantite in donnees.get("productions") or []:
            produire(
                depot=depot,
                recette=recettes[sku],
                quantite=Decimal(quantite),
                commentaire="Fournée du matin",
                cree_par=gerant,
            )
        return utilises

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

        for recul in range(self._jours, -1, -1):
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
                utilisateur.set_password(MOT_DE_PASSE_DEMO)
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
        return acheteur

    def _creer_commandes_en_ligne(self, boutiques, acheteur):
        """Trois commandes, à trois étapes différentes du traitement.

        Une démonstration qui ne montre que des commandes fraîches ne dit rien du
        travail réel : l'intérêt de l'écran est justement de séparer ce qui
        attend d'être accepté de ce qui est déjà en route. La commande
        multi-boutiques est là pour rendre l'éclatement visible — un panier, deux
        marchands, deux parts indépendantes.
        """
        from apps.orders.models import SousCommande
        from apps.orders.services import (
            accepter,
            expedier,
            marquer_payee,
            passer_commande,
            preparer,
        )

        articles = {}
        for boutique in boutiques:
            with contexte_boutique(boutique):
                articles[boutique.pk] = list(
                    Variante.objects.filter(actif=True).order_by("sku")[:2]
                )

        premiere = boutiques[0]
        paniers = [
            [(articles[premiere.pk][0], Decimal("2"))],
            [(articles[premiere.pk][1], Decimal("1"))],
        ]
        if len(boutiques) > 1:
            seconde = boutiques[1]
            paniers.append(
                [
                    (articles[premiere.pk][0], Decimal("1")),
                    (articles[seconde.pk][0], Decimal("3")),
                ]
            )

        # Nombre de gestes déjà accomplis sur la part de la première boutique :
        # une commande à accepter, une à préparer, une à expédier.
        for panier, gestes in zip(paniers, [0, 1, 2]):
            # Aucun code n'est passé : l'acheteur de démonstration porte déjà une
            # attribution à Sandrine, posée juste au-dessus. Les commissions
            # d'affiliation naissent donc seules, au paiement.
            commande = passer_commande(acheteur=acheteur, lignes=panier)
            marquer_payee(commande)

            with contexte_boutique(premiere):
                part = SousCommande.objects.filter(commande=commande).first()
            if part is None:
                continue
            for avancer in (accepter, preparer, expedier)[:gestes]:
                avancer(part)

        self.stdout.write("  3 commandes en ligne, à trois étapes du traitement")
