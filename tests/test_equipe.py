"""Gestion de l'équipe : embaucher, changer un rôle, retirer un accès.

Ce que ces tests protègent tient en une phrase : **un accès se retire, il ne se
supprime jamais**. L'employé qui part a encaissé des ventes et signé des
mouvements de stock ; effacer son compte effacerait la traçabilité de ce qu'il a
fait, et c'est précisément ce qu'un gérant cherchera à faire un jour de colère.

Les autres garde-fous protègent le gérant de lui-même : on ne se retire pas son
propre accès, et on ne retire pas le dernier gérant d'une boutique — dans les
deux cas, la porte se refermerait de l'intérieur.
"""

from django.contrib.auth import authenticate
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role, Utilisateur
from apps.backoffice.vues_equipe import generer_mot_de_passe
from apps.core.tenancy import contexte_boutique
from tests import fabrique
from tests.test_permissions import rattacher


class MotDePasseProvisoireTest(TestCase):
    def test_il_se_dicte_sans_ambiguite(self):
        """Il est remis de vive voix : ni O/0 ni I/1, sinon il faut épeler deux fois."""
        for _ in range(50):
            valeur = generer_mot_de_passe()
            self.assertNotRegex(valeur, r"[O0I1l]")
            self.assertEqual(len(valeur.replace("-", "")), 12)

    def test_deux_tirages_diffèrent(self):
        self.assertNotEqual(generer_mot_de_passe(), generer_mot_de_passe())


class RattachementTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Équipe", quota_utilisateurs=5)
        self.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(self.gerant, self.boutique, Role.GERANT)
        for code in (Role.CAISSIER, Role.MAGASINIER):
            Role.objects.get_or_create(
                code=code, defaults={"libelle": code.title(), "portee": Role.BOUTIQUE}
            )
        self.client.force_login(self.gerant)

    def _rattacher(self, telephone, nom="Marie Ekedi", role=Role.CAISSIER):
        return self.client.post(
            reverse("equipe"), {"telephone": telephone, "nom_complet": nom, "role": role}
        )

    def test_un_nouvel_employe_recoit_un_compte_et_un_mot_de_passe(self):
        reponse = self._rattacher("+237699887766")
        # Sans `fetch_redirect_response`, l'assertion irait chercher la page
        # d'arrivée — et consommerait le mot de passe, qui ne s'affiche qu'une fois.
        self.assertRedirects(reponse, reverse("equipe"), fetch_redirect_response=False)

        employe = Utilisateur.objects.get(telephone="+237699887766")
        self.assertEqual(employe.nom_complet, "Marie Ekedi")
        self.assertTrue(
            Appartenance.objects.filter(
                utilisateur=employe, boutique=self.boutique, role_id=Role.CAISSIER, actif=True
            ).exists()
        )

        page = self.client.get(reverse("equipe"))
        provisoire = page.context["mot_de_passe_provisoire"]
        self.assertEqual(provisoire["telephone"], "+237699887766")
        self.assertIsNotNone(authenticate(telephone=employe.telephone, password=provisoire["valeur"]))

    def test_le_mot_de_passe_n_est_affiche_qu_une_fois(self):
        self._rattacher("+237699887767")
        self.assertIsNotNone(self.client.get(reverse("equipe")).context["mot_de_passe_provisoire"])
        self.assertIsNone(self.client.get(reverse("equipe")).context["mot_de_passe_provisoire"])

    def test_un_compte_existant_est_rattache_sans_etre_recree(self):
        """Un même numéro n'ouvre jamais deux comptes : l'historique se scinderait."""
        ailleurs = fabrique.creer_boutique("Ailleurs", quota_utilisateurs=5)
        connu = fabrique.creer_utilisateur("Comptable de groupe", telephone="+237699112233")
        rattacher(connu, ailleurs, Role.COMPTABLE)

        self._rattacher("+237699112233", nom="Peu importe", role=Role.CAISSIER)

        self.assertEqual(Utilisateur.objects.filter(telephone="+237699112233").count(), 1)
        connu.refresh_from_db()
        self.assertEqual(connu.nom_complet, "Comptable de groupe")
        self.assertEqual(connu.appartenances.filter(actif=True).count(), 2)
        # Aucun mot de passe provisoire : le sien n'a pas changé.
        self.assertIsNone(self.client.get(reverse("equipe")).context["mot_de_passe_provisoire"])

    def test_rattacher_deux_fois_la_meme_personne_est_refuse(self):
        self._rattacher("+237699887768")
        reponse = self._rattacher("+237699887768", role=Role.MAGASINIER)
        self.assertEqual(reponse.status_code, 200)
        self.assertFormError(
            reponse.context["formulaire"], "telephone", "Cette personne fait déjà partie de votre équipe."
        )

    def test_le_quota_de_l_emplacement_est_opposable(self):
        """Le nombre d'accès fait partie de l'offre de location, pas du logiciel."""
        boutique = fabrique.creer_boutique("Étroite")
        gerant = fabrique.creer_utilisateur("Gérant seul")
        rattacher(gerant, boutique, Role.GERANT)  # quota par défaut : 1
        self.client.force_login(gerant)

        reponse = self.client.post(
            reverse("equipe"),
            {"telephone": "+237699000111", "nom_complet": "De trop", "role": Role.CAISSIER},
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("autorise 1 utilisateur", str(reponse.context["formulaire"].non_field_errors()))
        self.assertFalse(Utilisateur.objects.filter(telephone="+237699000111").exists())

    def test_le_nom_est_exige_pour_un_compte_neuf(self):
        reponse = self._rattacher("+237699887769", nom="")
        self.assertEqual(reponse.status_code, 200)
        self.assertFormError(
            reponse.context["formulaire"], "nom_complet", "Le nom est obligatoire pour un nouveau compte."
        )


class ChangementDeRoleTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Rôles", quota_utilisateurs=5)
        self.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(self.gerant, self.boutique, Role.GERANT)
        self.caissier = fabrique.creer_utilisateur("Caissier")
        self.appartenance = rattacher(self.caissier, self.boutique, Role.CAISSIER)
        Role.objects.get_or_create(
            code=Role.MAGASINIER, defaults={"libelle": "Magasinier", "portee": Role.BOUTIQUE}
        )
        self.client.force_login(self.gerant)

    def test_un_changement_de_role_change_ce_que_la_personne_voit(self):
        """La preuve utile n'est pas la ligne en base, c'est l'écran qui change."""
        self.client.post(
            reverse("equipe_role", args=[self.appartenance.pk]), {"role": Role.MAGASINIER}
        )

        self.client.force_login(self.caissier)
        # Magasinier : le coût d'achat s'ouvre, la caisse se ferme.
        self.assertEqual(self.client.get(reverse("caisse")).status_code, 403)
        self.assertContains(self.client.get(reverse("stock")), "Coût moyen")

    def test_le_dernier_gerant_ne_peut_pas_se_degrader(self):
        propre = Appartenance.objects.get(utilisateur=self.gerant, boutique=self.boutique)
        reponse = self.client.post(
            reverse("equipe_role", args=[propre.pk]), {"role": Role.CAISSIER}, follow=True
        )
        self.assertContains(reponse, "dernier gérant")

        propre.refresh_from_db()
        self.assertEqual(propre.role_id, Role.GERANT)

    def test_un_membre_d_une_autre_boutique_est_introuvable(self):
        ailleurs = fabrique.creer_boutique("Ailleurs", quota_utilisateurs=5)
        etranger = fabrique.creer_utilisateur("Étranger")
        appartenance = rattacher(etranger, ailleurs, Role.CAISSIER)

        reponse = self.client.post(
            reverse("equipe_role", args=[appartenance.pk]), {"role": Role.MAGASINIER}
        )
        self.assertEqual(reponse.status_code, 404)


class RetraitDAccesTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Retraits", quota_utilisateurs=5)
        self.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(self.gerant, self.boutique, Role.GERANT)
        self.caissier = fabrique.creer_utilisateur("Caissier")
        self.appartenance = rattacher(self.caissier, self.boutique, Role.CAISSIER)
        self.client.force_login(self.gerant)

    def test_retirer_un_acces_ne_supprime_pas_le_compte(self):
        """L'historique du départ doit rester lisible : il a encaissé de l'argent."""
        self.client.post(reverse("equipe_retirer", args=[self.appartenance.pk]))

        self.appartenance.refresh_from_db()
        self.assertFalse(self.appartenance.actif)
        self.assertIsNotNone(self.appartenance.jusqu_a)
        self.assertTrue(Utilisateur.objects.filter(pk=self.caissier.pk).exists())

    def test_l_acces_retire_ferme_reellement_la_porte(self):
        self.client.post(reverse("equipe_retirer", args=[self.appartenance.pk]))

        self.client.force_login(self.caissier)
        reponse = self.client.get(reverse("caisse"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("connexion"), reponse["Location"])

    def test_on_ne_retire_pas_son_propre_acces(self):
        propre = Appartenance.objects.get(utilisateur=self.gerant, boutique=self.boutique)
        reponse = self.client.post(
            reverse("equipe_retirer", args=[propre.pk]), follow=True
        )
        self.assertContains(reponse, "votre propre accès")

        propre.refresh_from_db()
        self.assertTrue(propre.actif)

    def test_le_dernier_gerant_ne_se_retire_pas(self):
        second = fabrique.creer_utilisateur("Second gérant")
        appartenance = rattacher(second, self.boutique, Role.GERANT)

        # Deux gérants : le retrait du second passe.
        self.client.post(reverse("equipe_retirer", args=[appartenance.pk]))
        appartenance.refresh_from_db()
        self.assertFalse(appartenance.actif)

    def test_rendre_l_acces_reutilise_la_meme_appartenance(self):
        """L'employé qui revient retrouve son historique, il ne repart pas de zéro."""
        self.client.post(reverse("equipe_retirer", args=[self.appartenance.pk]))
        self.client.post(reverse("equipe_reactiver", args=[self.appartenance.pk]))

        self.appartenance.refresh_from_db()
        self.assertTrue(self.appartenance.actif)
        self.assertIsNone(self.appartenance.jusqu_a)
        self.assertEqual(
            Appartenance.objects.filter(
                utilisateur=self.caissier, boutique=self.boutique
            ).count(),
            1,
        )

    def test_un_rattachement_apres_retrait_reactive_au_lieu_de_dupliquer(self):
        self.client.post(reverse("equipe_retirer", args=[self.appartenance.pk]))
        self.client.post(
            reverse("equipe"),
            {
                "telephone": self.caissier.telephone,
                "nom_complet": "Peu importe",
                "role": Role.CAISSIER,
            },
        )
        self.assertEqual(
            Appartenance.objects.filter(
                utilisateur=self.caissier, boutique=self.boutique
            ).count(),
            1,
        )


class ReinitialisationDuMotDePasseTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Oublis", quota_utilisateurs=5)
        self.gerant = fabrique.creer_utilisateur("Gérant")
        rattacher(self.gerant, self.boutique, Role.GERANT)
        self.caissier = fabrique.creer_utilisateur("Caissier")
        self.appartenance = rattacher(self.caissier, self.boutique, Role.CAISSIER)
        self.client.force_login(self.gerant)

    def test_le_gerant_regenere_un_mot_de_passe_utilisable(self):
        """Sans passerelle SMS, personne d'autre ne peut le faire."""
        self.client.post(reverse("equipe_mot_de_passe", args=[self.appartenance.pk]))

        provisoire = self.client.get(reverse("equipe")).context["mot_de_passe_provisoire"]
        self.assertEqual(provisoire["telephone"], self.caissier.telephone)
        self.assertIsNotNone(
            authenticate(telephone=self.caissier.telephone, password=provisoire["valeur"])
        )
        self.assertIsNone(
            authenticate(telephone=self.caissier.telephone, password="motdepasse")
        )

    def test_le_gerant_ne_reinitialise_pas_le_sien_par_ce_chemin(self):
        propre = Appartenance.objects.get(utilisateur=self.gerant, boutique=self.boutique)
        reponse = self.client.post(
            reverse("equipe_mot_de_passe", args=[propre.pk]), follow=True
        )
        self.assertContains(reponse, "depuis votre compte")
        self.assertIsNotNone(
            authenticate(telephone=self.gerant.telephone, password="motdepasse")
        )


class PorteDeLEcranEquipeTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Porte équipe", quota_utilisateurs=8)
        with contexte_boutique(self.boutique):
            fabrique.creer_depot(self.boutique)

    def test_seul_un_role_administrateur_y_accede(self):
        for code_role, attendu in (
            (Role.GERANT, 200),
            (Role.CAISSIER, 403),
            (Role.COMPTABLE, 403),
            (Role.MAGASINIER, 403),
        ):
            with self.subTest(role=code_role):
                utilisateur = fabrique.creer_utilisateur(code_role.title())
                rattacher(utilisateur, self.boutique, code_role)
                self.client.force_login(utilisateur)
                self.assertEqual(self.client.get(reverse("equipe")).status_code, attendu)
