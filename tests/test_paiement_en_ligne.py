"""Payer une commande en ligne, de la vitrine au séquestre.

Ce que ces tests protègent :

* **le prépaiement n'est proposé que s'il peut être payé** — sinon l'acheteur s'engage dans une
  commande qu'il ne pourra pas régler ;
* **une seule demande vivante par commande** — deux clics ne font pas deux demandes sur le téléphone ;
* **seul un paiement réussi, du bon montant, ouvre le séquestre** ;
* **une notification ne prouve rien** : son corps n'est jamais cru, le statut est relu auprès de
  l'opérateur ; un jeton Orange faux est refusé ;
* **le routage ne confond pas « à la livraison » avec une passerelle de paiement.**
"""

from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.management.commands.initialiser_referentiels import PRESTATAIRES
from apps.orders.models import Commande
from apps.payments import paiement_en_ligne as service
from apps.payments.adaptateurs import StatutTransaction, disjoncteur
from apps.payments.models import Prestataire, Sequestre, Transaction
from apps.payments.operateurs import AdaptateurOrangeMoney
from apps.payments.services import choisir_prestataire
from tests.test_sequestre import PRIX, SocleSequestre


def _prestataires():
    for code, libelle, frais, prefixes in PRESTATAIRES:
        Prestataire.objects.update_or_create(
            code=code,
            defaults={"libelle": libelle, "taux_frais": Decimal(frais), "prefixes_numero": prefixes},
        )


class RoutageTest(TestCase):
    def setUp(self):
        _prestataires()
        disjoncteur.reinitialiser()
        self.addCleanup(disjoncteur.reinitialiser)

    def test_le_paiement_a_la_livraison_n_est_jamais_une_passerelle(self):
        """Frais nuls, donc premier au tri : sans l'exclusion, il recevait les numéros en panne."""
        Prestataire.objects.filter(code=Prestataire.CARTE).update(actif=False)
        for _ in range(3):
            disjoncteur.echec(Prestataire.MTN_MOMO)
        with self.assertRaises(Exception):
            choisir_prestataire("+237677220022")


class PropositionDuPrepaiementTest(SocleSequestre):
    def _page(self):
        self.client.post(reverse("vitrine_panier_ajouter", args=[self.brouette.pk]), {"quantite": 1})
        return self.client.get(reverse("vitrine_commander"))

    def test_sans_moyen_de_payer_le_prepaiement_n_est_pas_propose(self):
        page = self._page()
        self.assertNotContains(page, "Payer d&#x27;avance par Mobile Money")
        self.assertContains(page, "pas encore ouvert")

    @override_settings(PAIEMENTS_SIMULES=True)
    def test_en_demonstration_il_l_est_et_la_page_le_dit(self):
        page = self._page()
        self.assertContains(page, "Payer d&#x27;avance par Mobile Money")

    def test_un_envoi_force_ne_cree_pas_de_prepaiement(self):
        self.client.post(reverse("vitrine_panier_ajouter", args=[self.brouette.pk]), {"quantite": 1})
        self.client.post(
            reverse("vitrine_commander"),
            {
                "nom_complet": "Marie Ekedi",
                "telephone": "+237699000123",
                "adresse_livraison": "Akwa",
                "mode_paiement": "prepaye",
            },
        )
        # Le choix « prépayé » n'existe pas dans la page : l'envoi forgé est refusé par le
        # formulaire, et aucune commande prépayée ne naît.
        from apps.core.tenancy import contexte_plateforme
        from apps.orders.models import SousCommande

        # Sous contexte : sans lui, la barrière 3 ne montrerait rien et le test passerait à vide.
        with contexte_plateforme():
            self.assertFalse(SousCommande.objects_all_tenants.filter(mode_paiement=SousCommande.PREPAYE).exists())


@override_settings(PAIEMENTS_SIMULES=True)
class ParcoursSimuleTest(SocleSequestre):
    """La démonstration : le simulateur répond selon le dernier chiffre du numéro."""

    def _commande_passee(self):
        self.client.post(reverse("vitrine_panier_ajouter", args=[self.brouette.pk]), {"quantite": 2})
        self.client.post(
            reverse("vitrine_commander"),
            {
                "nom_complet": "Marie Ekedi",
                "telephone": "+237699000123",
                "adresse_livraison": "Akwa",
                "mode_paiement": "prepaye",
            },
        )
        return Commande.objects.get()

    def test_payer_ouvre_le_sequestre(self):
        commande = self._commande_passee()
        self.assertEqual(service.montant_a_payer(commande), Decimal(PRIX) * 2)
        page = self.client.get(reverse("vitrine_commande", args=[commande.pk]))
        self.assertContains(page, "Paiement d'avance attendu")
        self.assertContains(page, "aucun argent réel")

        self.client.post(reverse("vitrine_payer", args=[commande.pk]), {"numero": "+237699000125"})

        commande.refresh_from_db()
        self.assertEqual(commande.etat, Commande.PAYEE)
        self.assertEqual(Sequestre.objects.filter(etat=Sequestre.BLOQUE).count(), 1)

    def test_un_refus_laisse_reessayer_avec_une_nouvelle_cle(self):
        commande = self._commande_passee()
        self.client.post(reverse("vitrine_payer", args=[commande.pk]), {"numero": "+237699000120"})
        commande.refresh_from_db()
        self.assertEqual(commande.etat, Commande.CONFIRMEE)
        self.client.post(reverse("vitrine_payer", args=[commande.pk]), {"numero": "+237699000125"})
        commande.refresh_from_db()
        self.assertEqual(commande.etat, Commande.PAYEE)
        cles = set(Transaction.objects.values_list("cle_idempotence", flat=True))
        self.assertEqual(len(cles), 2)

    def test_une_demande_en_attente_n_en_lance_pas_une_seconde(self):
        """Deux clics ne font pas deux demandes sur le téléphone de l'acheteur."""
        commande = self._commande_passee()
        with mock.patch(
            "apps.payments.adaptateurs.FauxPrestataire.statut",
            return_value=StatutTransaction(etat=Transaction.INITIEE, message="attente"),
        ):
            for _ in range(2):
                self.client.post(reverse("vitrine_payer", args=[commande.pk]), {"numero": "+237699000129"})
        self.assertEqual(Transaction.objects.filter(commande=commande).count(), 1)

    def test_un_inconnu_ne_paie_pas_ni_ne_lit_l_etat(self):
        commande = self._commande_passee()
        autre = self.client_class()
        reponse = autre.post(reverse("vitrine_payer", args=[commande.pk]), {"numero": "+237699000125"})
        self.assertEqual(reponse.status_code, 404)
        self.assertFalse(Transaction.objects.exists())


class ConstatTest(SocleSequestre):
    def setUp(self):
        super().setUp()
        _prestataires()
        self.commande = self.commander()
        self.mtn = Prestataire.objects.get(code=Prestataire.MTN_MOMO)

    def _transaction(self, montant, etat=Transaction.REUSSIE):
        return Transaction.objects.create(
            commande=self.commande,
            prestataire=self.mtn,
            sens=Transaction.ENCAISSEMENT,
            montant=montant,
            numero_payeur="+237677220022",
            etat=etat,
            cle_idempotence=f"test-{montant}-{etat}",
            reference_externe="uuid-mtn",
        )

    def test_un_montant_different_n_ouvre_pas_de_sequestre(self):
        operation = self._transaction(Decimal("100"))
        self.assertFalse(service.constater(operation))
        self.commande.refresh_from_db()
        self.assertEqual(self.commande.etat, Commande.CONFIRMEE)
        operation.refresh_from_db()
        self.assertIn("anomalie", operation.charge_utile_psp)

    def test_le_bon_montant_ouvre_le_sequestre_une_seule_fois(self):
        operation = self._transaction(service.montant_a_payer(self.commande))
        self.assertTrue(service.constater(operation))
        self.assertTrue(service.constater(operation))
        self.assertEqual(Sequestre.objects.count(), 1)


class NotificationsTest(SocleSequestre):
    def setUp(self):
        super().setUp()
        _prestataires()
        self.commande = self.commander()
        self.montant = service.montant_a_payer(self.commande)

    def _operation(self, code, **charge):
        return Transaction.objects.create(
            commande=self.commande,
            prestataire_id=code,
            sens=Transaction.ENCAISSEMENT,
            montant=self.montant,
            numero_payeur="+237677220022",
            cle_idempotence=f"notif-{code}",
            reference_externe="ref-op",
            charge_utile_psp=charge,
        )

    def test_mtn_le_corps_n_est_jamais_cru(self):
        """Un corps qui annonce SUCCESSFUL ne suffit pas : l'opérateur, relu, dit PENDING."""
        operation = self._operation(Prestataire.MTN_MOMO)
        with mock.patch(
            "apps.payments.operateurs.AdaptateurMtnMomo.statut",
            return_value=StatutTransaction(etat=Transaction.INITIEE, message="PENDING"),
        ) as relu:
            reponse = self.client.post(
                "/paiements/notifications/mtn/",
                data={"externalId": str(operation.pk), "status": "SUCCESSFUL"},
                content_type="application/json",
            )
        self.assertEqual(reponse.status_code, 200)
        relu.assert_called_once()
        self.commande.refresh_from_db()
        self.assertEqual(self.commande.etat, Commande.CONFIRMEE)

    def test_mtn_relu_reussi_ouvre_le_sequestre(self):
        operation = self._operation(Prestataire.MTN_MOMO)
        with mock.patch(
            "apps.payments.operateurs.AdaptateurMtnMomo.statut",
            return_value=StatutTransaction(etat=Transaction.REUSSIE, message="SUCCESSFUL"),
        ):
            self.client.put(
                "/paiements/notifications/mtn/",
                data={"externalId": str(operation.pk)},
                content_type="application/json",
            )
        self.commande.refresh_from_db()
        self.assertEqual(self.commande.etat, Commande.PAYEE)

    def test_orange_refuse_un_jeton_faux(self):
        operation = self._operation(
            Prestataire.ORANGE_MONEY,
            notif_token_empreinte=AdaptateurOrangeMoney.empreinte_jeton("le-vrai"),
            pay_token="pt",
            montant=int(self.montant),
            order_id="o",
        )
        with mock.patch("apps.payments.operateurs.AdaptateurOrangeMoney.statut") as relu:
            reponse = self.client.post(
                f"/paiements/notifications/orange/{operation.pk}/",
                data={"status": "SUCCESS", "notif_token": "un-faux"},
                content_type="application/json",
            )
        self.assertEqual(reponse.status_code, 403)
        relu.assert_not_called()

    def test_orange_jeton_juste_puis_statut_relu(self):
        operation = self._operation(
            Prestataire.ORANGE_MONEY,
            notif_token_empreinte=AdaptateurOrangeMoney.empreinte_jeton("le-vrai"),
            pay_token="pt",
            montant=int(self.montant),
            order_id="o",
        )
        with mock.patch(
            "apps.payments.operateurs.AdaptateurOrangeMoney.statut",
            return_value=StatutTransaction(etat=Transaction.REUSSIE, message="SUCCESS"),
        ):
            reponse = self.client.post(
                f"/paiements/notifications/orange/{operation.pk}/",
                data={"status": "SUCCESS", "notif_token": "le-vrai"},
                content_type="application/json",
            )
        self.assertEqual(reponse.status_code, 200)
        self.commande.refresh_from_db()
        self.assertEqual(self.commande.etat, Commande.PAYEE)

    def test_une_notification_pour_une_transaction_inconnue_ne_revele_rien(self):
        reponse = self.client.post(
            "/paiements/notifications/mtn/",
            data={"externalId": "pas-un-uuid"},
            content_type="application/json",
        )
        self.assertEqual(reponse.status_code, 200)
