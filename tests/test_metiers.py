"""Les métiers : ce que le logiciel déduit de ce qu'une boutique vend.

Trois choses s'y jouent, et la troisième est la seule qui puisse blesser
quelqu'un.

**Le vocabulaire.** Un pharmacien à qui l'écran parle d'« articles » se demande
s'il est au bon endroit. Ce n'est pas de l'habillage : c'est ce qui distingue un
logiciel fait pour lui d'un logiciel générique reconfiguré.

**Les valeurs par défaut.** Le régime de TVA d'une officine est l'exonération ;
un défaut qu'il faut corriger à chaque ligne finit par être subi, et la TVA
déclarée devient fausse.

**Le suivi des péremptions.** Une date manquante, c'est une alerte qui ne se
déclenchera jamais. Ces tests protègent surtout deux propriétés : la sortie
consomme le lot **le plus proche de périmer**, et le mécanisme est **entièrement
inerte** là où le métier ne l'active pas — une quincaillerie ne paie pas le coût
de la fonction d'une pharmacie.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Appartenance, Role
from apps.backoffice.forms import ArticleForm
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import LotStock, NiveauStock
from apps.inventory.services import entrer_stock, lots_a_surveiller, sortir_stock
from apps.marketplace import metiers
from apps.marketplace.models import Boutique
from tests import fabrique


def rattacher(utilisateur, boutique, code_role=Role.GERANT):
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    return Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class ReferentielTest(TestCase):
    def test_il_y_a_dix_metiers(self):
        self.assertEqual(len(metiers.METIERS), 10)

    def test_chaque_metier_est_coherent_avec_sa_cle(self):
        for code, metier in metiers.METIERS.items():
            with self.subTest(metier=code):
                self.assertEqual(metier.code, code)
                self.assertTrue(metier.libelle and metier.resume)
                self.assertTrue(metier.article and metier.articles)

    def test_toute_fonction_declaree_a_un_libelle(self):
        """Une fonction sans libellé serait invisible sur la fiche de la boutique."""
        for metier in metiers.METIERS.values():
            for fonction in metier.fonctions:
                with self.subTest(metier=metier.code, fonction=fonction):
                    self.assertIn(fonction, metiers.LIBELLES_FONCTIONS)

    def test_le_vocabulaire_est_grammaticalement_juste(self):
        """« Nouveau pièce » ou « Nom du article » font douter du reste du logiciel.

        Le genre et l'élision sont portés par le référentiel, pas devinés dans
        chaque gabarit : c'est le seul endroit où l'on peut les vérifier tous
        d'un coup, et c'est ce que fait ce test.
        """
        attendus = {
            "COMMERCE_GENERAL": ("Nouvel article", "de l'article"),
            "PHARMACIE": ("Nouveau médicament", "du médicament"),
            "PIECES_AUTO": ("Nouvelle pièce", "de la pièce"),
            "ELECTRONIQUE": ("Nouvel appareil", "de l'appareil"),
            "RESTAURATION": ("Nouveau plat", "du plat"),
        }
        for code, (nouveau, du) in attendus.items():
            metier = metiers.METIERS[code]
            with self.subTest(metier=code):
                self.assertEqual(f"{metier.nouveau} {metier.article}", nouveau)
                self.assertEqual(metier.du_article, du)

    def test_aucun_metier_ne_produit_une_elision_manquante(self):
        for metier in metiers.METIERS.values():
            with self.subTest(metier=metier.code):
                self.assertNotIn("du a", metier.du_article)
                self.assertNotIn("Nouveau a", f"{metier.nouveau} {metier.article}")

    def test_le_commerce_general_n_active_rien(self):
        """C'est le socle, et donc le repli sûr : le plus petit dénominateur."""
        self.assertEqual(metiers.METIERS[metiers.METIER_DEFAUT].fonctions, frozenset())

    def test_un_code_inconnu_retombe_sur_le_commerce_general(self):
        """Une boutique dont le code a disparu du référentiel doit continuer de tourner."""
        for essai in ("", None, "METIER_SUPPRIME"):
            with self.subTest(code=essai):
                self.assertEqual(metiers.metier_de(essai).code, metiers.METIER_DEFAUT)

    def test_la_pharmacie_est_exoneree_de_tva_par_defaut(self):
        """Les médicaments essentiels le sont au Cameroun ; le défaut doit le refléter."""
        self.assertEqual(metiers.METIERS["PHARMACIE"].regime_tva_defaut, "exonere")

    def test_les_produits_frais_se_vendent_au_kilo_par_defaut(self):
        self.assertEqual(metiers.METIERS["PRODUITS_FRAIS"].unite_defaut, "KG")

    def test_une_boutique_sans_metier_declare_reste_utilisable(self):
        boutique = fabrique.creer_boutique("Sans métier")
        self.assertEqual(boutique.metier_choisi.code, metiers.METIER_DEFAUT)


class FormulaireComposeTest(TestCase):
    """Le formulaire d'article est composé pour le métier, pas grisé après coup."""

    def _boutique(self, metier):
        boutique = fabrique.creer_boutique(f"Boutique {metier}")
        Boutique.objects.filter(pk=boutique.pk).update(metier=metier)
        boutique.refresh_from_db()
        return boutique

    def test_la_pharmacie_demande_la_peremption_et_le_lot(self):
        formulaire = ArticleForm(boutique=self._boutique("PHARMACIE"))
        self.assertIn("date_peremption", formulaire.fields)
        self.assertIn("numero_lot", formulaire.fields)

    def test_la_quincaillerie_ne_les_demande_pas(self):
        """Une saisie de plus par référence, pour rien, ne se rattrape pas."""
        formulaire = ArticleForm(boutique=self._boutique("QUINCAILLERIE"))
        self.assertNotIn("date_peremption", formulaire.fields)
        self.assertNotIn("numero_lot", formulaire.fields)

    def test_les_produits_frais_demandent_la_date_mais_pas_le_lot(self):
        """Un poissonnier suit des dates, pas des numéros de fabrication."""
        formulaire = ArticleForm(boutique=self._boutique("PRODUITS_FRAIS"))
        self.assertIn("date_peremption", formulaire.fields)
        self.assertNotIn("numero_lot", formulaire.fields)

    def test_le_libelle_parle_le_metier(self):
        formulaire = ArticleForm(boutique=self._boutique("PHARMACIE"))
        self.assertIn("médicament", formulaire.fields["libelle"].label)

    def test_le_regime_de_tva_par_defaut_suit_le_metier(self):
        self.assertEqual(
            ArticleForm(boutique=self._boutique("PHARMACIE")).fields["regime_tva"].initial,
            "exonere",
        )
        self.assertEqual(
            ArticleForm(boutique=self._boutique("QUINCAILLERIE")).fields["regime_tva"].initial,
            "normal",
        )

    def test_un_stock_initial_sans_date_est_refuse_en_pharmacie(self):
        """Sinon l'alerte de péremption ne se déclenchera jamais sur cette ligne."""
        formulaire = ArticleForm(
            data={
                "libelle": "Amoxicilline 1 g",
                "sku": "PHA-TEST",
                "prix_vente": "3200",
                "cout_unitaire": "2100",
                "quantite": "10",
                "seuil_alerte": "2",
                "regime_tva": "exonere",
            },
            boutique=self._boutique("PHARMACIE"),
        )
        self.assertFalse(formulaire.is_valid())
        self.assertIn("date_peremption", formulaire.errors)

    def test_la_meme_saisie_passe_en_quincaillerie(self):
        formulaire = ArticleForm(
            data={
                "libelle": "Ciment 50 kg",
                "sku": "QUI-TEST",
                "prix_vente": "6500",
                "cout_unitaire": "5200",
                "quantite": "10",
                "seuil_alerte": "2",
                "regime_tva": "normal",
            },
            boutique=self._boutique("QUINCAILLERIE"),
        )
        self.assertTrue(formulaire.is_valid(), formulaire.errors)


class SocleLots(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Officine")
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="PHARMACIE")
        self.boutique.refresh_from_db()
        self.depot = fabrique.creer_depot(self.boutique)
        self.medicament = fabrique.creer_variante(self.boutique, prix="600")
        self.aujourd_hui = timezone.localdate()

    def recevoir(self, quantite, jours, numero="", cout="380"):
        return entrer_stock(
            depot=self.depot,
            variante=self.medicament,
            quantite=Decimal(quantite),
            cout_unitaire=Decimal(cout),
            date_peremption=self.aujourd_hui + timedelta(days=jours),
            numero_lot=numero,
        )

    def lots(self):
        with contexte_boutique(self.boutique):
            return list(LotStock.objects.order_by("date_peremption"))


class SuiviParLotTest(SocleLots):
    def test_une_reception_datee_cree_son_lot(self):
        self.recevoir(50, jours=180, numero="L24A118")
        lots = self.lots()

        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].quantite, Decimal("50.0000"))
        self.assertEqual(lots[0].numero, "L24A118")

    def test_deux_receptions_du_meme_lot_alimentent_la_meme_ligne(self):
        """Un numéro de lot désigne une fabrication, pas une livraison."""
        self.recevoir(50, jours=180, numero="L24A118")
        self.recevoir(30, jours=180, numero="L24A118")

        lots = self.lots()
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].quantite, Decimal("80.0000"))

    def test_deux_echeances_differentes_font_deux_lots(self):
        self.recevoir(50, jours=180, numero="L24A118")
        self.recevoir(30, jours=30, numero="L24B072")
        self.assertEqual(len(self.lots()), 2)

    def test_la_sortie_consomme_le_plus_proche_de_perimer(self):
        """PEPS par péremption : c'est le seul ordre qui minimise la perte."""
        self.recevoir(50, jours=180, numero="LOIN")
        self.recevoir(20, jours=10, numero="PROCHE")

        sortir_stock(depot=self.depot, variante=self.medicament, quantite=Decimal("15"))

        par_numero = {l.numero: l.quantite for l in self.lots()}
        self.assertEqual(par_numero["PROCHE"], Decimal("5.0000"))
        self.assertEqual(par_numero["LOIN"], Decimal("50.0000"))

    def test_une_sortie_traverse_plusieurs_lots(self):
        self.recevoir(20, jours=10, numero="PROCHE")
        self.recevoir(50, jours=180, numero="LOIN")

        sortir_stock(depot=self.depot, variante=self.medicament, quantite=Decimal("35"))

        par_numero = {l.numero: l.quantite for l in self.lots()}
        self.assertEqual(par_numero["PROCHE"], Decimal("0.0000"))
        self.assertEqual(par_numero["LOIN"], Decimal("35.0000"))

    def test_une_sortie_non_couverte_par_les_lots_passe_quand_meme(self):
        """Le stock peut être négatif (ADR-005) : refuser la vente serait pire."""
        self.recevoir(5, jours=10, numero="PETIT")
        sortir_stock(depot=self.depot, variante=self.medicament, quantite=Decimal("12"))

        with contexte_boutique(self.boutique):
            niveau = NiveauStock.objects.get(variante=self.medicament, depot=self.depot)
        self.assertEqual(niveau.quantite, Decimal("-7.0000"))
        self.assertEqual(self.lots()[0].quantite, Decimal("0.0000"))

    def test_le_lot_ne_porte_pas_de_cout_et_le_cmp_reste_global(self):
        """Le lot répond « quoi périme quand », le CMP « combien ça a coûté »."""
        self.recevoir(10, jours=180, numero="A", cout="400")
        self.recevoir(10, jours=90, numero="B", cout="600")

        with contexte_boutique(self.boutique):
            niveau = NiveauStock.objects.get(variante=self.medicament, depot=self.depot)
        self.assertEqual(niveau.cmp, Decimal("500.0000"))
        self.assertFalse(hasattr(self.lots()[0], "cout_unitaire"))


class MecanismeInerteTest(TestCase):
    """Là où le métier n'active pas la fonction, rien ne se crée et rien ne coûte."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Quincaillerie")
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="QUINCAILLERIE")
        self.depot = fabrique.creer_depot(self.boutique)
        self.article = fabrique.creer_variante(self.boutique, prix="6500")

    def test_une_reception_sans_date_ne_cree_aucun_lot(self):
        entrer_stock(
            depot=self.depot,
            variante=self.article,
            quantite=Decimal("100"),
            cout_unitaire=Decimal("5200"),
        )
        with contexte_boutique(self.boutique):
            self.assertEqual(LotStock.objects.count(), 0)

    def test_une_sortie_sans_lot_ne_plante_pas(self):
        entrer_stock(
            depot=self.depot,
            variante=self.article,
            quantite=Decimal("100"),
            cout_unitaire=Decimal("5200"),
        )
        sortir_stock(depot=self.depot, variante=self.article, quantite=Decimal("40"))

        with contexte_boutique(self.boutique):
            niveau = NiveauStock.objects.get(variante=self.article, depot=self.depot)
        self.assertEqual(niveau.quantite, Decimal("60.0000"))


class EcranPeremptionsTest(SocleLots):
    def setUp(self):
        super().setUp()
        self.gerant = fabrique.creer_utilisateur("Pharmacienne")
        rattacher(self.gerant, self.boutique, Role.GERANT)
        self.client.force_login(self.gerant)

    def test_l_ecran_separe_les_perimes_des_bientot_perimes(self):
        self.recevoir(10, jours=-5, numero="DEJA")
        self.recevoir(20, jours=12, numero="BIENTOT")
        self.recevoir(30, jours=400, numero="TRANQUILLE")

        reponse = self.client.get(reverse("peremptions"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual([l.numero for l in reponse.context["perimes"]], ["DEJA"])
        self.assertEqual([l.numero for l in reponse.context["bientot"]], ["BIENTOT"])

    def test_un_lot_epuise_ne_remonte_plus(self):
        self.recevoir(10, jours=-5, numero="VIDE")
        sortir_stock(depot=self.depot, variante=self.medicament, quantite=Decimal("10"))

        with contexte_boutique(self.boutique):
            self.assertEqual(lots_a_surveiller().count(), 0)

    def test_l_ecran_n_existe_pas_pour_un_metier_qui_ne_perime_pas(self):
        """Un tableau vide lui laisserait croire qu'on surveille quelque chose."""
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="QUINCAILLERIE")
        self.assertEqual(self.client.get(reverse("peremptions")).status_code, 404)

    def test_le_rail_ne_montre_l_entree_qu_aux_metiers_concernes(self):
        self.recevoir(10, jours=-5, numero="DEJA")
        self.assertContains(self.client.get(reverse("stock")), "Péremptions")

        Boutique.objects.filter(pk=self.boutique.pk).update(metier="QUINCAILLERIE")
        self.assertNotContains(self.client.get(reverse("stock")), "Péremptions")

    def test_le_vocabulaire_de_l_ecran_suit_le_metier(self):
        reponse = self.client.get(reverse("stock"))
        self.assertContains(reponse, "Nouveau médicament")

    def test_la_perte_estimee_est_reservee_a_qui_voit_les_couts(self):
        self.recevoir(10, jours=-5, numero="DEJA")

        vendeur = fabrique.creer_utilisateur("Vendeur")
        rattacher(vendeur, self.boutique, Role.VENDEUR)
        self.client.force_login(vendeur)

        reponse = self.client.get(reverse("peremptions"))
        self.assertEqual(reponse.status_code, 200)
        self.assertIsNone(reponse.context["valeur_perimee"])
