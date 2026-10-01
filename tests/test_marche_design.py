"""Le système de design du marché, sa traduction et ses garanties d'accessibilité (docs/26).

Ce que ces tests protègent :

* **une seule vérité pour les couleurs** : les palettes affichées par la référence vivante sont
  celles de `tailwind.config.js` ;
* **les contrastes AA** de chaque rôle, dans les deux thèmes ;
* **la feuille compilée est à jour** et contient les composants ;
* **le français et l'anglais** sur le marché — et le back-office qui reste en français ;
* **le rechargement de la grille** par fragment, sans casser le cache ;
* **les bases d'accessibilité** de chaque page : langue, lien d'évitement, un seul `h1`, région
  principale, boutons nommés.
"""

import contextlib
import io
import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.vitrine import design_system
from apps.vitrine.templatetags.marche import fcfa, sigle
from tests.test_vitrine import SocleVitrine

RACINE = Path(__file__).resolve().parent.parent


class JetonsTest(SimpleTestCase):
    def test_les_palettes_affichees_sont_celles_de_la_configuration(self):
        config = (RACINE / "tailwind.config.js").read_text()
        for nom, nuances in design_system.PALETTES.items():
            bloc = re.search(rf"\b{nom}: \{{(.*?)\n        \}}", config, re.S)
            self.assertIsNotNone(bloc, nom)
            trouvees = re.findall(r'(\d+): "(#[0-9A-F]{6})"', bloc.group(1))
            self.assertEqual(
                [h for _, h in trouvees], nuances, f"palette {nom} : référence et configuration divergent"
            )
            self.assertEqual([int(c) for c, _ in trouvees], design_system.CRANS)

    def test_echelle_typographique_de_rapport_1_25(self):
        config = (RACINE / "tailwind.config.js").read_text()
        self.assertIn("const RAPPORT = 1.25;", config)

    def test_les_contrastes_passent_aa_dans_les_deux_themes(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("contrastes", RACINE / "outils" / "contrastes_marche.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            resultat = module.main()
        self.assertEqual(resultat, 0, sortie.getvalue())

    def test_la_feuille_compilee_contient_les_composants(self):
        css = (RACINE / "static" / "css" / "marche.css").read_text()
        for selecteur in (
            ".btn-primary", ".btn-secondary", ".btn-outline", ".btn-ghost", ".btn-accent",
            ".btn-sm", ".btn-md", ".btn-lg", ".input", ".badge-succes", ".carte", ".modale",
            ".squelette", ".vide", ".choix", "font-display:swap", "prefers-color-scheme:dark",
            "prefers-reduced-motion", '[data-theme=dark]',
        ):
            with self.subTest(selecteur=selecteur):
                self.assertIn(selecteur, css)
        # Minifiée : pas de commentaire ni d'indentation dans la sortie.
        self.assertNotIn("\n  ", css)

    def test_la_police_est_auto_hebergee(self):
        self.assertTrue((RACINE / "static" / "fonts" / "plus-jakarta-sans-latin.woff2").exists())
        self.assertTrue((RACINE / "static" / "fonts" / "plus-jakarta-sans-OFL.txt").exists())


class FiltresTest(SimpleTestCase):
    def test_sigle(self):
        self.assertEqual(sigle("Cosmétique & beauté"), "CB")
        self.assertEqual(sigle("Pièces détachées"), "PD")
        self.assertEqual(sigle("Électroménager"), "ÉL")
        self.assertEqual(sigle(""), "?")

    def test_les_milliers_sont_separes_par_une_espace_insecable_visible(self):
        self.assertEqual(fcfa(Decimal("34000")), "34 000")
        self.assertNotIn(" ", fcfa(Decimal("1250000")))


class _Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.lang = None
        self.evitement = False
        self.principal = False
        self.boutons_sans_nom = []
        self._bouton = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "h1":
            self.h1 += 1
        if tag == "a" and a.get("href") == "#contenu":
            self.evitement = True
        if tag == "main" and a.get("id") == "contenu":
            self.principal = True
        if tag == "button":
            self._bouton = {"nom": a.get("aria-label") or a.get("title") or "", "texte": ""}

    def handle_data(self, data):
        if self._bouton is not None:
            self._bouton["texte"] += data.strip()

    def handle_endtag(self, tag):
        if tag == "button" and self._bouton is not None:
            if not (self._bouton["nom"] or self._bouton["texte"]):
                self.boutons_sans_nom.append(self._bouton)
            self._bouton = None


class AccessibiliteTest(SocleVitrine):
    def pages(self):
        return {
            "accueil": reverse("vitrine_accueil"),
            "catalogue": reverse("vitrine_catalogue"),
            "recherche vide": reverse("vitrine_catalogue") + "?q=introuvable",
            "article": reverse("vitrine_article", args=[self.brouette.pk]),
            "boutique": reverse("vitrine_boutique", args=[self.ateba.slug]),
            "panier vide": reverse("vitrine_panier"),
            "design system": reverse("vitrine_design_system"),
        }

    def test_chaque_page_a_sa_structure(self):
        for nom, url in self.pages().items():
            with self.subTest(page=nom):
                reponse = self.client.get(url)
                self.assertEqual(reponse.status_code, 200)
                structure = _Structure()
                structure.feed(reponse.content.decode())
                self.assertEqual(structure.lang, "fr")
                self.assertTrue(structure.evitement, "lien « Aller au contenu »")
                self.assertTrue(structure.principal, "<main id=contenu>")
                self.assertEqual(structure.h1, 1, "un seul titre de niveau 1")
                self.assertEqual(structure.boutons_sans_nom, [], "bouton sans nom accessible")

    def test_la_carte_d_article_dit_ce_qu_elle_ajoute(self):
        reponse = self.client.get(reverse("vitrine_catalogue"))
        self.assertContains(reponse, f'aria-label="Ajouter {self.brouette.produit.libelle} au panier"')
        self.assertContains(reponse, "data-apparition")

    def test_la_page_404_a_son_titre(self):
        reponse = self.client.get(reverse("vitrine_article", args=["01a0f000-0000-7000-8000-000000000000"]))
        self.assertEqual(reponse.status_code, 404)
        structure = _Structure()
        structure.feed(reponse.content.decode())
        self.assertEqual(structure.h1, 1)


class LangueTest(SocleVitrine):
    def test_le_francais_par_defaut(self):
        reponse = self.client.get(reverse("vitrine_accueil"))
        self.assertContains(reponse, '<html lang="fr">')
        self.assertContains(reponse, "Le marché,")

    def test_l_anglais_si_le_navigateur_le_demande(self):
        reponse = self.client.get(reverse("vitrine_accueil"), HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9")
        self.assertContains(reponse, '<html lang="en">')
        self.assertContains(reponse, "The market,")
        self.assertContains(reponse, "Browse the aisles")
        self.assertEqual(reponse.headers["Content-Language"], "en")
        self.assertIn("Accept-Language", reponse.headers["Vary"])

    def test_le_choix_de_l_acheteur_l_emporte_et_se_garde(self):
        reponse = self.client.post(
            reverse("set_language"), {"language": "en", "next": reverse("vitrine_catalogue")}
        )
        self.assertRedirects(reponse, reverse("vitrine_catalogue"), fetch_redirect_response=False)
        self.assertEqual(reponse.cookies["hm_langue"].value, "en")
        page = self.client.get(reverse("vitrine_catalogue"), HTTP_ACCEPT_LANGUAGE="fr-FR")
        self.assertContains(page, "The whole market")
        self.assertContains(page, 'aria-pressed="true" title="English"')

    def test_les_messages_et_le_formulaire_suivent_la_langue(self):
        self.client.cookies["hm_langue"] = "en"
        reponse = self.client.post(
            reverse("vitrine_panier_ajouter", args=[self.brouette.pk]),
            {"suite": reverse("vitrine_panier")},
            follow=True,
        )
        self.assertContains(reponse, "Added to your cart.")
        commande = self.client.get(reverse("vitrine_commander"))
        self.assertContains(commande, "Your phone")
        self.assertContains(commande, "Pay on delivery")

    def test_le_back_office_reste_en_francais(self):
        reponse = self.client.get(reverse("connexion"), HTTP_ACCEPT_LANGUAGE="en-US")
        self.assertNotIn("Content-Language", reponse.headers)
        self.client.cookies["hm_langue"] = "en"
        reponse = self.client.get(reverse("connexion"))
        self.assertNotIn("Content-Language", reponse.headers)
        self.assertContains(reponse, "Connexion")


class CatalogueEnFragmentTest(SocleVitrine):
    def test_le_fragment_ne_contient_que_les_resultats(self):
        reponse = self.client.get(reverse("vitrine_catalogue") + "?q=brouette", HTTP_X_FRAGMENT="1")
        contenu = reponse.content.decode()
        self.assertNotIn("<html", contenu)
        self.assertIn("data-nombre-resultats", contenu)
        self.assertIn("data-titre-resultats", contenu)
        self.assertIn("X-Fragment", reponse.headers["Vary"])

    def test_la_page_porte_les_squelettes_et_la_region_annoncee(self):
        reponse = self.client.get(reverse("vitrine_catalogue"))
        self.assertContains(reponse, 'id="squelette-grille"')
        self.assertContains(reponse, "data-catalogue-annonce")
        self.assertContains(reponse, 'aria-live="polite"')

    def test_une_recherche_sans_resultat_propose_la_suite(self):
        reponse = self.client.get(reverse("vitrine_catalogue") + "?q=zzzz")
        self.assertContains(reponse, "Rien ne correspond à cette recherche.")
        self.assertContains(reponse, "Voir tout le marché")


class ReferenceVivanteTest(TestCase):
    def test_la_reference_montre_chaque_composant_et_ne_s_indexe_pas(self):
        reponse = self.client.get(reverse("vitrine_design_system"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.headers["X-Robots-Tag"], "noindex")
        for marque in (
            "btn-primary btn-sm", "btn-ghost btn-lg", "btn-accent btn-md", "aria-busy=\"true\"",
            "aria-invalid=\"true\"", "badge-erreur", "squelette", 'id="ds-modale"', "Quand ne pas l'utiliser",
            "Accessibilité à vérifier", "#00806A",
        ):
            with self.subTest(marque=marque):
                self.assertContains(reponse, marque, html=False)
