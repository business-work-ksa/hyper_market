"""Tests des écrans de gestion : reprise de stock, inventaire, caisse, ticket, export.

Ce sont les cinq chantiers qui manquaient avant une installation réelle
(docs/18, §6). Chacun touche au journal du stock ou à celui de la caisse : ce qui
est protégé ici, c'est qu'aucun d'eux n'écrit un compteur en direct.
"""

import io
import zipfile
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.catalog.models import Produit, Variante
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import Inventaire, MouvementStock, NiveauStock
from apps.inventory.services import entrer_stock
from apps.pos import services as caisse_service
from apps.pos.models import SessionCaisse, Ticket
from tests import fabrique

MOT_DE_PASSE = "motdepasse"


def _rattacher(utilisateur, boutique) -> None:
    role, _ = Role.objects.get_or_create(
        code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class BaseGestionTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Atelier")
        self.gerant = fabrique.creer_utilisateur("Gérante")
        _rattacher(self.gerant, self.boutique)
        with contexte_boutique(self.boutique):
            self.depot = fabrique.creer_depot(self.boutique)
        self.client.login(telephone=self.gerant.telephone, password=MOT_DE_PASSE)


class NouvelArticleTest(BaseGestionTest):
    DONNEES = {
        "libelle": "Ciment CIMENCAM 50 kg",
        "sku": "qui-cim-50",
        "code_barres": "",
        "prix_vente": "6500",
        "cout_unitaire": "5200",
        "quantite": "120",
        "seuil_alerte": "30",
        "regime_tva": Produit.NORMAL,
    }

    def test_affichage(self):
        self.assertEqual(self.client.get(reverse("nouvel_article")).status_code, 200)

    def test_creation_complete_en_une_soumission(self):
        """Produit, variante, seuil et entrée valorisée : un seul écran."""
        reponse = self.client.post(reverse("nouvel_article"), self.DONNEES)
        self.assertRedirects(reponse, reverse("stock"))

        with contexte_boutique(self.boutique):
            variante = Variante.objects.get(sku="QUI-CIM-50")  # normalisé en majuscules
            self.assertEqual(variante.produit.libelle, "Ciment CIMENCAM 50 kg")
            self.assertEqual(variante.prix_vente, Decimal("6500.00"))

            niveau = NiveauStock.objects.get(variante=variante)
            self.assertEqual(niveau.quantite, Decimal("120.0000"))
            self.assertEqual(niveau.cmp, Decimal("5200.0000"))
            self.assertEqual(niveau.seuil_alerte, Decimal("30.0000"))

            mouvement = MouvementStock.objects.get(variante=variante)
            self.assertEqual(mouvement.type, MouvementStock.ENTREE)
            self.assertEqual(mouvement.cout_unitaire, Decimal("5200.0000"))

    def test_enchainer_revient_sur_le_formulaire(self):
        """Pendant un comptage, on saisit vingt articles d'affilée."""
        reponse = self.client.post(reverse("nouvel_article"), {**self.DONNEES, "enchainer": "1"})
        self.assertRedirects(reponse, reverse("nouvel_article"))

    def test_quantite_nulle_ne_cree_aucun_mouvement(self):
        self.client.post(reverse("nouvel_article"), {**self.DONNEES, "quantite": "0"})
        with contexte_boutique(self.boutique):
            variante = Variante.objects.get(sku="QUI-CIM-50")
            self.assertFalse(MouvementStock.objects.filter(variante=variante).exists())
            self.assertEqual(NiveauStock.objects.get(variante=variante).quantite, Decimal("0"))

    def test_reference_deja_prise_refusee(self):
        self.client.post(reverse("nouvel_article"), self.DONNEES)
        reponse = self.client.post(reverse("nouvel_article"), self.DONNEES)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "existe déjà")
        with contexte_boutique(self.boutique):
            self.assertEqual(Variante.objects.filter(sku="QUI-CIM-50").count(), 1)

    def test_vente_a_perte_signalee(self):
        reponse = self.client.post(
            reverse("nouvel_article"), {**self.DONNEES, "cout_unitaire": "9000"}
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "à perte")


class EntreeStockTest(BaseGestionTest):
    def setUp(self):
        super().setUp()
        with contexte_boutique(self.boutique):
            self.variante = fabrique.creer_variante(self.boutique, prix="6500")
            entrer_stock(
                depot=self.depot,
                variante=self.variante,
                quantite=Decimal("10"),
                cout_unitaire=Decimal("1000"),
            )

    def test_entree_recalcule_le_cout_moyen(self):
        reponse = self.client.post(
            reverse("entree_stock", args=[self.variante.pk]),
            {"quantite": "10", "cout_unitaire": "2000", "commentaire": "BL 42"},
        )
        self.assertRedirects(reponse, reverse("article", args=[self.variante.pk]))

        with contexte_boutique(self.boutique):
            niveau = NiveauStock.objects.get(variante=self.variante)
            self.assertEqual(niveau.quantite, Decimal("20.0000"))
            # (10 × 1000 + 10 × 2000) / 20 = 1500
            self.assertEqual(niveau.cmp, Decimal("1500.0000"))

    def test_le_formulaire_propose_le_cout_courant(self):
        reponse = self.client.get(reverse("entree_stock", args=[self.variante.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(
            reponse.context["formulaire"].initial["cout_unitaire"], Decimal("1000")
        )

    def test_article_inconnu_renvoie_au_stock(self):
        import uuid

        reponse = self.client.get(reverse("entree_stock", args=[uuid.uuid4()]))
        self.assertRedirects(reponse, reverse("stock"))


class InventaireTest(BaseGestionTest):
    def setUp(self):
        super().setUp()
        with contexte_boutique(self.boutique):
            self.variante = fabrique.creer_variante(self.boutique, sku="INV-1")
            self.autre = fabrique.creer_variante(self.boutique, sku="INV-2")
            for variante in (self.variante, self.autre):
                entrer_stock(
                    depot=self.depot,
                    variante=variante,
                    quantite=Decimal("50"),
                    cout_unitaire=Decimal("800"),
                )

    def test_affichage(self):
        reponse = self.client.get(reverse("inventaire"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "INV-1")

    def test_ecart_regularise_par_un_ajustement(self):
        """L'écart passe par le journal, jamais par une correction du compteur."""
        reponse = self.client.post(
            reverse("inventaire"),
            {
                f"qte_{self.variante.pk}": "47",
                f"motif_{self.variante.pk}": "Casse non déclarée",
                f"qte_{self.autre.pk}": "",  # non compté
            },
        )
        self.assertRedirects(reponse, reverse("stock"))

        with contexte_boutique(self.boutique):
            self.assertEqual(NiveauStock.objects.get(variante=self.variante).quantite, Decimal("47.0000"))
            # L'article non compté n'est pas touché.
            self.assertEqual(NiveauStock.objects.get(variante=self.autre).quantite, Decimal("50.0000"))

            ajustement = MouvementStock.objects.get(
                variante=self.variante, type=MouvementStock.AJUSTEMENT
            )
            self.assertEqual(ajustement.quantite, Decimal("-3.0000"))
            self.assertEqual(ajustement.commentaire, "Casse non déclarée")
            self.assertEqual(Inventaire.objects.filter(etat=Inventaire.VALIDE).count(), 1)

    def test_comptage_conforme_ne_cree_aucun_ajustement(self):
        self.client.post(reverse("inventaire"), {f"qte_{self.variante.pk}": "50"})
        with contexte_boutique(self.boutique):
            self.assertFalse(
                MouvementStock.objects.filter(type=MouvementStock.AJUSTEMENT).exists()
            )

    def test_inventaire_vide_refuse(self):
        reponse = self.client.post(
            reverse("inventaire"), {f"qte_{self.variante.pk}": "", f"qte_{self.autre.pk}": ""}
        )
        self.assertRedirects(reponse, reverse("inventaire"))
        with contexte_boutique(self.boutique):
            self.assertEqual(Inventaire.objects.count(), 0)

    def test_valeur_illisible_ignoree(self):
        self.client.post(reverse("inventaire"), {f"qte_{self.variante.pk}": "beaucoup"})
        with contexte_boutique(self.boutique):
            self.assertEqual(
                NiveauStock.objects.get(variante=self.variante).quantite, Decimal("50.0000")
            )

    def test_virgule_decimale_acceptee(self):
        """Un clavier français produit « 47,5 » : le refuser serait absurde."""
        self.client.post(reverse("inventaire"), {f"qte_{self.variante.pk}": "47,5"})
        with contexte_boutique(self.boutique):
            self.assertEqual(
                NiveauStock.objects.get(variante=self.variante).quantite, Decimal("47.5000")
            )


class SessionCaisseTest(BaseGestionTest):
    def test_ouverture(self):
        reponse = self.client.post(reverse("session_caisse"), {"fonds_ouverture": "50000"})
        self.assertRedirects(reponse, reverse("caisse"))
        with contexte_boutique(self.boutique):
            session = SessionCaisse.objects.get(etat=SessionCaisse.OUVERTE)
            self.assertEqual(session.fonds_ouverture, Decimal("50000.00"))
            self.assertEqual(session.caissier, self.gerant)

    def test_fermeture_calcule_l_ecart(self):
        with contexte_boutique(self.boutique):
            variante = fabrique.creer_variante(self.boutique, prix="10000")
            entrer_stock(
                depot=self.depot, variante=variante, quantite=Decimal("5"),
                cout_unitaire=Decimal("6000"),
            )
            session = caisse_service.ouvrir_session(
                depot=self.depot, caissier=self.gerant, fonds_ouverture=Decimal("50000")
            )
            ticket = caisse_service.creer_ticket(session=session)
            caisse_service.ajouter_ligne(ticket=ticket, variante=variante, quantite=Decimal("1"))
            ticket.refresh_from_db()
            caisse_service.regler(ticket=ticket, moyen="especes", montant=ticket.total_ttc)
            caisse_service.cloturer_ticket(ticket)

        # Théorique : 50 000 + 10 000 = 60 000. Compté : 59 500 → manquant de 500.
        reponse = self.client.post(reverse("session_caisse"), {"fonds_compte": "59500"})
        self.assertRedirects(reponse, reverse("caisse"))

        with contexte_boutique(self.boutique):
            session.refresh_from_db()
            self.assertEqual(session.etat, SessionCaisse.FERMEE)
            self.assertEqual(session.fonds_theorique, Decimal("60000.00"))
            self.assertEqual(session.ecart, Decimal("-500.00"))

    def test_affichage_adapte_a_l_etat(self):
        self.assertContains(self.client.get(reverse("session_caisse")), "Ouvrir la caisse")
        self.client.post(reverse("session_caisse"), {"fonds_ouverture": "0"})
        self.assertContains(self.client.get(reverse("session_caisse")), "Fermer la caisse")


class TicketImprimableTest(BaseGestionTest):
    def setUp(self):
        super().setUp()
        with contexte_boutique(self.boutique):
            variante = fabrique.creer_variante(self.boutique, prix="11925")
            entrer_stock(
                depot=self.depot, variante=variante, quantite=Decimal("10"),
                cout_unitaire=Decimal("6800"),
            )
            session = caisse_service.ouvrir_session(depot=self.depot, caissier=self.gerant)
            self.ticket = caisse_service.creer_ticket(session=session)
            caisse_service.ajouter_ligne(ticket=self.ticket, variante=variante, quantite=Decimal("2"))
            self.ticket.refresh_from_db()
            caisse_service.regler(
                ticket=self.ticket, moyen="especes", montant=self.ticket.total_ttc
            )
            caisse_service.cloturer_ticket(self.ticket)

    def test_le_ticket_porte_les_mentions_legales(self):
        reponse = self.client.get(reverse("ticket", args=[self.ticket.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, self.ticket.numero)
        self.assertContains(reponse, self.boutique.raison_sociale)
        self.assertContains(reponse, "TOTAL")

    def test_ticket_inconnu_renvoie_aux_ventes(self):
        import uuid

        self.assertRedirects(
            self.client.get(reverse("ticket", args=[uuid.uuid4()])), reverse("ventes")
        )

    def test_un_ticket_d_une_autre_boutique_est_inatteignable(self):
        autre = fabrique.creer_boutique("Voisine")
        gerant = fabrique.creer_utilisateur("Voisin")
        _rattacher(gerant, autre)
        self.client.logout()
        self.client.login(telephone=gerant.telephone, password=MOT_DE_PASSE)

        self.assertRedirects(
            self.client.get(reverse("ticket", args=[self.ticket.pk])), reverse("ventes")
        )


class ExportTest(BaseGestionTest):
    def setUp(self):
        super().setUp()
        with contexte_boutique(self.boutique):
            self.variante = fabrique.creer_variante(self.boutique, sku="EXP-1", prix="11925")
            entrer_stock(
                depot=self.depot, variante=self.variante, quantite=Decimal("10"),
                cout_unitaire=Decimal("6800"),
            )
            session = caisse_service.ouvrir_session(depot=self.depot, caissier=self.gerant)
            ticket = caisse_service.creer_ticket(session=session)
            caisse_service.ajouter_ligne(ticket=ticket, variante=self.variante, quantite=Decimal("1"))
            ticket.refresh_from_db()
            caisse_service.regler(ticket=ticket, moyen="especes", montant=ticket.total_ttc)
            caisse_service.cloturer_ticket(ticket)

    def _archive(self):
        reponse = self.client.get(reverse("export_donnees"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/zip")
        return zipfile.ZipFile(io.BytesIO(reponse.content))

    def test_l_archive_contient_toutes_les_tables(self):
        archive = self._archive()
        self.assertEqual(
            sorted(archive.namelist()),
            sorted(
                [
                    "LISEZ-MOI.txt",
                    "articles.csv",
                    "stock.csv",
                    "mouvements_stock.csv",
                    "tickets.csv",
                    "lignes_ticket.csv",
                    "ecritures_comptables.csv",
                ]
            ),
        )

    def test_les_donnees_reelles_y_sont(self):
        archive = self._archive()
        articles = archive.read("articles.csv").decode("utf-8")
        self.assertTrue(articles.startswith("﻿"))  # BOM pour Excel en français
        self.assertIn("EXP-1", articles)
        self.assertIn("EXP-1", archive.read("stock.csv").decode("utf-8"))
        self.assertIn("6800", archive.read("mouvements_stock.csv").decode("utf-8"))
        self.assertIn("701", archive.read("ecritures_comptables.csv").decode("utf-8"))

    def test_l_export_ne_franchit_pas_la_frontiere_de_boutique(self):
        autre = fabrique.creer_boutique("Voisine")
        with contexte_boutique(autre):
            fabrique.creer_variante(autre, sku="SECRET-1")

        articles = self._archive().read("articles.csv").decode("utf-8")
        self.assertIn("EXP-1", articles)
        self.assertNotIn("SECRET-1", articles)

    def test_le_nom_du_fichier_porte_la_boutique(self):
        reponse = self.client.get(reverse("export_donnees"))
        self.assertIn(self.boutique.slug, reponse["Content-Disposition"])


class ServiceWorkerTest(TestCase):
    def test_servi_depuis_la_racine_avec_la_bonne_portee(self):
        """La portée d'un service worker est celle de son URL : il doit être à la racine."""
        reponse = self.client.get("/service-worker.js")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Service-Worker-Allowed"], "/")
        self.assertIn("javascript", reponse["Content-Type"])
        self.assertIn("caches", reponse.content.decode())

    def test_accessible_sans_authentification(self):
        """Le service worker s'enregistre avant même l'écran de connexion."""
        self.assertEqual(self.client.get("/service-worker.js").status_code, 200)
