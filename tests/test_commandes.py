"""Commandes en ligne : éclatement, commission figée, effets au bon moment.

Ce que ces tests protègent tient en quatre points.

**Un panier traverse les boutiques et se scinde.** L'acheteur paie une fois,
chaque marchand ne voit que sa part. Une erreur d'éclatement met la marchandise
d'un commerçant dans la comptabilité d'un autre.

**Le taux de commission est figé à la commande.** Une renégociation de bail ne
doit pas changer rétroactivement ce que la plateforme a prélevé sur des mois
clos.

**Chaque effet tombe à son étape.** Les écritures de vente au paiement, la
sortie de stock à l'expédition, le délai de retour à la livraison. Un effet
avancé ou retardé produit des comptes faux qu'aucun rapprochement ne rattrape,
puisque le journal est en ajout seul.

**L'argent du marchand est une créance, pas de la trésorerie.** Une vente en
ligne alimente le séquestre de la plateforme (`5313`), jamais la caisse.
"""

import uuid
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounting.services import solde_compte
from apps.affiliation.models import Attribution, Commission
from apps.affiliation.services import attribuer, creer_apporteur
from apps.core.tenancy import contexte_boutique, contexte_plateforme
from apps.inventory.models import MouvementStock, NiveauStock
from apps.inventory.services import entrer_stock
from apps.orders.models import Commande, LigneCommande, Retour, SousCommande
from apps.orders.services import (
    CommandeInvalide,
    accepter,
    accepter_retour,
    annuler_sous_commande,
    demander_retour,
    expedier,
    livrer,
    marquer_payee,
    passer_commande,
    preparer,
)
from tests import fabrique


class SocleCommande(TestCase):
    """Deux boutiques, un article en stock dans chacune, un acheteur."""

    def setUp(self):
        self.acheteur = fabrique.creer_utilisateur("Acheteuse")

        self.ateba = fabrique.creer_boutique("Ateba")
        self.depot_ateba = fabrique.creer_depot(self.ateba)
        self.brouette = fabrique.creer_variante(self.ateba, prix="11925")
        entrer_stock(
            depot=self.depot_ateba,
            variante=self.brouette,
            quantite=Decimal("10"),
            cout_unitaire=Decimal("7000"),
        )

        self.bella = fabrique.creer_boutique("Bella")
        self.depot_bella = fabrique.creer_depot(self.bella)
        self.creme = fabrique.creer_variante(self.bella, prix="5962.50")
        entrer_stock(
            depot=self.depot_bella,
            variante=self.creme,
            quantite=Decimal("20"),
            cout_unitaire=Decimal("3000"),
        )

    def commander(self, **options):
        lignes = options.pop("lignes", [(self.brouette, Decimal("2"))])
        return passer_commande(acheteur=self.acheteur, lignes=lignes, **options)

    def part(self, commande, boutique):
        with contexte_plateforme():
            return SousCommande.objects.get(commande=commande, boutique=boutique)


class EclatementTest(SocleCommande):
    def test_un_panier_multi_boutiques_produit_une_commande_et_deux_parts(self):
        commande = self.commander(
            lignes=[(self.brouette, Decimal("1")), (self.creme, Decimal("2"))]
        )

        with contexte_plateforme():
            parts = list(SousCommande.objects.filter(commande=commande))
        self.assertEqual(len(parts), 2)
        self.assertEqual({p.boutique_id for p in parts}, {self.ateba.pk, self.bella.pk})

    def test_le_total_de_la_commande_est_la_somme_de_ses_parts(self):
        commande = self.commander(
            lignes=[(self.brouette, Decimal("1")), (self.creme, Decimal("2"))]
        )
        # 11 925 + 2 × 5 962,50
        self.assertEqual(commande.total_ttc, Decimal("23850.00"))

    def test_les_frais_de_livraison_s_ajoutent_au_total_sans_entrer_dans_les_parts(self):
        """Ils ne sont dus à aucun marchand : ils ne doivent pas gonfler sa commission."""
        commande = self.commander(frais_livraison=Decimal("2000"))
        part = self.part(commande, self.ateba)

        self.assertEqual(part.total_ttc, Decimal("23850.00"))
        self.assertEqual(commande.total_ttc, Decimal("25850.00"))

    def test_la_ligne_suit_la_boutique_de_sa_variante(self):
        commande = self.commander(
            lignes=[(self.brouette, Decimal("1")), (self.creme, Decimal("1"))]
        )
        with contexte_boutique(self.ateba):
            lignes = list(LigneCommande.objects.filter(sous_commande__commande=commande))
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes[0].variante_id, self.brouette.pk)

    def test_un_panier_vide_est_refuse(self):
        with self.assertRaises(CommandeInvalide):
            passer_commande(acheteur=self.acheteur, lignes=[])

    def test_le_meme_double_clic_ne_commande_qu_une_fois(self):
        cle = uuid.uuid4()
        premiere = self.commander(operation_id=cle)
        seconde = self.commander(operation_id=cle)

        self.assertEqual(premiere.pk, seconde.pk)
        self.assertEqual(Commande.objects.count(), 1)


class CommissionFigeeTest(SocleCommande):
    def test_le_taux_est_repris_du_bail_actif(self):
        commande = self.commander()
        part = self.part(commande, self.ateba)
        self.assertEqual(part.taux_commission, Decimal("0.0500"))
        # 5 % de 20 000 F HT
        self.assertEqual(part.commission_plateforme, Decimal("1000.00"))

    def test_renegocier_le_bail_ne_touche_pas_les_commandes_passees(self):
        """Sinon la comptabilité du marchand et celle de la plateforme divergent."""
        from apps.marketplace.models import Bail

        commande = self.commander()
        Bail.objects.filter(boutique=self.ateba).update(taux_commission=Decimal("0.1200"))

        part = self.part(commande, self.ateba)
        self.assertEqual(part.taux_commission, Decimal("0.0500"))


class PaiementTest(SocleCommande):
    def test_le_paiement_ecrit_la_vente_le_sequestre_et_la_commission(self):
        commande = self.commander()
        marquer_payee(commande)

        self.assertEqual(commande.etat, Commande.PAYEE)
        # Vente : 20 000 HT + 3 850 de TVA
        self.assertEqual(solde_compte("701", boutique_id=self.ateba.pk), Decimal("-20000.00"))
        self.assertEqual(solde_compte("4431", boutique_id=self.ateba.pk), Decimal("-3850.00"))
        # Le client est soldé par le séquestre : la créance change de débiteur.
        self.assertEqual(solde_compte("411", boutique_id=self.ateba.pk), Decimal("0.00"))
        self.assertEqual(solde_compte("5313", boutique_id=self.ateba.pk), Decimal("23850.00"))
        # Commission de place : une charge, pas une réduction du chiffre d'affaires.
        self.assertEqual(solde_compte("632", boutique_id=self.ateba.pk), Decimal("1000.00"))

    def test_la_vente_en_ligne_ne_touche_jamais_la_caisse(self):
        """L'argent est chez la plateforme : écrire du 571 inventerait de la trésorerie."""
        commande = self.commander()
        marquer_payee(commande)
        self.assertEqual(solde_compte("571", boutique_id=self.ateba.pk), Decimal("0.00"))

    def test_le_stock_ne_bouge_pas_au_paiement(self):
        commande = self.commander()
        marquer_payee(commande)

        with contexte_boutique(self.ateba):
            niveau = NiveauStock.objects.get(variante=self.brouette, depot=self.depot_ateba)
        self.assertEqual(niveau.quantite, Decimal("10.0000"))

    def test_une_notification_recue_deux_fois_ne_comptabilise_qu_une_vente(self):
        commande = self.commander()
        marquer_payee(commande)
        marquer_payee(commande)
        self.assertEqual(solde_compte("701", boutique_id=self.ateba.pk), Decimal("-20000.00"))

    def test_une_commande_deja_livree_ne_se_paie_pas(self):
        commande = self.commander()
        marquer_payee(commande)
        commande.etat = Commande.LIVREE
        commande.save(update_fields=["etat"])
        commande.etat = Commande.LIVREE

        with self.assertRaises(CommandeInvalide):
            marquer_payee(commande)


class ExpeditionTest(SocleCommande):
    def _jusqu_a_l_expedition(self, **options):
        commande = self.commander(**options)
        marquer_payee(commande)
        part = self.part(commande, self.ateba)
        accepter(part)
        preparer(part)
        return commande, part

    def test_le_stock_sort_a_l_expedition_et_pas_avant(self):
        commande, part = self._jusqu_a_l_expedition()
        expedier(part)

        with contexte_boutique(self.ateba):
            niveau = NiveauStock.objects.get(variante=self.brouette, depot=self.depot_ateba)
        self.assertEqual(niveau.quantite, Decimal("8.0000"))

    def test_l_expedition_ecrit_la_sortie_de_stock_au_cmp(self):
        """La sortie est valorisée au CMP réellement appliqué, pas au prix de vente.

        Note sur le solde du 311 : il ressort négatif ici, et ce n'est pas un
        défaut de ce module. **Aucune entrée en stock n'écrit sa contrepartie
        comptable** — `entrer_stock` ne comptabilise rien, ni pour une réception
        fournisseur ni pour une reprise. Le débit `311` / crédit `6031` de la
        table du document 07 §3.4 n'est pas branché, pas plus que le cycle
        d'achat `6011` + `4452` / `401` qui l'accompagne. C'est un manque
        antérieur à la commande en ligne, qui affecte aussi la vente au
        comptoir, et il relève du lot 3.
        """
        commande, part = self._jusqu_a_l_expedition()
        expedier(part)
        # 2 × 7 000, au coût moyen pondéré
        self.assertEqual(solde_compte("6031", boutique_id=self.ateba.pk), Decimal("14000.00"))
        self.assertEqual(solde_compte("311", boutique_id=self.ateba.pk), Decimal("-14000.00"))

    def test_expedier_deux_fois_ne_destocke_pas_deux_fois(self):
        commande, part = self._jusqu_a_l_expedition()
        expedier(part)
        with self.assertRaises(CommandeInvalide):
            expedier(part)

        with contexte_boutique(self.ateba):
            niveau = NiveauStock.objects.get(variante=self.brouette, depot=self.depot_ateba)
        self.assertEqual(niveau.quantite, Decimal("8.0000"))

    def test_on_ne_saute_pas_une_etape(self):
        commande = self.commander()
        marquer_payee(commande)
        part = self.part(commande, self.ateba)

        with self.assertRaises(CommandeInvalide):
            expedier(part)


class LivraisonTest(SocleCommande):
    def _livrer_tout(self, commande):
        with contexte_plateforme():
            parts = list(SousCommande.objects.filter(commande=commande))
        for part in parts:
            accepter(part)
            preparer(part)
            expedier(part)
            livrer(part)
        commande.refresh_from_db()
        return parts

    def test_la_commande_passe_a_livree_quand_toutes_ses_parts_le_sont(self):
        commande = self.commander(
            lignes=[(self.brouette, Decimal("1")), (self.creme, Decimal("1"))]
        )
        marquer_payee(commande)

        parts = self._livrer_tout(commande)
        self.assertEqual(len(parts), 2)
        self.assertEqual(commande.etat, Commande.LIVREE)
        self.assertIsNotNone(commande.livree_le)

    def test_une_seule_part_livree_ne_livre_pas_la_commande(self):
        commande = self.commander(
            lignes=[(self.brouette, Decimal("1")), (self.creme, Decimal("1"))]
        )
        marquer_payee(commande)
        part = self.part(commande, self.ateba)
        accepter(part)
        preparer(part)
        expedier(part)
        livrer(part)

        commande.refresh_from_db()
        self.assertEqual(commande.etat, Commande.PAYEE)

    def test_une_commande_dont_tout_est_refuse_est_annulee_pas_livree(self):
        """Sinon des commissions s'acquerraient sur un chiffre d'affaires inexistant."""
        commande = self.commander()
        marquer_payee(commande)
        annuler_sous_commande(self.part(commande, self.ateba), motif="Rupture")

        commande.refresh_from_db()
        self.assertEqual(commande.etat, Commande.ANNULEE)


class AffiliationDeLaCommandeTest(SocleCommande):
    def setUp(self):
        super().setUp()
        self.awa = creer_apporteur(fabrique.creer_utilisateur("Awa"))
        self.junior = creer_apporteur(fabrique.creer_utilisateur("Junior"), parrain=self.awa)

    def test_un_code_presente_a_la_commande_fige_l_attribution(self):
        commande = self.commander(code_apporteur=self.junior.code)

        self.assertEqual(commande.apporteur_n1, self.junior)
        self.assertEqual(commande.apporteur_n2, self.awa)
        self.assertTrue(
            Attribution.objects.filter(
                cible_type=Attribution.ACHETEUR, cible_id=self.acheteur.pk
            ).exists()
        )

    def test_une_attribution_existante_n_est_pas_volee_par_un_code_ulterieur(self):
        """Protection contre le vol d'attribution (docs/06, §6)."""
        attribuer(
            apporteur=self.awa,
            cible_type=Attribution.ACHETEUR,
            cible_id=self.acheteur.pk,
            origine=Attribution.CLIC,
        )
        commande = self.commander(code_apporteur=self.junior.code)
        self.assertEqual(commande.apporteur_n1, self.awa)

    def test_un_code_inconnu_ne_fait_pas_echouer_la_commande(self):
        commande = self.commander(code_apporteur="ZZZZZZ")
        self.assertIsNone(commande.apporteur_n1)
        self.assertEqual(commande.code_apporteur, "ZZZZZZ")

    def test_les_commissions_naissent_au_paiement_a_l_etat_attendue(self):
        commande = self.commander(code_apporteur=self.junior.code)
        self.assertEqual(Commission.objects.count(), 0, "rien avant l'encaissement")

        marquer_payee(commande)
        commissions = list(Commission.objects.all())
        self.assertTrue(commissions)
        self.assertTrue(all(c.etat == Commission.ATTENDUE for c in commissions))

    def test_le_cumul_des_apporteurs_reste_sous_le_plafond(self):
        commande = self.commander(code_apporteur=self.junior.code)
        marquer_payee(commande)
        part = self.part(commande, self.ateba)

        cumul = sum(
            (c.montant for c in Commission.objects.filter(sous_commande=part)), Decimal("0")
        )
        plafond = part.commission_plateforme * Decimal("0.35")
        self.assertLessEqual(cumul, plafond)

    def test_annuler_une_part_annule_ses_commissions(self):
        commande = self.commander(code_apporteur=self.junior.code)
        marquer_payee(commande)
        part = self.part(commande, self.ateba)

        annuler_sous_commande(part, motif="Rupture de stock")
        etats = set(Commission.objects.filter(sous_commande=part).values_list("etat", flat=True))
        self.assertEqual(etats, {Commission.ANNULEE})


class RetourTest(SocleCommande):
    def _livrer(self):
        commande = self.commander()
        marquer_payee(commande)
        part = self.part(commande, self.ateba)
        accepter(part)
        preparer(part)
        expedier(part)
        livrer(part)
        return commande, part

    def test_on_ne_retourne_que_ce_qui_est_parti(self):
        commande = self.commander()
        marquer_payee(commande)
        with self.assertRaises(CommandeInvalide):
            demander_retour(self.part(commande, self.ateba), motif="Trop tard")

    def test_un_retour_accepte_reintegre_le_stock_a_son_cout_de_sortie(self):
        """Au coût de sortie, pas au CMP courant : rien n'a produit de plus-value."""
        commande, part = self._livrer()
        with contexte_boutique(self.ateba):
            avant = NiveauStock.objects.get(variante=self.brouette, depot=self.depot_ateba)
        self.assertEqual(avant.quantite, Decimal("8.0000"))

        retour = demander_retour(part, motif="Article abîmé")
        accepter_retour(retour)

        with contexte_boutique(self.ateba):
            apres = NiveauStock.objects.get(variante=self.brouette, depot=self.depot_ateba)
            entree = MouvementStock.objects.filter(
                origine_type="orders.SousCommande.retour", origine_id=part.pk
            ).first()
        self.assertEqual(apres.quantite, Decimal("10.0000"))
        self.assertEqual(apres.cmp, Decimal("7000.0000"))
        self.assertEqual(entree.cout_unitaire, Decimal("7000.0000"))

    def test_un_retour_accepte_annule_les_commissions(self):
        awa = creer_apporteur(fabrique.creer_utilisateur("Awa retour"))
        attribuer(
            apporteur=awa,
            cible_type=Attribution.ACHETEUR,
            cible_id=self.acheteur.pk,
            origine=Attribution.CODE,
        )
        commande, part = self._livrer()

        retour = demander_retour(part, motif="Article abîmé")
        accepter_retour(retour)

        etats = set(Commission.objects.filter(sous_commande=part).values_list("etat", flat=True))
        self.assertEqual(etats, {Commission.ANNULEE})

    def test_un_retour_ne_se_tranche_qu_une_fois(self):
        commande, part = self._livrer()
        retour = demander_retour(part, motif="Article abîmé")
        accepter_retour(retour)

        with self.assertRaises(CommandeInvalide):
            accepter_retour(retour)

    def test_le_montant_rembourse_par_defaut_est_le_total_de_la_part(self):
        commande, part = self._livrer()
        retour = accepter_retour(demander_retour(part, motif="Erreur"))
        self.assertEqual(retour.montant_rembourse, Decimal("23850.00"))


class IsolationDesCommandesTest(SocleCommande):
    def test_une_boutique_ne_voit_que_sa_part(self):
        commande = self.commander(
            lignes=[(self.brouette, Decimal("1")), (self.creme, Decimal("1"))]
        )
        with contexte_boutique(self.ateba):
            self.assertEqual(SousCommande.objects.filter(commande=commande).count(), 1)
        with contexte_boutique(self.bella):
            self.assertEqual(SousCommande.objects.filter(commande=commande).count(), 1)

    def test_les_ecritures_restent_chez_leur_marchand(self):
        commande = self.commander(
            lignes=[(self.brouette, Decimal("1")), (self.creme, Decimal("1"))]
        )
        marquer_payee(commande)

        self.assertEqual(solde_compte("701", boutique_id=self.ateba.pk), Decimal("-10000.00"))
        self.assertEqual(solde_compte("701", boutique_id=self.bella.pk), Decimal("-5000.00"))
