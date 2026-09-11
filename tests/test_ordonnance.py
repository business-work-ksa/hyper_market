"""Médicaments sur ordonnance : ordonnancier, et retrait de la vente en ligne.

Deux règles y sont tenues, et elles ne sont pas de même nature.

**Le retrait de la vitrine est une interdiction.** Un médicament qui ne se
délivre que sur ordonnance ne se commande pas sur un site : le pharmacien doit
voir l'ordonnance, et un panier ne la montre pas. La règle est posée à la seule
porte du catalogue public, donc elle couvre du même geste la liste, la
recherche, la page de l'article et l'ajout au panier.

**La consignation, elle, ne bloque rien.** La boîte est partie avec le client ;
refuser d'enregistrer la vente ne la ferait pas revenir, cela ferait seulement
disparaître la trace. Même règle que le stock négatif (ADR-005) : le logiciel
encaisse, puis réclame — et l'ordonnancier montre ce qui reste à consigner.

Une troisième propriété se joue plus discrètement : le drapeau est **figé sur la
ligne de ticket**. Un médicament que l'autorité reclasse l'an prochain ne doit
pas réécrire l'ordonnancier de cette année — un registre décrit ce qui était vrai
au moment de la délivrance.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.backoffice.forms import ArticleForm
from apps.catalog.models import Produit
from apps.core.tenancy import contexte_boutique
from apps.inventory.services import entrer_stock
from apps.marketplace import metiers
from apps.marketplace.models import Boutique
from apps.pos import services as caisse
from apps.pos.models import LigneTicket, Ticket
from apps.vitrine import catalogue
from tests import fabrique

MOT_DE_PASSE = "motdepasse"


def rattacher(utilisateur, boutique, code_role=Role.GERANT) -> None:
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class SocleOfficine(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Officine du Wouri")
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="PHARMACIE")
        self.boutique.refresh_from_db()
        self.depot = fabrique.creer_depot(self.boutique)

        self.paracetamol = self.medicament("Paracétamol 500 mg", sur_ordonnance=False)
        self.amoxicilline = self.medicament("Amoxicilline 1 g", sur_ordonnance=True)

        self.pharmacienne = fabrique.creer_utilisateur("Pharmacienne")
        rattacher(self.pharmacienne, self.boutique)

    def medicament(self, libelle, *, sur_ordonnance):
        variante = fabrique.creer_variante(self.boutique, prix="3200", libelle=libelle)
        if sur_ordonnance:
            with contexte_boutique(self.boutique):
                Produit.objects.filter(pk=variante.produit_id).update(sur_ordonnance=True)
            variante.produit.sur_ordonnance = True
        entrer_stock(
            depot=self.depot,
            variante=variante,
            quantite=Decimal("50"),
            cout_unitaire=Decimal("2100"),
        )
        return variante

    def vendre(self, *variantes, mention=""):
        # Le contexte est posé ici : la caisse est appelée depuis une vue en
        # temps normal, et la barrière 3 refuse une session écrite hors contexte.
        with contexte_boutique(self.boutique):
            session = caisse.ouvrir_session(depot=self.depot, caissier=self.pharmacienne)
            ticket, _ = caisse.encaisser(
                session=session,
                lignes=[(v, Decimal("1"), Decimal("0")) for v in variantes],
                cree_par=self.pharmacienne,
                mention_ordonnance=mention,
            )
        return ticket

    def relire(self, ticket):
        with contexte_boutique(self.boutique):
            return Ticket.objects.get(pk=ticket.pk)


class ReferentielTest(TestCase):
    def test_la_pharmacie_active_la_fonction(self):
        self.assertTrue(metiers.METIERS["PHARMACIE"].a(metiers.ORDONNANCE))

    def test_aucun_autre_metier_ne_l_active(self):
        for code, metier in metiers.METIERS.items():
            if code == "PHARMACIE":
                continue
            with self.subTest(metier=code):
                self.assertFalse(metier.a(metiers.ORDONNANCE))

    def test_la_mention_n_est_plus_promise(self):
        for promesse in metiers.METIERS["PHARMACIE"].a_venir:
            self.assertNotIn("ordonnance", promesse.lower())


class FormulaireTest(SocleOfficine):
    def test_la_case_n_existe_qu_en_officine(self):
        self.assertIn("sur_ordonnance", ArticleForm(boutique=self.boutique).fields)

        autre = fabrique.creer_boutique("Quincaillerie")
        Boutique.objects.filter(pk=autre.pk).update(metier="QUINCAILLERIE")
        autre.refresh_from_db()
        self.assertNotIn("sur_ordonnance", ArticleForm(boutique=autre).fields)

    def test_tout_champ_compose_est_rendu_par_l_ecran(self):
        """Le défaut qui a motivé cette liste : composé, exigé, et invisible.

        La date de péremption était réclamée par la validation sur un écran qui
        ne la proposait pas — le formulaire la créait, le gabarit ne la rendait
        pas. Ce test tient l'accord entre les deux.
        """
        for code in metiers.METIERS:
            boutique = fabrique.creer_boutique(f"Boutique {code}")
            Boutique.objects.filter(pk=boutique.pk).update(metier=code)
            boutique.refresh_from_db()
            formulaire = ArticleForm(boutique=boutique)

            rendus = {champ.name for champ in formulaire.champs_de_metier}
            attendus = {
                nom for nom in ArticleForm.CHAMPS_DE_METIER if nom in formulaire.fields
            }
            with self.subTest(metier=code):
                self.assertEqual(rendus, attendus)

    def test_l_ecran_affiche_reellement_les_champs_du_metier(self):
        self.client.login(telephone=self.pharmacienne.telephone, password=MOT_DE_PASSE)
        reponse = self.client.get(reverse("nouvel_article"))

        self.assertContains(reponse, 'name="date_peremption"')
        self.assertContains(reponse, 'name="numero_lot"')
        self.assertContains(reponse, 'name="sur_ordonnance"')


class VenteAuComptoirTest(SocleOfficine):
    def test_le_drapeau_est_fige_sur_la_ligne(self):
        ticket = self.vendre(self.amoxicilline, mention="Dr Manga, 11/09/2026")

        with contexte_boutique(self.boutique):
            lignes = list(LigneTicket.objects.filter(ticket=ticket))
        self.assertEqual([l.sur_ordonnance for l in lignes], [True])

    def test_un_medicament_reclasse_ne_reecrit_pas_le_registre(self):
        """Un registre décrit ce qui était vrai au moment de la délivrance."""
        ticket = self.vendre(self.paracetamol)

        with contexte_boutique(self.boutique):
            Produit.objects.filter(pk=self.paracetamol.produit_id).update(sur_ordonnance=True)
            ligne = LigneTicket.objects.get(ticket=ticket)
        self.assertFalse(ligne.sur_ordonnance)

    def test_la_mention_est_conservee(self):
        ticket = self.vendre(self.amoxicilline, mention="Dr Manga, 11/09/2026")
        self.assertEqual(self.relire(ticket).mention_ordonnance, "Dr Manga, 11/09/2026")

    def test_une_vente_sans_mention_n_est_pas_refusee(self):
        """La boîte est partie : refuser n'effacerait que la trace (ADR-005)."""
        ticket = self.vendre(self.amoxicilline)

        relu = self.relire(ticket)
        self.assertEqual(relu.etat, Ticket.CLOTURE)
        self.assertEqual(relu.mention_ordonnance, "")

    def test_elle_ressort_dans_les_delivrances_a_consigner(self):
        self.vendre(self.amoxicilline)
        with contexte_boutique(self.boutique):
            a_faire = list(caisse.delivrances_sur_ordonnance(incompletes_seulement=True))
        self.assertEqual(len(a_faire), 1)

    def test_une_vente_sans_medicament_sur_ordonnance_n_y_figure_pas(self):
        self.vendre(self.paracetamol)
        with contexte_boutique(self.boutique):
            self.assertEqual(list(caisse.delivrances_sur_ordonnance()), [])

    def test_consigner_apres_coup(self):
        ticket = self.vendre(self.amoxicilline)
        with contexte_boutique(self.boutique):
            caisse.consigner_ordonnance(ticket, mention="Dr Manga, 11/09/2026")
            self.assertEqual(
                caisse.delivrances_sur_ordonnance(incompletes_seulement=True).count(), 0
            )

    def test_une_mention_vide_ne_consigne_rien(self):
        ticket = self.vendre(self.amoxicilline)
        with contexte_boutique(self.boutique):
            with self.assertRaises(caisse.TicketInvalide):
                caisse.consigner_ordonnance(ticket, mention="   ")


class VitrineTest(SocleOfficine):
    """Le retrait de la vente en ligne est une interdiction, pas un filtre."""

    def test_le_medicament_sur_ordonnance_n_est_pas_au_catalogue(self):
        articles = catalogue.articles_en_vitrine(boutique=self.boutique)

        self.assertIn(self.paracetamol, articles)
        self.assertNotIn(self.amoxicilline, articles)

    def test_il_est_introuvable_par_la_recherche(self):
        self.assertEqual(
            catalogue.articles_en_vitrine(recherche="Amoxicilline"), []
        )

    def test_son_lien_direct_ne_fonctionne_pas(self):
        """Un lien gardé dans un favori ne doit pas contourner la règle."""
        self.assertIsNone(catalogue.article_par_identifiant(self.amoxicilline.pk))
        self.assertIsNotNone(catalogue.article_par_identifiant(self.paracetamol.pk))

    def test_sa_page_publique_repond_404(self):
        reponse = self.client.get(f"/marche/article/{self.amoxicilline.pk}/")
        self.assertEqual(reponse.status_code, 404)

    def test_il_ne_peut_pas_entrer_dans_un_panier(self):
        reponse = self.client.post(
            f"/marche/panier/ajouter/{self.amoxicilline.pk}/", {"quantite": "1"}
        )
        self.assertIn(reponse.status_code, (302, 404))

        panier = self.client.session.get("panier") or {}
        self.assertNotIn(str(self.amoxicilline.pk), panier)


class EcranTest(SocleOfficine):
    def setUp(self):
        super().setUp()
        self.client.login(telephone=self.pharmacienne.telephone, password=MOT_DE_PASSE)

    def test_l_ordonnancier_s_ouvre_en_officine(self):
        self.assertEqual(self.client.get(reverse("ordonnancier")).status_code, 200)

    def test_il_repond_404_ailleurs(self):
        """404 plutôt qu'un registre vide : une quincaillerie ne délivre rien."""
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="QUINCAILLERIE")
        self.assertEqual(self.client.get(reverse("ordonnancier")).status_code, 404)

    def test_il_separe_ce_qui_reste_a_faire(self):
        self.vendre(self.amoxicilline)
        self.vendre(self.amoxicilline, mention="Dr Manga, 11/09/2026")

        reponse = self.client.get(reverse("ordonnancier"))
        self.assertEqual(len(reponse.context["incompletes"]), 1)
        self.assertEqual(len(reponse.context["consignees"]), 1)

    def test_la_pastille_du_rail_compte_les_delivrances_en_attente(self):
        self.vendre(self.amoxicilline)
        reponse = self.client.get(reverse("ventes"))
        self.assertEqual(reponse.context["ordonnances_a_consigner"], 1)

    def test_consigner_depuis_l_ecran(self):
        ticket = self.vendre(self.amoxicilline)
        reponse = self.client.post(
            reverse("ordonnancier_consigner", args=[ticket.pk]),
            {"mention": "Dr Manga, 11/09/2026"},
        )

        self.assertRedirects(reponse, reverse("ordonnancier"))
        self.assertEqual(self.relire(ticket).mention_ordonnance, "Dr Manga, 11/09/2026")

    def test_la_caisse_transporte_le_drapeau_jusqu_au_catalogue_hors_ligne(self):
        """C'est la caisse qui doit réclamer l'ordonnance, réseau ou pas."""
        reponse = self.client.get(reverse("catalogue_json"))
        articles = {a["libelle"]: a for a in reponse.json()["articles"]}

        self.assertTrue(articles["Amoxicilline 1 g"]["sur_ordonnance"])
        self.assertFalse(articles["Paracétamol 500 mg"]["sur_ordonnance"])

    def test_l_ecran_de_caisse_marque_les_medicaments_concernes(self):
        reponse = self.client.get(reverse("caisse"))
        self.assertContains(reponse, 'data-ordonnance="1"')
        self.assertContains(reponse, "mention-ordonnance")


class DroitsTest(SocleOfficine):
    def test_un_vendeur_consulte_mais_ne_consigne_pas_sans_le_droit(self):
        comptable = fabrique.creer_utilisateur("Comptable")
        rattacher(comptable, self.boutique, Role.COMPTABLE)
        ticket = self.vendre(self.amoxicilline)

        self.client.login(telephone=comptable.telephone, password=MOT_DE_PASSE)
        reponse = self.client.post(
            reverse("ordonnancier_consigner", args=[ticket.pk]), {"mention": "Dr X"}
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(self.relire(ticket).mention_ordonnance, "")
