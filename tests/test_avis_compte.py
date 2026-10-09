"""L'avis au gérant quand un compte de versement est déclaré pour sa boutique.

Ce que ces tests protègent :

* **le gérant voit tout compte déclaré par quelqu'un d'autre**, sur toutes les pages, tant qu'il n'a
  pas répondu — et seulement lui ;
* **« ce n'est pas moi »** retire le compte, annule les versements qui y partaient et ouvre un
  signal critique pour la plateforme ;
* **« c'est bien moi »** fait disparaître l'avis sans rien changer d'autre ;
* un compte qu'il a **lui-même** déclaré ne lui est pas montré.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Appartenance, Role
from apps.confiance.models import SignalRisque
from apps.marketplace.models import CompteVersement
from tests import fabrique


class AvisAuGerantTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Ateba")
        fabrique.creer_depot(self.boutique)
        gerant, _ = Role.objects.get_or_create(
            code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
        )
        caissier, _ = Role.objects.get_or_create(
            code=Role.CAISSIER, defaults={"libelle": "Caissier", "portee": Role.BOUTIQUE}
        )
        self.gerant = fabrique.creer_utilisateur("Jeanne Ateba")
        Appartenance.objects.create(utilisateur=self.gerant, boutique=self.boutique, role=gerant)
        self.caissier = fabrique.creer_utilisateur("Paul")
        Appartenance.objects.create(utilisateur=self.caissier, boutique=self.boutique, role=caissier)
        self.intrus = fabrique.creer_utilisateur("Intrus")

    def _compte(self, *, declare_par, etat=CompteVersement.VERIFIE):
        return CompteVersement.objects.create(
            boutique=self.boutique,
            operateur="MTN_MOMO",
            numero="+237677001234",
            titulaire="Quelqu'un d'autre",
            etat=etat,
            declare_par=declare_par,
            utilisable_le=timezone.now() + timezone.timedelta(hours=48),
        )

    def _page(self, qui):
        self.client.force_login(qui)
        session = self.client.session
        session["boutique_id"] = str(self.boutique.pk)
        session.save()
        return self.client.get(reverse("verification"))

    def test_le_gerant_voit_le_compte_declare_par_un_autre(self):
        self._compte(declare_par=self.intrus)
        page = self._page(self.gerant)
        self.assertContains(page, "Un compte de versement a été déclaré pour votre boutique")
        self.assertContains(page, "1234")

    def test_le_caissier_ne_le_voit_pas(self):
        """Sur sa propre page de travail — la caisse — l'avis n'apparaît pas : ce n'est pas lui qui
        sait si le numéro est celui de la boutique."""
        self._compte(declare_par=self.intrus)
        self._page(self.caissier)
        page = self.client.get(reverse("caisse"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Est-ce bien vous")

    def test_un_compte_qu_il_a_declare_lui_meme_ne_lui_est_pas_montre(self):
        self._compte(declare_par=self.gerant)
        self.assertNotContains(self._page(self.gerant), "Est-ce bien vous")

    def test_ce_n_est_pas_moi_retire_le_compte_et_previent_la_plateforme(self):
        compte = self._compte(declare_par=self.intrus)
        self._page(self.gerant)
        self.client.post(reverse("compte_contester", args=[compte.pk]))

        compte.refresh_from_db()
        self.assertEqual(compte.etat, CompteVersement.RETIRE)
        self.assertEqual(compte.conteste_par, self.gerant)
        self.assertTrue(CompteVersement.objects.filter(pk=compte.pk).exists(), "retiré, pas supprimé")
        signal = SignalRisque.objects.get(boutique=self.boutique, type=SignalRisque.CHANGEMENT_COMPTE)
        self.assertEqual(signal.gravite, SignalRisque.CRITIQUE)
        self.assertIn("Intrus", signal.resume)
        self.assertNotContains(self._page(self.gerant), "Est-ce bien vous")

    def test_c_est_bien_moi_fait_disparaitre_l_avis_sans_rien_changer(self):
        compte = self._compte(declare_par=self.intrus)
        self._page(self.gerant)
        self.client.post(reverse("compte_confirmer", args=[compte.pk]))
        compte.refresh_from_db()
        self.assertEqual(compte.etat, CompteVersement.VERIFIE)
        self.assertIsNotNone(compte.confirme_par_gerant_le)
        self.assertNotContains(self._page(self.gerant), "Est-ce bien vous")

    def test_un_caissier_ne_peut_pas_contester(self):
        compte = self._compte(declare_par=self.intrus)
        self._page(self.caissier)
        reponse = self.client.post(reverse("compte_contester", args=[compte.pk]))
        self.assertEqual(reponse.status_code, 403)
        compte.refresh_from_db()
        self.assertEqual(compte.etat, CompteVersement.VERIFIE)
