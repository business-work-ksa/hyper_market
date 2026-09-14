"""Suivi à l'unité : numéros de série, IMEI, garantie et atelier.

Quatre propriétés sont éprouvées ici, et chacune protège une promesse faite à un
client réel.

**Le numéro nomme un objet, pas une quantité.** Un exemplaire vendu n'est plus en
stock, un exemplaire repris d'occasion retrouve *sa* ligne — avec son histoire.
Confondre les deux redonnerait un numéro neuf à un appareil déjà connu, et
effacerait ses passages à l'atelier le jour où ils comptent.

**La quantité reste la source de vérité.** Une réception saisie sans les IMEI
ajoute du stock et zéro exemplaire : ce n'est pas une erreur, c'est un écart, et
le système sait le chiffrer. La tentation inverse — refuser la réception — aurait
fait renoncer au suivi dès la première livraison pressée.

**L'échéance de garantie est figée à la vente.** Ramener la garantie du catalogue
de douze à six mois vaut pour les ventes futures ; les échéances déjà consenties
ne bougent pas. C'est la même règle que `sur_ordonnance` figé sur la ligne de
ticket : un engagement décrit ce qui était vrai au moment où il a été pris.

**La couverture d'une réparation est figée au dépôt.** Un appareil déposé la
veille de l'échéance est réparé sous garantie, même rendu trois semaines plus
tard. Recalculer à la sortie ferait basculer en payant une réparation déjà
promise gratuite.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Appartenance, Role
from apps.backoffice.forms import ArticleForm, EntreeStockForm
from apps.catalog.models import Variante
from apps.core.tenancy import contexte_boutique
from apps.inventory import series
from apps.inventory.models import NumeroSerie, PassageAtelier
from apps.inventory.services import entrer_stock
from apps.marketplace import metiers
from apps.marketplace.models import Boutique
from apps.pos import services as caisse
from tests import fabrique

MOT_DE_PASSE = "motdepasse"


def rattacher(utilisateur, boutique, code_role=Role.GERANT) -> None:
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class SocleElectronique(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Nkolo Électronique")
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="ELECTRONIQUE")
        self.boutique.refresh_from_db()
        self.depot = fabrique.creer_depot(self.boutique)

        self.telephone = self.appareil("Téléphone 128 Go", garantie=12, quantite=5)
        self.chargeur = self.appareil("Chargeur rapide 25 W", suivi=False, quantite=40)

        self.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(self.gerant, self.boutique)

    def appareil(self, libelle, *, suivi=True, garantie=0, quantite=0, prix="185000"):
        variante = fabrique.creer_variante(self.boutique, prix=prix, libelle=libelle)
        if suivi or garantie:
            with contexte_boutique(self.boutique):
                Variante.objects.filter(pk=variante.pk).update(
                    suivi_unitaire=suivi, garantie_mois=garantie
                )
            variante.suivi_unitaire = suivi
            variante.garantie_mois = garantie
        if quantite:
            entrer_stock(
                depot=self.depot,
                variante=variante,
                quantite=Decimal(quantite),
                cout_unitaire=Decimal("148000"),
                cree_par=None,
            )
        return variante

    def vendre(self, variante, numeros, *, client="Client", **kwargs):
        """Encaisse un appareil avec ses numéros, dans le contexte de la boutique.

        Le contexte est posé ici et non dans le service : `ouvrir_session` écrit
        une `SessionCaisse`, et la barrière 3 rejette une insertion faite hors du
        contexte de sa boutique.
        """
        with contexte_boutique(self.boutique):
            session = caisse.ouvrir_session(depot=self.depot, caissier=self.gerant)
            ticket, rejoue = caisse.encaisser(
                session=session,
                lignes=[(variante, Decimal("1"), Decimal("0"), numeros)],
                client_nom=client,
                cree_par=self.gerant,
                **kwargs,
            )
        return ticket, rejoue


# ---------------------------------------------------------------------------
# Le référentiel des métiers
# ---------------------------------------------------------------------------
class MetierTest(TestCase):
    def test_l_electronique_declare_les_deux_fonctions(self):
        metier = metiers.METIERS["ELECTRONIQUE"]
        self.assertTrue(metier.a(metiers.SERIE))
        self.assertTrue(metier.a(metiers.GARANTIE))

    def test_une_fonction_declaree_n_est_plus_annoncee_comme_a_venir(self):
        """Une fonction livrée doit disparaître de la liste des promesses.

        C'est la règle de l'en-tête du référentiel : `a_venir` sert à montrer au
        commerçant ce qui n'existe pas encore. Y laisser une fonction câblée
        annoncerait comme future une chose qu'il peut déjà utiliser.
        """
        metier = metiers.METIERS["ELECTRONIQUE"]
        promesses = " ".join(metier.a_venir).lower()
        self.assertNotIn("série", promesses)
        self.assertNotIn("garantie", promesses)

    def test_aucun_autre_metier_ne_suit_les_exemplaires(self):
        """Le suivi à l'unité coûte une saisie par appareil reçu.

        L'ouvrir à un métier qui n'en a pas besoin — une quincaillerie, une
        boulangerie — y ajouterait un champ inutile sur chaque écran de réception.
        """
        suivis = [c for c, m in metiers.METIERS.items() if m.a(metiers.SERIE)]
        self.assertEqual(suivis, ["ELECTRONIQUE"])

    def test_chaque_fonction_declaree_a_un_libelle(self):
        for code in (metiers.SERIE, metiers.GARANTIE):
            self.assertIn(code, metiers.LIBELLES_FONCTIONS)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
class NormalisationTest(TestCase):
    def test_les_espaces_de_saisie_disparaissent(self):
        self.assertEqual(series.normaliser(" 3569 3803 5643809 "), "356938035643809")

    def test_la_casse_est_uniformisee(self):
        self.assertEqual(series.normaliser("sn-5cd9482kj7"), "SN-5CD9482KJ7")

    def test_les_separateurs_du_fabricant_sont_conserves(self):
        """Un tiret dans une référence constructeur en fait partie.

        Le retirer ferait se confondre deux séries distinctes — et la confusion
        ne se verrait qu'au moment d'un litige de garantie.
        """
        self.assertEqual(series.normaliser("SN-123.456"), "SN-123.456")

    def test_les_doublons_de_copier_coller_sont_ecartes(self):
        propres = series.numeros_propres(["A1", "a1", "", "  ", "B2"])
        self.assertEqual(propres, ["A1", "B2"])

    def test_l_ordre_de_saisie_est_conserve(self):
        self.assertEqual(series.numeros_propres(["C", "A", "B"]), ["C", "A", "B"])


# ---------------------------------------------------------------------------
# Réception
# ---------------------------------------------------------------------------
class DeclarationTest(SocleElectronique):
    def test_les_exemplaires_recus_sont_nommes(self):
        declares = series.declarer(
            depot=self.depot, variante=self.telephone, numeros=["IMEI-1", "IMEI-2"]
        )
        self.assertEqual(len(declares), 2)
        with contexte_boutique(self.boutique):
            self.assertEqual(NumeroSerie.objects.filter(etat=NumeroSerie.EN_STOCK).count(), 2)

    def test_une_reception_retransmise_ne_double_pas_les_exemplaires(self):
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])
        rejoue = series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])
        self.assertEqual(rejoue, [])
        with contexte_boutique(self.boutique):
            self.assertEqual(NumeroSerie.objects.count(), 1)

    def test_un_numero_deja_porte_par_un_autre_article_est_refuse(self):
        """Un numéro nomme un objet ; le déplacer effacerait une histoire."""
        autre = self.appareil("Téléphone 64 Go", garantie=12)
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])
        with self.assertRaises(series.NumeroInvalide):
            series.declarer(depot=self.depot, variante=autre, numeros=["IMEI-1"])

    def test_un_article_non_suivi_refuse_les_numeros(self):
        """Sinon on créerait une trace qu'aucun écran ne lit et qu'aucune vente ne consomme."""
        with self.assertRaises(series.NumeroInvalide):
            series.declarer(depot=self.depot, variante=self.chargeur, numeros=["X1"])

    def test_un_appareil_repris_retrouve_sa_ligne(self):
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])
        self.vendre(self.telephone, ["IMEI-1"])

        repris = series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])

        self.assertEqual(len(repris), 1)
        with contexte_boutique(self.boutique):
            self.assertEqual(NumeroSerie.objects.count(), 1)
            exemplaire = NumeroSerie.objects.get(numero="IMEI-1")
        self.assertEqual(exemplaire.etat, NumeroSerie.EN_STOCK)
        # La vente passée reste lisible : c'est bien cet appareil-là qui avait
        # été vendu, et c'est ce qui donne sa valeur à la reprise.
        self.assertIsNotNone(exemplaire.vendu_le)


# ---------------------------------------------------------------------------
# Vente
# ---------------------------------------------------------------------------
class VenteTest(SocleElectronique):
    def setUp(self):
        super().setUp()
        series.declarer(
            depot=self.depot, variante=self.telephone, numeros=["IMEI-1", "IMEI-2", "IMEI-3"]
        )

    def test_l_exemplaire_vendu_quitte_le_stock(self):
        ticket, _ = self.vendre(self.telephone, ["IMEI-1"], client="Marthe Ngo")

        with contexte_boutique(self.boutique):
            exemplaire = NumeroSerie.objects.get(numero="IMEI-1")
        self.assertEqual(exemplaire.etat, NumeroSerie.VENDU)
        self.assertEqual(exemplaire.ticket_id, ticket.pk)
        self.assertEqual(exemplaire.ticket_numero, ticket.numero)
        self.assertEqual(exemplaire.client, "Marthe Ngo")

    def test_les_autres_exemplaires_restent_en_stock(self):
        self.vendre(self.telephone, ["IMEI-1"])
        with contexte_boutique(self.boutique):
            restants = set(
                NumeroSerie.objects.filter(etat=NumeroSerie.EN_STOCK).values_list(
                    "numero", flat=True
                )
            )
        self.assertEqual(restants, {"IMEI-2", "IMEI-3"})

    def test_un_numero_inconnu_est_cree_plutot_que_refuse(self):
        """L'appareil est parti avec le client : refuser n'effacerait que la trace.

        Même règle que le stock négatif (ADR-005). L'exemplaire est créé à
        l'état vendu, et son commentaire dit qu'il n'a jamais été reçu.
        """
        self.vendre(self.telephone, ["IMEI-INCONNU"])

        with contexte_boutique(self.boutique):
            exemplaire = NumeroSerie.objects.get(numero="IMEI-INCONNU")
        self.assertEqual(exemplaire.etat, NumeroSerie.VENDU)
        self.assertIn("sans réception", exemplaire.commentaire)

    def test_une_vente_sans_numero_n_est_jamais_bloquee(self):
        """Le registre ne commande pas la caisse.

        Un vendeur qui n'a pas relevé l'IMEI encaisse quand même : l'écart est
        ensuite visible, et rattrapable depuis la fiche de l'article.
        """
        ticket, _ = self.vendre(self.telephone, [])
        self.assertEqual(ticket.etat, "cloture")

    def test_un_encaissement_retransmis_ne_rejoue_pas_la_vente(self):
        cle = "018f0000-0000-7000-8000-0000000000aa"
        premier, rejoue_1 = self.vendre(self.telephone, ["IMEI-1"], operation_id=cle)
        second, rejoue_2 = self.vendre(self.telephone, ["IMEI-1"], operation_id=cle)

        self.assertEqual(premier.pk, second.pk)
        self.assertFalse(rejoue_1)
        self.assertTrue(rejoue_2)
        with contexte_boutique(self.boutique):
            self.assertEqual(NumeroSerie.objects.filter(numero="IMEI-1").count(), 1)

    def test_les_numeros_d_un_article_non_suivi_sont_ignores(self):
        """Un accessoire ne se met pas à porter des numéros par accident."""
        with contexte_boutique(self.boutique):
            session = caisse.ouvrir_session(depot=self.depot, caissier=self.gerant)
            caisse.encaisser(
                session=session,
                lignes=[(self.chargeur, Decimal("1"), Decimal("0"), [])],
                cree_par=self.gerant,
            )
            self.assertFalse(NumeroSerie.objects.filter(variante=self.chargeur).exists())


# ---------------------------------------------------------------------------
# Garantie
# ---------------------------------------------------------------------------
class GarantieTest(SocleElectronique):
    def test_l_echeance_se_compte_en_mois_de_calendrier(self):
        self.assertEqual(
            series.echeance_de_garantie(date(2026, 3, 15), 12), date(2027, 3, 15)
        )

    def test_le_31_recule_au_dernier_jour_reel_du_mois(self):
        """Un 31 janvier plus un mois donne le 28 février, pas le 3 mars."""
        self.assertEqual(series.echeance_de_garantie(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_le_29_fevrier_recule_aussi(self):
        self.assertEqual(series.echeance_de_garantie(date(2024, 2, 29), 12), date(2025, 2, 28))

    def test_une_garantie_nulle_ne_produit_aucune_echeance(self):
        self.assertIsNone(series.echeance_de_garantie(date(2026, 3, 15), 0))

    def test_l_echeance_est_figee_a_la_vente(self):
        """Raccourcir la garantie du catalogue ne reprend pas celles déjà vendues."""
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])
        self.vendre(self.telephone, ["IMEI-1"])

        with contexte_boutique(self.boutique):
            avant = NumeroSerie.objects.get(numero="IMEI-1").garantie_fin
            Variante.objects.filter(pk=self.telephone.pk).update(garantie_mois=1)
            apres = NumeroSerie.objects.get(numero="IMEI-1").garantie_fin

        self.assertEqual(avant, apres)

    def test_un_appareil_vendu_hier_est_sous_garantie(self):
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])
        self.vendre(self.telephone, ["IMEI-1"])
        with contexte_boutique(self.boutique):
            exemplaire = NumeroSerie.objects.get(numero="IMEI-1")
        self.assertTrue(exemplaire.sous_garantie())

    def test_une_echeance_passee_n_est_plus_couverte(self):
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])
        self.vendre(self.telephone, ["IMEI-1"])
        with contexte_boutique(self.boutique):
            exemplaire = NumeroSerie.objects.get(numero="IMEI-1")
            NumeroSerie.objects.filter(pk=exemplaire.pk).update(
                garantie_fin=timezone.localdate() - timedelta(days=1)
            )
            exemplaire.refresh_from_db()
        self.assertFalse(exemplaire.sous_garantie())

    def test_un_appareil_jamais_vendu_n_est_pas_sous_garantie(self):
        """Dire « oui » par défaut ferait offrir des réparations jamais promises."""
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])
        with contexte_boutique(self.boutique):
            self.assertFalse(NumeroSerie.objects.get(numero="IMEI-1").sous_garantie())


# ---------------------------------------------------------------------------
# Atelier
# ---------------------------------------------------------------------------
class AtelierTest(SocleElectronique):
    def setUp(self):
        super().setUp()
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-1"])
        self.vendre(self.telephone, ["IMEI-1"])
        with contexte_boutique(self.boutique):
            self.exemplaire = NumeroSerie.objects.get(numero="IMEI-1")

    def test_le_depot_a_l_atelier_change_l_etat(self):
        series.entrer_a_l_atelier(self.exemplaire, motif="Ne charge plus")
        with contexte_boutique(self.boutique):
            self.exemplaire.refresh_from_db()
        self.assertEqual(self.exemplaire.etat, NumeroSerie.ATELIER)

    def test_un_motif_vide_est_refuse(self):
        """Un passage sans motif ne se retrouve pas, et ne sert donc à rien."""
        with self.assertRaises(series.NumeroInvalide):
            series.entrer_a_l_atelier(self.exemplaire, motif="   ")

    def test_un_second_depot_immediat_ne_cree_pas_deux_passages(self):
        series.entrer_a_l_atelier(self.exemplaire, motif="Ne charge plus")
        series.entrer_a_l_atelier(self.exemplaire, motif="Ne charge plus")
        with contexte_boutique(self.boutique):
            self.assertEqual(PassageAtelier.objects.count(), 1)

    def test_la_couverture_est_figee_au_depot(self):
        """Rendu après l'échéance, l'appareil reste réparé sous garantie."""
        passage = series.entrer_a_l_atelier(self.exemplaire, motif="Écran cassé")
        self.assertTrue(passage.sous_garantie)

        with contexte_boutique(self.boutique):
            NumeroSerie.objects.filter(pk=self.exemplaire.pk).update(
                garantie_fin=timezone.localdate() - timedelta(days=1)
            )
            self.exemplaire.refresh_from_db()

        series.sortir_de_l_atelier(self.exemplaire, resultat="Écran remplacé")
        with contexte_boutique(self.boutique):
            passage.refresh_from_db()
        self.assertTrue(passage.sous_garantie)

    def test_un_appareil_vendu_ressort_vendu(self):
        series.entrer_a_l_atelier(self.exemplaire, motif="Écran cassé")
        series.sortir_de_l_atelier(self.exemplaire, resultat="Réparé")
        with contexte_boutique(self.boutique):
            self.exemplaire.refresh_from_db()
        self.assertEqual(self.exemplaire.etat, NumeroSerie.VENDU)

    def test_un_appareil_jamais_vendu_ressort_en_stock(self):
        """Le supposer vendu remettrait en vente un appareil absent de la boutique."""
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-2"])
        with contexte_boutique(self.boutique):
            neuf = NumeroSerie.objects.get(numero="IMEI-2")
        series.entrer_a_l_atelier(neuf, motif="Défaut à la réception")
        series.sortir_de_l_atelier(neuf, resultat="Échangé au grossiste")
        with contexte_boutique(self.boutique):
            neuf.refresh_from_db()
        self.assertEqual(neuf.etat, NumeroSerie.EN_STOCK)

    def test_sortir_un_appareil_qui_n_est_pas_a_l_atelier_ne_fait_rien(self):
        self.assertIsNone(series.sortir_de_l_atelier(self.exemplaire, resultat="—"))


# ---------------------------------------------------------------------------
# Écarts de numérotation
# ---------------------------------------------------------------------------
class EcartTest(SocleElectronique):
    def test_une_reception_sans_numeros_produit_un_ecart(self):
        with contexte_boutique(self.boutique):
            ecarts = series.ecarts_de_numerotation(depot=self.depot)
        self.assertEqual(len(ecarts), 1)
        self.assertEqual(ecarts[0]["manquants"], 5)

    def test_nommer_les_exemplaires_resorbe_l_ecart(self):
        series.declarer(
            depot=self.depot,
            variante=self.telephone,
            numeros=["I1", "I2", "I3", "I4", "I5"],
        )
        with contexte_boutique(self.boutique):
            self.assertEqual(series.ecarts_de_numerotation(depot=self.depot), [])

    def test_un_article_non_suivi_ne_produit_jamais_d_ecart(self):
        """Quarante chargeurs sans numéro ne sont pas quarante appareils perdus."""
        with contexte_boutique(self.boutique):
            ecarts = series.ecarts_de_numerotation(depot=self.depot)
        self.assertNotIn(self.chargeur.pk, [e["variante"].pk for e in ecarts])


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------
class RechercheTest(SocleElectronique):
    def setUp(self):
        super().setUp()
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["356938035643809"])

    def test_le_numero_se_retrouve_tel_qu_il_a_ete_saisi(self):
        with contexte_boutique(self.boutique):
            self.assertIsNotNone(series.rechercher("356938035643809"))

    def test_les_espaces_d_une_relecture_ne_font_pas_echouer_la_recherche(self):
        """Un IMEI se lit sur un écran, et se retape avec des espaces."""
        with contexte_boutique(self.boutique):
            self.assertIsNotNone(series.rechercher(" 3569 3803 5643809 "))

    def test_une_recherche_vide_ne_renvoie_rien(self):
        with contexte_boutique(self.boutique):
            self.assertIsNone(series.rechercher("   "))

    def test_le_numero_d_une_autre_boutique_reste_invisible(self):
        """La barrière du multi-tenant ne s'arrête pas aux écrans de gestion."""
        voisine = fabrique.creer_boutique("Voisine")
        with contexte_boutique(voisine):
            self.assertIsNone(series.rechercher("356938035643809"))


# ---------------------------------------------------------------------------
# Formulaires
# ---------------------------------------------------------------------------
class FormulaireTest(SocleElectronique):
    def test_l_article_d_electronique_propose_le_suivi_et_la_garantie(self):
        formulaire = ArticleForm(boutique=self.boutique)
        self.assertIn("suivi_unitaire", formulaire.fields)
        self.assertIn("garantie_mois", formulaire.fields)

    def test_un_autre_metier_ne_les_propose_pas(self):
        autre = fabrique.creer_boutique("Quincaillerie")
        Boutique.objects.filter(pk=autre.pk).update(metier="QUINCAILLERIE")
        autre.refresh_from_db()
        formulaire = ArticleForm(boutique=autre)
        self.assertNotIn("suivi_unitaire", formulaire.fields)
        self.assertNotIn("garantie_mois", formulaire.fields)

    def test_les_champs_composes_sont_tous_affichables(self):
        """Le défaut qui compte : un champ exigé par la validation et absent de l'écran.

        `champs_de_metier` est ce que le gabarit affiche ; `fields` est ce que le
        formulaire compose. Les laisser diverger rend un champ invisible et
        pourtant obligatoire — c'est arrivé à la date de péremption.
        """
        formulaire = ArticleForm(boutique=self.boutique)
        affichables = {champ.name for champ in formulaire.champs_de_metier}
        for nom in ("suivi_unitaire", "garantie_mois"):
            self.assertIn(nom, affichables)

    def test_la_reception_propose_les_numeros_pour_un_article_suivi(self):
        formulaire = EntreeStockForm(variante=self.telephone)
        self.assertIn("numeros_serie", formulaire.fields)

    def test_la_reception_d_un_accessoire_ne_les_propose_pas(self):
        formulaire = EntreeStockForm(variante=self.chargeur)
        self.assertNotIn("numeros_serie", formulaire.fields)

    def test_plus_de_numeros_que_d_appareils_est_refuse(self):
        """Cinq IMEI pour trois téléphones est une ligne de trop collée.

        Les accepter créerait des exemplaires qui ne sont dans aucun carton.
        """
        formulaire = EntreeStockForm(
            {
                "quantite": "3",
                "cout_unitaire": "148000",
                "commentaire": "",
                "numeros_serie": "A\nB\nC\nD\nE",
            },
            variante=self.telephone,
        )
        self.assertFalse(formulaire.is_valid())
        self.assertIn("numeros_serie", formulaire.errors)

    def test_moins_de_numeros_que_d_appareils_reste_accepte(self):
        """La marchandise est arrivée : refuser la réception serait pire que l'écart."""
        formulaire = EntreeStockForm(
            {
                "quantite": "3",
                "cout_unitaire": "148000",
                "commentaire": "",
                "numeros_serie": "A\nB",
            },
            variante=self.telephone,
        )
        self.assertTrue(formulaire.is_valid(), formulaire.errors)


# ---------------------------------------------------------------------------
# Écrans
# ---------------------------------------------------------------------------
class EcranTest(SocleElectronique):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.gerant)
        session = self.client.session
        session["boutique_id"] = str(self.boutique.pk)
        session["depot_id"] = str(self.depot.pk)
        session.save()

    def test_l_ecran_de_garantie_s_ouvre(self):
        reponse = self.client.get(reverse("garantie"))
        self.assertEqual(reponse.status_code, 200)

    def test_un_metier_qui_ne_suit_rien_n_a_pas_l_ecran(self):
        """Un écran vide use la confiance dans les autres : il n'existe pas."""
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="QUINCAILLERIE")
        reponse = self.client.get(reverse("garantie"))
        self.assertEqual(reponse.status_code, 404)

    def test_la_recherche_montre_l_appareil(self):
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-42"])
        reponse = self.client.get(reverse("garantie"), {"numero": "imei-42"})
        self.assertContains(reponse, "IMEI-42")

    def test_un_numero_inconnu_le_dit(self):
        reponse = self.client.get(reverse("garantie"), {"numero": "RIEN"})
        self.assertContains(reponse, "Aucun appareil")

    def test_l_ecart_de_numerotation_est_affiche(self):
        reponse = self.client.get(reverse("garantie"))
        self.assertContains(reponse, "En stock sans numéro")

    def test_la_fiche_article_montre_les_exemplaires(self):
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-7"])
        reponse = self.client.get(reverse("article", args=[self.telephone.pk]))
        self.assertContains(reponse, "Exemplaires suivis")
        self.assertContains(reponse, "IMEI-7")

    def test_la_fiche_d_un_accessoire_ne_montre_pas_la_carte(self):
        reponse = self.client.get(reverse("article", args=[self.chargeur.pk]))
        self.assertNotContains(reponse, "Exemplaires suivis")

    def test_la_declaration_depuis_la_fiche_nomme_les_exemplaires(self):
        reponse = self.client.post(
            reverse("exemplaires_declarer", args=[self.telephone.pk]),
            {"numeros": "IMEI-A\nIMEI-B"},
        )
        self.assertEqual(reponse.status_code, 302)
        with contexte_boutique(self.boutique):
            self.assertEqual(NumeroSerie.objects.count(), 2)

    def test_le_depot_a_l_atelier_passe_par_l_ecran(self):
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-9"])
        with contexte_boutique(self.boutique):
            exemplaire = NumeroSerie.objects.get(numero="IMEI-9")

        reponse = self.client.post(
            reverse("atelier_entrer", args=[exemplaire.pk]), {"motif": "Ne charge plus"}
        )
        self.assertEqual(reponse.status_code, 302)
        with contexte_boutique(self.boutique):
            exemplaire.refresh_from_db()
        self.assertEqual(exemplaire.etat, NumeroSerie.ATELIER)

    def test_la_reception_enregistre_les_numeros(self):
        reponse = self.client.post(
            reverse("entree_stock", args=[self.telephone.pk]),
            {
                "quantite": "2",
                "cout_unitaire": "148000",
                "commentaire": "BL-2026-118",
                "numeros_serie": "IMEI-X\nIMEI-Y",
            },
        )
        self.assertEqual(reponse.status_code, 302)
        with contexte_boutique(self.boutique):
            numeros = set(NumeroSerie.objects.values_list("numero", flat=True))
        self.assertEqual(numeros, {"IMEI-X", "IMEI-Y"})

    def test_le_catalogue_de_caisse_porte_le_drapeau(self):
        """La caisse doit réclamer l'IMEI hors ligne aussi : le drapeau voyage."""
        reponse = self.client.get(reverse("catalogue_json"))
        articles = {a["sku"]: a for a in reponse.json()["articles"]}
        self.assertTrue(articles[self.telephone.sku]["suivi_unitaire"])
        self.assertFalse(articles[self.chargeur.sku]["suivi_unitaire"])

    def test_l_encaissement_du_comptoir_transmet_les_numeros(self):
        series.declarer(depot=self.depot, variante=self.telephone, numeros=["IMEI-Z"])
        reponse = self.client.post(
            reverse("caisse_encaisser"),
            data={
                "operation_id": "018f0000-0000-7000-8000-0000000000bb",
                "lignes": [
                    {"variante": str(self.telephone.pk), "quantite": 1, "numeros": ["IMEI-Z"]}
                ],
                "moyen": "especes",
            },
            content_type="application/json",
        )
        self.assertEqual(reponse.status_code, 200, reponse.content)
        with contexte_boutique(self.boutique):
            self.assertEqual(
                NumeroSerie.objects.get(numero="IMEI-Z").etat, NumeroSerie.VENDU
            )
