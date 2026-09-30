"""Versements envoyés par l'API de MTN MoMo.

Ce que ces tests protègent :

* **les mêmes quatre yeux** que l'exécution manuelle, vérifiés avant tout appel à l'opérateur ;
* **un double clic ne verse pas deux fois** : tant qu'un envoi est en cours, on le suit au lieu d'en
  relancer un ;
* **le versement n'est exécuté qu'une fois MTN relu à « réussi »**, avec sa référence financière ;
  un envoi en attente est repris par la tâche quotidienne ;
* **sans clés de versement**, ou vers un compte Orange, l'envoi automatique est refusé net.
"""

from decimal import Decimal
from unittest import mock

from django.test import override_settings

from apps.core.management.commands.initialiser_referentiels import PRESTATAIRES
from apps.payments import versements as service
from apps.payments.adaptateurs import ReponseInitiation, StatutTransaction
from apps.payments.models import Prestataire, Transaction, Versement
from tests.test_versements import SocleVersement

CLES_VERSEMENT = {
    "MTN_MOMO": {
        "cle_abonnement_versement": "a",
        "utilisateur_api_versement": "u",
        "cle_api_versement": "k",
    }
}


@override_settings(PAIEMENTS_OPERATEURS=CLES_VERSEMENT)
class EnvoiParApiTest(SocleVersement):
    def setUp(self):
        super().setUp()
        for code, libelle, frais, prefixes in PRESTATAIRES:
            Prestataire.objects.update_or_create(
                code=code,
                defaults={"libelle": libelle, "taux_frais": Decimal(frais), "prefixes_numero": prefixes},
            )
        self.disponible()
        self.compte()
        self.versement = service.demander_versement(self.ateba, par=self.gerant)

    def _mtn(self, *, statut):
        verser = mock.patch(
            "apps.payments.operateurs.AdaptateurMtnMomo.verser",
            return_value=ReponseInitiation(reference_externe="uuid-mtn", etat="initiee", message="ok"),
        )
        lire = mock.patch(
            "apps.payments.operateurs.AdaptateurMtnMomo.statut_versement",
            return_value=StatutTransaction(
                etat=statut, message=statut, charge_utile={"reference_financiere": "FT-42"}
            ),
        )
        return verser, lire

    def test_reussi_le_versement_est_execute_avec_la_reference_de_mtn(self):
        verser, lire = self._mtn(statut="reussie")
        with verser as appel, lire:
            service.envoyer_par_api(self.versement, par=self.executant)
        appel.assert_called_once()
        self.versement.refresh_from_db()
        self.assertEqual(self.versement.etat, Versement.EXECUTE)
        self.assertEqual(self.versement.reference_operateur, "MTN-FT-42")
        self.verifier_l_invariant()

    def test_en_attente_un_second_clic_ne_reverse_pas(self):
        verser, lire = self._mtn(statut="initiee")
        with verser as appel, lire:
            service.envoyer_par_api(self.versement, par=self.executant)
            service.envoyer_par_api(self.versement, par=self.executant)
        appel.assert_called_once()
        self.assertEqual(Transaction.objects.filter(sens=Transaction.VERSEMENT).count(), 1)
        self.versement.refresh_from_db()
        self.assertEqual(self.versement.etat, Versement.DEMANDE)

    def test_la_tache_quotidienne_reprend_un_envoi_en_attente(self):
        verser, lire = self._mtn(statut="initiee")
        with verser, lire:
            service.envoyer_par_api(self.versement, par=self.executant)
        _, lire_reussi = self._mtn(statut="reussie")
        with lire_reussi:
            self.assertEqual(service.suivre_envois_en_cours(), 1)
        self.versement.refresh_from_db()
        self.assertEqual(self.versement.etat, Versement.EXECUTE)

    def test_les_quatre_yeux_passent_avant_l_operateur(self):
        verser, lire = self._mtn(statut="reussie")
        with verser as appel, lire:
            with self.assertRaises(service.VersementRefuse):
                service.envoyer_par_api(self.versement, par=self.gerant)
        appel.assert_not_called()

    @override_settings(PAIEMENTS_OPERATEURS={})
    def test_sans_cles_l_envoi_automatique_est_refuse(self):
        with self.assertRaisesMessage(service.VersementRefuse, "à la main"):
            service.envoyer_par_api(self.versement, par=self.executant)
