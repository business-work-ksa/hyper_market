"""Tests du moteur d'affiliation.

Vérifie que les garde-fous juridiques du docs/06, §2.3 sont bien dans le code et pas seulement
dans la documentation : profondeur limitée à 2 niveaux, plafond de reversement à 35 %, commission
assise sur du chiffre d'affaires encaissé et non annulé.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.affiliation.models import Apporteur, Attribution, Commission, FiliationInvalide, Revendeur
from apps.affiliation.services import (
    acquerir_commissions,
    annuler_commissions,
    attribuer,
    calculer_commissions,
    creer_apporteur,
    resoudre_apporteurs,
)
from apps.core.tenancy import contexte_boutique
from apps.orders.models import Commande, LigneCommande, SousCommande
from tests import fabrique


class FiliationTest(TestCase):
    def setUp(self):
        self.awa = creer_apporteur(fabrique.creer_utilisateur("Awa"))
        self.junior = creer_apporteur(fabrique.creer_utilisateur("Junior"), parrain=self.awa)
        self.sandrine = creer_apporteur(fabrique.creer_utilisateur("Sandrine"), parrain=self.junior)

    def test_deux_niveaux_renseignes(self):
        self.assertEqual(self.sandrine.parrain_n1, self.junior)
        self.assertEqual(self.sandrine.parrain_n2, self.awa)

    def test_la_chaine_s_arrete_a_deux_niveaux(self):
        """Arbitrage A11 : Awa ne touche rien sur le filleul de Sandrine."""
        eric = creer_apporteur(fabrique.creer_utilisateur("Éric"), parrain=self.sandrine)
        self.assertEqual(eric.parrain_n1, self.sandrine)
        self.assertEqual(eric.parrain_n2, self.junior)
        self.assertNotEqual(eric.parrain_n2, self.awa)

    def test_auto_parrainage_refuse(self):
        with self.assertRaises(FiliationInvalide):
            self.awa.rattacher(self.awa)

    def test_cycle_refuse(self):
        with self.assertRaises(FiliationInvalide):
            self.awa.rattacher(self.junior)

    def test_filiation_definitive(self):
        autre = creer_apporteur(fabrique.creer_utilisateur("Autre"))
        with self.assertRaises(FiliationInvalide):
            self.sandrine.rattacher(autre)

    def test_code_apporteur_sans_caracteres_ambigus(self):
        for apporteur in Apporteur.objects.all():
            self.assertNotIn("O", apporteur.code[3:])
            self.assertNotIn("0", apporteur.code[3:])
            self.assertNotIn("I", apporteur.code[3:])
            self.assertNotIn("1", apporteur.code[3:])


class AttributionTest(TestCase):
    def setUp(self):
        self.awa = creer_apporteur(fabrique.creer_utilisateur("Awa"))
        self.junior = creer_apporteur(fabrique.creer_utilisateur("Junior"), parrain=self.awa)
        self.acheteur = fabrique.creer_utilisateur("Acheteuse")

    def test_resolution_des_deux_niveaux(self):
        attribuer(
            apporteur=self.junior,
            cible_type=Attribution.ACHETEUR,
            cible_id=self.acheteur.pk,
            origine=Attribution.CODE,
        )
        n1, n2 = resoudre_apporteurs(self.acheteur)
        self.assertEqual(n1, self.junior)
        self.assertEqual(n2, self.awa)

    def test_sans_attribution_aucun_apporteur(self):
        self.assertEqual(resoudre_apporteurs(self.acheteur), (None, None))

    def test_attribution_non_ecrasee(self):
        """Protection contre le vol d'attribution : le premier rattachement l'emporte."""
        attribuer(
            apporteur=self.junior,
            cible_type=Attribution.ACHETEUR,
            cible_id=self.acheteur.pk,
            origine=Attribution.CODE,
        )
        attribuer(
            apporteur=self.awa,
            cible_type=Attribution.ACHETEUR,
            cible_id=self.acheteur.pk,
            origine=Attribution.CLIC,
        )
        n1, _ = resoudre_apporteurs(self.acheteur)
        self.assertEqual(n1, self.junior)

    def test_apporteur_suspendu_ne_percoit_rien(self):
        attribuer(
            apporteur=self.junior,
            cible_type=Attribution.ACHETEUR,
            cible_id=self.acheteur.pk,
            origine=Attribution.CODE,
        )
        Apporteur.objects.filter(pk=self.junior.pk).update(etat=Apporteur.SUSPENDU)
        self.assertEqual(resoudre_apporteurs(self.acheteur), (None, None))


class CommissionTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique(avec_comptabilite=False)
        self.contexte = contexte_boutique(self.boutique)
        self.contexte.__enter__()
        self.addCleanup(self.contexte.__exit__, None, None, None)

        self.awa = creer_apporteur(fabrique.creer_utilisateur("Awa"))
        self.junior = creer_apporteur(fabrique.creer_utilisateur("Junior"), parrain=self.awa)
        self.acheteur = fabrique.creer_utilisateur("Acheteuse")
        self.variante = fabrique.creer_variante(self.boutique, prix="11925")

    def _sous_commande(self, *, avec_apporteurs=True, revendeur=None, quantite="10"):
        n1, n2 = (self.junior, self.awa) if avec_apporteurs else (None, None)
        commande = Commande.objects.create(
            numero=Commande.numero_suivant(),
            acheteur=self.acheteur,
            apporteur_n1=n1,
            apporteur_n2=n2,
            revendeur=revendeur,
        )
        sous_commande = SousCommande.objects.create(
            boutique=self.boutique,
            commande=commande,
            taux_commission=Decimal("0.0500"),
        )
        LigneCommande.objects.create(
            boutique=self.boutique,
            sous_commande=sous_commande,
            variante=self.variante,
            libelle=str(self.variante),
            quantite=Decimal(quantite),
            pu_ttc=self.variante.prix_vente,
            taux_tva=self.variante.taux_tva,
        )
        sous_commande.recalculer()
        return sous_commande

    def test_assiette_est_la_commission_plateforme(self):
        """La commission d'affiliation ne s'ajoute jamais au prix payé par l'acheteur."""
        sous_commande = self._sous_commande()
        # 10 × 11 925 TTC = 119 250 TTC → 100 000 HT → 5 % = 5 000 F de commission plateforme.
        self.assertEqual(sous_commande.total_ht, Decimal("100000.00"))
        self.assertEqual(sous_commande.commission_plateforme, Decimal("5000.00"))

    def test_parts_n1_et_n2(self):
        sous_commande = self._sous_commande()
        calculer_commissions(sous_commande)

        n1 = Commission.objects.get(sous_commande=sous_commande, role=Commission.N1)
        n2 = Commission.objects.get(sous_commande=sous_commande, role=Commission.N2)
        self.assertEqual(n1.montant, Decimal("500.00"))  # 10 % de 5 000
        self.assertEqual(n2.montant, Decimal("150.00"))  # 3 % de 5 000
        self.assertEqual(n1.beneficiaire, self.junior.utilisateur)
        self.assertEqual(n2.beneficiaire, self.awa.utilisateur)

    @override_settings(
        AFFILIATION={
            **settings.AFFILIATION,
            "PART_N1": "0.30",  # barème volontairement excessif : le plafond doit écrêter
            "PART_N2": "0.20",
        }
    )
    def test_plafond_de_reversement_a_35_pourcent(self):
        """Invariant 2 : N1 + N2 ne dépassent jamais 35 % de la commission plateforme."""
        sous_commande = self._sous_commande()
        calculer_commissions(sous_commande)

        n1 = Commission.objects.get(sous_commande=sous_commande, role=Commission.N1)
        n2 = Commission.objects.get(sous_commande=sous_commande, role=Commission.N2)

        # 30 % de 5 000 = 1 500 pour N1 ; N2 demanderait 1 000 mais le plafond ne laisse que 250.
        self.assertEqual(n1.montant, Decimal("1500.00"))
        self.assertEqual(n2.montant, Decimal("250.00"))
        self.assertEqual(n1.montant + n2.montant, sous_commande.commission_plateforme * Decimal("0.35"))

    def test_marge_revendeur_prise_sur_la_marge_marchand(self):
        """Le revendeur est payé par le marchand : il ne consomme pas la commission plateforme."""
        from apps.affiliation.models import CatalogueRevendeur

        revendeur = Revendeur.objects.create(
            utilisateur=fabrique.creer_utilisateur("Revendeur"), slug_vitrine="revendeur-test"
        )
        CatalogueRevendeur.objects.create(
            revendeur=revendeur, variante=self.variante, marge=Decimal("0.1000")
        )

        sous_commande = self._sous_commande(revendeur=revendeur)
        calculer_commissions(sous_commande)

        commission = Commission.objects.get(
            sous_commande=sous_commande, role=Commission.REVENDEUR
        )
        # 10 % des 100 000 F HT vendus, indépendamment des 5 000 F de commission plateforme.
        self.assertEqual(commission.assiette, Decimal("100000.00"))
        self.assertEqual(commission.montant, Decimal("10000.00"))

        # Les apporteurs restent, eux, plafonnés sur la commission plateforme.
        apporteurs = Commission.objects.filter(
            sous_commande=sous_commande, role__in=[Commission.N1, Commission.N2]
        )
        cumul = sum(c.montant for c in apporteurs)
        self.assertLessEqual(cumul, sous_commande.commission_plateforme * Decimal("0.35"))

    def test_marge_revendeur_superieure_a_100_pourcent_refusee(self):
        from django.db.utils import IntegrityError

        from apps.affiliation.models import CatalogueRevendeur

        revendeur = Revendeur.objects.create(
            utilisateur=fabrique.creer_utilisateur("Revendeur"), slug_vitrine="revendeur-abusif"
        )
        with self.assertRaises(IntegrityError):
            CatalogueRevendeur.objects.create(
                revendeur=revendeur, variante=self.variante, marge=Decimal("1.5000")
            )

    def test_sans_apporteur_aucune_commission(self):
        sous_commande = self._sous_commande(avec_apporteurs=False)
        self.assertEqual(calculer_commissions(sous_commande), [])

    def test_calcul_idempotent(self):
        sous_commande = self._sous_commande()
        calculer_commissions(sous_commande)
        calculer_commissions(sous_commande)
        self.assertEqual(Commission.objects.filter(sous_commande=sous_commande).count(), 2)

    def test_rien_n_est_acquis_avant_le_delai_de_retour(self):
        """Invariant 3 : la protection contre la fraude par commande fictive."""
        sous_commande = self._sous_commande()
        calculer_commissions(sous_commande)
        sous_commande.livree_le = timezone.now()
        sous_commande.save(update_fields=["livree_le"])

        self.assertEqual(acquerir_commissions(sous_commande), 0)
        self.assertEqual(
            Commission.objects.filter(etat=Commission.ATTENDUE).count(), 2
        )

    def test_acquisition_apres_le_delai(self):
        sous_commande = self._sous_commande()
        calculer_commissions(sous_commande)
        sous_commande.livree_le = timezone.now() - timedelta(days=8)
        sous_commande.save(update_fields=["livree_le"])

        self.assertEqual(acquerir_commissions(sous_commande), 2)
        self.assertEqual(Commission.objects.filter(etat=Commission.ACQUISE).count(), 2)

    def test_acquisition_impossible_sans_livraison(self):
        sous_commande = self._sous_commande()
        calculer_commissions(sous_commande)
        with self.assertRaises(Exception):
            acquerir_commissions(sous_commande)

    def test_retour_annule_les_commissions(self):
        sous_commande = self._sous_commande()
        calculer_commissions(sous_commande)
        self.assertEqual(annuler_commissions(sous_commande), 2)
        self.assertEqual(Commission.objects.filter(etat=Commission.ANNULEE).count(), 2)

    def test_commission_deja_payee_est_reprise_et_non_annulee(self):
        sous_commande = self._sous_commande()
        calculer_commissions(sous_commande)
        Commission.objects.filter(sous_commande=sous_commande).update(etat=Commission.PAYEE)

        annuler_commissions(sous_commande)

        self.assertEqual(Commission.objects.filter(etat=Commission.REPRISE).count(), 2)
        self.assertEqual(Commission.objects.filter(etat=Commission.ANNULEE).count(), 0)
