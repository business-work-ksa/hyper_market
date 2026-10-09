"""Multi-dépôts et mouvements de stock hors ligne.

Deux manques que le modèle ne connaissait pas mais que l'interface imposait :

1. **Le dépôt était toujours le principal.** Une réserve et un comptoir ont des
   stocks différents ; un comptage fait dans la mauvaise réserve produit des
   écarts inventés de toutes pièces, et une vente sortait la marchandise du
   mauvais endroit.
2. **Seules les ventes survivaient à une coupure.** Une réception saisie pendant
   la panne était perdue — et le camion, lui, était bien reparti.
"""

import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import MouvementStock, NiveauStock
from apps.inventory.services import entrer_stock
from apps.pos.models import SessionCaisse, Ticket
from tests import fabrique
from tests.test_permissions import rattacher


class DepotCourantTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boutique = fabrique.creer_boutique("Deux dépôts", quota_depots=3)
        with contexte_boutique(cls.boutique):
            cls.comptoir = fabrique.creer_depot(cls.boutique, "Comptoir")
            cls.reserve = fabrique.creer_depot(cls.boutique, "Réserve", principal=False)
            cls.variante = fabrique.creer_variante(cls.boutique, sku="DEP-1", prix="2000")
            entrer_stock(
                depot=cls.comptoir, variante=cls.variante, quantite=10, cout_unitaire=Decimal("800")
            )
            entrer_stock(
                depot=cls.reserve, variante=cls.variante, quantite=90, cout_unitaire=Decimal("750")
            )

        cls.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(cls.gerant, cls.boutique, Role.GERANT)

    def setUp(self):
        self.client.force_login(self.gerant)

    def _basculer(self, depot):
        return self.client.post(
            reverse("choisir_depot"), {"depot": str(depot.pk), "suite": reverse("stock")}
        )

    def test_le_depot_principal_est_choisi_par_defaut(self):
        reponse = self.client.get(reverse("stock"))
        self.assertEqual(reponse.context["depot_courant"], self.comptoir)

    def test_le_selecteur_n_apparait_qu_a_partir_de_deux_depots(self):
        """Un commerçant qui n'a qu'un dépôt n'a pas à choisir entre une option.

        Le filtre vit désormais dans la boîte de filtres de la liste : c'est le
        champ du formulaire qui existe ou non, pas un `<select>` grisé.
        """
        reponse = self.client.get(reverse("stock"))
        self.assertIn("depot", reponse.context["filtres"].fields)

        seule = fabrique.creer_boutique("Un seul dépôt")
        with contexte_boutique(seule):
            fabrique.creer_depot(seule)
        solo = fabrique.creer_utilisateur("Gérant solo")
        rattacher(solo, seule, Role.GERANT)

        self.client.force_login(solo)
        self.assertNotIn("depot", self.client.get(reverse("stock")).context["filtres"].fields)

    def test_le_choix_de_depot_est_retenu_en_session(self):
        self._basculer(self.reserve)
        reponse = self.client.get(reverse("inventaire"))
        self.assertEqual(reponse.context["depot"], self.reserve)

    def test_un_depot_d_une_autre_boutique_est_ignore(self):
        """Le gestionnaire est filtré sur le tenant : l'identifiant ne se résout pas."""
        autre = fabrique.creer_boutique("Voisine")
        with contexte_boutique(autre):
            intrus = fabrique.creer_depot(autre, "Chez le voisin")

        self.client.post(reverse("choisir_depot"), {"depot": str(intrus.pk)})
        reponse = self.client.get(reverse("stock"))
        self.assertEqual(reponse.context["depot_courant"], self.comptoir)

    def test_l_inventaire_ne_compte_que_le_depot_courant(self):
        self._basculer(self.reserve)
        reponse = self.client.get(reverse("inventaire"))
        niveaux = reponse.context["niveaux"]
        self.assertTrue(all(n.depot_id == self.reserve.pk for n in niveaux))

    def test_la_liste_de_stock_se_filtre_par_depot(self):
        reponse = self.client.get(reverse("stock"), {"depot": str(self.reserve.pk)})
        self.assertTrue(all(n.depot_id == self.reserve.pk for n in reponse.context["niveaux"]))

    def test_un_filtre_de_depot_fantaisiste_retombe_sur_tous(self):
        """Ces URL se bricolent à la main : un identifiant de travers n'est pas une panne.

        Le filtre est confronté à la liste réelle des dépôts ouverts ; ce qui
        n'y figure pas ne filtre rien, et la liste complète s'affiche.
        """
        reponse = self.client.get(reverse("stock"), {"depot": "pas-un-uuid"})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context["filtres"].valeurs.get("depot"), "")
        self.assertEqual(len(reponse.context["niveaux"]), 2)

    def test_l_encaissement_sort_le_stock_du_depot_courant(self):
        self._basculer(self.reserve)
        reponse = self.client.post(
            reverse("caisse_encaisser"),
            data=json.dumps(
                {
                    "operation_id": "018f0000-0000-7000-8000-0000000000d1",
                    "lignes": [{"variante": str(self.variante.pk), "quantite": 4}],
                    "moyen": "especes",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(reponse.status_code, 200)

        with contexte_boutique(self.boutique):
            self.assertEqual(
                NiveauStock.objects.get(depot=self.reserve, variante=self.variante).quantite,
                Decimal("86.0000"),
            )
            self.assertEqual(
                NiveauStock.objects.get(depot=self.comptoir, variante=self.variante).quantite,
                Decimal("10.0000"),
            )

    def test_une_session_ouverte_l_emporte_sur_le_selecteur(self):
        """Sinon, changer de dépôt en cours de journée déplacerait la caisse."""
        with contexte_boutique(self.boutique):
            SessionCaisse.objects.create(
                boutique=self.boutique, depot=self.comptoir, caissier=self.gerant
            )

        self._basculer(self.reserve)
        self.client.post(
            reverse("caisse_encaisser"),
            data=json.dumps(
                {
                    "operation_id": "018f0000-0000-7000-8000-0000000000d2",
                    "lignes": [{"variante": str(self.variante.pk), "quantite": 2}],
                    "moyen": "especes",
                }
            ),
            content_type="application/json",
        )

        with contexte_boutique(self.boutique):
            ticket = Ticket.objects.filter(etat=Ticket.CLOTURE).first()
            self.assertEqual(ticket.session.depot_id, self.comptoir.pk)
            self.assertEqual(
                NiveauStock.objects.get(depot=self.comptoir, variante=self.variante).quantite,
                Decimal("8.0000"),
            )


class TransfertEntreDepotsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boutique = fabrique.creer_boutique("Transferts", quota_depots=3)
        with contexte_boutique(cls.boutique):
            cls.comptoir = fabrique.creer_depot(cls.boutique, "Comptoir")
            cls.reserve = fabrique.creer_depot(cls.boutique, "Réserve", principal=False)
            cls.variante = fabrique.creer_variante(cls.boutique, sku="TRF-1", prix="2000")
            entrer_stock(
                depot=cls.comptoir, variante=cls.variante, quantite=40, cout_unitaire=Decimal("900")
            )

        cls.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(cls.gerant, cls.boutique, Role.GERANT)

    def setUp(self):
        self.client.force_login(self.gerant)

    def test_un_transfert_deplace_la_marchandise_sans_creer_de_valeur(self):
        reponse = self.client.post(
            reverse("transfert_stock", args=[self.variante.pk]),
            {"cible": str(self.reserve.pk), "quantite": "15", "commentaire": "Réassort"},
        )
        self.assertRedirects(reponse, reverse("article", args=[self.variante.pk]))

        with contexte_boutique(self.boutique):
            comptoir = NiveauStock.objects.get(depot=self.comptoir, variante=self.variante)
            reserve = NiveauStock.objects.get(depot=self.reserve, variante=self.variante)

            self.assertEqual(comptoir.quantite, Decimal("25.0000"))
            self.assertEqual(reserve.quantite, Decimal("15.0000"))
            # Le coût suit la marchandise : la valeur totale ne bouge pas.
            self.assertEqual(reserve.cmp, Decimal("900.0000"))
            self.assertEqual(comptoir.valeur + reserve.valeur, Decimal("36000.00"))

    def test_le_depot_source_ne_figure_pas_parmi_les_cibles(self):
        reponse = self.client.get(reverse("transfert_stock", args=[self.variante.pk]))
        cibles = dict(reponse.context["formulaire"].fields["cible"].choices)
        self.assertNotIn(str(self.comptoir.pk), cibles)
        self.assertIn(str(self.reserve.pk), cibles)

    def test_un_depot_d_une_autre_boutique_est_refuse(self):
        autre = fabrique.creer_boutique("Voisine")
        with contexte_boutique(autre):
            intrus = fabrique.creer_depot(autre, "Chez le voisin")

        reponse = self.client.post(
            reverse("transfert_stock", args=[self.variante.pk]),
            {"cible": str(intrus.pk), "quantite": "5"},
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.context["formulaire"].errors)

        with contexte_boutique(self.boutique):
            self.assertEqual(
                NiveauStock.objects.get(depot=self.comptoir, variante=self.variante).quantite,
                Decimal("40.0000"),
            )


class OuvertureDeDepotTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Quota", quota_depots=2)
        with contexte_boutique(self.boutique):
            fabrique.creer_depot(self.boutique, "Comptoir")
        self.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(self.gerant, self.boutique, Role.GERANT)
        self.client.force_login(self.gerant)

    def test_un_depot_supplementaire_s_ouvre_dans_la_limite_du_quota(self):
        reponse = self.client.post(
            reverse("nouveau_depot"), {"libelle": "Réserve Akwa", "type": "reserve", "adresse": ""}
        )
        self.assertRedirects(reponse, reverse("boutique"))

        with contexte_boutique(self.boutique):
            from apps.inventory.models import Depot

            self.assertEqual(Depot.objects.count(), 2)
            self.assertFalse(Depot.objects.get(libelle="Réserve Akwa").principal)

    def test_le_quota_de_l_emplacement_est_opposable(self):
        """Le quota est commercial avant d'être technique : il est annoncé et appliqué."""
        self.client.post(reverse("nouveau_depot"), {"libelle": "Réserve 1", "type": "reserve"})
        reponse = self.client.post(
            reverse("nouveau_depot"), {"libelle": "Réserve 2", "type": "reserve"}
        )
        self.assertRedirects(reponse, reverse("boutique"))

        with contexte_boutique(self.boutique):
            from apps.inventory.models import Depot

            self.assertEqual(Depot.objects.count(), 2)


class ReceptionHorsLigneTest(TestCase):
    """Une réception saisie sans réseau part au retour, et une seule fois."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Réception")
        with contexte_boutique(self.boutique):
            self.depot = fabrique.creer_depot(self.boutique)
            self.variante = fabrique.creer_variante(self.boutique, sku="REC-1", prix="2000")
            entrer_stock(
                depot=self.depot, variante=self.variante, quantite=10, cout_unitaire=Decimal("500")
            )

        self.magasinier = fabrique.creer_utilisateur("Magasinier")
        rattacher(self.magasinier, self.boutique, Role.MAGASINIER)
        self.client.force_login(self.magasinier)

    def _recevoir(self, operation_id="018f0000-0000-7000-8000-0000000000e1", quantite="30"):
        return self.client.post(
            reverse("entree_stock_json", args=[self.variante.pk]),
            data=json.dumps(
                {
                    "operation_id": operation_id,
                    "quantite": quantite,
                    "cout_unitaire": "700",
                    "commentaire": "Bon de livraison 42",
                }
            ),
            content_type="application/json",
        )

    def test_la_reception_recalcule_le_cout_moyen(self):
        reponse = self._recevoir()
        self.assertEqual(reponse.status_code, 200)
        corps = reponse.json()
        self.assertTrue(corps["ok"])
        self.assertEqual(corps["quantite_apres"], 40.0)
        # (10 × 500 + 30 × 700) / 40 = 650
        self.assertEqual(corps["cmp_apres"], 650.0)

    def test_le_rejeu_ne_dedouble_pas_la_reception(self):
        """Sans cette garantie, le CMP serait faussé à chaque retransmission."""
        premier = self._recevoir().json()
        second = self._recevoir().json()

        self.assertEqual(premier["quantite_apres"], second["quantite_apres"])
        with contexte_boutique(self.boutique):
            self.assertEqual(
                MouvementStock.objects.filter(
                    variante=self.variante, type=MouvementStock.ENTREE
                ).count(),
                2,  # la reprise initiale + une seule réception
            )
            self.assertEqual(
                NiveauStock.objects.get(depot=self.depot, variante=self.variante).cmp,
                Decimal("650.0000"),
            )

    def test_une_saisie_invalide_est_refusee_avec_son_motif(self):
        """Règle 3 de la file : une erreur métier en sort, elle ne boucle pas."""
        reponse = self._recevoir(quantite="0")
        self.assertEqual(reponse.status_code, 400)
        self.assertFalse(reponse.json()["ok"])
        self.assertIn("quantite", reponse.json()["erreurs"])

    def test_la_reception_vise_le_depot_courant(self):
        with contexte_boutique(self.boutique):
            reserve = fabrique.creer_depot(self.boutique, "Réserve", principal=False)

        self.client.post(reverse("choisir_depot"), {"depot": str(reserve.pk)})
        self._recevoir()

        with contexte_boutique(self.boutique):
            self.assertEqual(
                NiveauStock.objects.get(depot=reserve, variante=self.variante).quantite,
                Decimal("30.0000"),
            )


class CatalogueHorsLigneTest(TestCase):
    """Le catalogue servi à la caisse ne dépend pas de la fraîcheur de la page."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Catalogue")
        with contexte_boutique(self.boutique):
            self.depot = fabrique.creer_depot(self.boutique)
            self.variante = fabrique.creer_variante(self.boutique, sku="CAT-1", prix="1500")
            entrer_stock(
                depot=self.depot, variante=self.variante, quantite=7, cout_unitaire=Decimal("900")
            )

        self.caissier = fabrique.creer_utilisateur("Caissier")
        rattacher(self.caissier, self.boutique, Role.CAISSIER)
        self.client.force_login(self.caissier)

    def test_le_catalogue_json_porte_les_articles_du_depot(self):
        corps = self.client.get(reverse("catalogue_json")).json()

        self.assertTrue(corps["ok"])
        self.assertEqual(len(corps["articles"]), 1)
        article = corps["articles"][0]
        self.assertEqual(article["sku"], "CAT-1")
        self.assertEqual(article["prix"], 1500.0)
        self.assertEqual(article["stock"], 7.0)

    def test_le_catalogue_ne_divulgue_aucun_cout(self):
        """C'est le point d'entrée le plus exposé : il est lu par la caisse."""
        corps = self.client.get(reverse("catalogue_json")).json()
        contenu = json.dumps(corps)
        self.assertNotIn("cmp", contenu)
        self.assertNotIn("cout", contenu)
        self.assertNotIn("900", contenu)

    def test_un_article_cree_apres_coup_apparait_sans_recharger_la_page(self):
        with contexte_boutique(self.boutique):
            nouvelle = fabrique.creer_variante(self.boutique, sku="CAT-2", prix="800")
            entrer_stock(
                depot=self.depot, variante=nouvelle, quantite=3, cout_unitaire=Decimal("400")
            )

        skus = {a["sku"] for a in self.client.get(reverse("catalogue_json")).json()["articles"]}
        self.assertEqual(skus, {"CAT-1", "CAT-2"})

    def test_le_catalogue_est_borne_a_la_boutique(self):
        voisine = fabrique.creer_boutique("Voisine")
        with contexte_boutique(voisine):
            depot = fabrique.creer_depot(voisine)
            variante = fabrique.creer_variante(voisine, sku="VOISIN-1")
            entrer_stock(
                depot=depot, variante=variante, quantite=5, cout_unitaire=Decimal("100")
            )

        corps = self.client.get(reverse("catalogue_json")).json()
        self.assertNotIn("VOISIN-1", json.dumps(corps))
