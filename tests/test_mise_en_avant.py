"""Les emplacements premium sur la vitrine, et leur mesure (docs/22, §4.1).

Ce que ces tests protègent :

* **ce qui est vendu est montré** — accueil, bandeau de rayon, tête de gondole — avec la mention
  « Sponsorisé », et **seulement** pendant la période payée, chez une boutique qui vend encore ;
* **on compte des acheteurs** : un affichage par page, ni robot, ni aperçu de lien, ni
  préchargement ; un clic par passage par le compteur ;
* **le compteur n'est pas une redirection ouverte** ;
* **une commande n'est attribuée qu'à l'emplacement de son commerçant**, dans les sept jours ;
* **on ne vend pas une place que la vitrine ne montrerait pas** ;
* **le commerçant voit ses chiffres** ; la console voit affichages et clics, pas ses ventes.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.marketplace import mesures
from apps.marketplace.models import Boutique, EmplacementPremium, MesureEmplacement
from apps.plateforme import services
from apps.vitrine import mise_en_avant
from tests import fabrique
from tests.test_backoffice_gestion import BaseGestionTest
from tests.test_console import PersonnagesMixin
from tests import test_vitrine
from tests.test_vitrine import SocleVitrine

NAVIGATEUR = "Mozilla/5.0 (Linux; Android 13) Chrome/124 Mobile"


def emplacement(boutique, type_, *, rayon=None, debut=0, fin=6, tarif="75000"):
    aujourdhui = timezone.localdate()
    return EmplacementPremium.objects.create(
        type=type_, rayon=rayon, boutique_occupante=boutique, tarif=Decimal(tarif),
        debut=aujourdhui + timedelta(days=debut), fin=aujourdhui + timedelta(days=fin),
    )


def mesure(e):
    totaux = mesures.bilans([e])[0]
    return totaux.affichages, totaux.clics, totaux.commandes, totaux.montant


class AccueilTest(SocleVitrine):
    def accueil(self, **entetes):
        return self.client.get(reverse("vitrine_accueil"), HTTP_USER_AGENT=entetes.pop("ua", NAVIGATEUR), **entetes)

    def test_l_emplacement_paye_est_montre_et_signale(self):
        e = emplacement(self.ateba, EmplacementPremium.ACCUEIL)
        reponse = self.accueil()
        self.assertContains(reponse, "À la une du marché")
        self.assertContains(reponse, "Sponsorisé")
        self.assertContains(reponse, reverse("vitrine_mise_en_avant", args=[e.pk]))
        self.assertEqual(mesure(e)[0], 1)
        self.accueil()
        self.assertEqual(mesure(e)[0], 2, "chaque page rendue compte un affichage")

    def test_hors_periode_ou_boutique_suspendue_rien_n_est_montre(self):
        passe = emplacement(self.ateba, EmplacementPremium.ACCUEIL, debut=-10, fin=-1)
        futur = emplacement(self.ateba, EmplacementPremium.ACCUEIL, debut=2, fin=8)
        self.assertNotContains(self.accueil(), "Sponsorisé")
        courant = emplacement(self.bella, EmplacementPremium.ACCUEIL)
        Boutique.objects.filter(pk=self.bella.pk).update(etat=Boutique.SUSPENDUE)
        self.assertNotContains(self.accueil(), "Sponsorisé")
        for e in (passe, futur, courant):
            self.assertEqual(mesure(e)[0], 0)

    def test_robots_apercus_et_prechargement_ne_comptent_pas(self):
        e = emplacement(self.ateba, EmplacementPremium.ACCUEIL)
        self.accueil(ua="Googlebot/2.1 (+http://www.google.com/bot.html)")
        self.accueil(ua="WhatsApp/2.23.20.0")
        self.accueil(HTTP_SEC_PURPOSE="prefetch")
        self.assertEqual(mesure(e)[0], 0)

    def test_au_dela_de_la_capacite_le_premier_vendu_passe(self):
        e = [emplacement(fabrique.creer_boutique(), EmplacementPremium.ACCUEIL) for _ in range(4)]
        montres = mise_en_avant.emplacements_du_jour(EmplacementPremium.ACCUEIL)
        self.assertEqual([m.pk for m in montres], [x.pk for x in e[:3]])


class RayonTest(SocleVitrine):
    def setUp(self):
        super().setUp()
        self.rayon = self.ateba.rayon_principal
        self.bandeau = emplacement(self.ateba, EmplacementPremium.BANDEAU_RAYON, rayon=self.rayon)
        self.gondole = emplacement(self.ateba, EmplacementPremium.TETE_DE_GONDOLE, rayon=self.rayon)

    def catalogue(self, **params):
        fragment = params.pop("fragment", None)
        entetes = {"HTTP_USER_AGENT": NAVIGATEUR}
        if fragment:
            entetes["HTTP_X_FRAGMENT"] = fragment
        return self.client.get(reverse("vitrine_catalogue"), {"rayon": self.rayon.code, **params}, **entetes)

    def test_bandeau_et_tete_de_gondole_en_tete_du_rayon(self):
        reponse = self.catalogue()
        self.assertContains(reponse, "En tête de gondole")
        self.assertContains(reponse, reverse("vitrine_mise_en_avant", args=[self.bandeau.pk]))
        self.assertContains(reponse, reverse("vitrine_mise_en_avant", args=[self.gondole.pk]))
        self.assertEqual(mesure(self.bandeau)[0], 1)
        self.assertEqual(mesure(self.gondole)[0], 1)

    def test_le_fragment_des_filtres_les_garde(self):
        self.assertContains(self.catalogue(fragment="1"), "En tête de gondole")

    def test_ni_dans_une_recherche_ni_dans_la_suite_ni_dans_un_autre_rayon(self):
        self.assertNotContains(self.catalogue(q="brouette"), "En tête de gondole")
        self.assertNotContains(self.catalogue(page="2", fragment="suite"), "Sponsorisé")
        autre = self.client.get(reverse("vitrine_catalogue"), {"rayon": self.bella.rayon_principal.code})
        self.assertNotContains(autre, "Sponsorisé")
        self.assertEqual(mesure(self.bandeau)[0], 0)


class ClicTest(SocleVitrine):
    def test_le_clic_est_compte_puis_mene_a_la_page(self):
        e = emplacement(self.ateba, EmplacementPremium.ACCUEIL)
        cible = reverse("vitrine_boutique", args=[self.ateba.slug])
        reponse = self.client.get(mise_en_avant.lien(e, cible), HTTP_USER_AGENT=NAVIGATEUR)
        self.assertRedirects(reponse, cible, fetch_redirect_response=False)
        self.assertEqual(mesure(e)[1], 1)
        self.assertIn(str(e.pk), self.client.session[mise_en_avant.CLE_SESSION])

    def test_le_compteur_n_est_pas_une_redirection_ouverte(self):
        e = emplacement(self.ateba, EmplacementPremium.ACCUEIL)
        url = reverse("vitrine_mise_en_avant", args=[e.pk])
        for piege in ("https://hameconnage.example/marche/", "//hameconnage.example/x", "/admin/", ""):
            reponse = self.client.get(url, {"vers": piege})
            self.assertEqual(reponse["Location"], reverse("vitrine_accueil"), piege)


class AttributionTest(SocleVitrine):
    # Repris du tunnel sans importer sa classe : le chargeur de tests la relancerait ici.
    DONNEES = test_vitrine.TunnelTest.DONNEES
    _commander = test_vitrine.TunnelTest._commander

    def cliquer(self, e, boutique):
        self.client.get(
            mise_en_avant.lien(e, reverse("vitrine_boutique", args=[boutique.slug])), HTTP_USER_AGENT=NAVIGATEUR
        )

    def test_la_commande_chez_l_occupant_est_attribuee(self):
        e = emplacement(self.ateba, EmplacementPremium.ACCUEIL)
        self.cliquer(e, self.ateba)
        self.ajouter_au_panier(self.brouette)
        self.ajouter_au_panier(self.creme)
        self.assertEqual(self._commander().status_code, 302)
        affichages, clics, commandes, montant = mesure(e)
        self.assertEqual((clics, commandes), (1, 1))
        self.assertEqual(montant, Decimal("34500"), "seule la part de l'occupant compte")

    def test_rien_pour_un_autre_commercant_ni_apres_sept_jours(self):
        e = emplacement(self.bella, EmplacementPremium.ACCUEIL)
        self.cliquer(e, self.bella)
        self.ajouter_au_panier(self.brouette)  # Ateba, pas Bella
        self._commander()
        self.assertEqual(mesure(e)[2], 0)

        session = self.client.session
        ancien = (timezone.now() - timedelta(days=8)).isoformat()
        session[mise_en_avant.CLE_SESSION] = {str(e.pk): ancien}
        session.save()
        self.ajouter_au_panier(self.creme)
        self._commander(telephone="+237690112244")
        self.assertEqual(mesure(e)[2], 0)


class CapaciteTest(PersonnagesMixin, TestCase):
    def setUp(self):
        self.poser_les_personnages()
        self.aujourdhui = timezone.localdate()
        self.rayon = self.boutique.rayon_principal

    def vendre(self, boutique, type_, debut, fin, rayon=None):
        return services.vendre_emplacement(
            par=self.administrateur, boutique=boutique, type_emplacement=type_, rayon=rayon,
            debut=self.aujourdhui + timedelta(days=debut), fin=self.aujourdhui + timedelta(days=fin),
            tarif=Decimal("35000"),
        )

    def test_un_bandeau_par_rayon_et_par_jour(self):
        self.vendre(self.boutique, EmplacementPremium.BANDEAU_RAYON, 0, 6, rayon=self.rayon)
        autre = fabrique.creer_boutique("Concurrente")
        with self.assertRaises(ValidationError) as refus:
            self.vendre(autre, EmplacementPremium.BANDEAU_RAYON, 5, 10, rayon=self.rayon)
        self.assertIn("Chez un tiers", str(refus.exception))
        # Le lendemain de la fin, la place est libre ; dans un autre rayon aussi.
        self.vendre(autre, EmplacementPremium.BANDEAU_RAYON, 7, 13, rayon=self.rayon)
        self.vendre(autre, EmplacementPremium.BANDEAU_RAYON, 0, 6, rayon=autre.rayon_principal)

    def test_pas_d_emplacement_dans_un_rayon_ferme(self):
        self.rayon.ouvert = False
        self.rayon.save(update_fields=["ouvert"])
        with self.assertRaises(ValidationError) as refus:
            self.vendre(self.boutique, EmplacementPremium.TETE_DE_GONDOLE, 0, 6, rayon=self.rayon)
        self.assertIn("fermé", str(refus.exception))

    def test_l_accueil_en_montre_trois_le_meme_jour(self):
        boutiques = [fabrique.creer_boutique() for _ in range(4)]
        self.vendre(boutiques[0], EmplacementPremium.ACCUEIL, 0, 3)
        self.vendre(boutiques[1], EmplacementPremium.ACCUEIL, 4, 8)  # ne chevauche pas le premier
        self.vendre(boutiques[2], EmplacementPremium.ACCUEIL, 0, 8)
        self.vendre(boutiques[3], EmplacementPremium.ACCUEIL, 2, 6)  # jour 2 : 3 occupants, c'est plein
        with self.assertRaises(ValidationError):
            self.vendre(self.boutique, EmplacementPremium.ACCUEIL, 2, 2 + 1)


class EcransTest(BaseGestionTest):
    def test_le_commercant_voit_ses_chiffres(self):
        e = emplacement(self.boutique, EmplacementPremium.ACCUEIL, debut=-2, fin=4)
        hier = timezone.localdate() - timedelta(days=1)
        MesureEmplacement.objects.create(
            emplacement=e, jour=hier, affichages=200, clics=10, commandes=2, montant=Decimal("25000")
        )
        reponse = self.client.get(reverse("mise_en_avant"))
        self.assertContains(reponse, "200")
        self.assertContains(reponse, "5,0 %")  # 10 clics / 200 affichages
        self.assertContains(reponse, "7\u202f500 FCFA")  # 75 000 / 10 clics (espace fine insécable)
        self.assertContains(reponse, "25\u202f000 FCFA")
        self.assertContains(self.client.get(reverse("boutique")), reverse("mise_en_avant"))

    def test_sans_emplacement_l_ecran_explique(self):
        self.assertContains(self.client.get(reverse("mise_en_avant")), "aucun emplacement")


class ConsoleTest(PersonnagesMixin, TestCase):
    def test_la_console_voit_affichages_et_clics_pas_les_ventes(self):
        self.poser_les_personnages()
        e = emplacement(self.boutique, EmplacementPremium.ACCUEIL)
        MesureEmplacement.objects.create(
            emplacement=e, jour=timezone.localdate(), affichages=321, clics=12, commandes=3,
            montant=Decimal("98765"),
        )
        self.client.force_login(self.administrateur)
        reponse = self.client.get(reverse("plateforme:emplacements"))
        self.assertContains(reponse, "321")
        self.assertNotContains(reponse, "98\u202f765")
        self.assertNotContains(reponse, "98765")


class CompteurTest(TestCase):
    def test_les_increments_s_additionnent(self):
        e = emplacement(fabrique.creer_boutique(), EmplacementPremium.ACCUEIL)
        for _ in range(3):
            mise_en_avant._incrementer(e.pk, affichages=1)
        mise_en_avant._incrementer(e.pk, clics=1, commandes=1, montant=Decimal("1500"))
        self.assertEqual(MesureEmplacement.objects.get().affichages, 3)
        self.assertEqual(mesure(e), (3, 1, 1, Decimal("1500")))
