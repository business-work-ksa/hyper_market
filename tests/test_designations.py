"""Le même article sous un autre nom, et les articles qui se valent.

Deux scènes, un seul mécanisme. En officine : quelqu'un demande du Doliprane, la
pharmacie n'a que de l'Efferalgan. Au comptoir des pièces : un client pose un
filtre marqué « W 68/3 », le vendeur n'a que la référence Toyota. Dans les deux
cas, la marchandise est en rayon et la vente ne se fait pas.

Quatre propriétés sont éprouvées ici.

**L'équivalence se déduit, elle ne se stocke pas.** Deux articles se valent
parce qu'ils portent la même désignation, pas parce que quelqu'un a déclaré la
paire. C'est ce qui fait qu'un article ajouté demain rejoint ses confrères sans
que personne ne retouche quoi que ce soit — et une table de paires aurait exigé
l'inverse, article par article, jusqu'à la première désynchronisation.

**Le nom commercial ne fait pas équivalence.** « Doliprane » est un autre nom du
*même* article, pas le nom d'un autre : le poser en équivalence proposerait au
pharmacien de substituer une boîte par elle-même.

**La recherche du stock regarde ces noms-là.** Sans cela, la saisie ne servirait
qu'à la fiche article — c'est-à-dire à l'écran qu'on ouvre *après* avoir trouvé.

**Rien de tout cela n'existe hors du métier qui le nomme.** Une quincaillerie ne
se voit pas offrir de déclarer des molécules, et la porte elle-même refuse.
"""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.backoffice.forms import DesignationForm
from apps.catalog import equivalences
from apps.catalog.models import Designation
from apps.core.tenancy import contexte_boutique
from apps.marketplace import metiers
from apps.marketplace.models import Boutique
from tests import fabrique

MOT_DE_PASSE = "motdepasse"


def rattacher(utilisateur, boutique, code_role=Role.GERANT) -> None:
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class Socle(TestCase):
    """Une officine, ses boîtes, et son gérant connecté."""

    METIER = "PHARMACIE"

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Pharmacie du Wouri")
        Boutique.objects.filter(pk=self.boutique.pk).update(metier=self.METIER)
        self.boutique.refresh_from_db()
        self.depot = fabrique.creer_depot(self.boutique)

        self.gerant = fabrique.creer_utilisateur("Gérante")
        self.gerant.set_password(MOT_DE_PASSE)
        self.gerant.save()
        rattacher(self.gerant, self.boutique)

    def article(self, libelle, sku=None):
        return fabrique.creer_variante(self.boutique, libelle=libelle, sku=sku)

    def nommer(self, variante, valeur, type_designation=Designation.DCI, source=""):
        with contexte_boutique(self.boutique):
            return Designation.objects.create(
                boutique=self.boutique,
                variante=variante,
                type=type_designation,
                valeur=Designation.normaliser(valeur),
                source=source,
            )

    def connecter(self):
        self.client.login(telephone=self.gerant.telephone, password=MOT_DE_PASSE)
        session = self.client.session
        session["boutique_id"] = str(self.boutique.pk)
        session.save()


# ---------------------------------------------------------------------------
# La normalisation
# ---------------------------------------------------------------------------
class NormalisationTest(TestCase):
    def test_la_casse_et_les_espaces_ne_font_pas_deux_designations(self):
        """« paracétamol  500 mg » et « PARACÉTAMOL 500 MG » sont le même mot.

        Deux pharmaciens saisissent la même molécule comme ils l'écrivent, et
        l'un met deux espaces. Sans normalisation, les deux boîtes ne se
        rapprocheraient pas — et rien à l'écran ne dirait pourquoi.
        """
        self.assertEqual(
            Designation.normaliser("  paracétamol   500 mg "),
            Designation.normaliser("PARACÉTAMOL 500 MG"),
        )

    def test_une_designation_vide_reste_vide(self):
        self.assertEqual(Designation.normaliser("   "), "")
        self.assertEqual(Designation.normaliser(None), "")

    def test_la_longueur_est_bornee_a_celle_de_la_colonne(self):
        """Tronquer vaut mieux que lever : la colonne fait 120 signes.

        Une référence de 200 caractères est une erreur de copier-coller, pas une
        raison de refuser toute la saisie d'un inventaire en cours.
        """
        self.assertEqual(len(Designation.normaliser("A" * 200)), 120)


# ---------------------------------------------------------------------------
# L'équivalence déduite
# ---------------------------------------------------------------------------
class EquivalenceTest(Socle):
    def setUp(self):
        super().setUp()
        self.doliprane = self.article("Doliprane 500 mg — boîte de 20", sku="PHA-PARA-500")
        self.efferalgan = self.article("Efferalgan 500 mg — 16 comprimés", sku="PHA-EFFE-500")
        self.amoxicilline = self.article("Amoxicilline 1 g", sku="PHA-AMOX-1G")

    def test_deux_articles_qui_partagent_une_dci_se_valent(self):
        self.nommer(self.doliprane, "Paracétamol 500 mg")
        self.nommer(self.efferalgan, "Paracétamol 500 mg")

        with contexte_boutique(self.boutique):
            trouves = equivalences.equivalents_de(self.doliprane)

        self.assertEqual([e["variante"].pk for e in trouves], [self.efferalgan.pk])

    def test_l_equivalence_dit_par_quoi_elle_passe(self):
        """Poser une liste d'articles sans dire pourquoi ne s'utilise pas.

        Un pharmacien ne substitue pas une boîte sur la foi d'un écran : il
        vérifie le rapprochement. Nommer la désignation partagée est ce qui rend
        cette vérification possible sans quitter la fiche.
        """
        self.nommer(self.doliprane, "Paracétamol 500 mg")
        self.nommer(self.efferalgan, "Paracétamol 500 mg")

        with contexte_boutique(self.boutique):
            trouves = equivalences.equivalents_de(self.doliprane)

        self.assertEqual([d.valeur for d in trouves[0]["par"]], ["PARACÉTAMOL 500 MG"])

    def test_un_article_arrive_ensuite_rejoint_ses_confreres_sans_rien_redeclarer(self):
        """C'est la raison d'être de la déduction, et elle s'éprouve ici.

        Une table de paires aurait demandé, à chaque nouvelle boîte, de la
        rattacher une à une à toutes les précédentes. La première oubliée
        désynchronise l'ensemble sans que rien ne le signale.
        """
        self.nommer(self.doliprane, "Paracétamol 500 mg")
        self.nommer(self.efferalgan, "Paracétamol 500 mg")

        nouveau = self.article("Paracétamol générique 500 mg", sku="PHA-GENE-500")
        self.nommer(nouveau, "Paracétamol 500 mg")

        with contexte_boutique(self.boutique):
            trouves = equivalences.equivalents_de(self.doliprane)

        self.assertEqual(
            {e["variante"].pk for e in trouves}, {self.efferalgan.pk, nouveau.pk}
        )

    def test_retirer_la_designation_defait_le_rapprochement(self):
        self.nommer(self.doliprane, "Paracétamol 500 mg")
        designation = self.nommer(self.efferalgan, "Paracétamol 500 mg")

        with contexte_boutique(self.boutique):
            Designation.objects.filter(pk=designation.pk).delete()
            self.assertEqual(equivalences.equivalents_de(self.doliprane), [])

    def test_le_nom_commercial_ne_rapproche_pas_deux_articles(self):
        """Substituer une boîte par elle-même n'est pas une substitution.

        « Doliprane » désigne le *même* article autrement. Deux articles qui
        porteraient par erreur le même nom commercial ne se valent pas pour
        autant — c'est la DCI qui dit qu'une molécule en remplace une autre.
        """
        self.nommer(self.doliprane, "Doliprane 500 mg", Designation.COMMERCIAL)
        self.nommer(self.efferalgan, "Doliprane 500 mg", Designation.COMMERCIAL)

        with contexte_boutique(self.boutique):
            self.assertEqual(equivalences.equivalents_de(self.doliprane), [])

    def test_une_dci_sans_confrere_ne_fabrique_pas_d_equivalent(self):
        self.nommer(self.amoxicilline, "Amoxicilline 1 g")

        with contexte_boutique(self.boutique):
            self.assertEqual(equivalences.equivalents_de(self.amoxicilline), [])

    def test_un_article_n_est_jamais_son_propre_equivalent(self):
        self.nommer(self.doliprane, "Paracétamol 500 mg")
        self.nommer(self.doliprane, "Paracétamol", Designation.COMMERCIAL)

        with contexte_boutique(self.boutique):
            self.assertEqual(equivalences.equivalents_de(self.doliprane), [])

    def test_les_types_qui_rapprochent_excluent_le_nom_commercial(self):
        self.assertNotIn(Designation.COMMERCIAL, equivalences.TYPES_EQUIVALENTS)
        self.assertIn(Designation.DCI, equivalences.TYPES_EQUIVALENTS)
        self.assertIn(Designation.REFERENCE, equivalences.TYPES_EQUIVALENTS)


# ---------------------------------------------------------------------------
# La recherche
# ---------------------------------------------------------------------------
class RechercheTest(Socle):
    def setUp(self):
        super().setUp()
        self.doliprane = self.article("Doliprane 500 mg", sku="PHA-PARA-500")
        self.nommer(self.doliprane, "Paracétamol 500 mg")

    def test_on_trouve_par_une_designation_exacte(self):
        with contexte_boutique(self.boutique):
            trouves = list(equivalences.chercher("Paracétamol 500 mg"))
        self.assertEqual([v.pk for v in trouves], [self.doliprane.pk])

    def test_on_trouve_par_un_fragment(self):
        """Un vendeur tape ce qu'il lit, et ce qu'il lit est souvent partiel.

        « 68/3 » plutôt que « W 68/3 » : exiger l'exactitude ferait échouer la
        recherche précisément dans le cas où elle sert.
        """
        with contexte_boutique(self.boutique):
            trouves = list(equivalences.chercher("paracét"))
        self.assertEqual([v.pk for v in trouves], [self.doliprane.pk])

    def test_la_casse_ne_compte_pas(self):
        with contexte_boutique(self.boutique):
            self.assertEqual(len(equivalences.chercher("PARACÉTAMOL")), 1)

    def test_un_terme_vide_ne_renvoie_pas_tout_le_catalogue(self):
        """Le piège inverse du filtre tolérant : tolérer n'est pas tout montrer.

        Une recherche vide qui renverrait le catalogue entier ferait apparaître
        « tous vos articles sont équivalents » sur l'écran d'un pharmacien.
        """
        with contexte_boutique(self.boutique):
            self.assertEqual(list(equivalences.chercher("   ")), [])

    def test_les_valeurs_connues_ne_repetent_pas_une_designation(self):
        """Pour la saisie assistée : une valeur, une seule entrée.

        Le piège est celui des marques de véhicules : sans `order_by()` vidé
        avant le `distinct()`, l'ordre par défaut du modèle ajoute ses colonnes
        au `SELECT` et « PARACÉTAMOL 500 MG » ressort autant de fois qu'il y a
        de boîtes qui le portent.
        """
        autre = self.article("Efferalgan 500 mg", sku="PHA-EFFE-500")
        self.nommer(autre, "Paracétamol 500 mg")

        with contexte_boutique(self.boutique):
            self.assertEqual(
                equivalences.valeurs_connues(Designation.DCI), ["PARACÉTAMOL 500 MG"]
            )


# ---------------------------------------------------------------------------
# L'isolation
# ---------------------------------------------------------------------------
class IsolationTest(Socle):
    def test_une_boutique_ne_voit_pas_les_designations_d_une_autre(self):
        """Prise ensemble, la liste des désignations est l'assortiment complet.

        C'est ce qu'un concurrent d'en face aurait un intérêt direct à lire :
        quelles références sont tenues, et lesquelles ne le sont pas.
        """
        mienne = self.article("Doliprane 500 mg")
        self.nommer(mienne, "Paracétamol 500 mg")

        voisine = fabrique.creer_boutique("Pharmacie d'en face")
        Boutique.objects.filter(pk=voisine.pk).update(metier="PHARMACIE")

        with contexte_boutique(voisine):
            self.assertEqual(list(equivalences.chercher("paracétamol")), [])
            self.assertEqual(equivalences.valeurs_connues(Designation.DCI), [])


# ---------------------------------------------------------------------------
# Le référentiel des métiers
# ---------------------------------------------------------------------------
class MetierTest(TestCase):
    def test_la_pharmacie_declare_la_dci(self):
        self.assertTrue(metiers.METIERS["PHARMACIE"].a(metiers.DCI))

    def test_les_pieces_auto_declarent_l_equivalence(self):
        self.assertTrue(metiers.METIERS["PIECES_AUTO"].a(metiers.EQUIVALENCE))

    def test_une_fonction_livree_n_est_plus_annoncee_comme_a_venir(self):
        """Une fonction câblée doit disparaître de la liste des promesses.

        `a_venir` sert à montrer au commerçant ce qui n'existe pas encore. Y
        laisser une fonction livrée annoncerait comme future une chose qu'il
        peut déjà utiliser.
        """
        promesses = " ".join(metiers.METIERS["PHARMACIE"].a_venir).lower()
        self.assertNotIn("dci", promesses)
        self.assertNotIn("équivalent", promesses)

        promesses = " ".join(metiers.METIERS["PIECES_AUTO"].a_venir).lower()
        self.assertNotIn("équivalen", promesses)

    def test_les_metiers_sans_second_nom_ne_le_proposent_pas(self):
        """La quincaillerie ne nomme pas ses articles deux fois.

        Un tournevis n'a ni molécule ni référence d'équipementier concurrent :
        lui ouvrir la carte demanderait au quincaillier de trancher une question
        qui ne se pose pas chez lui.
        """
        for code in ("QUINCAILLERIE", "BOULANGERIE", "ELECTRONIQUE"):
            metier = metiers.METIERS[code]
            self.assertFalse(metier.a(metiers.DCI), code)
            self.assertFalse(metier.a(metiers.EQUIVALENCE), code)


# ---------------------------------------------------------------------------
# Le formulaire
# ---------------------------------------------------------------------------
class FormulaireTest(Socle):
    def test_la_pharmacie_se_voit_proposer_la_dci(self):
        formulaire = DesignationForm(metier=metiers.METIERS["PHARMACIE"])
        natures = [cle for cle, _ in formulaire.fields["type"].choices]
        self.assertIn(Designation.DCI, natures)

    def test_les_pieces_auto_ne_se_voient_pas_proposer_la_dci(self):
        """Ce que le métier ne sait pas nommer, il ne le propose pas.

        C'est la même règle que les droits : ce qui n'est pas ouvert n'est pas
        composé, pas grisé.
        """
        formulaire = DesignationForm(metier=metiers.METIERS["PIECES_AUTO"])
        natures = [cle for cle, _ in formulaire.fields["type"].choices]
        self.assertNotIn(Designation.DCI, natures)
        self.assertEqual(formulaire.fields["type"].initial, Designation.REFERENCE)

    def test_une_designation_vide_est_refusee(self):
        formulaire = DesignationForm(
            {"type": Designation.DCI, "valeur": "   "}, metier=metiers.METIERS["PHARMACIE"]
        )
        self.assertFalse(formulaire.is_valid())

    def test_la_valeur_est_normalisee_a_la_validation(self):
        formulaire = DesignationForm(
            {"type": Designation.DCI, "valeur": "  paracétamol  500 mg "},
            metier=metiers.METIERS["PHARMACIE"],
        )
        self.assertTrue(formulaire.is_valid())
        self.assertEqual(formulaire.cleaned_data["valeur"], "PARACÉTAMOL 500 MG")

    def test_un_doublon_sur_le_meme_article_est_refuse(self):
        variante = self.article("Doliprane 500 mg")
        self.nommer(variante, "Paracétamol 500 mg")

        with contexte_boutique(self.boutique):
            formulaire = DesignationForm(
                {"type": Designation.DCI, "valeur": "paracétamol 500 mg"},
                metier=metiers.METIERS["PHARMACIE"],
                variante=variante,
            )
            self.assertFalse(formulaire.is_valid())
            self.assertIn("déjà", str(formulaire.errors))


# ---------------------------------------------------------------------------
# Les écrans
# ---------------------------------------------------------------------------
class EcranTest(Socle):
    def setUp(self):
        super().setUp()
        self.connecter()
        self.doliprane = self.article("Doliprane 500 mg", sku="PHA-PARA-500")

    def test_la_fiche_article_montre_la_carte_des_designations(self):
        reponse = self.client.get(reverse("article", args=[self.doliprane.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertIsNotNone(reponse.context["designations"])
        self.assertContains(reponse, "Aussi appelé")

    def test_ajouter_un_nom_depuis_la_fiche(self):
        self.client.post(
            reverse("designation_ajouter", args=[self.doliprane.pk]),
            {"type": Designation.DCI, "valeur": "paracétamol 500 mg", "source": "OMS"},
        )
        with contexte_boutique(self.boutique):
            designation = Designation.objects.get(variante=self.doliprane)
        self.assertEqual(designation.valeur, "PARACÉTAMOL 500 MG")
        self.assertEqual(designation.source, "OMS")

    def test_corriger_une_designation_mal_recopiee(self):
        """Une référence de travers est pire qu'une référence absente.

        Elle ne rapproche rien, et le vendeur croit pourtant avoir cherché.
        """
        designation = self.nommer(self.doliprane, "Paracetamol 50 mg")

        self.client.post(
            reverse("designation_modifier", args=[self.doliprane.pk, designation.pk]),
            {"type": Designation.DCI, "valeur": "paracétamol 500 mg", "source": ""},
        )
        with contexte_boutique(self.boutique):
            designation.refresh_from_db()
        self.assertEqual(designation.valeur, "PARACÉTAMOL 500 MG")

    def test_retirer_plusieurs_designations_d_un_coup(self):
        une = self.nommer(self.doliprane, "Paracétamol 500 mg")
        deux = self.nommer(self.doliprane, "Doliprane", Designation.COMMERCIAL)

        self.client.post(
            reverse("designations_retirer", args=[self.doliprane.pk]),
            {"ids": [str(une.pk), str(deux.pk)]},
        )
        with contexte_boutique(self.boutique):
            self.assertEqual(Designation.objects.filter(variante=self.doliprane).count(), 0)

    def test_la_recherche_du_stock_regarde_les_autres_noms(self):
        """Sans cela, la saisie ne sert qu'à l'écran qu'on ouvre après avoir trouvé."""
        from decimal import Decimal

        from apps.inventory.services import entrer_stock

        entrer_stock(
            depot=self.depot,
            variante=self.doliprane,
            quantite=Decimal("10"),
            cout_unitaire=Decimal("380"),
            cree_par=None,
        )
        self.nommer(self.doliprane, "Paracétamol 500 mg")

        reponse = self.client.get(reverse("stock"), {"q": "paracétamol"})
        self.assertEqual(
            [n.variante_id for n in reponse.context["niveaux"]], [self.doliprane.pk]
        )

    def test_un_article_qui_porte_deux_designations_correspondantes_ne_sort_qu_une_fois(self):
        """La jointure naïve afficherait la même boîte deux fois dans le stock."""
        from decimal import Decimal

        from apps.inventory.services import entrer_stock

        entrer_stock(
            depot=self.depot,
            variante=self.doliprane,
            quantite=Decimal("10"),
            cout_unitaire=Decimal("380"),
            cree_par=None,
        )
        self.nommer(self.doliprane, "Paracétamol 500 mg")
        self.nommer(self.doliprane, "Paracétamol comprimé", Designation.COMMERCIAL)

        reponse = self.client.get(reverse("stock"), {"q": "paracétamol"})
        self.assertEqual(len(reponse.context["niveaux"]), 1)

    def test_l_export_emporte_les_designations(self):
        """La réversibilité porte sur le travail de saisie, pas sur les seuls chiffres.

        Une officine qui a renseigné la DCI de six cents boîtes ne doit pas avoir
        à la ressaisir ailleurs pour la seule raison qu'elle s'en va.
        """
        import io
        import zipfile

        self.nommer(self.doliprane, "Paracétamol 500 mg")

        reponse = self.client.get(reverse("export_donnees"))
        archive = zipfile.ZipFile(io.BytesIO(reponse.content))
        self.assertIn("designations.csv", archive.namelist())
        self.assertIn("PARACÉTAMOL 500 MG", archive.read("designations.csv").decode("utf-8"))


class EcranSansLaFonctionTest(Socle):
    """Une quincaillerie n'a ni carte ni porte."""

    METIER = "QUINCAILLERIE"

    def setUp(self):
        super().setUp()
        self.connecter()
        self.tournevis = self.article("Tournevis cruciforme")

    def test_la_carte_n_est_pas_composee(self):
        reponse = self.client.get(reverse("article", args=[self.tournevis.pk]))
        self.assertIsNone(reponse.context["designations"])
        self.assertNotContains(reponse, "Aussi appelé")

    def test_la_porte_refuse(self):
        """Pas d'écran masqué devant une vue qui accepterait quand même.

        Un geste que le métier n'ouvre pas ne doit pas être atteignable en
        tapant l'URL : c'est la règle du back-office, et elle vaut ici comme
        ailleurs.
        """
        reponse = self.client.post(
            reverse("designation_ajouter", args=[self.tournevis.pk]),
            {"type": Designation.DCI, "valeur": "paracétamol 500 mg"},
        )
        self.assertEqual(reponse.status_code, 404)

    def test_la_recherche_du_stock_ne_paie_pas_la_sous_requete(self):
        """Ce qui n'est pas activé n'est pas seulement caché : il n'est pas calculé."""
        reponse = self.client.get(reverse("stock"), {"q": "quoi que ce soit"})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(list(reponse.context["niveaux"]), [])
