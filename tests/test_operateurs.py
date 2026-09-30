"""Les clients HTTP de MTN MoMo et d'Orange Money, contre des réponses simulées.

Aucun appel ne sort d'ici : `requete_http` est remplacée, et chaque test vérifie **ce que nous
envoyons** (en-têtes, corps, adresse) autant que **ce que nous faisons de la réponse**. C'est la
moitié du travail d'intégration qu'on peut prouver sans compte marchand ; l'autre moitié est
l'aller-retour réel de `essayer_prestataire`, contre le bac à sable de l'opérateur.
"""

import json
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.payments.adaptateurs import PaiementIndisponible, PrestataireNonConfigure
from apps.payments.operateurs import (
    AdaptateurMtnMomo,
    AdaptateurOrangeMoney,
    ReponseHttp,
    _msisdn,
)

MTN = {
    "MTN_MOMO": {
        "url_base": "https://mtn.exemple",
        "environnement": "sandbox",
        "cle_abonnement_collecte": "abonnement-collecte",
        "utilisateur_api_collecte": "utilisateur-collecte",
        "cle_api_collecte": "cle-collecte",
        "cle_abonnement_versement": "abonnement-versement",
        "utilisateur_api_versement": "utilisateur-versement",
        "cle_api_versement": "cle-versement",
    }
}
ORANGE = {
    "ORANGE_MONEY": {
        "url_base": "https://orange.exemple",
        "chemin": "orange-money-webpay/dev/v1",
        "id_client": "client",
        "secret_client": "secret",
        "cle_marchand": "marchand",
    }
}


def _json(statut, donnees=None):
    return ReponseHttp(statut, json.dumps(donnees).encode() if donnees is not None else b"", {})


class Enregistreur:
    """Remplace `requete_http` : rend des réponses dans l'ordre et garde chaque appel."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels = []

    def __call__(self, methode, url, *, entetes, corps=None):
        self.appels.append({"methode": methode, "url": url, "entetes": entetes, "corps": corps})
        return self.reponses.pop(0)


def _jeton():
    return _json(200, {"access_token": "jeton-1", "expires_in": 3600})


class MsisdnTest(SimpleTestCase):
    def test_toutes_les_ecritures_d_un_numero_donnent_la_meme_forme(self):
        for saisie in ("+237 6 77 22 00 22", "00237677220022", "677220022", "237677220022"):
            self.assertEqual(_msisdn(saisie), "237677220022", saisie)


@override_settings(PAIEMENTS_OPERATEURS=MTN, URL_PUBLIQUE="https://hypermarche.exemple")
class MtnCollecteTest(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_la_demande_porte_les_bons_en_tetes_et_le_bon_corps(self):
        faux = Enregistreur(_jeton(), _json(202))
        with mock.patch("apps.payments.operateurs.requete_http", faux):
            reponse = AdaptateurMtnMomo().initier(
                reference="ref-interne", montant=Decimal("12500.00"), numero="+237677220022"
            )

        jeton, demande = faux.appels
        self.assertTrue(jeton["url"].endswith("/collection/token/"))
        self.assertTrue(jeton["entetes"]["Authorization"].startswith("Basic "))
        self.assertEqual(jeton["entetes"]["Ocp-Apim-Subscription-Key"], "abonnement-collecte")

        self.assertTrue(demande["url"].endswith("/collection/v1_0/requesttopay"))
        self.assertEqual(demande["entetes"]["Authorization"], "Bearer jeton-1")
        self.assertEqual(demande["entetes"]["X-Target-Environment"], "sandbox")
        self.assertEqual(demande["entetes"]["X-Reference-Id"], reponse.reference_externe)
        self.assertEqual(
            demande["entetes"]["X-Callback-Url"],
            "https://hypermarche.exemple/paiements/notifications/mtn/",
        )
        corps = json.loads(demande["corps"])
        # Un entier en chaîne : le franc CFA n'a pas de centimes en usage.
        self.assertEqual(corps["amount"], "12500")
        self.assertEqual(corps["currency"], "EUR", "le bac à sable MTN n'accepte que l'euro")
        self.assertEqual(corps["payer"], {"partyIdType": "MSISDN", "partyId": "237677220022"})
        self.assertEqual(corps["externalId"], "ref-interne")
        self.assertEqual(reponse.etat, "initiee")

    def test_aucun_secret_dans_la_charge_utile_enregistree(self):
        faux = Enregistreur(_jeton(), _json(202))
        with mock.patch("apps.payments.operateurs.requete_http", faux):
            reponse = AdaptateurMtnMomo().initier(reference="r", montant=Decimal("100"), numero="677220022")
        texte = json.dumps(reponse.charge_utile)
        for secret in ("cle-collecte", "abonnement-collecte", "jeton-1"):
            self.assertNotIn(secret, texte)

    def test_le_jeton_est_garde_en_cache(self):
        """Sans cache, chaque paiement redemanderait un jeton — et MTN limite ces demandes."""
        faux = Enregistreur(_jeton(), _json(202), _json(202))
        with mock.patch("apps.payments.operateurs.requete_http", faux):
            for _ in range(2):
                AdaptateurMtnMomo().initier(reference="r", montant=Decimal("100"), numero="677220022")
        self.assertEqual(sum(1 for a in faux.appels if a["url"].endswith("/token/")), 1)

    def test_un_refus_4xx_est_un_echec_de_la_transaction_pas_une_panne(self):
        faux = Enregistreur(_jeton(), _json(400, {"code": "PAYER_NOT_FOUND", "message": "Payer not found"}))
        with mock.patch("apps.payments.operateurs.requete_http", faux):
            reponse = AdaptateurMtnMomo().initier(reference="r", montant=Decimal("100"), numero="677220022")
        self.assertEqual(reponse.etat, "echouee")
        self.assertIn("Payer not found", reponse.message)

    def test_un_5xx_est_une_panne_que_le_disjoncteur_comptera(self):
        faux = Enregistreur(_jeton(), _json(503))
        with mock.patch("apps.payments.operateurs.requete_http", faux):
            with self.assertRaises(PaiementIndisponible):
                AdaptateurMtnMomo().initier(reference="r", montant=Decimal("100"), numero="677220022")

    def test_lecture_du_statut(self):
        cas = {
            "SUCCESSFUL": "reussie",
            "FAILED": "echouee",
            "PENDING": "initiee",
        }
        for brut, attendu in cas.items():
            with self.subTest(brut=brut):
                cache.clear()
                faux = Enregistreur(
                    _jeton(), _json(200, {"status": brut, "financialTransactionId": "FT-9"})
                )
                with mock.patch("apps.payments.operateurs.requete_http", faux):
                    statut = AdaptateurMtnMomo().statut("uuid-mtn")
                self.assertEqual(statut.etat, attendu)
                self.assertTrue(faux.appels[1]["url"].endswith("/collection/v1_0/requesttopay/uuid-mtn"))

    @override_settings(PAIEMENTS_OPERATEURS={})
    def test_sans_configuration_rien_n_est_tente(self):
        faux = Enregistreur()
        with mock.patch("apps.payments.operateurs.requete_http", faux):
            with self.assertRaises(PrestataireNonConfigure) as capture:
                AdaptateurMtnMomo().initier(reference="r", montant=Decimal("100"), numero="677220022")
        self.assertEqual(faux.appels, [])
        self.assertIn("cle_abonnement_collecte", str(capture.exception))


@override_settings(PAIEMENTS_OPERATEURS=MTN)
class MtnVersementTest(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_le_versement_utilise_les_cles_du_produit_versement(self):
        """Une clé de collecte volée ne doit pas permettre de verser : MTN sépare les deux."""
        faux = Enregistreur(_jeton(), _json(202))
        with mock.patch("apps.payments.operateurs.requete_http", faux):
            reponse = AdaptateurMtnMomo().verser(
                reference="versement-1", beneficiaire="+237677220022", montant=Decimal("50000")
            )
        jeton, transfert = faux.appels
        self.assertTrue(jeton["url"].endswith("/disbursement/token/"))
        self.assertEqual(jeton["entetes"]["Ocp-Apim-Subscription-Key"], "abonnement-versement")
        self.assertTrue(transfert["url"].endswith("/disbursement/v1_0/transfer"))
        self.assertEqual(json.loads(transfert["corps"])["payee"]["partyId"], "237677220022")
        self.assertEqual(reponse.etat, "initiee")


@override_settings(PAIEMENTS_OPERATEURS=ORANGE, URL_PUBLIQUE="https://hypermarche.exemple")
class OrangeTest(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _initier(self, faux):
        with mock.patch("apps.payments.operateurs.requete_http", faux):
            return AdaptateurOrangeMoney().initier(
                reference="0190aaaa-bbbb-7ccc-8ddd-eeeeffff0000",
                montant=Decimal("7500"),
                numero="",
                url_retour="https://hypermarche.exemple/marche/commande/x/",
            )

    def test_la_demande_renvoie_une_adresse_de_paiement(self):
        faux = Enregistreur(
            _jeton(),
            _json(201, {"status": 201, "pay_token": "pt-1", "payment_url": "https://orange/pay/1", "notif_token": "nt-1"}),
        )
        reponse = self._initier(faux)
        demande = faux.appels[1]
        corps = json.loads(demande["corps"])
        self.assertTrue(demande["url"].endswith("/orange-money-webpay/dev/v1/webpayment"))
        self.assertEqual(corps["currency"], "OUV", "la devise du bac à sable Orange")
        self.assertEqual(corps["amount"], 7500)
        self.assertEqual(
            corps["notif_url"],
            "https://hypermarche.exemple/paiements/notifications/orange/0190aaaa-bbbb-7ccc-8ddd-eeeeffff0000/",
        )
        self.assertEqual(reponse.etat, "initiee")
        self.assertEqual(reponse.charge_utile["payment_url"], "https://orange/pay/1")
        # Le jeton de notification n'est gardé qu'en empreinte : la base n'a pas de quoi en forger.
        self.assertNotIn("nt-1", json.dumps(reponse.charge_utile))
        self.assertEqual(
            reponse.charge_utile["notif_token_empreinte"], AdaptateurOrangeMoney.empreinte_jeton("nt-1")
        )

    @override_settings(URL_PUBLIQUE="")
    def test_sans_adresse_publique_on_ne_demarre_pas(self):
        faux = Enregistreur()
        with self.assertRaises(PrestataireNonConfigure):
            self._initier(faux)
        self.assertEqual(faux.appels, [])

    def test_lecture_du_statut_rappelle_le_jeton_et_le_montant(self):
        faux = Enregistreur(_jeton(), _json(200, {"status": "SUCCESS", "txnid": "MP123"}))
        with mock.patch("apps.payments.operateurs.requete_http", faux):
            statut = AdaptateurOrangeMoney().statut(
                "ordre", charge_utile={"order_id": "ordre", "montant": 7500, "pay_token": "pt-1"}
            )
        self.assertEqual(statut.etat, "reussie")
        self.assertEqual(statut.charge_utile["reference_financiere"], "MP123")
        self.assertEqual(json.loads(faux.appels[1]["corps"]), {"order_id": "ordre", "amount": 7500, "pay_token": "pt-1"})

    def test_orange_ne_verse_pas_et_le_dit(self):
        with self.assertRaises(PrestataireNonConfigure):
            AdaptateurOrangeMoney().verser(reference="v", beneficiaire="+237699110011", montant=Decimal("1"))
