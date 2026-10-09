"""Les commandes, envoyées sur WhatsApp à ceux qui les traitent.

Ce que ces tests protègent :

* **les bonnes personnes** : celles de la boutique dont le rôle traite les commandes, que le gérant
  n'a pas retirées de la liste — pas le caissier, pas la boutique voisine ;
* **au bon moment** : une part payée à la livraison dès la commande, une part prépayée seulement
  une fois l'argent constaté, et jamais avant que la transaction soit enregistrée ;
* **rien sur l'acheteur** dans le message : ni nom, ni téléphone, ni adresse ;
* **un avis par personne et par part**, et un avis qui échoue ne fait jamais échouer la commande ;
* **sans clés, aucun appel** — et l'écran de la commande propose le lien wa.me à la place.
"""

import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.core import whatsapp
from apps.core.tenancy import contexte_boutique
from apps.orders import avis
from apps.orders.models import AvisCommande, SousCommande
from apps.orders.services import marquer_payee
from tests import fabrique
from tests.test_sequestre import SocleSequestre

CONFIGURATION = {
    "jeton": "jeton-de-test",
    "numero_id": "1234567890",
    "gabarit_commande": "nouvelle_commande",
}


def _role(code, libelle):
    role, _ = Role.objects.get_or_create(code=code, defaults={"libelle": libelle, "portee": Role.BOUTIQUE})
    return role


class FausseApi:
    """Remplace l'appel HTTP : garde ce qui a été envoyé, répond ce qu'on lui dit."""

    def __init__(self, statut=200, corps=None):
        self.envois = []
        self.statut = statut
        self.corps = corps if corps is not None else {"messages": [{"id": "wamid.TEST"}]}

    def __call__(self, url, *, entetes, corps):
        self.envois.append({"url": url, "entetes": entetes, "charge": json.loads(corps)})
        return whatsapp.ReponseHttp(self.statut, json.dumps(self.corps).encode())

    def destinataires(self):
        return sorted(e["charge"]["to"] for e in self.envois)


class WhatsAppTest(TestCase):
    def test_numero_et_parametres(self):
        self.assertEqual(whatsapp.numero_international("699 00 00 00"), "237699000000")
        self.assertEqual(whatsapp.numero_international("+237699000000"), "237699000000")
        self.assertEqual(whatsapp.parametre("a\nb\t c      d"), "a · b ·  c   d")

    @override_settings(WHATSAPP={})
    def test_sans_cles_aucun_appel(self):
        api = FausseApi()
        with mock.patch.object(whatsapp, "requete_http", api):
            with self.assertRaises(whatsapp.WhatsAppRefuse):
                whatsapp.envoyer_gabarit("699000000", parametres=["x"])
        self.assertEqual(api.envois, [])

    @override_settings(WHATSAPP=CONFIGURATION)
    def test_le_gabarit_part_avec_ses_parametres(self):
        api = FausseApi()
        with mock.patch.object(whatsapp, "requete_http", api):
            reference = whatsapp.envoyer_gabarit("699000000", parametres=["C-1", "Ateba"])
        self.assertEqual(reference, "wamid.TEST")
        envoi = api.envois[0]
        self.assertTrue(envoi["url"].endswith("/1234567890/messages"))
        self.assertEqual(envoi["entetes"]["Authorization"], "Bearer jeton-de-test")
        gabarit = envoi["charge"]["template"]
        self.assertEqual(gabarit["name"], "nouvelle_commande")
        self.assertEqual(gabarit["language"]["code"], "fr")
        self.assertEqual(
            [p["text"] for p in gabarit["components"][0]["parameters"]], ["C-1", "Ateba"]
        )

    @override_settings(WHATSAPP=CONFIGURATION)
    def test_un_refus_de_meta_est_un_refus(self):
        api = FausseApi(statut=400, corps={"error": {"message": "Template name does not exist"}})
        with mock.patch.object(whatsapp, "requete_http", api):
            with self.assertRaisesMessage(whatsapp.WhatsAppRefuse, "Template name"):
                whatsapp.envoyer_gabarit("699000000", parametres=["x"])


class SocleAvis(SocleSequestre):
    def setUp(self):
        super().setUp()
        self.vendeur = fabrique.creer_utilisateur("Paul Vendeur", telephone="699111111")
        self.caissier = fabrique.creer_utilisateur("Awa Caissière", telephone="699222222")
        self.gerant = fabrique.creer_utilisateur("Marie Gérante", telephone="699333333")
        self.voisin = fabrique.creer_utilisateur("Vendeur de Bella", telephone="699444444")
        self.appartenance_vendeur = Appartenance.objects.create(
            utilisateur=self.vendeur, boutique=self.ateba, role=_role(Role.VENDEUR, "Vendeur")
        )
        Appartenance.objects.create(
            utilisateur=self.caissier, boutique=self.ateba, role=_role(Role.CAISSIER, "Caissier")
        )
        Appartenance.objects.create(
            utilisateur=self.gerant, boutique=self.ateba, role=_role(Role.GERANT, "Gérant")
        )
        Appartenance.objects.create(
            utilisateur=self.voisin, boutique=self.bella, role=_role(Role.VENDEUR, "Vendeur")
        )

    def avis_de(self, part):
        with contexte_boutique(part.boutique_id):
            return list(AvisCommande.objects.filter(sous_commande=part))


class ResponsablesTest(SocleAvis):
    def test_ceux_qui_traitent_les_commandes_et_eux_seuls(self):
        noms = [p.nom_complet for p in avis.responsables(self.ateba.pk)]
        self.assertEqual(noms, ["Marie Gérante", "Paul Vendeur"])

    def test_le_gerant_peut_retirer_quelqu_un(self):
        self.appartenance_vendeur.avis_commandes = False
        self.appartenance_vendeur.save()
        self.assertEqual([p.nom_complet for p in avis.responsables(self.ateba.pk)], ["Marie Gérante"])

    def test_un_acces_retire_n_est_plus_prevenu(self):
        self.appartenance_vendeur.actif = False
        self.appartenance_vendeur.save()
        self.assertNotIn(self.vendeur, avis.responsables(self.ateba.pk))


@override_settings(WHATSAPP=CONFIGURATION, URL_PUBLIQUE="https://hypermarche.example")
class EnvoiTest(SocleAvis):
    def test_une_commande_a_la_livraison_previent_l_equipe_tout_de_suite(self):
        api = FausseApi()
        with mock.patch.object(whatsapp, "requete_http", api):
            with self.captureOnCommitCallbacks(execute=True):
                commande = self.commander(
                    [(self.brouette, Decimal("2")), (self.creme, Decimal("1"))],
                    mode_paiement=SousCommande.A_LA_LIVRAISON,
                )
        # Ateba prévient sa gérante et son vendeur ; Bella son vendeur. Jamais le caissier.
        self.assertEqual(api.destinataires(), ["237699111111", "237699333333", "237699444444"])

        part = self.part(commande)
        envoyes = self.avis_de(part)
        self.assertEqual(len(envoyes), 2)
        self.assertTrue(all(a.etat == AvisCommande.ENVOYE and a.reference == "wamid.TEST" for a in envoyes))

        envoi = next(e for e in api.envois if e["charge"]["to"] == "237699111111")
        textes = [p["text"] for p in envoi["charge"]["template"]["components"][0]["parameters"]]
        self.assertEqual(textes[0], commande.numero)
        self.assertEqual(textes[1], "Ateba")
        self.assertIn("2 × ", textes[2])
        self.assertEqual(textes[4], "à encaisser à la livraison")
        self.assertEqual(textes[5], f"https://hypermarche.example/commandes/{part.pk}/")
        tout = " ".join(textes)
        self.assertNotIn(self.acheteur.nom_complet, tout, "jamais le nom de l'acheteur")
        self.assertNotIn(self.acheteur.telephone[-6:], tout, "jamais son téléphone")

    def test_une_part_prepayee_attend_que_l_argent_soit_constate(self):
        api = FausseApi()
        with mock.patch.object(whatsapp, "requete_http", api):
            with self.captureOnCommitCallbacks(execute=True):
                commande = self.commander()
            self.assertEqual(api.envois, [], "rien tant que l'acheteur n'a pas payé")
            with self.captureOnCommitCallbacks(execute=True):
                marquer_payee(commande)
        self.assertEqual(api.destinataires(), ["237699111111", "237699333333"])
        self.assertEqual(api.envois[0]["charge"]["template"]["components"][0]["parameters"][4]["text"], "déjà payée en ligne")

    def test_rien_ne_part_avant_l_enregistrement(self):
        api = FausseApi()
        with mock.patch.object(whatsapp, "requete_http", api):
            with self.captureOnCommitCallbacks(execute=False) as rappels:
                self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
        self.assertEqual(api.envois, [])
        self.assertEqual(len(rappels), 1)

    def test_un_avis_par_personne_et_par_part(self):
        api = FausseApi()
        with mock.patch.object(whatsapp, "requete_http", api):
            with self.captureOnCommitCallbacks(execute=True):
                commande = self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
            avis.aviser(self.part(commande))
        self.assertEqual(len(api.envois), 2)
        self.assertEqual(len(self.avis_de(self.part(commande))), 2)

    def test_un_avis_qui_echoue_ne_fait_pas_echouer_la_commande(self):
        api = FausseApi(statut=401, corps={"error": {"message": "Invalid OAuth access token"}})
        with mock.patch.object(whatsapp, "requete_http", api):
            with self.captureOnCommitCallbacks(execute=True):
                commande = self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
        echecs = self.avis_de(self.part(commande))
        self.assertEqual({a.etat for a in echecs}, {AvisCommande.ECHEC})
        self.assertIn("Invalid OAuth", echecs[0].erreur)
        self.assertNotIn("jeton-de-test", echecs[0].erreur)

    def test_une_panne_reseau_non_plus(self):
        def en_panne(*args, **kwargs):
            raise whatsapp.WhatsAppIndisponible("WhatsApp injoignable (TimeoutError).")

        with mock.patch.object(whatsapp, "requete_http", en_panne):
            with self.captureOnCommitCallbacks(execute=True):
                commande = self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
        self.assertEqual({a.etat for a in self.avis_de(self.part(commande))}, {AvisCommande.ECHEC})


@override_settings(WHATSAPP={})
class SansApiTest(SocleAvis):
    def test_sans_cles_rien_ne_part_et_l_ecran_propose_le_lien(self):
        api = FausseApi()
        with mock.patch.object(whatsapp, "requete_http", api):
            with self.captureOnCommitCallbacks(execute=True):
                commande = self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
        self.assertEqual(api.envois, [])

        part = self.part(commande)
        self.client.login(telephone=self.gerant.telephone, password="motdepasse")
        reponse = self.client.get(reverse("commande", args=[part.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "équipe sur WhatsApp</h2>")
        self.assertContains(reponse, "%C3%80%20traiter%20%3A%20http%3A//testserver/commandes/")
        self.assertContains(reponse, "https://wa.me/237699111111?text=")
        self.assertContains(reponse, "Paul Vendeur")
        self.assertNotContains(reponse, "https://wa.me/237699222222", msg_prefix="pas le caissier")

    def test_pas_de_lien_pour_une_part_prepayee_non_payee(self):
        commande = self.commander()
        self.client.login(telephone=self.gerant.telephone, password="motdepasse")
        reponse = self.client.get(reverse("commande", args=[self.part(commande).pk]))
        self.assertNotContains(reponse, "https://wa.me/")

    def test_le_gerant_regle_qui_est_prevenu(self):
        self.client.login(telephone=self.gerant.telephone, password="motdepasse")
        self.assertContains(self.client.get(reverse("equipe")), "Commandes sur WhatsApp")

        self.client.post(reverse("equipe_avis_commandes", args=[self.appartenance_vendeur.pk]))
        self.appartenance_vendeur.refresh_from_db()
        self.assertFalse(self.appartenance_vendeur.avis_commandes)

        caissier = Appartenance.objects.get(utilisateur=self.caissier)
        self.client.post(reverse("equipe_avis_commandes", args=[caissier.pk]))
        caissier.refresh_from_db()
        self.assertTrue(caissier.avis_commandes, "inchangé : son rôle ne traite pas les commandes")
