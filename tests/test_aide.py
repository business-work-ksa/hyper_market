"""L'aide en ligne : une fiche par écran, filtrée comme l'écran lui-même.

Une aide se dégrade sans bruit. Les écrans bougent, les droits se déplacent, et
le texte reste — décrivant un bouton qui n'existe plus, ou promettant un écran
que le lecteur ne peut pas ouvrir. Rien ne plante, personne ne le signale, et la
seule personne qui s'en aperçoit est celle qui cherchait de l'aide.

Ces tests tiennent les trois points où la dérive se produit.

**Le droit déclaré doit être celui que la vue exige.** Comparé au décorateur
`@exige(...)` lu dans le code, pas à un souvenir. L'écriture de ce module a
produit exactement cette erreur : la fiche de la garantie annonçait
`STOCK_VOIR` là où la vue demande `VENTES_VOIR`, et un magasinier aurait lu
l'aide d'un écran qui le refuse.

**Chaque écran du menu doit avoir sa fiche**, et sous la clé exacte que la vue
passe à `contexte_commun` — c'est elle qui relie le bouton « ? » à la bonne
ancre. Une clé fausse ouvre l'aide en haut de page sans rien montrer.

**Ce qui n'est pas ouvert ne doit pas être composé.** Un caissier ne lit pas
l'aide de la comptabilité ; une quincaillerie ne lit pas celle de
l'ordonnancier.
"""

import ast
import pathlib
import re

from django.test import TestCase
from django.urls import reverse

from apps.accounts import permissions as droit
from apps.accounts.models import Appartenance, Role
from apps.backoffice import aide
from apps.marketplace import metiers
from apps.marketplace.models import Boutique
from tests import fabrique

MOT_DE_PASSE = "motdepasse-solide"
RACINE = pathlib.Path(__file__).resolve().parent.parent

# Les écrans du menu principal. La liste est ici en clair : elle doit être lue
# et discutée quand une entrée s'ajoute, pas déduite d'un gabarit.
ECRANS_DU_MENU = (
    "tableau_de_bord", "caisse", "stock", "peremptions", "production",
    "ventes", "ordonnancier", "garantie", "commandes", "comptabilite", "boutique",
)


def rattacher(utilisateur, boutique, code_role=Role.GERANT) -> None:
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


def droits_exiges_par_les_vues() -> dict[str, str]:
    """Le droit que chaque vue exige, lu dans son décorateur.

    Source de vérité pour ces tests : le code qui refuse réellement l'accès. Une
    constante recopiée dans le fichier de test ne prouverait que sa propre
    cohérence.
    """
    trouves: dict[str, str] = {}
    for fichier in sorted(pathlib.Path(RACINE / "apps" / "backoffice").glob("v*.py")):
        arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        for noeud in arbre.body:
            if not isinstance(noeud, ast.FunctionDef) or noeud.name not in ECRANS_DU_MENU:
                continue
            for decorateur in noeud.decorator_list:
                texte = ast.unparse(decorateur)
                correspond = re.fullmatch(r"exige\(droit\.([A-Z_]+)\)", texte)
                if correspond:
                    trouves[noeud.name] = getattr(droit, correspond.group(1))
    return trouves


class ContenuTest(TestCase):
    def test_chaque_ecran_du_menu_a_sa_fiche(self):
        couvertes = {f.cle for f in aide.FICHES}
        manquantes = set(ECRANS_DU_MENU) - couvertes
        self.assertEqual(manquantes, set(), f"écrans sans aide : {sorted(manquantes)}")

    def test_aucune_fiche_ne_vise_un_ecran_inexistant(self):
        """Une ancre sans écran ouvre l'aide en haut de page, sans rien montrer."""
        en_trop = {f.cle for f in aide.FICHES} - set(ECRANS_DU_MENU)
        self.assertEqual(en_trop, set(), f"fiches orphelines : {sorted(en_trop)}")

    def test_le_droit_declare_est_celui_que_la_vue_exige(self):
        """Le test qui aurait attrapé l'erreur de la garantie du premier coup."""
        exiges = droits_exiges_par_les_vues()
        self.assertEqual(
            set(exiges), set(ECRANS_DU_MENU), "un écran du menu n'a pas été analysé"
        )
        for fiche in aide.FICHES:
            self.assertEqual(
                fiche.droit_requis,
                exiges[fiche.cle],
                f"« {fiche.titre} » annonce {fiche.droit_requis!r} alors que la vue "
                f"exige {exiges[fiche.cle]!r}",
            )

    def test_les_fonctions_de_metier_citees_existent(self):
        connues = set(metiers.LIBELLES_FONCTIONS)
        for fiche in aide.FICHES:
            if fiche.fonction_requise:
                self.assertIn(fiche.fonction_requise, connues, fiche.cle)

    def test_aucune_fiche_ne_contient_de_syntaxe_markdown(self):
        """Ce texte est rendu tel quel, pas interprété.

        Le premier jet portait « **retiré de la vente** » : les astérisques se
        sont affichées à l'écran, au milieu d'une phrase qui expliquait
        justement quelque chose d'important. Une capture l'a montré, pas la
        suite de tests — d'où celui-ci.
        """
        for fiche in aide.FICHES:
            # `gestes` porte des 2-uplets ou des 3-uplets selon que le geste
            # demande un droit : on ne lit que le texte, en deuxième position.
            textes = [fiche.resume, *(g[1] for g in fiche.gestes), *fiche.pieges]
            for texte in textes:
                for marqueur in ("**", "__", "`"):
                    self.assertNotIn(
                        marqueur, texte, f"{marqueur} visible dans « {fiche.titre} »"
                    )

    def test_chaque_fiche_dit_quelque_chose(self):
        """Un titre sans contenu est pire qu'une fiche absente : il promet."""
        for fiche in aide.FICHES:
            self.assertTrue(fiche.resume.strip(), fiche.cle)
            self.assertTrue(fiche.gestes or fiche.pieges, fiche.cle)


class FiltrageTest(TestCase):
    def fiches(self, code_role, code_metier="PHARMACIE"):
        return {
            f.cle
            for f in aide.fiches_pour(
                droit.droits_du_role(code_role), metiers.METIERS[code_metier]
            )
        }

    def test_un_caissier_ne_lit_pas_l_aide_de_la_comptabilite(self):
        self.assertNotIn("comptabilite", self.fiches(Role.CAISSIER))
        self.assertIn("caisse", self.fiches(Role.CAISSIER))

    def test_un_caissier_ne_lit_pas_l_aide_de_l_equipe(self):
        self.assertNotIn("boutique", self.fiches(Role.CAISSIER))

    def test_un_comptable_ne_lit_pas_l_aide_de_la_caisse(self):
        self.assertNotIn("caisse", self.fiches(Role.COMPTABLE))
        self.assertIn("comptabilite", self.fiches(Role.COMPTABLE))

    def test_une_quincaillerie_ne_lit_pas_l_aide_de_l_ordonnancier(self):
        """Le métier filtre autant que le rôle.

        Un gérant a tous les droits ; cela ne lui ouvre pas l'ordonnancier, qui
        n'existe pas chez lui.
        """
        self.assertNotIn("ordonnancier", self.fiches(Role.GERANT, "QUINCAILLERIE"))
        self.assertIn("ordonnancier", self.fiches(Role.GERANT, "PHARMACIE"))

    def test_chaque_metier_voit_ce_qui_lui_est_propre(self):
        for code_metier, attendu in (
            ("PHARMACIE", "ordonnancier"),
            ("BOULANGERIE", "production"),
            ("ELECTRONIQUE", "garantie"),
        ):
            self.assertIn(attendu, self.fiches(Role.GERANT, code_metier), code_metier)

    def test_un_metier_sans_fonction_ne_voit_aucune_fiche_de_metier(self):
        vues = self.fiches(Role.GERANT, "COMMERCE_GENERAL")
        for propre_a_un_metier in ("peremptions", "production", "ordonnancier", "garantie"):
            self.assertNotIn(propre_a_un_metier, vues)

    def test_un_caissier_ne_lit_pas_comment_recevoir_du_stock(self):
        """Ouvrir un écran et pouvoir tout y faire sont deux choses.

        Une caissière consulte le stock ; elle ne reçoit pas la marchandise et
        ne lance pas d'inventaire. Le premier jet lui expliquait « Stock ›
        Inventaire » — un bouton qui n'est pas composé pour elle.
        """
        caissier = droit.droits_du_role(Role.CAISSIER)
        pharma = metiers.METIERS["PHARMACIE"]
        stock = aide.fiche_de("stock", caissier, pharma)
        quands = {quand for quand, _ in stock.gestes}
        self.assertIn("Chercher", quands)
        self.assertNotIn("Recevoir", quands)
        self.assertNotIn("Compter", quands)

    def test_un_magasinier_lit_comment_recevoir_du_stock(self):
        magasinier = droit.droits_du_role(Role.MAGASINIER)
        stock = aide.fiche_de("stock", magasinier, metiers.METIERS["PHARMACIE"])
        quands = {quand for quand, _ in stock.gestes}
        self.assertIn("Recevoir", quands)
        self.assertIn("Compter", quands)

    def test_un_comptable_ne_lit_pas_comment_gerer_l_equipe(self):
        """Il consulte la fiche de la boutique ; il n'administre rien."""
        comptable = droit.droits_du_role(Role.COMPTABLE)
        boutique = aide.fiche_de("boutique", comptable, metiers.METIERS["PHARMACIE"])
        quands = {quand for quand, _ in boutique.gestes}
        self.assertNotIn("Équipe", quands)
        self.assertNotIn("Dépôts", quands)
        self.assertIn("Exporter", quands)

    def test_les_pieges_ne_sont_pas_filtres(self):
        """Savoir qu'une quantité ne se retape pas est utile même à qui ne la
        retapera jamais : c'est ce qui permet de comprendre ce qu'on lit."""
        caissier = droit.droits_du_role(Role.CAISSIER)
        stock = aide.fiche_de("stock", caissier, metiers.METIERS["PHARMACIE"])
        self.assertTrue(any("retapant" in p for p in stock.pieges))

    def test_fiche_de_respecte_le_meme_filtre_que_la_liste(self):
        """Sinon le bouton « ? » d'un écran contournerait ce que la page cache."""
        caissier = droit.droits_du_role(Role.CAISSIER)
        pharma = metiers.METIERS["PHARMACIE"]
        self.assertIsNone(aide.fiche_de("comptabilite", caissier, pharma))
        self.assertIsNotNone(aide.fiche_de("caisse", caissier, pharma))


class EcranTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Pharmacie du Wouri")
        Boutique.objects.filter(pk=self.boutique.pk).update(metier="PHARMACIE")
        self.boutique.refresh_from_db()
        fabrique.creer_depot(self.boutique)

    def connecter(self, code_role=Role.GERANT):
        utilisateur = fabrique.creer_utilisateur("Personne")
        utilisateur.set_password(MOT_DE_PASSE)
        utilisateur.save()
        rattacher(utilisateur, self.boutique, code_role)
        self.client.login(telephone=utilisateur.telephone, password=MOT_DE_PASSE)
        session = self.client.session
        session["boutique_id"] = str(self.boutique.pk)
        session.save()
        return utilisateur

    def test_la_page_s_ouvre(self):
        self.connecter()
        reponse = self.client.get(reverse("aide"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Caisse")
        self.assertContains(reponse, "Comptabilité")

    def test_la_page_ne_montre_que_ce_qui_est_ouvert(self):
        self.connecter(Role.CAISSIER)
        reponse = self.client.get(reverse("aide"))
        cles = {f.cle for f in reponse.context["fiches"]}
        self.assertIn("caisse", cles)
        self.assertNotIn("comptabilite", cles)

    def test_il_faut_etre_connecte(self):
        reponse = self.client.get(reverse("aide"))
        self.assertIn(reponse.status_code, (302, 403))

    def test_chaque_ecran_porte_un_bouton_vers_sa_propre_fiche(self):
        """Le « ? » de l'en-tête doit pointer sur l'ancre de l'écran courant.

        Posé une seule fois dans le gabarit de base plutôt que dans chaque écran :
        un bouton d'aide qu'il faut penser à ajouter finit par manquer sur
        l'écran le moins évident.
        """
        self.connecter()
        for nom in ("stock", "ventes", "comptabilite", "boutique"):
            reponse = self.client.get(reverse(nom))
            self.assertContains(
                reponse, f"#{nom}", msg_prefix=f"pas d'ancre d'aide sur « {nom} »"
            )

    def test_l_aide_ne_renvoie_pas_vers_elle_meme(self):
        self.connecter()
        reponse = self.client.get(reverse("aide"))
        self.assertNotContains(reponse, "Aide sur cet écran")

    def test_le_retour_ramene_d_ou_l_on_vient(self):
        self.connecter()
        reponse = self.client.get(reverse("aide"), {"de": "/stock/"})
        self.assertContains(reponse, 'href="/stock/"')

    def test_l_aide_est_mise_de_cote_pour_le_hors_ligne(self):
        """C'est le moment où elle sert le plus : réseau tombé, personne à qui demander."""
        coquille = (RACINE / "static" / "js" / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('"/aide/"', coquille)
