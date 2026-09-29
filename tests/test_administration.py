"""Les trois niveaux d'administration, et la frontière entre eux.

Ce que ces tests défendent, et pourquoi chacun compte :

1. **Le superadministrateur voit tout, l'administrateur du marché non.** C'est la distinction
   demandée, et elle ne tient que par le groupe de permissions : un compte `is_staff` sans
   permission voit une administration vide, un compte `is_superuser` voit tout sans en avoir
   aucune. Le second est un recours technique, le premier un métier quotidien.
2. **L'administrateur du marché ne voit ni comptabilité, ni stock, ni cahier de crédit.** C'est
   la raison d'être de la liste écrite : un exploitant qui vend aussi sur sa place ne doit pas
   lire les chiffres de ses concurrents par la porte de service.
3. **La liste ne contient pas de permission fantôme.** Un nom de modèle mal orthographié
   produirait un administrateur incapable de travailler, sans que rien ne l'explique — et j'en ai
   écrit un en composant la liste (`facturelover` pour `factureloyer`).
"""

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase

from apps.accounts.administration import (
    APPLICATIONS_INTERDITES,
    NOM_GROUPE,
    PERMISSIONS,
    codes_de_permission,
    synchroniser_le_groupe,
)
from apps.accounts.models import Role, RolePlateforme
from apps.accounts.permissions import TOUS, TOUS_PLATEFORME, droits_de, droits_plateforme_de
from tests import fabrique


class ListeDePermissionsTest(TestCase):
    def test_aucune_permission_fantome(self):
        """Chaque ligne de la liste doit désigner un modèle qui existe réellement."""
        _, manquantes = synchroniser_le_groupe()
        self.assertEqual(
            manquantes,
            [],
            "Ces permissions n'existent pas : modèle renommé ou faute de frappe. "
            + ", ".join(manquantes),
        )

    def test_le_groupe_porte_exactement_ce_que_la_liste_nomme(self):
        groupe, _ = synchroniser_le_groupe()
        self.assertEqual(groupe.name, NOM_GROUPE)
        self.assertEqual(groupe.permissions.count(), len(codes_de_permission()))

    def test_aucune_permission_sur_les_applications_interdites(self):
        """La frontière. Comptabilité, stock, caisse, cahier, catalogue, commandes, paiements.

        Ce n'est pas une précaution : c'est ce qui distingue un bailleur d'un concurrent qui
        aurait les clés. Un ajout dans ces applications doit être un choix assumé, pas une
        distraction — et ce test le transforme en décision visible.
        """
        for app, modele, actions in PERMISSIONS:
            self.assertNotIn(
                app,
                APPLICATIONS_INTERDITES,
                f"« {app}.{modele} » ouvre une application dont l'administrateur du marché "
                "n'a pas à connaître le contenu.",
            )

    def test_la_synchronisation_est_idempotente(self):
        """Elle tourne à chaque mise en ligne : elle ne doit rien empiler."""
        premier, _ = synchroniser_le_groupe()
        compte = premier.permissions.count()
        second, _ = synchroniser_le_groupe()
        self.assertEqual(second.pk, premier.pk)
        self.assertEqual(second.permissions.count(), compte)

    def test_rien_ne_se_supprime_de_ce_qui_a_une_histoire(self):
        """« On supprime ce qui n'a pas d'histoire, on retire ce qui en a une. »

        Un compte porte des ventes, une appartenance dit qui tenait la caisse le jour d'un
        écart de fonds, une boutique porte tout ce qu'elle a vendu. Aucun des trois ne
        s'efface : on les désactive.
        """
        avec_histoire = {
            ("accounts", "utilisateur"),
            ("accounts", "appartenance"),
            ("marketplace", "boutique"),
        }
        for app, modele, actions in PERMISSIONS:
            if (app, modele) in avec_histoire:
                self.assertNotIn(
                    "delete",
                    actions,
                    f"« {app}.{modele} » porte une histoire : il se retire, il ne se supprime pas.",
                )


class TroisNiveauxTest(TestCase):
    """Le superadministrateur, l'administrateur du marché, le gérant."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Boutique d'un tiers")

        self.superadmin = fabrique.creer_utilisateur("Superadministrateur")
        self.administrateur = fabrique.creer_utilisateur("Administratrice du marché")
        self.gerant = fabrique.creer_utilisateur("Gérant")

        call_command(
            "preparer_administrateur",
            superadmin="",  # posé à la main ci-dessous : la commande ne fabrique pas de superuser
            administrateur=self.administrateur.telephone,
            verbosity=0,
        )
        self.superadmin.is_superuser = True
        self.superadmin.is_staff = True
        self.superadmin.save(update_fields=["is_superuser", "is_staff"])
        self.administrateur.refresh_from_db()

    def test_le_superadministrateur_voit_tout_dans_l_administration(self):
        """Django court-circuite le contrôle pour lui : c'est le recours technique."""
        for code in codes_de_permission():
            self.assertTrue(self.superadmin.has_perm(code), code)
        # Et même celles qu'on lui a délibérément refusées ailleurs.
        self.assertTrue(self.superadmin.has_perm("accounting.view_ecriturecomptable"))

    def test_l_administrateur_du_marche_voit_ce_que_le_groupe_ouvre(self):
        self.assertTrue(self.administrateur.is_staff)
        self.assertFalse(
            self.administrateur.is_superuser,
            "is_superuser rendrait décoratifs son groupe et son rôle",
        )
        for code in codes_de_permission():
            self.assertTrue(self.administrateur.has_perm(code), code)

    def test_l_administrateur_du_marche_ne_voit_ni_comptabilite_ni_stock_ni_cahier(self):
        """La frontière, vérifiée sur les modèles précis qui comptent le plus."""
        interdits = [
            "accounting.view_ecriturecomptable",
            "accounting.view_ligneecriture",
            "inventory.view_mouvementstock",
            "inventory.view_niveaustock",
            "pos.view_ticket",
            "pos.view_clientcahier",
            "pos.view_reglementcahier",
            "catalog.view_produit",
        ]
        for code in interdits:
            self.assertFalse(
                self.administrateur.has_perm(code),
                f"{code} : l'administrateur du marché n'a pas à connaître cela.",
            )

    def test_l_administrateur_du_marche_n_a_aucun_droit_metier_sur_une_boutique(self):
        """`/admin/` lui ouvre des tables ; il ne lui ouvre aucun écran de commerçant."""
        self.assertEqual(droits_de(self.administrateur, self.boutique), frozenset())
        self.assertEqual(droits_plateforme_de(self.administrateur), TOUS_PLATEFORME)

    def test_le_superadministrateur_non_plus_n_a_pas_les_droits_metier(self):
        """Depuis l'ADR-012, un booléen n'ouvre plus la marge d'un commerçant.

        Il garde `/admin/`, qui laisse une trace dans le journal d'administration de Django —
        ce que le court-circuit `is_superuser` de `droits_de()` ne faisait pas.
        """
        self.assertEqual(droits_de(self.superadmin, self.boutique), frozenset())

    def test_le_gerant_a_tous_les_droits_chez_lui_et_aucun_ailleurs(self):
        from apps.accounts.models import Appartenance

        role, _ = Role.objects.get_or_create(
            code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
        )
        Appartenance.objects.create(
            utilisateur=self.gerant, boutique=self.boutique, role=role
        )
        autre = fabrique.creer_boutique("Une autre")

        self.assertEqual(droits_de(self.gerant, self.boutique), TOUS)
        self.assertEqual(droits_de(self.gerant, autre), frozenset())
        self.assertEqual(droits_plateforme_de(self.gerant), frozenset())


class CommandeTest(TestCase):
    def test_elle_retire_is_superuser_a_l_administrateur_du_marche(self):
        """La confusion que cette commande répare, vérifiée sur le geste qui la répare."""
        confus = fabrique.creer_utilisateur("Confus")
        confus.is_superuser = True
        confus.save(update_fields=["is_superuser"])

        call_command("preparer_administrateur", administrateur=confus.telephone, verbosity=0)

        confus.refresh_from_db()
        self.assertFalse(confus.is_superuser)
        self.assertTrue(confus.is_staff)
        self.assertTrue(
            RolePlateforme.objects.filter(utilisateur=confus, actif=True).exists()
        )

    def test_elle_refuse_le_meme_numero_pour_les_deux_casquettes(self):
        """Deux casquettes, deux comptes : sinon le journal des accès redevient ambigu."""
        fabrique.creer_boutique("Une boutique")
        personne = fabrique.creer_utilisateur("Une personne")

        call_command(
            "preparer_administrateur",
            administrateur=personne.telephone,
            commercant=personne.telephone,
            verbosity=0,
        )
        from apps.accounts.models import Appartenance

        self.assertFalse(
            Appartenance.objects.filter(utilisateur=personne).exists(),
            "le même compte a reçu les deux casquettes",
        )

    def test_elle_est_idempotente(self):
        administrateur = fabrique.creer_utilisateur("Administratrice")
        for _ in range(3):
            call_command(
                "preparer_administrateur",
                administrateur=administrateur.telephone,
                verbosity=0,
            )
        self.assertEqual(
            RolePlateforme.objects.filter(utilisateur=administrateur).count(),
            1,
            "un rôle empilé à chaque mise en ligne",
        )
        self.assertEqual(
            Permission.objects.filter(group__name=NOM_GROUPE).count(),
            len(codes_de_permission()),
        )
