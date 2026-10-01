"""Tests du back-office marchand.

Deux choses à protéger ici :

1. **l'isolation vue par le navigateur** — un gérant connecté ne doit voir que sa
   boutique, quelle que soit l'URL qu'il demande ;
2. **la chaîne d'encaissement de bout en bout** — un appel à la caisse produit le
   ticket, la sortie de stock et les écritures, et une retransmission ne dédouble
   rien (ADR-004).
"""

import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounting.models import EcritureComptable
from apps.accounts.models import Appartenance, Role
from apps.backoffice.templatetags.hm import ESPACE_FINE, fcfa, initiales, pourcent, quantite
from apps.backoffice.views import geometrie_graphe
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import NiveauStock
from apps.inventory.services import entrer_stock
from apps.pos.models import Ticket
from tests import fabrique

MOT_DE_PASSE = "motdepasse"


def _rattacher(utilisateur, boutique) -> None:
    role, _ = Role.objects.get_or_create(
        code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class FiltresAffichageTest(TestCase):
    def test_montant_en_francs_cfa(self):
        # Espace fine insécable en séparateur de milliers, aucune décimale.
        self.assertEqual(fcfa(Decimal("1250000")), "1 250 000")
        self.assertEqual(fcfa(Decimal("0")), "0")
        self.assertEqual(fcfa(Decimal("-4500")), "-4 500")
        self.assertEqual(fcfa(None), "—")

    def test_quantite_sans_decimales_inutiles(self):
        self.assertEqual(quantite(Decimal("12.0000")), "12")
        self.assertEqual(quantite(Decimal("2.5000")), "2,5")
        self.assertEqual(quantite(Decimal("1500")), "1 500")

    def test_pourcentage(self):
        self.assertEqual(pourcent(Decimal("24.75")), f"24,8{ESPACE_FINE}%")

    def test_initiales(self):
        self.assertEqual(initiales("Quincaillerie Ateba"), "QA")
        self.assertEqual(initiales("Bella"), "BE")
        self.assertEqual(initiales(""), "?")


class GeometrieGrapheTest(TestCase):
    def _serie(self, valeurs):
        return [
            {
                "date": None,
                "libelle": f"j{rang}",
                "libelle_long": f"0{rang}/01/2027",
                "valeur": Decimal(str(v)),
            }
            for rang, v in enumerate(valeurs)
        ]

    def test_toutes_les_coordonnees_sont_numeriques(self):
        """Aucune coordonnée vide : c'est le défaut qui empilait les étiquettes à y=0."""
        graphe = geometrie_graphe(self._serie([0, 120000, 45000, 300000]))
        # L'invariant n'est pas le type exact mais le fait que la valeur soit un
        # nombre : c'est une chaîne vide qui empilait les étiquettes à y=0.
        for ligne in graphe["lignes"]:
            self.assertIsInstance(ligne["y"], (int, float))
            self.assertIsInstance(ligne["y_texte"], (int, float))
        for barre in graphe["barres"]:
            self.assertIsInstance(barre["y"], (int, float))
            self.assertIsInstance(barre["y_etiquette"], (int, float))

    def test_les_barres_sont_ancrees_sur_la_ligne_de_base(self):
        graphe = geometrie_graphe(self._serie([100, 200, 300]))
        for barre in graphe["barres"]:
            self.assertAlmostEqual(barre["y"] + barre["hauteur"], graphe["y_base"], places=1)

    def test_une_seule_etiquette_directe_sur_le_maximum(self):
        graphe = geometrie_graphe(self._serie([100, 900, 300, 400]))
        maxima = [b for b in graphe["barres"] if b["est_max"]]
        self.assertEqual(len(maxima), 1)
        self.assertEqual(maxima[0]["valeur"], Decimal("900"))

    def test_une_valeur_nulle_ne_dessine_aucune_marque(self):
        graphe = geometrie_graphe(self._serie([0, 500]))
        self.assertEqual(graphe["barres"][0]["chemin"], "")
        self.assertNotEqual(graphe["barres"][1]["chemin"], "")

    def test_serie_entierement_vide_ne_plante_pas(self):
        graphe = geometrie_graphe(self._serie([0, 0, 0]))
        self.assertTrue(all(b["chemin"] == "" for b in graphe["barres"]))
        self.assertEqual(len(graphe["lignes"]), 5)


class IsolationDesVuesTest(TestCase):
    """Un gérant ne voit que sa boutique, quelle que soit l'URL demandée."""

    @classmethod
    def setUpTestData(cls):
        cls.boutique_a = fabrique.creer_boutique("Alpha")
        cls.boutique_b = fabrique.creer_boutique("Beta")

        cls.gerant_a = fabrique.creer_utilisateur("Gérant A")
        _rattacher(cls.gerant_a, cls.boutique_a)

        with contexte_boutique(cls.boutique_a):
            cls.variante_a = fabrique.creer_variante(cls.boutique_a, sku="ALPHA-1")
            depot = fabrique.creer_depot(cls.boutique_a)
            entrer_stock(
                depot=depot, variante=cls.variante_a, quantite=10, cout_unitaire=Decimal("1000")
            )
        with contexte_boutique(cls.boutique_b):
            cls.variante_b = fabrique.creer_variante(cls.boutique_b, sku="BETA-1")
            depot_b = fabrique.creer_depot(cls.boutique_b)
            entrer_stock(
                depot=depot_b, variante=cls.variante_b, quantite=99, cout_unitaire=Decimal("2000")
            )

    def setUp(self):
        self.client.login(telephone=self.gerant_a.telephone, password=MOT_DE_PASSE)

    def test_le_stock_affiche_ne_contient_que_la_boutique_courante(self):
        reponse = self.client.get(reverse("stock"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "ALPHA-1")
        self.assertNotContains(reponse, "BETA-1")

    def test_un_article_d_une_autre_boutique_est_inatteignable(self):
        reponse = self.client.get(reverse("article", args=[self.variante_b.pk]))
        self.assertRedirects(reponse, reverse("stock"))

    def test_la_caisse_ne_propose_que_les_articles_de_la_boutique(self):
        reponse = self.client.get(reverse("caisse"))
        self.assertContains(reponse, "ALPHA-1")
        self.assertNotContains(reponse, "BETA-1")

    def test_toutes_les_pages_repondent(self):
        for nom in ("tableau_de_bord", "caisse", "stock", "ventes", "comptabilite", "boutique"):
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)

    def test_un_visiteur_anonyme_est_renvoye_vers_la_connexion(self):
        self.client.logout()
        reponse = self.client.get(reverse("tableau_de_bord"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("connexion"), reponse["Location"])


class ConnexionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boutique = fabrique.creer_boutique("Gamma")
        cls.gerant = fabrique.creer_utilisateur("Gérant")
        _rattacher(cls.gerant, cls.boutique)
        cls.orphelin = fabrique.creer_utilisateur("Sans boutique")

    def test_connexion_reussie_ouvre_la_boutique(self):
        reponse = self.client.post(
            reverse("connexion"),
            {"telephone": self.gerant.telephone, "mot_de_passe": MOT_DE_PASSE},
        )
        self.assertRedirects(reponse, reverse("tableau_de_bord"))
        self.assertEqual(self.client.session["boutique_id"], str(self.boutique.pk))

    def test_mauvais_mot_de_passe_refuse(self):
        reponse = self.client.post(
            reverse("connexion"), {"telephone": self.gerant.telephone, "mot_de_passe": "faux"}
        )
        self.assertEqual(reponse.status_code, 401)
        self.assertContains(reponse, "incorrect", status_code=401)

    def test_compte_sans_boutique_refuse_explicitement(self):
        reponse = self.client.post(
            reverse("connexion"),
            {"telephone": self.orphelin.telephone, "mot_de_passe": MOT_DE_PASSE},
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertContains(reponse, "aucune boutique", status_code=403)


class EncaissementTest(TestCase):
    """La chaîne complète : un appel produit ticket, stock et comptabilité."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Delta")
        self.gerant = fabrique.creer_utilisateur("Caissier")
        _rattacher(self.gerant, self.boutique)

        with contexte_boutique(self.boutique):
            self.depot = fabrique.creer_depot(self.boutique)
            # 11 925 F TTC = 10 000 F HT + 1 925 F de TVA à 19,25 %.
            self.variante = fabrique.creer_variante(self.boutique, prix="11925")
            entrer_stock(
                depot=self.depot, variante=self.variante, quantite=20, cout_unitaire=Decimal("6800")
            )

        self.client.login(telephone=self.gerant.telephone, password=MOT_DE_PASSE)

    def _encaisser(self, operation_id="018f0000-0000-7000-8000-000000000001", quantite=2):
        return self.client.post(
            reverse("caisse_encaisser"),
            data=json.dumps(
                {
                    "operation_id": operation_id,
                    "lignes": [{"variante": str(self.variante.pk), "quantite": quantite}],
                    "moyen": "especes",
                }
            ),
            content_type="application/json",
        )

    def test_encaissement_produit_toute_la_chaine(self):
        reponse = self._encaisser()
        self.assertEqual(reponse.status_code, 200)
        charge = reponse.json()
        self.assertTrue(charge["ok"])
        self.assertEqual(charge["total"], 23850.0)

        with contexte_boutique(self.boutique):
            ticket = Ticket.objects.get(numero=charge["numero"])
            self.assertEqual(ticket.etat, Ticket.CLOTURE)

            niveau = NiveauStock.objects.get(depot=self.depot, variante=self.variante)
            self.assertEqual(niveau.quantite, Decimal("18.0000"))

            self.assertEqual(
                EcritureComptable.objects.filter(origine_id=ticket.pk).count(), 3
            )

    def test_retransmission_ne_dedouble_rien(self):
        """Une opération hors ligne renvoyée après coupure ne crée pas deux ventes."""
        premier = self._encaisser().json()
        second = self._encaisser().json()

        self.assertEqual(premier["numero"], second["numero"])
        self.assertTrue(second["rejoue"])

        with contexte_boutique(self.boutique):
            self.assertEqual(Ticket.objects.filter(etat=Ticket.CLOTURE).count(), 1)
            niveau = NiveauStock.objects.get(depot=self.depot, variante=self.variante)
            self.assertEqual(niveau.quantite, Decimal("18.0000"))

    def test_panier_vide_refuse(self):
        reponse = self.client.post(
            reverse("caisse_encaisser"),
            data=json.dumps({"lignes": [], "moyen": "especes"}),
            content_type="application/json",
        )
        self.assertEqual(reponse.status_code, 400)
        self.assertFalse(reponse.json()["ok"])

    def test_requete_illisible_refusee(self):
        reponse = self.client.post(
            reverse("caisse_encaisser"), data="pas du json", content_type="application/json"
        )
        self.assertEqual(reponse.status_code, 400)

    def test_le_tableau_de_bord_reflete_la_vente(self):
        self._encaisser()
        reponse = self.client.get(reverse("tableau_de_bord"))
        self.assertEqual(reponse.status_code, 200)
        # Marge = 23 850 TTC − (2 × 6 800) de coût = 10 250 F.
        self.assertEqual(reponse.context["marge_jour"], Decimal("10250.00"))
