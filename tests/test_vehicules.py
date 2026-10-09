"""Chercher une pièce par la voiture du client.

Un client de pièces détachées ne demande pas « un filtre à huile » : il demande
« le filtre à huile de ma Corolla de 2015 ». Ces tests protègent la règle qui
gouverne tout l'appariement — **l'absence d'information ne produit jamais une
absence de résultat** — et ses deux conséquences :

* une compatibilité déclarée sur toute une marque couvre **tous** ses modèles ;
* une année absente, dans la déclaration comme dans la recherche, ne borne rien.

Le risque assumé est de montrer une pièce de trop plutôt que d'en cacher une.
Au comptoir, un vendeur écarte en trois secondes une pièce qui ne convient pas ;
il ne peut rien contre une pièce qu'on ne lui a jamais montrée.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.backoffice.forms import ArticleForm, CompatibiliteForm
from apps.catalog import vehicules
from apps.catalog.models import CompatibiliteVehicule
from apps.core.tenancy import contexte_boutique
from apps.inventory.services import entrer_stock
from apps.marketplace import metiers
from apps.marketplace.models import Boutique
from tests import fabrique

MOT_DE_PASSE = "motdepasse"


def rattacher(utilisateur, boutique, code_role=Role.GERANT) -> None:
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class SocleCasse(TestCase):
    """Un vendeur de pièces, quatre références, et leurs compatibilités."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Auto Pièces")
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="PIECES_AUTO")
        self.boutique.refresh_from_db()
        self.depot = fabrique.creer_depot(self.boutique)

        self.filtre = self.piece("Filtre à huile", "90915-YZZD4")
        self.plaquettes = self.piece("Plaquettes de frein avant", "04465-0K090")
        self.amortisseur = self.piece("Amortisseur arrière", "")
        self.huile = self.piece("Huile 15W40 — 5 L", "")

        self.declarer(self.filtre, "Toyota", "Corolla", debut=2007, fin=2018)
        self.declarer(self.plaquettes, "Toyota", "Hilux", debut=2005, fin=2015)
        self.declarer(self.amortisseur, "Nissan", "Navara", debut=2005, fin=2014)
        # Une huile va sur tout : ni modèle, ni bornes.
        self.declarer(self.huile, "Toyota", "")

    def piece(self, libelle, reference):
        variante = fabrique.creer_variante(self.boutique, prix="3500", libelle=libelle)
        if reference:
            with contexte_boutique(self.boutique):
                type(variante).objects.filter(pk=variante.pk).update(
                    reference_constructeur=reference
                )
        # L'écran du stock se construit sur les niveaux, pas sur les variantes :
        # une pièce jamais reçue n'y figure pas, et les tests d'écran ne
        # verraient rien.
        entrer_stock(
            depot=self.depot,
            variante=variante,
            quantite=Decimal("10"),
            cout_unitaire=Decimal("2100"),
        )
        return variante

    def declarer(self, variante, marque, modele, *, motorisation="", debut=None, fin=None):
        with contexte_boutique(self.boutique):
            return CompatibiliteVehicule.objects.create(
                boutique=self.boutique,
                variante=variante,
                marque=marque,
                modele=modele,
                motorisation=motorisation,
                annee_debut=debut,
                annee_fin=fin,
            )

    def chercher(self, **criteres):
        with contexte_boutique(self.boutique):
            return list(vehicules.compatibles(**criteres))


class ReferentielTest(TestCase):
    def test_les_pieces_auto_ont_enfin_une_fonction(self):
        self.assertTrue(metiers.METIERS["PIECES_AUTO"].a(metiers.COMPATIBILITE))

    def test_les_autres_metiers_ne_l_activent_pas(self):
        """Une quincaillerie n'a pas de véhicules : ce serait une saisie pour rien."""
        for code, metier in metiers.METIERS.items():
            if code == "PIECES_AUTO":
                continue
            with self.subTest(metier=code):
                self.assertFalse(metier.a(metiers.COMPATIBILITE))

    def test_la_compatibilite_n_est_plus_promise(self):
        """Ce qui est câblé sort de `a_venir`, sinon la liste ment à l'envers."""
        for promesse in metiers.METIERS["PIECES_AUTO"].a_venir:
            self.assertNotIn("Compatibilité véhicule", promesse)


class AppariementTest(SocleCasse):
    def test_la_marque_et_le_modele_trouvent_la_piece(self):
        trouvees = self.chercher(marque="Toyota", modele="Corolla")
        self.assertIn(self.filtre, trouvees)
        self.assertNotIn(self.amortisseur, trouvees)

    def test_une_compatibilite_sans_modele_couvre_toute_la_marque(self):
        """C'est ce que le vendeur a voulu dire en laissant le champ vide."""
        trouvees = self.chercher(marque="Toyota", modele="Corolla")
        self.assertIn(self.huile, trouvees)

        trouvees = self.chercher(marque="Toyota", modele="Hilux")
        self.assertIn(self.huile, trouvees)

    def test_l_annee_borne_la_recherche(self):
        self.assertIn(self.filtre, self.chercher(marque="Toyota", modele="Corolla", annee=2015))
        self.assertNotIn(self.filtre, self.chercher(marque="Toyota", modele="Corolla", annee=2004))
        self.assertNotIn(self.filtre, self.chercher(marque="Toyota", modele="Corolla", annee=2022))

    def test_une_annee_absente_ne_borne_rien(self):
        """Un client sait rarement l'année exacte de sa voiture."""
        self.assertIn(self.filtre, self.chercher(marque="Toyota", modele="Corolla", annee=None))

    def test_une_piece_sans_borne_sort_a_toutes_les_annees(self):
        for annee in (1998, 2015, 2030):
            with self.subTest(annee=annee):
                self.assertIn(self.huile, self.chercher(marque="Toyota", annee=annee))

    def test_la_recherche_est_insensible_a_la_casse(self):
        """« toyota » tapé à la va-vite au comptoir doit trouver la pièce."""
        self.assertIn(self.filtre, self.chercher(marque="toyota", modele="COROLLA"))

    def test_une_recherche_vide_ne_renvoie_rien(self):
        """Renvoyer tout le stock ferait passer une recherche ratée pour un succès."""
        self.assertEqual(self.chercher(marque="", modele="", annee=None), [])

    def test_une_marque_inconnue_ne_renvoie_rien(self):
        self.assertEqual(self.chercher(marque="Peugeot"), [])

    def test_les_marques_connues_alimentent_la_saisie(self):
        with contexte_boutique(self.boutique):
            self.assertEqual(vehicules.marques_connues(), ["Nissan", "Toyota"])

    def test_la_normalisation_evite_trois_toyota_dans_la_liste(self):
        for essai in ("toyota", "TOYOTA", "  Toyota  ", "toyota "):
            with self.subTest(saisie=essai):
                self.assertEqual(vehicules.normaliser(essai), "Toyota")


class FormulaireTest(SocleCasse):
    def test_le_champ_reference_n_existe_que_pour_ce_metier(self):
        formulaire = ArticleForm(boutique=self.boutique)
        self.assertIn("reference_constructeur", formulaire.fields)

        autre = fabrique.creer_boutique("Quincaillerie")
        Boutique.objects.filter(pk=autre.pk).update(metier="QUINCAILLERIE")
        autre.refresh_from_db()
        self.assertNotIn("reference_constructeur", ArticleForm(boutique=autre).fields)

    def test_la_marque_est_normalisee_a_la_saisie(self):
        formulaire = CompatibiliteForm(
            data={"marque": "  toyota ", "modele": "corolla"}, variante=self.filtre
        )
        with contexte_boutique(self.boutique):
            self.assertTrue(formulaire.is_valid(), formulaire.errors)
        self.assertEqual(formulaire.cleaned_data["marque"], "Toyota")
        self.assertEqual(formulaire.cleaned_data["modele"], "Corolla")

    def test_un_intervalle_a_l_envers_est_refuse(self):
        """Il décrirait une pièce compatible avec rien, sans que personne ne le voie."""
        formulaire = CompatibiliteForm(
            data={"marque": "Toyota", "annee_debut": "2018", "annee_fin": "2007"},
            variante=self.filtre,
        )
        with contexte_boutique(self.boutique):
            self.assertFalse(formulaire.is_valid())
        self.assertIn("annee_fin", formulaire.errors)

    def test_un_doublon_exact_est_ecarte(self):
        formulaire = CompatibiliteForm(
            data={"marque": "Toyota", "modele": "Corolla", "annee_debut": "2007", "annee_fin": "2018"},
            variante=self.filtre,
        )
        with contexte_boutique(self.boutique):
            self.assertFalse(formulaire.is_valid())
        self.assertIn("marque", formulaire.errors)

    def test_le_modele_et_les_annees_restent_facultatifs(self):
        """Exiger des bornes produirait des bornes inventées, donc des pièces fausses."""
        formulaire = CompatibiliteForm(data={"marque": "Suzuki"}, variante=self.filtre)
        with contexte_boutique(self.boutique):
            self.assertTrue(formulaire.is_valid(), formulaire.errors)


class EcransTest(SocleCasse):
    def setUp(self):
        super().setUp()
        self.gerant = fabrique.creer_utilisateur("Vendeur")
        rattacher(self.gerant, self.boutique)
        self.client.login(telephone=self.gerant.telephone, password=MOT_DE_PASSE)

    def test_la_recherche_par_vehicule_filtre_la_liste(self):
        reponse = self.client.get(reverse("stock"), {"marque": "Nissan", "modele": "Navara"})

        self.assertEqual(reponse.status_code, 200)
        trouvees = {n.variante_id for n in reponse.context["niveaux"]}
        self.assertIn(self.amortisseur.pk, trouvees)
        self.assertNotIn(self.filtre.pk, trouvees)

    def test_une_annee_illisible_est_ignoree_et_non_refusee(self):
        """« dans les 2015 » tapé « 15 » doit donner la liste, pas une erreur."""
        reponse = self.client.get(
            reverse("stock"), {"marque": "Toyota", "modele": "Corolla", "annee": "15"}
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertIsNone(reponse.context["vehicule"]["annee"])
        self.assertIn(
            self.filtre.pk, {n.variante_id for n in reponse.context["niveaux"]}
        )

    def test_la_recherche_par_reference_constructeur(self):
        """C'est souvent la seule chose que le client apporte."""
        reponse = self.client.get(reverse("stock"), {"q": "90915"})
        self.assertEqual(
            [n.variante_id for n in reponse.context["niveaux"]], [self.filtre.pk]
        )

    def test_le_formulaire_vehicule_est_absent_ailleurs(self):
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="QUINCAILLERIE")
        reponse = self.client.get(reverse("stock"))

        self.assertEqual(reponse.status_code, 200)
        self.assertIsNone(reponse.context["vehicule"])
        self.assertNotContains(reponse, "Marque du véhicule")

    def test_l_article_montre_ses_compatibilites(self):
        reponse = self.client.get(reverse("article", args=[self.filtre.pk]))

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Corolla")
        self.assertContains(reponse, "2007–2018")

    def test_la_carte_est_absente_dans_un_metier_qui_ne_suit_pas(self):
        """Composée, pas masquée : la vue ne calcule rien (docs/14, §3.6)."""
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="QUINCAILLERIE")
        reponse = self.client.get(reverse("article", args=[self.filtre.pk]))

        self.assertIsNone(reponse.context["compatibilites"])
        self.assertNotContains(reponse, "Se monte sur")

    def test_ajouter_puis_retirer_une_compatibilite(self):
        self.client.post(
            reverse("compatibilite_ajouter", args=[self.filtre.pk]),
            {"marque": "suzuki", "modele": "swift", "annee_debut": "2010"},
        )
        with contexte_boutique(self.boutique):
            ligne = CompatibiliteVehicule.objects.get(variante=self.filtre, marque="Suzuki")
        self.assertEqual(ligne.modele, "Swift")
        self.assertEqual(ligne.annees, "depuis 2010")

        self.client.post(
            reverse("compatibilite_retirer", args=[self.filtre.pk, ligne.pk])
        )
        with contexte_boutique(self.boutique):
            self.assertFalse(
                CompatibiliteVehicule.objects.filter(pk=ligne.pk).exists()
            )

    def test_un_caissier_ne_declare_pas_de_compatibilite(self):
        caissiere = fabrique.creer_utilisateur("Caissière")
        rattacher(caissiere, self.boutique, Role.CAISSIER)
        self.client.login(telephone=caissiere.telephone, password=MOT_DE_PASSE)

        reponse = self.client.post(
            reverse("compatibilite_ajouter", args=[self.filtre.pk]), {"marque": "Suzuki"}
        )
        self.assertEqual(reponse.status_code, 403)


class IntervalleLisibleTest(SocleCasse):
    def test_les_trois_formes_d_intervalle(self):
        """Un intervalle se lit d'un coup d'œil ou ne sert à rien."""
        cas = [
            ({"debut": 2012, "fin": 2018}, "2012–2018"),
            ({"debut": 2012}, "depuis 2012"),
            ({"fin": 2018}, "jusqu'en 2018"),
            ({}, ""),
        ]
        for bornes, attendu in cas:
            with self.subTest(bornes=bornes):
                ligne = CompatibiliteVehicule(marque="Toyota", **_bornes(bornes))
                self.assertEqual(ligne.annees, attendu)

    def test_une_annee_absente_couvre_tout(self):
        ligne = CompatibiliteVehicule(marque="Toyota", annee_debut=2007, annee_fin=2018)
        self.assertTrue(ligne.couvre(None))
        self.assertTrue(ligne.couvre(2010))
        self.assertFalse(ligne.couvre(2020))


class IsolationTest(SocleCasse):
    def test_le_tableau_de_compatibilite_d_un_confrere_est_invisible(self):
        """C'est le fonds de commerce d'un vendeur de pièces, pas une donnée publique."""
        autre = fabrique.creer_boutique("Casse d'en face")
        Boutique.objects.filter(pk=autre.pk).update(metier="PIECES_AUTO")
        voisin = fabrique.creer_utilisateur("Voisin")
        rattacher(voisin, autre)
        fabrique.creer_depot(autre)

        with contexte_boutique(autre):
            self.assertEqual(list(vehicules.compatibles(marque="Toyota")), [])
            self.assertEqual(vehicules.marques_connues(), [])


def _bornes(valeurs):
    return {"annee_debut": valeurs.get("debut"), "annee_fin": valeurs.get("fin")}
