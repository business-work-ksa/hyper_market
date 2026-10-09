"""Fabriquer : fiches techniques, production, coût de revient, invendus.

Ce que ces tests protègent tient en une phrase : **fabriquer ne crée pas de
valeur et n'en détruit pas.** Ce qui sort des ingrédients entre dans le produit
fini, au centime. Une production qui perdrait un franc en chemin ferait dériver
la valeur du stock sans que personne ne le voie, et une valorisation de stock qui
dérive silencieusement est exactement le genre d'erreur qu'on découvre à
l'inventaire annuel, un an trop tard.

Deux autres propriétés y sont tenues :

* le coût de revient est **calculé au moment où on le regarde**, jamais figé sur
  la fiche — un boulanger qui fixe son prix sur le prix de la farine du mois
  dernier vend à perte sans le voir ;
* la fonction est **entièrement inerte** là où le métier ne l'active pas : une
  quincaillerie n'a ni écran de production, ni fiche technique.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Appartenance, Role
from apps.backoffice.forms import FicheForm, IngredientForm
from apps.catalog.models import LigneRecette, Recette
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import MouvementStock, NiveauStock
from apps.inventory.services import (
    MouvementInvalide,
    cout_de_revient,
    entrer_stock,
    production_du_jour,
    produire,
)
from apps.marketplace import metiers
from apps.marketplace.models import Boutique
from tests import fabrique

MOT_DE_PASSE = "motdepasse"


def rattacher(utilisateur, boutique, code_role=Role.GERANT) -> None:
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class SocleFournil(TestCase):
    """Une boulangerie, sa farine, sa levure, et sa fiche de baguette."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Fournil Ateba")
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="BOULANGERIE")
        self.boutique.refresh_from_db()
        self.depot = fabrique.creer_depot(self.boutique)

        self.farine = fabrique.creer_variante(self.boutique, prix="900", libelle="Farine T55")
        self.levure = fabrique.creer_variante(self.boutique, prix="1500", libelle="Levure")
        self.baguette = fabrique.creer_variante(self.boutique, prix="150", libelle="Baguette 250 g")

        # 100 kg de farine à 500 F, 2 kg de levure à 4 000 F.
        entrer_stock(
            depot=self.depot, variante=self.farine,
            quantite=Decimal("100"), cout_unitaire=Decimal("500"),
        )
        entrer_stock(
            depot=self.depot, variante=self.levure,
            quantite=Decimal("2"), cout_unitaire=Decimal("4000"),
        )

        with contexte_boutique(self.boutique):
            self.fiche = Recette.objects.create(
                boutique=self.boutique, variante=self.baguette,
                rendement=Decimal("40"), duree_conservation_jours=2,
            )
            LigneRecette.objects.create(
                boutique=self.boutique, recette=self.fiche,
                ingredient=self.farine, quantite=Decimal("10"),
            )
            LigneRecette.objects.create(
                boutique=self.boutique, recette=self.fiche,
                ingredient=self.levure, quantite=Decimal("0.2"),
            )

    def niveau(self, variante) -> NiveauStock:
        with contexte_boutique(self.boutique):
            return NiveauStock.objects.get(depot=self.depot, variante=variante)

    def mouvements(self, **filtres):
        with contexte_boutique(self.boutique):
            return list(MouvementStock.objects.filter(**filtres).order_by("cree_le"))


class ReferentielTest(TestCase):
    def test_la_boulangerie_et_la_restauration_fabriquent(self):
        for code in ("BOULANGERIE", "RESTAURATION"):
            with self.subTest(metier=code):
                self.assertTrue(metiers.METIERS[code].a(metiers.RECETTE))

    def test_le_commerce_general_ne_fabrique_pas(self):
        """Le socle reste le plus petit dénominateur : il n'active rien."""
        self.assertFalse(metiers.METIERS["COMMERCE_GENERAL"].a(metiers.RECETTE))

    def test_aucun_metier_ne_promet_encore_ce_qui_est_ecrit(self):
        """Ce qui est câblé sort de `a_venir`, sinon la liste ment dans les deux sens."""
        for metier in metiers.METIERS.values():
            for promesse in metier.a_venir:
                with self.subTest(metier=metier.code, promesse=promesse):
                    self.assertNotIn("Fiches techniques", promesse)
                    self.assertNotIn("Production du jour", promesse)
                    self.assertNotIn("Recettes", promesse)


class ProduireTest(SocleFournil):
    def test_la_fournee_consomme_les_ingredients(self):
        produire(depot=self.depot, recette=self.fiche, quantite=Decimal("40"))

        self.assertEqual(self.niveau(self.farine).quantite, Decimal("90.0000"))
        self.assertEqual(self.niveau(self.levure).quantite, Decimal("1.8000"))
        self.assertEqual(self.niveau(self.baguette).quantite, Decimal("40.0000"))

    def test_une_demi_fournee_consomme_la_moitie(self):
        """Le boulanger demande vingt baguettes ; le rapport au rendement est notre affaire."""
        produire(depot=self.depot, recette=self.fiche, quantite=Decimal("20"))

        self.assertEqual(self.niveau(self.farine).quantite, Decimal("95.0000"))
        self.assertEqual(self.niveau(self.levure).quantite, Decimal("1.9000"))

    def test_rien_ne_se_perd_entre_ce_qui_sort_et_ce_qui_entre(self):
        """La propriété centrale : fabriquer ne crée ni ne détruit de valeur.

        10 kg de farine à 500 F = 5 000 F ; 0,2 kg de levure à 4 000 F = 800 F.
        Les 40 baguettes valent donc 5 800 F, soit 145 F pièce — et pas un franc
        de plus, quelle que soit la manière dont on arrondit en chemin.
        """
        entree, sorties = produire(depot=self.depot, recette=self.fiche, quantite=Decimal("40"))

        sorti = sum(
            (-m.quantite * m.cout_unitaire for m in sorties), Decimal("0")
        )
        entre = entree.quantite * entree.cout_unitaire

        self.assertEqual(sorti, Decimal("5800.0000"))
        self.assertEqual(entre, sorti)
        self.assertEqual(entree.cout_unitaire, Decimal("145.0000"))

    def test_le_cout_est_constate_au_prix_du_jour(self):
        """Une farine plus chère renchérit la fournée suivante, pas la précédente."""
        premiere, _ = produire(depot=self.depot, recette=self.fiche, quantite=Decimal("40"))

        # Réapprovisionnement à 800 F : le CMP de la farine monte.
        entrer_stock(
            depot=self.depot, variante=self.farine,
            quantite=Decimal("90"), cout_unitaire=Decimal("800"),
        )
        seconde, _ = produire(depot=self.depot, recette=self.fiche, quantite=Decimal("40"))

        self.assertGreater(seconde.cout_unitaire, premiere.cout_unitaire)
        # La première fournée garde son coût : il est historisé sur son mouvement.
        # Relu depuis la base, dans le contexte de la boutique — `refresh_from_db`
        # passe par le gestionnaire de base, qui ne contourne pas la barrière 3.
        with contexte_boutique(self.boutique):
            relue = MouvementStock.objects.get(pk=premiere.pk)
        self.assertEqual(relue.cout_unitaire, Decimal("145.0000"))

    def test_le_produit_fini_porte_sa_date_de_peremption(self):
        """La seule date que le boulanger n'a pas à saisir, donc la seule qu'il ne rate pas."""
        from apps.inventory.models import LotStock

        produire(depot=self.depot, recette=self.fiche, quantite=Decimal("40"))

        with contexte_boutique(self.boutique):
            lot = LotStock.objects.get(variante=self.baguette)
        self.assertEqual(lot.date_peremption, timezone.localdate() + timedelta(days=2))
        self.assertEqual(lot.quantite, Decimal("40.0000"))

    def test_sans_duree_de_conservation_aucun_lot_n_est_cree(self):
        """Le mécanisme reste inerte là où il n'a rien à suivre."""
        from apps.inventory.models import LotStock

        with contexte_boutique(self.boutique):
            Recette.objects.filter(pk=self.fiche.pk).update(duree_conservation_jours=None)
            self.fiche.refresh_from_db()

        produire(depot=self.depot, recette=self.fiche, quantite=Decimal("40"))

        with contexte_boutique(self.boutique):
            self.assertFalse(LotStock.objects.filter(variante=self.baguette).exists())

    def test_la_production_est_un_seul_type_de_mouvement_signe(self):
        """Comme un transfert : le lien entre la sortie et l'entrée est le type."""
        produire(depot=self.depot, recette=self.fiche, quantite=Decimal("40"))

        mouvements = self.mouvements(type=MouvementStock.PRODUCTION)
        self.assertEqual(len(mouvements), 3)
        self.assertEqual(sum(1 for m in mouvements if m.quantite > 0), 1)
        self.assertTrue(all(m.origine_type == "catalog.Recette" for m in mouvements))
        self.assertTrue(all(m.origine_id == self.fiche.pk for m in mouvements))

    def test_une_fiche_vide_ne_produit_rien(self):
        vide = fabrique.creer_variante(self.boutique, prix="500", libelle="Pain de mie")
        with contexte_boutique(self.boutique):
            fiche = Recette.objects.create(boutique=self.boutique, variante=vide)

        with self.assertRaises(MouvementInvalide):
            produire(depot=self.depot, recette=fiche, quantite=Decimal("1"))

    def test_une_fiche_retiree_ne_produit_plus(self):
        with contexte_boutique(self.boutique):
            Recette.objects.filter(pk=self.fiche.pk).update(actif=False)
            self.fiche.refresh_from_db()

        with self.assertRaises(MouvementInvalide):
            produire(depot=self.depot, recette=self.fiche, quantite=Decimal("40"))

    def test_une_quantite_nulle_ou_negative_est_refusee(self):
        for essai in (Decimal("0"), Decimal("-5")):
            with self.subTest(quantite=essai):
                with self.assertRaises(MouvementInvalide):
                    produire(depot=self.depot, recette=self.fiche, quantite=essai)

    def test_le_stock_peut_devenir_negatif_sur_un_ingredient(self):
        """ADR-005 : on n'invente pas un blocage que la caisse n'a pas.

        Le boulanger a pétri : la farine est physiquement partie, même si le
        compteur ne l'avait pas vue arriver. Refuser l'écriture ferait mentir le
        stock dans l'autre sens, ce qui est pire.
        """
        produire(depot=self.depot, recette=self.fiche, quantite=Decimal("800"))

        self.assertLess(self.niveau(self.farine).quantite, 0)
        self.assertEqual(self.niveau(self.baguette).quantite, Decimal("800.0000"))

    def test_un_ingredient_de_trace_sous_le_quantum_ne_bloque_pas_la_fournee(self):
        """Une baguette seule ramène 0,005 kg de levure : arrondi à zéro, pas d'erreur."""
        entree, sorties = produire(depot=self.depot, recette=self.fiche, quantite=Decimal("1"))

        self.assertEqual(entree.quantite, Decimal("1.0000"))
        self.assertTrue(any(m.variante_id == self.farine.pk for m in sorties))

    def test_la_production_du_jour_ne_liste_que_les_produits_finis(self):
        """Sinon « 40 baguettes, 10 kg de farine » se lirait comme deux productions."""
        produire(depot=self.depot, recette=self.fiche, quantite=Decimal("40"))

        with contexte_boutique(self.boutique):
            lignes = list(production_du_jour(depot=self.depot))
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes[0].variante_id, self.baguette.pk)


class CoutDeRevientTest(SocleFournil):
    def test_le_detail_accompagne_toujours_le_total(self):
        """« 5 800 F » ne dit pas quoi faire ; « dont 5 000 de farine » si."""
        with contexte_boutique(self.boutique):
            revient = cout_de_revient(self.fiche, depot=self.depot)

        self.assertEqual(revient["total"], Decimal("5800.00"))
        self.assertEqual(revient["unitaire"], Decimal("145.00"))
        self.assertEqual(len(revient["lignes"]), 2)
        self.assertTrue(revient["complet"])

    def test_le_cout_suit_le_cmp_du_jour(self):
        entrer_stock(
            depot=self.depot, variante=self.farine,
            quantite=Decimal("100"), cout_unitaire=Decimal("700"),
        )
        with contexte_boutique(self.boutique):
            revient = cout_de_revient(self.fiche, depot=self.depot)

        # CMP de la farine : (100×500 + 100×700) / 200 = 600.
        self.assertEqual(revient["total"], Decimal("6800.00"))

    def test_un_ingredient_jamais_recu_est_signale_et_non_masque(self):
        """Un coût de revient faussement bas est ce qui fait fixer un prix à perte."""
        sel = fabrique.creer_variante(self.boutique, prix="300", libelle="Sel")
        with contexte_boutique(self.boutique):
            LigneRecette.objects.create(
                boutique=self.boutique, recette=self.fiche,
                ingredient=sel, quantite=Decimal("0.2"),
            )
            revient = cout_de_revient(self.fiche, depot=self.depot)

        self.assertFalse(revient["complet"])
        inconnues = [d for d in revient["lignes"] if not d["connu"]]
        self.assertEqual(len(inconnues), 1)
        self.assertEqual(inconnues[0]["ligne"].ingredient_id, sel.pk)
        self.assertEqual(revient["total"], Decimal("5800.00"))


class FormulairesTest(SocleFournil):
    def test_un_produit_ne_peut_pas_etre_son_propre_ingredient(self):
        """Sinon la production consommerait ce qu'elle fabrique."""
        formulaire = IngredientForm(
            data={"ingredient": str(self.baguette.pk), "quantite": "1"},
            recette=self.fiche,
        )
        self.assertFalse(formulaire.is_valid())
        self.assertIn("ingredient", formulaire.errors)

    def test_un_ingredient_deja_present_n_est_plus_proposable(self):
        formulaire = IngredientForm(
            data={"ingredient": str(self.farine.pk), "quantite": "1"},
            recette=self.fiche,
        )
        self.assertFalse(formulaire.is_valid())

    def test_un_produit_qui_a_deja_une_fiche_n_est_plus_proposable(self):
        """Deux fiches sur le même produit rendraient la production ambiguë."""
        with contexte_boutique(self.boutique):
            formulaire = FicheForm(
                data={"variante": str(self.baguette.pk), "rendement": "10"},
                boutique=self.boutique,
            )
            self.assertFalse(formulaire.is_valid())

    def test_le_libelle_du_formulaire_parle_le_metier(self):
        with contexte_boutique(self.boutique):
            formulaire = FicheForm(boutique=self.boutique)
        self.assertIn("Produit", formulaire.fields["variante"].label)


class EcransTest(SocleFournil):
    def setUp(self):
        super().setUp()
        self.gerant = fabrique.creer_utilisateur("Boulanger")
        rattacher(self.gerant, self.boutique)
        self.client.login(telephone=self.gerant.telephone, password=MOT_DE_PASSE)

    def test_l_ecran_de_production_s_ouvre_en_boulangerie(self):
        self.assertEqual(self.client.get(reverse("production")).status_code, 200)
        self.assertEqual(self.client.get(reverse("fiches")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("fiche", args=[self.fiche.pk])).status_code, 200
        )

    def test_il_repond_404_dans_un_metier_qui_ne_fabrique_pas(self):
        """404 plutôt qu'un tableau vide : un quincaillier n'a pas de fournée."""
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="QUINCAILLERIE")
        for nom in ("production", "fiches"):
            with self.subTest(ecran=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 404)

    def test_l_entree_de_navigation_n_apparait_que_la_ou_l_on_fabrique(self):
        reponse = self.client.get(reverse("production"))
        self.assertContains(reponse, "Production du jour")

        Boutique.objects.filter(pk=self.boutique.pk).update(metier="QUINCAILLERIE")
        reponse = self.client.get(reverse("stock"))
        self.assertNotContains(reponse, reverse("production"))

    def test_produire_depuis_l_ecran_ecrit_les_mouvements(self):
        reponse = self.client.post(
            reverse("production_lancer", args=[self.fiche.pk]),
            {"quantite": "40", "commentaire": "Fournée du matin"},
        )
        self.assertRedirects(reponse, reverse("production"))
        self.assertEqual(self.niveau(self.baguette).quantite, Decimal("40.0000"))
        self.assertEqual(self.niveau(self.farine).quantite, Decimal("90.0000"))

    def test_le_commercant_apprend_tout_de_suite_ce_que_la_fournee_a_coute(self):
        """C'est maintenant qu'il ajuste son prix, pas au bilan annuel."""
        reponse = self.client.post(
            reverse("production_lancer", args=[self.fiche.pk]),
            {"quantite": "40"},
            follow=True,
        )
        self.assertContains(reponse, "145")

    def test_les_invendus_sortent_en_perte(self):
        self.client.post(reverse("production_lancer", args=[self.fiche.pk]), {"quantite": "40"})
        self.client.post(
            reverse("production_invendus"),
            {"variante": str(self.baguette.pk), "quantite": "7", "motif": "Invendus du soir"},
        )

        pertes = self.mouvements(type=MouvementStock.PERTE)
        self.assertEqual(len(pertes), 1)
        self.assertEqual(pertes[0].quantite, Decimal("-7.0000"))
        self.assertEqual(self.niveau(self.baguette).quantite, Decimal("33.0000"))

    def test_ajouter_puis_retirer_un_ingredient(self):
        sel = fabrique.creer_variante(self.boutique, prix="300", libelle="Sel")
        self.client.post(
            reverse("fiche_ingredient", args=[self.fiche.pk]),
            {"ingredient": str(sel.pk), "quantite": "0.2"},
        )
        with contexte_boutique(self.boutique):
            ligne = LigneRecette.objects.get(recette=self.fiche, ingredient=sel)

        self.client.post(
            reverse("fiche_ingredient_retirer", args=[self.fiche.pk, ligne.pk])
        )
        with contexte_boutique(self.boutique):
            self.assertFalse(
                LigneRecette.objects.filter(recette=self.fiche, ingredient=sel).exists()
            )

    def test_une_fiche_retiree_reste_lisible(self):
        """Elle explique les fabrications déjà écrites au journal du stock."""
        self.client.post(reverse("fiche_basculer", args=[self.fiche.pk]))
        with contexte_boutique(self.boutique):
            self.fiche.refresh_from_db()

        self.assertFalse(self.fiche.actif)
        self.assertEqual(
            self.client.get(reverse("fiche", args=[self.fiche.pk])).status_code, 200
        )


class DroitsTest(SocleFournil):
    """Un caissier voit ce qui est sorti du four ; pas ce qu'il a coûté."""

    def setUp(self):
        super().setUp()
        self.caissiere = fabrique.creer_utilisateur("Caissière")
        rattacher(self.caissiere, self.boutique, Role.CAISSIER)
        self.client.login(telephone=self.caissiere.telephone, password=MOT_DE_PASSE)

    def test_le_cout_de_production_n_est_pas_calcule_sans_le_droit(self):
        reponse = self.client.get(reverse("production"))

        self.assertEqual(reponse.status_code, 200)
        self.assertIsNone(reponse.context["valeur_produite"])
        self.assertIsNone(reponse.context["pertes"])

    def test_le_cout_de_revient_d_une_fiche_non_plus(self):
        reponse = self.client.get(reverse("fiche", args=[self.fiche.pk]))

        self.assertEqual(reponse.status_code, 200)
        self.assertIsNone(reponse.context["revient"])
        self.assertNotContains(reponse, "Coût de revient")

    def test_un_caissier_ne_lance_pas_de_fournee(self):
        reponse = self.client.post(
            reverse("production_lancer", args=[self.fiche.pk]), {"quantite": "40"}
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(self.mouvements(type=MouvementStock.PRODUCTION), [])


class IsolationTest(SocleFournil):
    def test_la_fiche_d_un_confrere_est_invisible(self):
        """Une fiche technique est le secret d'un commerce."""
        autre = fabrique.creer_boutique("Fournil d'en face")
        Boutique.objects.filter(pk=autre.pk).update(metier="BOULANGERIE")
        voisin = fabrique.creer_utilisateur("Voisin")
        rattacher(voisin, autre)
        fabrique.creer_depot(autre)

        self.client.login(telephone=voisin.telephone, password=MOT_DE_PASSE)
        reponse = self.client.get(reverse("fiche", args=[self.fiche.pk]))

        self.assertEqual(reponse.status_code, 404)
        self.assertNotContains(reponse, "Baguette", status_code=404)

    def test_produire_avec_le_depot_d_un_autre_est_refuse(self):
        autre = fabrique.creer_boutique("Fournil d'en face")
        depot_voisin = fabrique.creer_depot(autre)

        with self.assertRaises(MouvementInvalide):
            produire(depot=depot_voisin, recette=self.fiche, quantite=Decimal("40"))
