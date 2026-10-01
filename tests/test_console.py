"""La porte de la console de la plateforme (ADR-012).

Trois personnages, trois réponses :

* le **superadministrateur** entre partout, y compris sur les écrans qui lui sont réservés ;
* l'**administrateur du marché** entre dans la console, mais pas sur ces écrans-là ;
* le **commerçant** n'entre pas : la console existe, ce n'est pas la sienne — et il doit le lire,
  pas croire à une panne.

Et une règle : lire l'activité à travers les boutiques exige un motif, et chaque lecture laisse
une ligne dans le journal.
"""

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.plateforme.acces import (
    CONSOLE_ADMINISTRATEURS,
    CONSOLE_TECHNIQUE,
    droits_console_de,
    suivi_actif,
)
from apps.accounts.permissions import TOUS_PLATEFORME
from tests import fabrique


class PersonnagesMixin:
    def poser_les_personnages(self):
        self.boutique = fabrique.creer_boutique("Chez un tiers")
        self.superadmin = fabrique.creer_utilisateur("Superadministratrice")
        self.superadmin.is_superuser = True
        self.superadmin.is_staff = True
        self.superadmin.save(update_fields=["is_superuser", "is_staff"])

        self.administrateur = fabrique.creer_utilisateur("Administrateur du marché")
        call_command(
            "preparer_administrateur", administrateur=self.administrateur.telephone, verbosity=0
        )
        self.administrateur.refresh_from_db()

        self.commercant = fabrique.creer_utilisateur("Commerçant")
        role, _ = Role.objects.get_or_create(
            code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
        )
        Appartenance.objects.create(utilisateur=self.commercant, boutique=self.boutique, role=role)


class DroitsDeLaConsoleTest(PersonnagesMixin, TestCase):
    def setUp(self):
        self.poser_les_personnages()

    def test_le_superadministrateur_a_tout_et_ses_ecrans_reserves(self):
        droits = droits_console_de(self.superadmin)
        self.assertTrue(TOUS_PLATEFORME <= droits)
        self.assertIn(CONSOLE_ADMINISTRATEURS, droits)
        self.assertIn(CONSOLE_TECHNIQUE, droits)

    def test_l_administrateur_a_son_role_et_pas_les_ecrans_reserves(self):
        droits = droits_console_de(self.administrateur)
        self.assertEqual(droits, TOUS_PLATEFORME)
        self.assertNotIn(CONSOLE_ADMINISTRATEURS, droits)

    def test_le_commercant_n_a_aucun_droit_de_console(self):
        self.assertEqual(droits_console_de(self.commercant), frozenset())

    def test_un_compte_desactive_n_a_plus_rien(self):
        self.superadmin.is_active = False
        self.superadmin.save(update_fields=["is_active"])
        self.assertEqual(droits_console_de(self.superadmin), frozenset())


class PorteDeLaConsoleTest(PersonnagesMixin, TestCase):
    def setUp(self):
        self.poser_les_personnages()
        self.url = reverse("plateforme:tableau_de_bord")

    def test_un_visiteur_est_renvoye_a_la_connexion(self):
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("connexion"), reponse["Location"])

    def test_le_commercant_lit_un_refus_explicite(self):
        self.client.force_login(self.commercant)
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.status_code, 403)
        self.assertContains(reponse, "réservée au superadministrateur", status_code=403)

    def test_les_deux_administrateurs_entrent(self):
        for compte in (self.superadmin, self.administrateur):
            self.client.force_login(compte)
            self.assertEqual(self.client.get(self.url).status_code, 200, compte)

    def test_l_administrateur_du_marche_ne_nomme_pas_les_administrateurs(self):
        self.client.force_login(self.administrateur)
        reponse = self.client.get(reverse("plateforme:administrateurs"))
        self.assertEqual(reponse.status_code, 403)

    def test_le_superadministrateur_nomme_les_administrateurs(self):
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.get(reverse("plateforme:administrateurs")).status_code, 200)

    def test_la_connexion_d_un_administrateur_ouvre_sa_console(self):
        self.administrateur.set_password("motdepasse-solide")
        self.administrateur.save(update_fields=["password"])
        reponse = self.client.post(
            reverse("connexion"),
            {"telephone": self.administrateur.telephone, "mot_de_passe": "motdepasse-solide"},
        )
        self.assertRedirects(reponse, self.url, fetch_redirect_response=False)


class MotifDeSuiviTest(PersonnagesMixin, TestCase):
    def setUp(self):
        self.poser_les_personnages()
        self.client.force_login(self.administrateur)

    def test_l_activite_demande_un_motif_puis_revient_a_l_ecran(self):
        cible = reverse("plateforme:activite")
        reponse = self.client.get(cible)
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("plateforme:suivi_ouvrir"), reponse["Location"])

        reponse = self.client.post(
            reverse("plateforme:suivi_ouvrir"), {"motif": "suivi_mensuel", "suite": cible}
        )
        self.assertRedirects(reponse, cible, fetch_redirect_response=False)

    def test_autre_exige_une_precision(self):
        reponse = self.client.post(reverse("plateforme:suivi_ouvrir"), {"motif": "autre"})
        self.assertEqual(reponse.status_code, 400)
        self.assertIsNone(suivi_actif(reponse.wsgi_request))

    def test_un_motif_hors_liste_est_refuse(self):
        reponse = self.client.post(reverse("plateforme:suivi_ouvrir"), {"motif": "curiosite"})
        self.assertEqual(reponse.status_code, 400)

    def test_la_suite_ne_mene_pas_hors_du_site(self):
        reponse = self.client.post(
            reverse("plateforme:suivi_ouvrir"),
            {"motif": "suivi_mensuel", "suite": "https://ailleurs.example/piege"},
        )
        self.assertRedirects(
            reponse, reverse("plateforme:tableau_de_bord"), fetch_redirect_response=False
        )


class LaConsoleNeContournePasLeJournalTest(TestCase):
    def test_aucun_module_de_la_console_n_ouvre_le_contexte_plateforme(self):
        """La console est l'endroit où un humain regarde à travers les boutiques : c'est
        précisément là où `contexte_plateforme()` — l'accès technique, sans motif ni trace — n'a
        pas sa place. Toute lecture transverse y passe par `lecture_journalisee()`. Pas de
        dérogation possible ici, contrairement au back-office.
        """
        import pathlib

        coupables = [
            str(f)
            for f in sorted(pathlib.Path("apps/plateforme").rglob("*.py"))
            if "contexte_plateforme(" in f.read_text()
        ]
        self.assertEqual(coupables, [], ", ".join(coupables))


class ContratsDeDemonstrationTest(TestCase):
    def test_garnis_une_fois_et_jamais_sur_une_instance_qui_a_des_loyers(self):
        """Idempotente : elle tourne à chaque construction de la démonstration."""
        from apps.marketplace.models import Boutique, FactureLoyer

        fabrique.creer_boutique("Boutique de démonstration")
        call_command("garnir_contrats_demo", verbosity=0)
        factures = FactureLoyer.objects.count()
        self.assertEqual(factures, 6, "six mois de loyers pour le bail actif")
        self.assertTrue(Boutique.objects.filter(etat=Boutique.CANDIDATURE).exists())

        call_command("garnir_contrats_demo", verbosity=0)
        self.assertEqual(FactureLoyer.objects.count(), factures)


class TachesQuotidiennesTest(TestCase):
    """La porte des tâches de nuit déplace de l'argent : elle se ferme par défaut."""

    url = "/taches/quotidiennes/"

    def test_fermee_sans_secret_configure(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CRON_SECRET", None)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(
                self.client.get(self.url, HTTP_AUTHORIZATION="Bearer ").status_code, 403
            )

    def test_fermee_avec_un_mauvais_secret(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"CRON_SECRET": "le-bon-secret-long"}):
            reponse = self.client.get(self.url, HTTP_AUTHORIZATION="Bearer mauvais")
            self.assertEqual(reponse.status_code, 403)

    def test_lance_les_deux_commandes_avec_le_bon_secret(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"CRON_SECRET": "le-bon-secret-long"}):
            reponse = self.client.get(
                self.url, HTTP_AUTHORIZATION="Bearer le-bon-secret-long"
            )
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual(
            set(reponse.json()), {"actualiser_paiements", "liberer_sequestres", "evaluer_confiance"}
        )


class ConsoleEnAnglaisTest(PersonnagesMixin, TestCase):
    """La console suit la langue choisie, comme le marché et le back-office."""

    def setUp(self):
        self.poser_les_personnages()
        self.client.force_login(self.superadmin)

    def test_la_console_se_lit_en_anglais(self):
        self.client.cookies["hm_langue"] = "en"
        for nom in ("plateforme:tableau_de_bord", "plateforme:boutiques", "plateforme:rayons"):
            with self.subTest(ecran=nom):
                reponse = self.client.get(reverse(nom))
                self.assertEqual(reponse.status_code, 200)
                self.assertContains(reponse, '<html lang="en"')
                self.assertContains(reponse, 'class="choix-langue"')
        self.assertContains(self.client.get(reverse("plateforme:boutiques")), "Open a shop")
