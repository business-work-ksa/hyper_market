"""Les tableaux de données : sélection, correction, suppression, filtres.

Ce fichier protège une règle de produit et trois règles d'interface.

**La règle de produit : on supprime ce qui n'a pas d'histoire, on retire ce qui
en a une.** Effacer un article vendu l'an dernier arracherait son libellé de
tickets imprimés et d'écritures validées — le journal comptable est en ajout seul
précisément pour que cela n'arrive pas. Mais interdire toute suppression
empêcherait de corriger une référence créée par erreur il y a trois minutes. Le
logiciel tranche **ligne par ligne**, et **dit lequel des deux il a fait** :
« supprimé » et « retiré de la vente » ne sont pas la même chose, et laisser
croire à l'un quand c'est l'autre fait chercher longtemps un article encore là.

**On ne modifie qu'une ligne à la fois.** Deux lignes différentes n'ont pas la
même correction à apporter.

**Un filtre illisible n'invalide que lui-même.** Un `?depot=n-importe-quoi` collé
de travers ne doit pas faire tomber les autres filtres avec lui : la liste
affichée cesserait de correspondre à l'URL qui la décrit.

**Un garde-fou ne se contourne pas par le lot.** Retirer les deux derniers
gérants dans la même sélection fermerait la boutique aussi sûrement que de les
retirer l'un après l'autre.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.backoffice.filtres import FiltresStockForm, FiltresVentesForm
from apps.catalog.models import CompatibiliteVehicule, LigneRecette, Produit, Recette, Variante
from apps.core.tenancy import contexte_boutique
from apps.inventory.models import Depot, NiveauStock, NumeroSerie
from apps.inventory.services import entrer_stock
from apps.marketplace.models import Boutique, LienMarketing
from tests import fabrique


def rattacher(utilisateur, boutique, code_role=Role.GERANT) -> Appartenance:
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    return Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class SocleBackoffice(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Quincaillerie", quota_depots=3, quota_utilisateurs=5)
        self.depot = fabrique.creer_depot(self.boutique)
        self.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(self.gerant, self.boutique)

        self.client.force_login(self.gerant)
        session = self.client.session
        session["boutique_id"] = str(self.boutique.pk)
        session["depot_id"] = str(self.depot.pk)
        session.save()

    def article(self, libelle="Article", *, avec_stock=False):
        variante = fabrique.creer_variante(self.boutique, libelle=libelle)
        with contexte_boutique(self.boutique):
            NiveauStock.objects.create(
                boutique=self.boutique, depot=self.depot, variante=variante
            )
        if avec_stock:
            entrer_stock(
                depot=self.depot,
                variante=variante,
                quantite=Decimal("10"),
                cout_unitaire=Decimal("100"),
            )
        return variante


# ---------------------------------------------------------------------------
# Supprimer ou retirer : la règle qui gouverne tous les écrans
# ---------------------------------------------------------------------------
class SuppressionArticleTest(SocleBackoffice):
    def test_un_article_sans_histoire_disparait_vraiment(self):
        variante = self.article("Vis à bois")
        reponse = self.client.post(reverse("articles_supprimer"), {"ids": [str(variante.pk)]})

        self.assertEqual(reponse.status_code, 302)
        with contexte_boutique(self.boutique):
            self.assertFalse(Variante.objects.filter(pk=variante.pk).exists())

    def test_un_article_qui_a_bouge_est_retire_et_pas_efface(self):
        """Son libellé est cité par des mouvements : l'effacer les rendrait muets."""
        variante = self.article("Ciment", avec_stock=True)
        self.client.post(reverse("articles_supprimer"), {"ids": [str(variante.pk)]})

        with contexte_boutique(self.boutique):
            variante.refresh_from_db()
        self.assertFalse(variante.actif)

    def test_le_message_distingue_les_deux_issues(self):
        """« Supprimé » et « retiré de la vente » ne sont pas la même chose."""
        neuf = self.article("Neuf")
        ancien = self.article("Ancien", avec_stock=True)

        reponse = self.client.post(
            reverse("articles_supprimer"),
            {"ids": [str(neuf.pk), str(ancien.pk)]},
            follow=True,
        )
        textes = " ".join(str(m) for m in reponse.context["messages"])
        self.assertIn("supprimé", textes)
        self.assertIn("retiré de la vente", textes)

    def test_le_produit_orphelin_part_avec_sa_derniere_variante(self):
        """Un produit sans variante n'a ni prix ni stock : il n'est plus vendable."""
        variante = self.article("Éphémère")
        produit_id = variante.produit_id
        self.client.post(reverse("articles_supprimer"), {"ids": [str(variante.pk)]})

        with contexte_boutique(self.boutique):
            self.assertFalse(Produit.objects.filter(pk=produit_id).exists())

    def test_la_liste_annonce_la_consequence_avant_le_clic(self):
        """Un bouton qui refuse après coup fait perdre le geste.

        La ligne porte la conséquence — « sera retiré, pas supprimé » — et la
        barre la reprend. C'est une **note**, pas une protection : le bouton
        reste actif, il fait simplement autre chose.
        """
        self.article("Ciment", avec_stock=True)
        reponse = self.client.get(reverse("stock"))
        self.assertContains(reponse, "sera retiré de la vente, pas supprimé")

    def test_un_article_d_une_autre_boutique_est_introuvable(self):
        voisine = fabrique.creer_boutique("Voisine")
        depot_voisin = fabrique.creer_depot(voisine)
        intrus = fabrique.creer_variante(voisine, libelle="Chez le voisin")
        with contexte_boutique(voisine):
            NiveauStock.objects.create(boutique=voisine, depot=depot_voisin, variante=intrus)

        self.client.post(reverse("articles_supprimer"), {"ids": [str(intrus.pk)]})

        with contexte_boutique(voisine):
            self.assertTrue(Variante.objects.filter(pk=intrus.pk).exists())


class ModificationArticleTest(SocleBackoffice):
    def test_la_fiche_s_ouvre_prete_a_corriger(self):
        variante = self.article("Ciment CIMENCAM")
        reponse = self.client.get(reverse("article_modifier", args=[variante.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context["formulaire"].initial["libelle"], "Ciment CIMENCAM")

    def test_ni_quantite_ni_cout_ne_s_y_corrigent(self):
        """Les offrir donnerait le moyen d'écrire du stock sans passer par son journal."""
        variante = self.article()
        formulaire = self.client.get(reverse("article_modifier", args=[variante.pk])).context[
            "formulaire"
        ]
        self.assertNotIn("quantite", formulaire.fields)
        self.assertNotIn("cout_unitaire", formulaire.fields)

    def test_la_correction_est_ecrite(self):
        variante = self.article("Avant")
        self.client.post(
            reverse("article_modifier", args=[variante.pk]),
            {
                "libelle": "Après",
                "sku": variante.sku,
                "prix_vente": "2500",
                "seuil_alerte": "7",
                "regime_tva": Produit.NORMAL,
                "actif": "on",
            },
        )
        # Tout se relit **dans** le contexte : `refresh_from_db` vide les
        # relations en cache, et `variante.produit` se recharge à la première
        # lecture — hors contexte, la barrière 3 ne renvoie rien.
        with contexte_boutique(self.boutique):
            variante.refresh_from_db()
            libelle = variante.produit.libelle
            prix = variante.prix_vente
            niveau = NiveauStock.objects.get(variante=variante, depot=self.depot)
        self.assertEqual(libelle, "Après")
        self.assertEqual(prix, Decimal("2500"))
        self.assertEqual(niveau.seuil_alerte, Decimal("7"))

    def test_reenregistrer_sans_rien_changer_est_accepte(self):
        """L'unicité de la référence ne doit pas se heurter à la référence elle-même."""
        variante = self.article()
        reponse = self.client.post(
            reverse("article_modifier", args=[variante.pk]),
            {
                "libelle": "Article",
                "sku": variante.sku,
                "prix_vente": "11925",
                "seuil_alerte": "0",
                "regime_tva": Produit.NORMAL,
                "actif": "on",
            },
        )
        self.assertEqual(reponse.status_code, 302)

    def test_la_reference_d_un_autre_article_reste_refusee(self):
        premier = self.article("Premier")
        second = self.article("Second")
        reponse = self.client.post(
            reverse("article_modifier", args=[second.pk]),
            {
                "libelle": "Second",
                "sku": premier.sku,
                "prix_vente": "1000",
                "seuil_alerte": "0",
                "regime_tva": Produit.NORMAL,
                "actif": "on",
            },
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("sku", reponse.context["formulaire"].errors)

    def test_un_magasinier_ne_voit_pas_de_bouton_qu_il_ne_peut_pas_actionner(self):
        """Un droit refusé n'est pas grisé : il n'est pas composé (docs/14, §3.6)."""
        caissier = fabrique.creer_utilisateur("Caissier")
        rattacher(caissier, self.boutique, Role.CAISSIER)
        self.client.force_login(caissier)
        session = self.client.session
        session["boutique_id"] = str(self.boutique.pk)
        session.save()

        contexte = self.client.get(reverse("stock")).context
        self.assertEqual(contexte["url_creer"], "")
        self.assertEqual(contexte["url_supprimer"], "")
        self.assertFalse(contexte["peut_mouvementer"])


# ---------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------
class FiltreTest(TestCase):
    def test_une_valeur_inconnue_n_emporte_pas_les_autres_filtres(self):
        """Sinon la liste affichée cesse de correspondre à l'URL qui la décrit."""
        filtres = FiltresStockForm({"depot": "pas-un-uuid", "etat": "rupture"})
        self.assertEqual(filtres.valeurs.get("etat"), "rupture")
        self.assertEqual(filtres.valeurs.get("depot", ""), "")

    def test_une_date_illisible_s_efface_sans_casser_la_page(self):
        filtres = FiltresVentesForm({"depuis": "32/13/2026", "q": "T-0001"})
        self.assertIsNone(filtres.valeurs.get("depuis"))
        self.assertEqual(filtres.valeurs.get("q"), "T-0001")

    def test_le_compteur_ne_compte_que_ce_qui_filtre_vraiment(self):
        """« Tous » n'est pas un filtre : l'annoncer ferait chercher une liste tronquée."""
        self.assertEqual(FiltresStockForm({"etat": "", "q": ""}).actifs, 0)
        self.assertEqual(FiltresStockForm({"etat": "rupture"}).actifs, 1)

    def test_un_intervalle_a_l_envers_est_remis_a_l_endroit(self):
        """Il ne renverrait rien, et ne dirait pas pourquoi."""
        filtres = FiltresVentesForm({"depuis": "2026-09-30", "jusqua": "2026-09-01"})
        valeurs = filtres.valeurs
        self.assertLess(valeurs["depuis"], valeurs["jusqua"])

    def test_un_dépôt_unique_ne_se_choisit_pas(self):
        boutique = fabrique.creer_boutique("Un seul dépôt")
        depot = fabrique.creer_depot(boutique)
        self.assertNotIn("depot", FiltresStockForm(None, depots=[depot]).fields)


class FiltreStockTest(SocleBackoffice):
    def test_l_etat_du_stock_filtre_la_liste(self):
        self.article("En stock", avec_stock=True)
        self.article("Jamais reçu")

        rupture = self.client.get(reverse("stock"), {"etat": "rupture"}).context["niveaux"]
        self.assertEqual([n.variante.produit.libelle for n in rupture], ["Jamais reçu"])

    def test_la_recherche_conserve_les_filtres_deja_poses(self):
        """Chercher un mot ne doit pas effacer le dépôt qu'on venait de choisir."""
        reponse = self.client.get(reverse("stock"), {"etat": "rupture"})
        self.assertEqual(reponse.context["conserver_dans_recherche"].get("etat"), "rupture")


# ---------------------------------------------------------------------------
# Équipe : le lot ne contourne pas les garde-fous
# ---------------------------------------------------------------------------
class RetraitEnLotTest(SocleBackoffice):
    def setUp(self):
        super().setUp()
        self.vendeur = fabrique.creer_utilisateur("Vendeur")
        self.appartenance_vendeur = rattacher(self.vendeur, self.boutique, Role.VENDEUR)

    def test_plusieurs_acces_se_retirent_d_un_geste(self):
        caissier = fabrique.creer_utilisateur("Caissier")
        acces_caissier = rattacher(caissier, self.boutique, Role.CAISSIER)

        self.client.post(
            reverse("equipe_retirer_lot"),
            {"ids": [str(self.appartenance_vendeur.pk), str(acces_caissier.pk)]},
        )
        self.appartenance_vendeur.refresh_from_db()
        acces_caissier.refresh_from_db()
        self.assertFalse(self.appartenance_vendeur.actif)
        self.assertFalse(acces_caissier.actif)

    def test_on_ne_se_retire_pas_soi_meme(self):
        """Ce serait fermer la porte de l'intérieur, sans personne dehors."""
        mien = Appartenance.objects.get(utilisateur=self.gerant, boutique=self.boutique)
        self.client.post(reverse("equipe_retirer_lot"), {"ids": [str(mien.pk)]})
        mien.refresh_from_db()
        self.assertTrue(mien.actif)

    def test_les_deux_derniers_gerants_dans_le_meme_lot_sont_refuses(self):
        """Le garde-fou regarde ce qui restera **après le lot entier**.

        Le vérifier ligne par ligne laisserait passer la sélection qui retire
        tous les gérants d'un coup : chacun aurait « un autre gérant » derrière
        lui, et il n'en resterait aucun.
        """
        second = fabrique.creer_utilisateur("Second gérant")
        acces_second = rattacher(second, self.boutique, Role.GERANT)
        mien = Appartenance.objects.get(utilisateur=self.gerant, boutique=self.boutique)

        self.client.post(
            reverse("equipe_retirer_lot"), {"ids": [str(acces_second.pk), str(mien.pk)]}
        )
        acces_second.refresh_from_db()
        mien.refresh_from_db()
        self.assertTrue(acces_second.actif)
        self.assertTrue(mien.actif)

    def test_le_refus_est_nomme(self):
        mien = Appartenance.objects.get(utilisateur=self.gerant, boutique=self.boutique)
        reponse = self.client.post(
            reverse("equipe_retirer_lot"), {"ids": [str(mien.pk)]}, follow=True
        )
        textes = " ".join(str(m) for m in reponse.context["messages"])
        self.assertIn("Gérant", textes)

    def test_aucun_compte_n_est_jamais_supprime(self):
        from apps.accounts.models import Utilisateur

        self.client.post(
            reverse("equipe_retirer_lot"), {"ids": [str(self.appartenance_vendeur.pk)]}
        )
        self.assertTrue(Utilisateur.objects.filter(pk=self.vendeur.pk).exists())


# ---------------------------------------------------------------------------
# Liens marketing
# ---------------------------------------------------------------------------
class LienTest(SocleBackoffice):
    def lien(self, libelle="Flyer marché central", code="ABCDEFG"):
        with contexte_boutique(self.boutique):
            return LienMarketing.objects.create(
                boutique=self.boutique, libelle=libelle, code=code
            )

    def test_un_lien_se_renomme(self):
        lien = self.lien()
        self.client.post(
            reverse("lien_modifier", args=[lien.pk]), {"libelle": "Statut WhatsApp"}
        )
        with contexte_boutique(self.boutique):
            lien.refresh_from_db()
        self.assertEqual(lien.libelle, "Statut WhatsApp")

    def test_le_code_ne_change_jamais(self):
        """Il est peut-être imprimé sur mille flyers."""
        lien = self.lien(code="ZZZZZZZ")
        self.client.post(
            reverse("lien_modifier", args=[lien.pk]),
            {"libelle": "Autre", "code": "AUTRECODE"},
        )
        with contexte_boutique(self.boutique):
            lien.refresh_from_db()
        self.assertEqual(lien.code, "ZZZZZZZ")

    def test_plusieurs_liens_se_retirent_sans_etre_effaces(self):
        """Leur compteur de clics reste lisible : c'est tout l'intérêt de l'avoir compté."""
        premier = self.lien("Premier", code="AAAAAAA")
        second = self.lien("Second", code="BBBBBBB")

        self.client.post(
            reverse("liens_retirer"), {"ids": [str(premier.pk), str(second.pk)]}
        )
        with contexte_boutique(self.boutique):
            premier.refresh_from_db()
            second.refresh_from_db()
            # `objects_all_tenants` contourne le gestionnaire, jamais la base :
            # l'existence se vérifie donc dans le contexte, comme le reste.
            existe_encore = LienMarketing.objects_all_tenants.filter(pk=premier.pk).exists()
        self.assertFalse(premier.actif)
        self.assertFalse(second.actif)
        self.assertTrue(existe_encore)


# ---------------------------------------------------------------------------
# Dépôts
# ---------------------------------------------------------------------------
class DepotTest(SocleBackoffice):
    def test_un_depot_se_renomme(self):
        with contexte_boutique(self.boutique):
            reserve = Depot.objects.create(
                boutique=self.boutique, libelle="Réserve", type=Depot.RESERVE
            )
        self.client.post(
            reverse("depot_modifier", args=[reserve.pk]),
            {"libelle": "Réserve Akwa", "type": Depot.RESERVE, "adresse": "Rue Njo-Njo"},
        )
        with contexte_boutique(self.boutique):
            reserve.refresh_from_db()
        self.assertEqual(reserve.libelle, "Réserve Akwa")
        self.assertEqual(reserve.adresse, "Rue Njo-Njo")

    def test_un_depot_sans_mouvement_disparait(self):
        with contexte_boutique(self.boutique):
            reserve = Depot.objects.create(
                boutique=self.boutique, libelle="Jamais servi", type=Depot.RESERVE
            )
        self.client.post(reverse("depots_supprimer"), {"ids": [str(reserve.pk)]})
        with contexte_boutique(self.boutique):
            self.assertFalse(Depot.objects.filter(pk=reserve.pk).exists())

    def test_un_depot_qui_a_recu_est_ferme_et_pas_efface(self):
        with contexte_boutique(self.boutique):
            reserve = Depot.objects.create(
                boutique=self.boutique, libelle="Réserve", type=Depot.RESERVE
            )
        variante = self.article()
        entrer_stock(
            depot=reserve, variante=variante, quantite=Decimal("3"), cout_unitaire=Decimal("10")
        )

        self.client.post(reverse("depots_supprimer"), {"ids": [str(reserve.pk)]})
        with contexte_boutique(self.boutique):
            reserve.refresh_from_db()
        self.assertFalse(reserve.actif)

    def test_le_depot_principal_ne_se_ferme_pas(self):
        """Une boutique sans dépôt principal n'a plus où poser son stock."""
        self.client.post(reverse("depots_supprimer"), {"ids": [str(self.depot.pk)]})
        with contexte_boutique(self.boutique):
            self.depot.refresh_from_db()
        self.assertTrue(self.depot.actif)


# ---------------------------------------------------------------------------
# Fiches techniques et ingrédients
# ---------------------------------------------------------------------------
class FicheTest(SocleBackoffice):
    def setUp(self):
        super().setUp()
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="BOULANGERIE")
        self.boutique.refresh_from_db()
        self.pain = self.article("Baguette")
        self.farine = self.article("Farine")
        with contexte_boutique(self.boutique):
            self.recette = Recette.objects.create(
                boutique=self.boutique, variante=self.pain, rendement=Decimal("40")
            )
            self.ligne = LigneRecette.objects.create(
                boutique=self.boutique,
                recette=self.recette,
                ingredient=self.farine,
                quantite=Decimal("0.15"),
            )

    def test_une_fiche_se_corrige(self):
        self.client.post(
            reverse("fiche_modifier", args=[self.recette.pk]),
            {"rendement": "60", "duree_conservation_jours": "3", "note": "Pétrissage 12 min"},
        )
        with contexte_boutique(self.boutique):
            self.recette.refresh_from_db()
        self.assertEqual(self.recette.rendement, Decimal("60"))
        self.assertEqual(self.recette.duree_conservation_jours, 3)

    def test_un_rendement_nul_est_refuse(self):
        self.client.post(
            reverse("fiche_modifier", args=[self.recette.pk]), {"rendement": "0"}
        )
        with contexte_boutique(self.boutique):
            self.recette.refresh_from_db()
        self.assertEqual(self.recette.rendement, Decimal("40"))

    def test_une_fiche_qui_n_a_rien_produit_disparait(self):
        self.client.post(reverse("fiches_supprimer"), {"ids": [str(self.recette.pk)]})
        with contexte_boutique(self.boutique):
            self.assertFalse(Recette.objects.filter(pk=self.recette.pk).exists())

    def test_une_fiche_qui_a_produit_est_retiree(self):
        """Elle explique des fournées inscrites au journal du stock."""
        from apps.inventory.services import produire

        entrer_stock(
            depot=self.depot,
            variante=self.farine,
            quantite=Decimal("10"),
            cout_unitaire=Decimal("26000"),
        )
        produire(depot=self.depot, recette=self.recette, quantite=Decimal("40"))

        self.client.post(reverse("fiches_supprimer"), {"ids": [str(self.recette.pk)]})
        with contexte_boutique(self.boutique):
            self.recette.refresh_from_db()
        self.assertFalse(self.recette.actif)

    def test_la_quantite_d_un_ingredient_se_corrige(self):
        self.client.post(
            reverse("fiche_ingredient_modifier", args=[self.recette.pk, self.ligne.pk]),
            {"quantite": "0.2"},
        )
        with contexte_boutique(self.boutique):
            self.ligne.refresh_from_db()
        self.assertEqual(self.ligne.quantite, Decimal("0.2000"))

    def test_plusieurs_ingredients_se_retirent_d_un_geste(self):
        sel = self.article("Sel")
        with contexte_boutique(self.boutique):
            autre = LigneRecette.objects.create(
                boutique=self.boutique,
                recette=self.recette,
                ingredient=sel,
                quantite=Decimal("0.008"),
            )
        self.client.post(
            reverse("fiche_ingredients_retirer", args=[self.recette.pk]),
            {"ids": [str(self.ligne.pk), str(autre.pk)]},
        )
        with contexte_boutique(self.boutique):
            self.assertEqual(LigneRecette.objects.filter(recette=self.recette).count(), 0)


# ---------------------------------------------------------------------------
# Exemplaires et compatibilités
# ---------------------------------------------------------------------------
class ExemplaireTest(SocleBackoffice):
    def setUp(self):
        super().setUp()
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="ELECTRONIQUE")
        self.boutique.refresh_from_db()
        self.telephone = self.article("Téléphone")
        with contexte_boutique(self.boutique):
            Variante.objects.filter(pk=self.telephone.pk).update(suivi_unitaire=True)
        self.telephone.suivi_unitaire = True

    def exemplaire(self, numero, etat=NumeroSerie.EN_STOCK, vendu_le=None):
        with contexte_boutique(self.boutique):
            return NumeroSerie.objects.create(
                boutique=self.boutique,
                variante=self.telephone,
                depot=self.depot,
                numero=numero,
                etat=etat,
                vendu_le=vendu_le,
            )

    def test_un_numero_saisi_par_erreur_s_efface(self):
        """Il ne désigne aucun appareil réel."""
        faux = self.exemplaire("IMEI-FAUX")
        self.client.post(
            reverse("exemplaires_supprimer", args=[self.telephone.pk]), {"ids": [str(faux.pk)]}
        )
        with contexte_boutique(self.boutique):
            self.assertFalse(NumeroSerie.objects.filter(pk=faux.pk).exists())

    def test_un_exemplaire_vendu_ne_s_efface_pas(self):
        """Il porte une garantie due à quelqu'un."""
        from django.utils import timezone

        vendu = self.exemplaire("IMEI-VENDU", NumeroSerie.VENDU, timezone.now())
        self.client.post(
            reverse("exemplaires_supprimer", args=[self.telephone.pk]), {"ids": [str(vendu.pk)]}
        )
        with contexte_boutique(self.boutique):
            self.assertTrue(NumeroSerie.objects.filter(pk=vendu.pk).exists())

    def test_le_refus_est_nomme(self):
        from django.utils import timezone

        vendu = self.exemplaire("IMEI-VENDU", NumeroSerie.VENDU, timezone.now())
        reponse = self.client.post(
            reverse("exemplaires_supprimer", args=[self.telephone.pk]),
            {"ids": [str(vendu.pk)]},
            follow=True,
        )
        self.assertIn("IMEI-VENDU", " ".join(str(m) for m in reponse.context["messages"]))


class CompatibiliteTest(SocleBackoffice):
    def setUp(self):
        super().setUp()
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="PIECES_AUTO")
        self.boutique.refresh_from_db()
        self.piece = self.article("Filtre à huile")
        with contexte_boutique(self.boutique):
            self.compat = CompatibiliteVehicule.objects.create(
                boutique=self.boutique, variante=self.piece, marque="Toyota", modele="Corola"
            )

    def test_une_compatibilite_se_corrige(self):
        """Une affirmation fausse fait repartir un client avec la mauvaise pièce."""
        self.client.post(
            reverse("compatibilite_modifier", args=[self.piece.pk, self.compat.pk]),
            {"marque": "toyota", "modele": "corolla", "annee_debut": "2007"},
        )
        with contexte_boutique(self.boutique):
            self.compat.refresh_from_db()
        # Les marques sont normalisées à l'écriture : une faute de casse ne doit
        # pas créer une seconde « toyota » introuvable.
        self.assertEqual(self.compat.marque, "Toyota")
        self.assertEqual(self.compat.modele, "Corolla")
        self.assertEqual(self.compat.annee_debut, 2007)

    def test_plusieurs_compatibilites_se_retirent_vraiment(self):
        with contexte_boutique(self.boutique):
            autre = CompatibiliteVehicule.objects.create(
                boutique=self.boutique, variante=self.piece, marque="Nissan"
            )
        self.client.post(
            reverse("compatibilites_retirer", args=[self.piece.pk]),
            {"ids": [str(self.compat.pk), str(autre.pk)]},
        )
        with contexte_boutique(self.boutique):
            self.assertEqual(
                CompatibiliteVehicule.objects.filter(variante=self.piece).count(), 0
            )


# ---------------------------------------------------------------------------
# Le contrat de balisage du composant
# ---------------------------------------------------------------------------
class BalisageTest(SocleBackoffice):
    """Ce que `static/js/tableau.js` attend du gabarit.

    Le script pose la colonne de cases, lit `data-id` et `data-libelle`, et
    décide de l'état des boutons. Un gabarit qui cesserait de les poser
    n'afficherait **aucune erreur** : il rendrait simplement un tableau inerte,
    et personne ne s'en apercevrait avant d'essayer de supprimer une ligne.
    """

    def test_chaque_ligne_du_stock_porte_son_identifiant_et_son_libelle(self):
        self.article("Ciment CIMENCAM")
        page = self.client.get(reverse("stock")).content.decode()
        self.assertIn("data-id=", page)
        self.assertIn('data-libelle="Ciment CIMENCAM"', page)

    def test_le_panneau_declare_le_nom_de_ce_qu_il_liste(self):
        """C'est lui qui fait dire « 3 articles sélectionnés » plutôt que « 3 lignes »."""
        page = self.client.get(reverse("stock")).content.decode()
        self.assertIn('data-tableau', page)
        self.assertIn('data-noms="articles"', page)

    def test_la_boite_de_suppression_est_servie_avec_la_page(self):
        page = self.client.get(reverse("stock")).content.decode()
        self.assertIn('data-modale="supprimer"', page)
        self.assertIn("data-identifiants", page)

    def test_les_boutons_contextuels_arrivent_desactives(self):
        """Sans JavaScript, la page ne promet pas des gestes qu'elle ne tient pas."""
        page = self.client.get(reverse("stock")).content.decode()
        self.assertIn('data-action="modifier" disabled', page)
        self.assertIn('data-action="supprimer" disabled', page)
