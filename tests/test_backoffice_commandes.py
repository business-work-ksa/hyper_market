"""L'écran de traitement des commandes, vu par le navigateur.

Deux choses s'y jouent que le moteur de commande seul ne protège pas.

**Un marchand ne voit que sa part.** La sous-commande d'un confrère n'est pas
interdite, elle est introuvable — un 403 confirmerait son existence.

**Un bouton resté affiché ne doit pas pouvoir agir.** Un onglet ouvert ce matin
affiche encore « Expédier » sur une commande annulée depuis. L'action envoyée
est donc confrontée à l'état réel avant d'être appliquée.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.core.tenancy import contexte_boutique, contexte_plateforme
from apps.inventory.models import NiveauStock
from apps.inventory.services import entrer_stock
from apps.orders.models import SousCommande
from apps.orders.services import marquer_payee, passer_commande
from tests import fabrique

MOT_DE_PASSE = "motdepasse"


def rattacher(utilisateur, boutique, code_role=Role.GERANT):
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    return Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class SocleEcranCommandes(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Écran", quota_utilisateurs=5)
        self.depot = fabrique.creer_depot(self.boutique)
        self.variante = fabrique.creer_variante(self.boutique, prix="11925")
        entrer_stock(
            depot=self.depot,
            variante=self.variante,
            quantite=Decimal("10"),
            cout_unitaire=Decimal("7000"),
        )

        self.gerant = fabrique.creer_utilisateur("Gérante")
        rattacher(self.gerant, self.boutique, Role.GERANT)
        self.client.force_login(self.gerant)

        self.acheteur = fabrique.creer_utilisateur("Acheteur")
        self.commande = passer_commande(
            acheteur=self.acheteur, lignes=[(self.variante, Decimal("2"))]
        )
        marquer_payee(self.commande)
        with contexte_plateforme():
            self.part = SousCommande.objects.get(commande=self.commande)

    def avancer(self, action, part=None):
        return self.client.post(
            reverse("commande_avancer", args=[(part or self.part).pk]), {"action": action}
        )

    def relire(self):
        """Relit la part en annonçant sa boutique.

        `refresh_from_db` passe par le gestionnaire non filtré, qui ne contourne
        pas la base : sans contexte, la barrière 3 ne rend aucune ligne.
        """
        with contexte_boutique(self.boutique):
            self.part.refresh_from_db()
        return self.part


class ListeTest(SocleEcranCommandes):
    def test_l_ecran_affiche_la_commande_a_accepter(self):
        reponse = self.client.get(reverse("commandes"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, self.commande.numero)
        self.assertContains(reponse, "À accepter")

    def test_le_rail_porte_une_pastille_du_nombre_a_traiter(self):
        reponse = self.client.get(reverse("commandes"))
        self.assertEqual(reponse.context["a_traiter"], 1)

    def test_un_caissier_n_ouvre_pas_l_ecran(self):
        caissier = fabrique.creer_utilisateur("Caissier")
        rattacher(caissier, self.boutique, Role.CAISSIER)
        self.client.force_login(caissier)
        self.assertEqual(self.client.get(reverse("commandes")).status_code, 403)

    def test_un_magasinier_l_ouvre(self):
        """C'est lui qui prépare et qui expédie."""
        magasinier = fabrique.creer_utilisateur("Magasinier")
        rattacher(magasinier, self.boutique, Role.MAGASINIER)
        self.client.force_login(magasinier)
        self.assertEqual(self.client.get(reverse("commandes")).status_code, 200)


class ParcoursTest(SocleEcranCommandes):
    def test_le_parcours_complet_sort_le_stock_a_l_expedition(self):
        self.avancer("accepter")
        self.avancer("preparer")

        with contexte_boutique(self.boutique):
            avant = NiveauStock.objects.get(variante=self.variante, depot=self.depot)
        self.assertEqual(avant.quantite, Decimal("10.0000"))

        self.avancer("expedier")

        with contexte_boutique(self.boutique):
            apres = NiveauStock.objects.get(variante=self.variante, depot=self.depot)
        self.assertEqual(apres.quantite, Decimal("8.0000"))

        self.avancer("livrer")
        self.assertEqual(self.relire().etat, SousCommande.LIVREE)

    def test_un_bouton_perime_ne_fait_rien(self):
        """Un onglet ouvert depuis ce matin ne doit pas expédier une commande annulée."""
        reponse = self.avancer("expedier")

        self.assertEqual(self.relire().etat, SousCommande.EN_ATTENTE)
        self.assertEqual(reponse.status_code, 302)

    def test_refuser_avant_expedition_n_a_rien_a_reintegrer(self):
        """Le stock n'est pas encore sorti : il n'y a rien à faire rentrer."""
        self.avancer("accepter")
        self.client.post(
            reverse("commande_annuler", args=[self.part.pk]), {"motif": "Rupture"}
        )

        self.assertEqual(self.relire().etat, SousCommande.ANNULEE)
        with contexte_boutique(self.boutique):
            niveau = NiveauStock.objects.get(variante=self.variante, depot=self.depot)
        self.assertEqual(niveau.quantite, Decimal("10.0000"))

    def test_une_commande_expediee_ne_se_refuse_plus(self):
        """La marchandise est partie : le chemin qui la ramène est le retour."""
        self.avancer("accepter")
        self.avancer("preparer")
        self.avancer("expedier")

        detail = self.client.get(reverse("commande", args=[self.part.pk]))
        self.assertFalse(detail.context["peut_refuser"])
        self.assertTrue(detail.context["peut_retourner"])

        self.client.post(
            reverse("commande_annuler", args=[self.part.pk]), {"motif": "Trop tard"}
        )
        self.assertEqual(self.relire().etat, SousCommande.EXPEDIEE)

    def test_un_retour_ramene_la_marchandise_au_cout_de_sortie(self):
        self.avancer("accepter")
        self.avancer("preparer")
        self.avancer("expedier")

        self.client.post(
            reverse("commande_retour", args=[self.part.pk]), {"motif": "Article cassé"}
        )

        with contexte_boutique(self.boutique):
            niveau = NiveauStock.objects.get(variante=self.variante, depot=self.depot)
        self.assertEqual(niveau.quantite, Decimal("10.0000"))
        self.assertEqual(niveau.cmp, Decimal("7000.0000"))

    def test_un_retour_sans_motif_est_refuse(self):
        self.avancer("accepter")
        self.avancer("preparer")
        self.avancer("expedier")

        self.client.post(reverse("commande_retour", args=[self.part.pk]), {"motif": "  "})
        with contexte_boutique(self.boutique):
            niveau = NiveauStock.objects.get(variante=self.variante, depot=self.depot)
        self.assertEqual(niveau.quantite, Decimal("8.0000"), "rien n'a bougé")

    def test_le_detail_montre_les_articles_et_la_commission(self):
        reponse = self.client.get(reverse("commande", args=[self.part.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Commission de place")
        self.assertContains(reponse, self.acheteur.nom_complet)


class IsolationEcranTest(SocleEcranCommandes):
    def test_la_part_du_voisin_est_introuvable(self):
        voisine = fabrique.creer_boutique("Voisine")
        depot_voisin = fabrique.creer_depot(voisine)
        article_voisin = fabrique.creer_variante(voisine, prix="500")
        entrer_stock(
            depot=depot_voisin,
            variante=article_voisin,
            quantite=Decimal("5"),
            cout_unitaire=Decimal("200"),
        )
        commande = passer_commande(
            acheteur=self.acheteur, lignes=[(article_voisin, Decimal("1"))]
        )
        with contexte_plateforme():
            part_voisine = SousCommande.objects.get(commande=commande, boutique=voisine)

        reponse = self.client.get(reverse("commande", args=[part_voisine.pk]))
        self.assertEqual(reponse.status_code, 404)

    def test_la_liste_ne_montre_pas_les_commandes_du_voisin(self):
        voisine = fabrique.creer_boutique("Voisine 2")
        depot_voisin = fabrique.creer_depot(voisine)
        article_voisin = fabrique.creer_variante(voisine, prix="500")
        entrer_stock(
            depot=depot_voisin,
            variante=article_voisin,
            quantite=Decimal("5"),
            cout_unitaire=Decimal("200"),
        )
        commande = passer_commande(
            acheteur=self.acheteur, lignes=[(article_voisin, Decimal("1"))]
        )

        reponse = self.client.get(reverse("commandes"))
        self.assertEqual(reponse.context["a_traiter"], 1)
        self.assertNotContains(reponse, commande.numero)
