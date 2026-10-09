"""Ce que les remboursements et les ventes à la livraison écrivent dans les livres du marchand.

Ce que ces tests protègent :

* **un remboursement total défait la vente** : chiffre d'affaires, TVA collectée, créance sur la
  plateforme et commission reviennent à zéro — un marchand remboursé ne déclare pas une TVA qu'il
  n'a pas encaissée ;
* **un remboursement partiel est un avoir au prorata**, et le `5313` qui reste est exactement la
  part libérée ;
* **rien ne s'écrit deux fois** ;
* **une vente payée à la livraison entre dans les livres à la remise**, avec sa commission due.
"""

from decimal import Decimal

from apps.accounting.services import comptabiliser_remboursement, solde_compte
from apps.core.tenancy import contexte_boutique
from apps.orders.models import SousCommande
from apps.orders.services import livrer
from apps.payments import sequestre as service
from apps.payments.models import Sequestre
from tests.test_sequestre import SocleSequestre


class RemboursementTest(SocleSequestre):
    def solde(self, numero):
        with contexte_boutique(self.ateba):
            return solde_compte(numero, boutique_id=self.ateba.pk)

    def _sequestre(self, part):
        return Sequestre.objects.get(sous_commande=part)

    def test_un_remboursement_total_defait_la_vente(self):
        _, part = self.payee()
        self.assertLess(self.solde("701"), 0, "la vente est bien au crédit du 701")

        service.rembourser(self._sequestre(part), motif="Article jamais livré")

        for numero in ("701", "4431", "5313", "401", "632"):
            with self.subTest(compte=numero):
                self.assertEqual(self.solde(numero), 0)

    def test_rien_ne_s_ecrit_deux_fois(self):
        _, part = self.payee()
        sequestre = service.rembourser(self._sequestre(part), motif="Article jamais livré")
        with contexte_boutique(self.ateba):
            self.assertEqual(comptabiliser_remboursement(sequestre), [])
        self.assertEqual(self.solde("701"), 0)

    def test_un_remboursement_partiel_est_un_avoir_au_prorata(self):
        _, part = self.payee()
        vente_ht = -self.solde("701")
        sequestre = self._sequestre(part)
        rendu = Decimal("5000")

        sequestre = service.rembourser(sequestre, montant_marchand=rendu, motif="Un article abîmé")

        avoir_ht = (rendu * part.total_ht / part.total_ttc).quantize(Decimal("0.01"))
        self.assertEqual(-self.solde("701"), vente_ht - avoir_ht)
        # Ce qui reste sur la créance plateforme est exactement la part libérée au marchand.
        self.assertEqual(self.solde("5313"), sequestre.montant_libere)
        with contexte_boutique(self.ateba):
            self.assertEqual(comptabiliser_remboursement(sequestre), [], "l'avoir ne se repasse pas")


class VenteALaLivraisonTest(SocleSequestre):
    def solde(self, numero):
        with contexte_boutique(self.ateba):
            return solde_compte(numero, boutique_id=self.ateba.pk)

    def test_la_vente_entre_dans_les_livres_a_la_remise(self):
        commande = self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
        part = self.expediee(self.part(commande))
        self.assertEqual(self.solde("701"), 0, "rien n'est encaissé avant la remise")

        livrer(part)

        self.recharger(part)
        self.assertEqual(-self.solde("701"), part.total_ht)
        self.assertEqual(self.solde("571"), part.total_ttc, "le livreur rapporte le TTC en caisse")
        self.assertEqual(self.solde("411"), 0)
        # La commission due (401) est aussitôt compensée sur ce que la plateforme doit au marchand
        # (5313) : la dette s'éteint, et le compte plateforme porte la retenue.
        commission = service.commission_ttc(part)
        self.assertGreater(commission, 0)
        self.assertEqual(self.solde("401"), 0)
        self.assertEqual(self.solde("5313"), -commission)

    def test_la_commission_est_retenue_sur_le_disponible_et_l_argent_tombe_juste(self):
        from apps.payments import versements

        commande = self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
        part = self.expediee(self.part(commande))
        livrer(part)
        self.recharger(part)

        bilan = service.bilan(self.ateba)
        self.assertEqual(bilan["disponible"], -service.commission_ttc(part))
        self.assertEqual(bilan["commissions_compensees"], service.commission_ttc(part))
        self.assertEqual(bilan["ecart"], 0, "aucun franc ne disparaît ni n'apparaît")

    def test_la_compensation_ne_se_fait_qu_une_fois(self):
        commande = self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
        part = self.expediee(self.part(commande))
        livrer(part)
        self.recharger(part)
        service.compenser_commission_a_la_livraison(part)
        self.assertEqual(service.bilan(self.ateba)["disponible"], -service.commission_ttc(part))


from tests.test_versements import SocleVersement  # noqa: E402


class DetteDeCommissionTest(SocleVersement):
    def test_tant_que_la_dette_court_rien_n_est_verse_et_le_marchand_sait_pourquoi(self):
        from apps.payments import versements

        self.compte()
        commande = self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
        part = self.expediee(self.part(commande))
        livrer(part)
        with self.assertRaisesMessage(versements.VersementRefuse, "ventes payées à la livraison"):
            versements.demander_versement(self.ateba, par=self.gerant)
        self.verifier_l_invariant()
