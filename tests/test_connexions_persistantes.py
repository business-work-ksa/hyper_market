"""Une connexion réutilisée ne doit pas transporter le tenant de la requête d'avant.

`CONN_MAX_AGE` garde une connexion PostgreSQL ouverte d'une requête à l'autre.
C'est ce qui rend une base distante utilisable — sans cela, chaque requête paie
une poignée de main TCP puis TLS, et un écran de stock derrière une liaison
transatlantique passe de quelques dizaines de millisecondes à plusieurs
secondes.

Mais cette réutilisation touche directement la barrière 3. Le contexte de
boutique est posé par `set_config(..., false)` : le troisième argument dit
**non local à la transaction**, donc le réglage vit aussi longtemps que la
session. Sur une connexion neuve à chaque requête, cela n'a aucune
conséquence — la session meurt avec la requête. Sur une connexion réutilisée,
un réglage laissé derrière serait hérité par la requête suivante, servie à
quelqu'un d'autre.

Ce serait la pire fuite possible du système : pas un contournement, pas une
requête mal filtrée, mais deux commerçants qui se lisent l'un l'autre parce
qu'une connexion a été recyclée. Rien ne planterait, et les trois barrières
diraient toutes que tout va bien.

Le middleware restaure le contexte dans un `finally`, et son commentaire
annonce déjà ce cas. Ces tests vérifient que c'est vrai, parce qu'un
commentaire ne s'exécute pas.
"""

import pathlib

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Appartenance, Role
from apps.core.rls import NOM_REGLAGE
from apps.core.tenancy import contexte_boutique
from tests import fabrique

MOT_DE_PASSE = "motdepasse-solide"
RACINE = pathlib.Path(__file__).resolve().parent.parent


def rattacher(utilisateur, boutique, code_role=Role.GERANT) -> None:
    role, _ = Role.objects.get_or_create(
        code=code_role, defaults={"libelle": code_role.title(), "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


def reglage_de_session():
    """Ce que la connexion **courante** porte comme contexte de boutique.

    Lu dans PostgreSQL et non dans le `ContextVar` de Python : c'est la valeur
    que verront les politiques RLS, et c'est elle qui survit à une requête si
    personne ne la remet.
    """
    with connection.cursor() as curseur:
        curseur.execute("SELECT current_setting(%s, true)", [NOM_REGLAGE])
        return curseur.fetchone()[0]


class ContexteSurConnexionPersistanteTest(TestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Le réglage de session est spécifique à PostgreSQL.")

        self.une = fabrique.creer_boutique("Quincaillerie Ateba")
        self.autre = fabrique.creer_boutique("Pharmacie du Wouri")

        self.gerant = fabrique.creer_utilisateur("Gérant")
        self.gerant.set_password(MOT_DE_PASSE)
        self.gerant.save()
        rattacher(self.gerant, self.une)

    def connecter(self, boutique):
        self.client.login(telephone=self.gerant.telephone, password=MOT_DE_PASSE)
        session = self.client.session
        session["boutique_id"] = str(boutique.pk)
        session.save()

    def test_une_requete_ne_laisse_pas_son_tenant_derriere_elle(self):
        """Le cœur du sujet : après la requête, la connexion doit être neutre."""
        self.connecter(self.une)
        self.client.get(reverse("stock"))

        self.assertNotIn(
            str(self.une.pk),
            reglage_de_session() or "",
            "la connexion porte encore la boutique de la requête précédente",
        )

    def test_le_contexte_est_bien_pose_pendant_la_requete(self):
        """Le test précédent ne vaut que si le réglage est réellement posé.

        Sans celui-ci, une implémentation qui ne poserait jamais rien passerait
        le premier test avec les honneurs.
        """
        with contexte_boutique(self.une):
            self.assertEqual(reglage_de_session(), str(self.une.pk))

    def test_deux_contextes_successifs_ne_se_melangent_pas(self):
        with contexte_boutique(self.une):
            self.assertEqual(reglage_de_session(), str(self.une.pk))
        with contexte_boutique(self.autre):
            self.assertEqual(reglage_de_session(), str(self.autre.pk))
        self.assertNotEqual(reglage_de_session(), str(self.autre.pk))

    def test_un_contexte_imbrique_restaure_celui_du_dessus(self):
        """Une tâche de fond ouvre parfois un contexte dans un autre.

        Si la sortie remettait « rien » au lieu du contexte englobant, la suite
        du traitement extérieur ne verrait plus ses propres données — panne
        silencieuse, et bien plus difficile à lire qu'une erreur.
        """
        with contexte_boutique(self.une):
            with contexte_boutique(self.autre):
                self.assertEqual(reglage_de_session(), str(self.autre.pk))
            self.assertEqual(reglage_de_session(), str(self.une.pk))

    def test_une_requete_anonyme_ne_recupere_pas_le_tenant_du_precedent(self):
        """Le scénario complet, celui qui justifie tout ce fichier.

        Une requête authentifiée, puis une requête sans compte sur la **même
        connexion**. La seconde ne doit rien voir.
        """
        self.connecter(self.une)
        self.client.get(reverse("stock"))

        self.client.logout()
        self.client.get(reverse("connexion"))

        self.assertNotIn(str(self.une.pk), reglage_de_session() or "")


class SecoursTest(TestCase):
    """`DATABASE_URL_SECOURS` l'emporte, et c'est une porte de sortie payée cher.

    Chez un hébergeur qui compose `DATABASE_URL` depuis son propre fichier de
    déploiement, cette valeur n'est rafraîchie qu'à la resynchronisation de ce
    fichier — pas à un redéploiement. Le service continue alors de viser une
    base injoignable, et aucune modification du dépôt n'y change rien. Ajouter
    une variable, en revanche, n'est jamais verrouillé.

    Éprouvé dans un interpréteur séparé : la précédence se joue au chargement du
    module de réglages, et `override_settings` arrive trop tard pour la voir.
    """

    def hote_obtenu(self, **variables):
        import os
        import subprocess
        import sys

        code = (
            "import django, os; "
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); "
            "django.setup(); "
            "from django.db import connection; "
            "print(connection.settings_dict['HOST'])"
        )
        milieu = {**os.environ, **variables}
        # Le `.env` du poste de travail contient parfois une autre base : on
        # neutralise ce qui n'est pas explicitement demandé par le test.
        milieu.pop("DATABASE_URL_SECOURS", None)
        milieu.update(variables)
        sortie = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(RACINE), env=milieu, capture_output=True, text=True, timeout=90,
        )
        return sortie.stdout.strip().splitlines()[-1] if sortie.stdout.strip() else ""

    def test_sans_secours_c_est_database_url_qui_decide(self):
        hote = self.hote_obtenu(
            DATABASE_URL="postgres://u:p@hote-attendu.example:5432/base"
        )
        self.assertEqual(hote, "hote-attendu.example")

    def test_le_secours_supplante_database_url(self):
        hote = self.hote_obtenu(
            DATABASE_URL="postgres://u:p@hote-impose-par-l-hebergeur:5432/base",
            DATABASE_URL_SECOURS="postgres://u:p@hote-choisi.example:5432/base",
        )
        self.assertEqual(hote, "hote-choisi.example")


class ReglageTest(TestCase):
    def test_les_connexions_sont_persistantes_sur_postgresql(self):
        """Sinon tout ce fichier vérifie une précaution sans objet.

        Et si quelqu'un remet `CONN_MAX_AGE` à zéro un jour, ce test le dira —
        ce n'est pas forcément une erreur, mais c'est une décision.
        """
        from django.conf import settings

        if connection.vendor != "postgresql":
            self.skipTest("Le repli SQLite ne configure pas de connexion persistante.")
        self.assertGreater(settings.DATABASES["default"].get("CONN_MAX_AGE", 0), 0)

    def test_les_connexions_reutilisees_sont_verifiees_avant_usage(self):
        """Une connexion gardée dix minutes peut avoir été coupée entre-temps.

        Sans ce contrôle, la requête suivante échoue une fois sur une erreur
        sans rapport avec elle — et sur une liaison longue distance, ces
        coupures sont la règle.
        """
        from django.conf import settings

        if connection.vendor != "postgresql":
            self.skipTest("Sans objet hors PostgreSQL.")
        self.assertTrue(settings.DATABASES["default"].get("CONN_HEALTH_CHECKS"))
