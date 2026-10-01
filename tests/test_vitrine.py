"""Vitrine publique : ce qu'elle montre, ce qu'elle cache, ce qu'elle crée.

La vitrine est le seul endroit du produit qui lit **en contexte plateforme** —
il le faut, un acheteur cherche sur tout le marché. C'est donc le seul endroit
où une erreur de périmètre exposerait la donnée d'un commerçant à tout le monde,
et ces tests existent d'abord pour cela.

Trois familles :

**Ce qui est en vitrine.** Une boutique suspendue ou sans bail actif disparaît
du catalogue tout en gardant son back-office ; un article désactivé aussi. Le
lien qu'on en avait gardé cesse de fonctionner, et c'est voulu.

**Ce qui n'y est pas.** Le stock, le coût d'achat, la marge. Rien de ce qui
appartient au commerçant ne doit fuir par la page qui sert à lui amener des
clients.

**Ce que le tunnel produit.** Une commande éclatée entre marchands, une
attribution d'affiliation figée, un compte acheteur qui n'ouvre aucune session.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Utilisateur
from apps.affiliation.models import Attribution
from apps.affiliation.services import creer_apporteur
from apps.core.tenancy import contexte_boutique, contexte_plateforme
from apps.inventory.services import entrer_stock
from apps.marketplace.models import Bail, Boutique
from apps.orders.models import Commande, SousCommande
from apps.vitrine import panier as panier_service
from tests import fabrique


class SocleVitrine(TestCase):
    """Deux boutiques ouvertes, un article dans chacune."""

    def setUp(self):
        self.ateba = fabrique.creer_boutique("Ateba")
        self.depot_ateba = fabrique.creer_depot(self.ateba)
        self.brouette = fabrique.creer_variante(self.ateba, prix="34500")
        entrer_stock(
            depot=self.depot_ateba,
            variante=self.brouette,
            quantite=Decimal("6"),
            cout_unitaire=Decimal("21000"),
        )

        self.bella = fabrique.creer_boutique("Bella")
        self.depot_bella = fabrique.creer_depot(self.bella)
        self.creme = fabrique.creer_variante(self.bella, prix="5900")
        entrer_stock(
            depot=self.depot_bella,
            variante=self.creme,
            quantite=Decimal("30"),
            cout_unitaire=Decimal("3000"),
        )

    def ajouter_au_panier(self, article, quantite=1):
        return self.client.post(
            reverse("vitrine_panier_ajouter", args=[article.pk]), {"quantite": quantite}
        )


class CatalogueTest(SocleVitrine):
    def test_l_accueil_montre_les_articles_de_toutes_les_boutiques(self):
        reponse = self.client.get(reverse("vitrine_accueil"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, self.brouette.produit.libelle)
        self.assertContains(reponse, self.creme.produit.libelle)

    def test_chaque_article_nomme_son_commercant(self):
        """Sur une place de marché, savoir qui vend est de premier plan."""
        reponse = self.client.get(reverse("vitrine_catalogue"))
        self.assertContains(reponse, self.ateba.enseigne)
        self.assertContains(reponse, self.bella.enseigne)

    def test_la_recherche_traverse_les_boutiques(self):
        reponse = self.client.get(reverse("vitrine_catalogue"), {"q": self.creme.produit.libelle})
        self.assertContains(reponse, self.creme.produit.libelle)
        self.assertNotContains(reponse, self.brouette.produit.libelle)

    def test_une_boutique_suspendue_disparait_de_la_vitrine(self):
        """Elle garde son back-office : on ne coupe pas sa comptabilité à un marchand."""
        Boutique.objects.filter(pk=self.bella.pk).update(etat=Boutique.SUSPENDUE)

        reponse = self.client.get(reverse("vitrine_catalogue"))
        self.assertNotContains(reponse, self.creme.produit.libelle)
        self.assertContains(reponse, self.brouette.produit.libelle)

    def test_une_boutique_sans_bail_actif_n_est_pas_en_vitrine(self):
        Bail.objects.filter(boutique=self.bella).update(etat=Bail.RESILIE)
        reponse = self.client.get(reverse("vitrine_catalogue"))
        self.assertNotContains(reponse, self.creme.produit.libelle)

    def test_un_article_desactive_n_est_plus_atteignable(self):
        with contexte_boutique(self.bella):
            self.creme.actif = False
            self.creme.save(update_fields=["actif"])

        reponse = self.client.get(reverse("vitrine_article", args=[self.creme.pk]))
        self.assertEqual(reponse.status_code, 404)

    def test_le_lien_d_un_article_de_boutique_suspendue_cesse_de_fonctionner(self):
        Boutique.objects.filter(pk=self.bella.pk).update(etat=Boutique.SUSPENDUE)
        reponse = self.client.get(reverse("vitrine_article", args=[self.creme.pk]))
        self.assertEqual(reponse.status_code, 404)

    def test_la_vitrine_d_une_boutique_ne_montre_que_ses_articles(self):
        reponse = self.client.get(reverse("vitrine_boutique", args=[self.ateba.slug]))
        self.assertContains(reponse, self.brouette.produit.libelle)
        self.assertNotContains(reponse, self.creme.produit.libelle)


class CeQuiNeSortPasTest(SocleVitrine):
    """La vitrine lit en contexte plateforme : c'est là qu'une fuite arriverait."""

    def test_le_stock_n_est_pas_publie(self):
        reponse = self.client.get(reverse("vitrine_article", args=[self.brouette.pk]))
        corps = reponse.content.decode()
        self.assertNotIn("6.0000", corps)
        self.assertNotIn("en stock", corps.lower())

    def test_le_cout_d_achat_n_est_pas_publie(self):
        """21 000 est ce que la brouette a coûté ; 34 500 est ce qu'elle est vendue."""
        for adresse in (
            reverse("vitrine_article", args=[self.brouette.pk]),
            reverse("vitrine_catalogue"),
            reverse("vitrine_boutique", args=[self.ateba.slug]),
        ):
            with self.subTest(adresse=adresse):
                corps = self.client.get(adresse).content.decode()
                self.assertNotIn("21 000", corps)
                self.assertNotIn("21000", corps)

    def test_aucune_page_publique_n_exige_de_compte(self):
        for nom, arguments in (
            ("vitrine_accueil", []),
            ("vitrine_catalogue", []),
            ("vitrine_panier", []),
            ("vitrine_article", [self.brouette.pk]),
            ("vitrine_boutique", [self.ateba.slug]),
        ):
            with self.subTest(page=nom):
                reponse = self.client.get(reverse(nom, args=arguments))
                self.assertEqual(reponse.status_code, 200)


class PanierTest(SocleVitrine):
    def test_un_article_ajoute_se_retrouve_au_panier(self):
        self.ajouter_au_panier(self.brouette, 2)
        reponse = self.client.get(reverse("vitrine_panier"))

        self.assertContains(reponse, self.brouette.produit.libelle)
        self.assertEqual(panier_service.nombre_articles(self.client.session), 2)

    def test_le_panier_traverse_les_boutiques_et_les_groupe(self):
        self.ajouter_au_panier(self.brouette)
        self.ajouter_au_panier(self.creme)

        reponse = self.client.get(reverse("vitrine_panier"))
        self.assertEqual(len(reponse.context["groupes"]), 2)
        self.assertEqual(reponse.context["total"], Decimal("40400.00"))

    def test_le_prix_est_relu_a_chaque_affichage(self):
        """Un prix recopié en session finirait par diverger de celui du marchand."""
        self.ajouter_au_panier(self.brouette)
        with contexte_boutique(self.ateba):
            self.brouette.prix_vente = Decimal("39000")
            self.brouette.save(update_fields=["prix_vente"])

        reponse = self.client.get(reverse("vitrine_panier"))
        self.assertEqual(reponse.context["total"], Decimal("39000.00"))

    def test_un_article_devenu_indisponible_quitte_le_panier(self):
        """Mieux vaut le voir disparaître ici qu'être refusé au dernier écran."""
        self.ajouter_au_panier(self.creme)
        Boutique.objects.filter(pk=self.bella.pk).update(etat=Boutique.SUSPENDUE)

        reponse = self.client.get(reverse("vitrine_panier"))
        self.assertEqual(reponse.context["lignes"], [])

    def test_une_quantite_nulle_retire_la_ligne(self):
        self.ajouter_au_panier(self.brouette, 3)
        self.client.post(reverse("vitrine_panier_modifier", args=[self.brouette.pk]), {"quantite": 0})
        self.assertEqual(panier_service.nombre_articles(self.client.session), 0)

    def test_le_retour_apres_ajout_reste_sur_le_site(self):
        """Une redirection ouverte ferait d'un lien du marché un lien vers ailleurs."""
        reponse = self.client.post(
            reverse("vitrine_panier_ajouter", args=[self.brouette.pk]),
            {"quantite": 1, "suite": "https://ailleurs.example/piege"},
        )
        self.assertEqual(reponse["Location"], reverse("vitrine_panier"))

    def test_une_adresse_relative_deguisee_est_refusee(self):
        reponse = self.client.post(
            reverse("vitrine_panier_ajouter", args=[self.brouette.pk]),
            {"quantite": 1, "suite": "//ailleurs.example/piege"},
        )
        self.assertEqual(reponse["Location"], reverse("vitrine_panier"))


class TunnelTest(SocleVitrine):
    DONNEES = {
        "nom_complet": "Aïcha Nkomo",
        "telephone": "+237690112233",
        "adresse_livraison": "Bonapriso, derrière la pharmacie",
        "note": "Appeler avant midi",
    }

    def _commander(self, **remplacements):
        donnees = {**self.DONNEES, **remplacements}
        return self.client.post(reverse("vitrine_commander"), donnees)

    def test_un_panier_vide_ne_se_commande_pas(self):
        reponse = self.client.get(reverse("vitrine_commander"))
        self.assertRedirects(reponse, reverse("vitrine_catalogue"))

    def test_la_commande_eclate_entre_les_marchands(self):
        self.ajouter_au_panier(self.brouette, 2)
        self.ajouter_au_panier(self.creme, 3)

        reponse = self._commander()
        self.assertEqual(reponse.status_code, 302)

        with contexte_plateforme():
            commande = Commande.objects.get()
            parts = list(SousCommande.objects.filter(commande=commande))
        self.assertEqual(len(parts), 2)
        # 2 × 34 500 + 3 × 5 900
        self.assertEqual(commande.total_ttc, Decimal("86700.00"))

    def test_la_commande_porte_l_adresse_de_livraison(self):
        self.ajouter_au_panier(self.brouette)
        self._commander()

        with contexte_plateforme():
            commande = Commande.objects.get()
        self.assertEqual(commande.adresse_livraison, self.DONNEES["adresse_livraison"])
        self.assertEqual(commande.note, self.DONNEES["note"])

    def test_le_panier_est_vide_apres_la_commande(self):
        self.ajouter_au_panier(self.brouette)
        self._commander()
        self.assertEqual(panier_service.nombre_articles(self.client.session), 0)

    def test_un_compte_est_cree_mais_aucune_session_ouverte(self):
        """Un numéro non vérifié ne doit pas donner accès à son historique."""
        self.ajouter_au_panier(self.brouette)
        self._commander()

        acheteur = Utilisateur.objects.get(telephone=self.DONNEES["telephone"])
        self.assertEqual(acheteur.nom_complet, self.DONNEES["nom_complet"])
        self.assertFalse(acheteur.has_usable_password())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_un_numero_deja_connu_n_est_pas_renomme(self):
        """Un formulaire public ne renomme pas le compte d'un gérant."""
        existant = fabrique.creer_utilisateur("Nom d'origine", telephone="+237690445566")
        self.ajouter_au_panier(self.brouette)
        self._commander(telephone="+237690445566", nom_complet="Nom injecté")

        existant.refresh_from_db()
        self.assertEqual(existant.nom_complet, "Nom d'origine")

    def test_la_commande_arrive_chez_le_marchand_a_traiter(self):
        self.ajouter_au_panier(self.brouette)
        self._commander()

        with contexte_boutique(self.ateba):
            part = SousCommande.objects.get()
        self.assertEqual(part.etat, SousCommande.EN_ATTENTE)

    def test_le_suivi_est_adresse_par_identifiant_et_non_par_numero(self):
        self.ajouter_au_panier(self.brouette)
        reponse = self._commander()

        with contexte_plateforme():
            commande = Commande.objects.get()
        self.assertEqual(reponse["Location"], reverse("vitrine_commande", args=[commande.pk]))

        suivi = self.client.get(reponse["Location"])
        self.assertContains(suivi, commande.numero)
        self.assertContains(suivi, self.ateba.enseigne)


class ParrainageTest(SocleVitrine):
    def setUp(self):
        super().setUp()
        self.awa = creer_apporteur(fabrique.creer_utilisateur("Awa"))

    def test_un_lien_de_parrainage_est_retenu_puis_fige_a_la_commande(self):
        """Un revendeur partage le lien d'un produit, pas celui de l'accueil."""
        self.client.get(
            reverse("vitrine_article", args=[self.brouette.pk]), {"ref": self.awa.code}
        )
        self.assertEqual(
            self.client.session[panier_service.CLE_PARRAINAGE], self.awa.code
        )

        self.ajouter_au_panier(self.brouette)
        self.client.post(reverse("vitrine_commander"), TunnelTest.DONNEES)

        with contexte_plateforme():
            commande = Commande.objects.get()
        self.assertEqual(commande.apporteur_n1, self.awa)
        self.assertTrue(
            Attribution.objects.filter(
                cible_type=Attribution.ACHETEUR, cible_id=commande.acheteur_id
            ).exists()
        )

    def test_un_code_inconnu_ne_bloque_pas_la_commande(self):
        self.client.get(reverse("vitrine_accueil"), {"ref": "INCONNU"})
        self.ajouter_au_panier(self.brouette)
        reponse = self.client.post(reverse("vitrine_commander"), TunnelTest.DONNEES)

        self.assertEqual(reponse.status_code, 302)
        with contexte_plateforme():
            commande = Commande.objects.get()
        self.assertIsNone(commande.apporteur_n1)
