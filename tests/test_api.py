"""API REST : authentification par jeton, isolation, droits, idempotence.

Ce que ces tests protègent tient en trois phrases.

**Le jeton porte la boutique.** Un client ne peut pas demander à lire une autre
boutique, parce qu'il n'a aucun moyen de la nommer. C'est la propriété que
l'ADR-010 achète, et le seul endroit où elle se vérifie est ici.

**Les droits sont les mêmes qu'à l'écran.** Une API qui exposerait le coût
d'achat à un caissier annulerait la matrice de droits du back-office, sans que
personne ne s'en aperçoive : l'écran continuerait de bien se comporter.

**Un encaissement retransmis ne débite pas deux fois.** Même invariant que la
caisse hors ligne, même clé, même service.
"""

import uuid
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.api.models import JetonApi, empreinte_de, generer_jeton
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import MouvementStock, NiveauStock
from apps.inventory.services import entrer_stock
from apps.pos.models import Ticket
from tests import fabrique


def rattacher(utilisateur, boutique, code_role=Role.GERANT):
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    return Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class SocleApi(TestCase):
    """Une boutique, un dépôt, un article en stock, et un porteur par rôle."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Api")
        self.depot = fabrique.creer_depot(self.boutique)
        self.variante = fabrique.creer_variante(self.boutique, prix="11925")
        entrer_stock(
            depot=self.depot,
            variante=self.variante,
            quantite=Decimal("10"),
            cout_unitaire=Decimal("7000"),
        )

    def porteur(self, code_role=Role.GERANT, boutique=None, nom=None):
        """Utilisateur rattaché avec un rôle, et son jeton en clair."""
        boutique = boutique or self.boutique
        utilisateur = fabrique.creer_utilisateur(nom or code_role.title())
        rattacher(utilisateur, boutique, code_role)
        _, secret = JetonApi.emettre(
            utilisateur=utilisateur, boutique=boutique, libelle=f"Test {code_role}"
        )
        return utilisateur, secret

    def appeler(self, adresse, secret, methode="get", **kwargs):
        fonction = getattr(self.client, methode)
        return fonction(
            adresse,
            HTTP_AUTHORIZATION=f"Bearer {secret}",
            content_type="application/json",
            **kwargs,
        )


class JetonTest(TestCase):
    def test_un_jeton_est_unique_a_chaque_emission(self):
        premier, _, _ = generer_jeton()
        second, _, _ = generer_jeton()
        self.assertNotEqual(premier, second)

    def test_le_secret_n_est_pas_stocke(self):
        """Une fuite de la table ne doit donner aucun accès."""
        boutique = fabrique.creer_boutique("Empreinte")
        utilisateur = fabrique.creer_utilisateur("Porteur")
        jeton, secret = JetonApi.emettre(
            utilisateur=utilisateur, boutique=boutique, libelle="Caisse"
        )

        _, _, morceau_secret = secret.split("_")
        self.assertNotIn(morceau_secret, jeton.empreinte)
        self.assertEqual(jeton.empreinte, empreinte_de(morceau_secret))
        self.assertTrue(jeton.correspond(morceau_secret))
        self.assertFalse(jeton.correspond("faux"))

    def test_le_jeton_ne_contient_aucun_caractere_ambigu(self):
        """Un jeton finit toujours par être recopié à la main une fois."""
        secret, _, _ = generer_jeton()
        for ambigu in "0O1lI":
            self.assertNotIn(ambigu, secret.split("_", 1)[1])


class AuthentificationTest(SocleApi):
    def test_sans_jeton_c_est_401(self):
        reponse = self.client.get(reverse("api:moi"))
        self.assertEqual(reponse.status_code, 401)

    def test_un_jeton_inconnu_est_refuse(self):
        reponse = self.appeler(reverse("api:moi"), "hm_abcdefgh_inexistant")
        self.assertEqual(reponse.status_code, 401)

    def test_un_jeton_mal_forme_est_refuse(self):
        for essai in ("nimporte-quoi", "hm_troppeu", "autre_prefixe_secret"):
            with self.subTest(jeton=essai):
                self.assertEqual(self.appeler(reverse("api:moi"), essai).status_code, 401)

    def test_un_jeton_revoque_ne_sert_plus(self):
        _, secret = self.porteur()
        self.assertEqual(self.appeler(reverse("api:moi"), secret).status_code, 200)

        JetonApi.objects.get(prefixe=secret.split("_")[1]).revoquer()
        self.assertEqual(self.appeler(reverse("api:moi"), secret).status_code, 401)

    def test_retirer_l_acces_ferme_le_jeton_immediatement(self):
        """L'appartenance est revérifiée à chaque requête, jamais figée à l'émission."""
        utilisateur, secret = self.porteur()
        self.assertEqual(self.appeler(reverse("api:moi"), secret).status_code, 200)

        Appartenance.objects.filter(utilisateur=utilisateur).update(actif=False)
        self.assertEqual(self.appeler(reverse("api:moi"), secret).status_code, 401)

    def test_un_compte_desactive_ne_passe_plus(self):
        utilisateur, secret = self.porteur()
        utilisateur.is_active = False
        utilisateur.save(update_fields=["is_active"])
        self.assertEqual(self.appeler(reverse("api:moi"), secret).status_code, 401)

    def test_l_usage_est_horodate(self):
        _, secret = self.porteur()
        self.appeler(reverse("api:moi"), secret)
        jeton = JetonApi.objects.get(prefixe=secret.split("_")[1])
        self.assertIsNotNone(jeton.dernier_usage_le)


class IdentiteTest(SocleApi):
    def test_moi_annonce_la_boutique_et_les_droits(self):
        _, secret = self.porteur(Role.CAISSIER)
        corps = self.appeler(reverse("api:moi"), secret).json()

        self.assertEqual(corps["boutique"]["id"], str(self.boutique.pk))
        self.assertEqual(sorted(corps["droits"]), ["caisse.encaisser", "stock.voir", "ventes.voir"])

    def test_moi_reste_ouvert_meme_sans_aucun_droit(self):
        """Un client doit pouvoir apprendre qu'il ne peut rien faire."""
        _, secret = self.porteur(Role.RESP_RAYON)
        reponse = self.appeler(reverse("api:moi"), secret)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["droits"], [])


class IsolationTest(SocleApi):
    """La propriété centrale de l'ADR-010 : le client ne nomme pas sa boutique."""

    def setUp(self):
        super().setUp()
        self.voisine = fabrique.creer_boutique("Voisine")
        self.depot_voisin = fabrique.creer_depot(self.voisine)
        self.variante_voisine = fabrique.creer_variante(self.voisine, prix="500")

    def test_le_catalogue_s_arrete_a_la_boutique_du_jeton(self):
        _, secret = self.porteur()
        corps = self.appeler(reverse("api:articles"), secret).json()

        identifiants = {article["id"] for article in corps["results"]}
        self.assertIn(str(self.variante.pk), identifiants)
        self.assertNotIn(str(self.variante_voisine.pk), identifiants)

    def test_l_entete_x_boutique_ne_change_rien(self):
        """Le middleware lit cet en-tête ; l'API, elle, lit le jeton."""
        _, secret = self.porteur()
        reponse = self.client.get(
            reverse("api:articles"),
            HTTP_AUTHORIZATION=f"Bearer {secret}",
            HTTP_X_BOUTIQUE=str(self.voisine.pk),
        )
        identifiants = {article["id"] for article in reponse.json()["results"]}
        self.assertNotIn(str(self.variante_voisine.pk), identifiants)
        self.assertIn(str(self.variante.pk), identifiants)

    def test_un_depot_voisin_est_refuse_et_non_remplace(self):
        """Ni repli silencieux, ni zéros : un dépôt inconnu se dit.

        Retomber sur le dépôt principal servirait le stock d'un autre dépôt que
        celui demandé — et un comptage fait dans la mauvaise réserve invente des
        écarts. Répondre des zéros ressemblerait à un dépôt vide.
        """
        _, secret = self.porteur()
        reponse = self.appeler(
            f"{reverse('api:articles')}?depot={self.depot_voisin.pk}", secret
        )
        self.assertEqual(reponse.status_code, 400)
        self.assertIn("depot", reponse.json())

    def test_sans_depot_demande_le_principal_sert_de_repli(self):
        _, secret = self.porteur()
        reponse = self.appeler(reverse("api:articles"), secret)
        stocks = {a["id"]: a["quantite"] for a in reponse.json()["results"]}
        self.assertEqual(Decimal(stocks[str(self.variante.pk)]), Decimal("10.0000"))

    def test_un_ticket_voisin_est_introuvable_et_non_interdit(self):
        _, secret = self.porteur()
        with contexte_boutique(self.voisine):
            session = self._session_voisine()
            ticket = Ticket.objects.create(
                boutique=self.voisine, session=session, numero="T-00000001"
            )
        reponse = self.appeler(
            reverse("api:vente-detail", args=[ticket.pk]), secret
        )
        self.assertEqual(reponse.status_code, 404)

    def _session_voisine(self):
        from apps.pos.services import ouvrir_session

        caissier = fabrique.creer_utilisateur("Voisin")
        rattacher(caissier, self.voisine, Role.CAISSIER)
        return ouvrir_session(depot=self.depot_voisin, caissier=caissier)


class DroitsTest(SocleApi):
    def test_un_caissier_ne_lit_pas_la_comptabilite(self):
        _, secret = self.porteur(Role.CAISSIER)
        reponse = self.appeler(reverse("api:balance"), secret)
        self.assertEqual(reponse.status_code, 403)

    def test_le_refus_nomme_le_droit_qui_manque(self):
        """Un refus muet fait croire à une panne."""
        _, secret = self.porteur(Role.CAISSIER)
        corps = self.appeler(reverse("api:balance"), secret).json()
        codes = [d["code"] for d in corps["droits_manquants"]]
        self.assertEqual(codes, ["comptabilite.voir"])

    def test_un_comptable_lit_les_ventes_mais_n_encaisse_pas(self):
        _, secret = self.porteur(Role.COMPTABLE)
        self.assertEqual(self.appeler(reverse("api:ventes"), secret).status_code, 200)

        reponse = self.appeler(
            reverse("api:ventes"),
            secret,
            methode="post",
            data='{"lignes": [{"variante": "%s", "quantite": "1"}]}' % self.variante.pk,
        )
        self.assertEqual(reponse.status_code, 403)

    def test_le_cout_d_achat_est_absent_de_la_reponse_faite_a_un_caissier(self):
        """Absent, pas vide : un champ à `null` dit qu'il existe."""
        _, secret = self.porteur(Role.CAISSIER)
        article = self.appeler(reverse("api:articles"), secret).json()["results"][0]

        self.assertNotIn("cmp", article)
        self.assertNotIn("valeur_stock", article)
        self.assertIn("prix_vente", article)

    def test_le_magasinier_voit_le_cout(self):
        _, secret = self.porteur(Role.MAGASINIER)
        article = self.appeler(reverse("api:articles"), secret).json()["results"][0]
        self.assertEqual(Decimal(article["cmp"]), Decimal("7000.0000"))

    def test_la_marge_d_un_ticket_est_reservee(self):
        _, secret_caissier = self.porteur(Role.CAISSIER, nom="Caissière")
        creation = self.appeler(
            reverse("api:ventes"),
            secret_caissier,
            methode="post",
            data='{"lignes": [{"variante": "%s", "quantite": "2"}]}' % self.variante.pk,
        )
        self.assertEqual(creation.status_code, 201)
        self.assertNotIn("marge", creation.json())

        _, secret_gerant = self.porteur(Role.GERANT, nom="Gérante")
        detail = self.appeler(
            reverse("api:vente-detail", args=[creation.json()["id"]]), secret_gerant
        ).json()
        self.assertIn("marge", detail)
        self.assertIn("cout_marchandise", detail)


class CatalogueTest(SocleApi):
    def test_la_recherche_porte_sur_le_libelle_et_le_sku(self):
        _, secret = self.porteur()
        adresse = f"{reverse('api:articles')}?q={self.variante.sku}"
        corps = self.appeler(adresse, secret).json()
        self.assertEqual(corps["count"], 1)

    def test_le_filtre_d_alerte_ne_retient_que_les_articles_sous_le_seuil(self):
        _, secret = self.porteur()
        with contexte_boutique(self.boutique):
            NiveauStock.objects.filter(variante=self.variante).update(seuil_alerte=Decimal("50"))

        corps = self.appeler(f"{reverse('api:articles')}?alerte=1", secret).json()
        self.assertEqual(corps["count"], 1)
        self.assertTrue(corps["results"][0]["en_alerte"])

    def test_les_depots_sont_listes_le_principal_en_tete(self):
        _, secret = self.porteur()
        fabrique.creer_depot(self.boutique, "Réserve", principal=False)
        corps = self.appeler(reverse("api:depots"), secret).json()
        self.assertEqual(corps[0]["libelle"], "Magasin")
        self.assertTrue(corps[0]["principal"])


class EncaissementTest(SocleApi):
    def _encaisser(self, secret, operation_id=None, quantite="2"):
        charge = '{"lignes": [{"variante": "%s", "quantite": "%s"}]%s}' % (
            self.variante.pk,
            quantite,
            f', "operation_id": "{operation_id}"' if operation_id else "",
        )
        return self.appeler(reverse("api:ventes"), secret, methode="post", data=charge)

    def test_un_encaissement_cree_le_ticket_et_sort_le_stock(self):
        _, secret = self.porteur(Role.CAISSIER)
        reponse = self._encaisser(secret)

        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(reponse.json()["etat"], Ticket.CLOTURE)

        with contexte_boutique(self.boutique):
            niveau = NiveauStock.objects.get(variante=self.variante, depot=self.depot)
        self.assertEqual(niveau.quantite, Decimal("8.0000"))

    def test_la_meme_operation_ne_vend_jamais_deux_fois(self):
        """Même invariant que la caisse hors ligne, même clé (ADR-004)."""
        _, secret = self.porteur(Role.CAISSIER)
        cle = uuid.uuid4()

        premier = self._encaisser(secret, operation_id=cle)
        second = self._encaisser(secret, operation_id=cle)

        self.assertEqual(premier.status_code, 201)
        self.assertEqual(second.status_code, 200, "un rejeu ne crée rien")
        self.assertTrue(second.json()["rejoue"])
        self.assertEqual(premier.json()["numero"], second.json()["numero"])

        with contexte_boutique(self.boutique):
            self.assertEqual(Ticket.objects.count(), 1)
            niveau = NiveauStock.objects.get(variante=self.variante, depot=self.depot)
        self.assertEqual(niveau.quantite, Decimal("8.0000"))

    def test_une_reference_inconnue_est_refusee_et_nommee(self):
        """L'API refuse là où le comptoir ignore : personne n'est là pour rattraper."""
        _, secret = self.porteur(Role.CAISSIER)
        inconnue = uuid.uuid4()
        reponse = self.appeler(
            reverse("api:ventes"),
            secret,
            methode="post",
            data='{"lignes": [{"variante": "%s", "quantite": "1"}]}' % inconnue,
        )
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["variante"], str(inconnue))

    def test_un_panier_vide_est_refuse(self):
        _, secret = self.porteur(Role.CAISSIER)
        reponse = self.appeler(
            reverse("api:ventes"), secret, methode="post", data='{"lignes": []}'
        )
        self.assertEqual(reponse.status_code, 400)

    def test_la_vente_hors_ligne_porte_son_heure(self):
        """Les écritures la portent, et le journal en ajout seul la fige (ADR-003)."""
        _, secret = self.porteur(Role.CAISSIER)
        reponse = self.appeler(
            reverse("api:ventes"),
            secret,
            methode="post",
            data=(
                '{"lignes": [{"variante": "%s", "quantite": "1"}], '
                '"encaisse_le": "2026-01-15T10:30:00Z"}' % self.variante.pk
            ),
        )
        self.assertEqual(reponse.status_code, 201)
        self.assertTrue(reponse.json()["cloture_le"].startswith("2026-01-15"))

    def test_le_journal_des_ventes_liste_le_ticket(self):
        _, secret = self.porteur()
        self._encaisser(secret)
        corps = self.appeler(reverse("api:ventes"), secret).json()
        self.assertEqual(corps["count"], 1)


class ReceptionTest(SocleApi):
    def _recevoir(self, secret, operation_id=None, quantite="5"):
        charge = '{"variante": "%s", "quantite": "%s", "cout_unitaire": "8000"%s}' % (
            self.variante.pk,
            quantite,
            f', "operation_id": "{operation_id}"' if operation_id else "",
        )
        return self.appeler(
            reverse("api:stock-entrees"), secret, methode="post", data=charge
        )

    def test_une_reception_entre_le_stock_et_deplace_le_cmp(self):
        _, secret = self.porteur(Role.MAGASINIER)
        reponse = self._recevoir(secret)

        self.assertEqual(reponse.status_code, 201)
        with contexte_boutique(self.boutique):
            niveau = NiveauStock.objects.get(variante=self.variante, depot=self.depot)
        self.assertEqual(niveau.quantite, Decimal("15.0000"))
        # (10 × 7000 + 5 × 8000) / 15
        self.assertEqual(niveau.cmp, Decimal("7333.3333"))

    def test_la_meme_operation_ne_receptionne_qu_une_fois(self):
        _, secret = self.porteur(Role.MAGASINIER)
        cle = uuid.uuid4()
        self._recevoir(secret, operation_id=cle)
        self._recevoir(secret, operation_id=cle)

        with contexte_boutique(self.boutique):
            entrees = MouvementStock.objects.filter(
                variante=self.variante, type=MouvementStock.ENTREE
            ).count()
        self.assertEqual(entrees, 2, "la réception initiale du socle, plus une seule reçue")

    def test_un_caissier_ne_receptionne_pas(self):
        _, secret = self.porteur(Role.CAISSIER)
        self.assertEqual(self._recevoir(secret).status_code, 403)

    def test_une_quantite_nulle_est_refusee_a_la_validation(self):
        _, secret = self.porteur(Role.MAGASINIER)
        self.assertEqual(self._recevoir(secret, quantite="0").status_code, 400)


class ComptabiliteTest(SocleApi):
    def test_la_balance_est_servie_au_comptable(self):
        _, secret_caissier = self.porteur(Role.CAISSIER, nom="Caissière")
        self.appeler(
            reverse("api:ventes"),
            secret_caissier,
            methode="post",
            data='{"lignes": [{"variante": "%s", "quantite": "1"}]}' % self.variante.pk,
        )

        _, secret = self.porteur(Role.COMPTABLE)
        corps = self.appeler(reverse("api:balance"), secret).json()

        self.assertTrue(corps, "une vente doit avoir produit des écritures")
        total_debit = sum(Decimal(ligne["debit"]) for ligne in corps)
        total_credit = sum(Decimal(ligne["credit"]) for ligne in corps)
        self.assertEqual(total_debit, total_credit, "la balance est équilibrée")


class ContexteDeTenantTest(SocleApi):
    """Le contexte ouvert par une requête ne doit pas fuir vers la suivante.

    Les connexions sont persistantes et le contexte est répercuté sur la
    connexion PostgreSQL : une requête qui ne restaurerait pas laisserait la
    suivante hériter de sa boutique.
    """

    def test_le_contexte_est_referme_apres_la_requete(self):
        from apps.core.tenancy import boutique_courante

        _, secret = self.porteur()
        self.appeler(reverse("api:articles"), secret)
        self.assertIsNone(boutique_courante())

    def test_le_contexte_est_referme_meme_apres_un_refus(self):
        from apps.core.tenancy import boutique_courante

        _, secret = self.porteur(Role.CAISSIER)
        self.assertEqual(self.appeler(reverse("api:balance"), secret).status_code, 403)
        self.assertIsNone(boutique_courante())
