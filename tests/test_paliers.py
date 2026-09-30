"""Les paliers de confiance, et la confiance montrée aux acheteurs.

Ce qui est défendu ici :

* seules les livraisons **confirmées** comptent, et seulement auprès d'acheteurs distincts et sans
  lien avec la boutique — sinon un palier s'achète ;
* on monte d'**un** palier par évaluation, pas avant la fin de la fenêtre de litige, et relancer
  l'évaluation le même jour ne change rien ;
* on descend **tout de suite** quand les litiges perdus dépassent le plafond du palier courant ;
* une boutique suspendue est au palier 0 ;
* la vitrine ne dit « Identité vérifiée » que si c'est vrai, et ne coûte pas une requête par carte.
"""

from datetime import timedelta

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Appartenance, DossierKyc, Role, Utilisateur
from apps.confiance.models import ChangementPalier, MesureConfiance, SignalRisque
from apps.confiance.paliers import evaluer_paliers, mesurer_une
from apps.core.tenancy import contexte_boutique
from apps.marketplace.models import Bail, Boutique
from apps.orders.models import Commande, Litige, SousCommande
from tests import fabrique

_n = {"i": 0}


def vieillir(boutique, jours):
    """La boutique a été créée et activée il y a `jours` jours."""
    passe = timezone.now() - timedelta(days=jours)
    Boutique.objects.filter(pk=boutique.pk).update(cree_le=passe)
    Bail.objects.filter(boutique=boutique).update(debut=passe.date())
    boutique.refresh_from_db()
    return boutique


def acheteurs(nombre):
    base = _n["i"]
    _n["i"] += nombre
    return Utilisateur.objects.bulk_create(
        [Utilisateur(telephone=f"+2376955{base + i:05d}", nom_complet=f"Acheteur {base + i}") for i in range(nombre)]
    )


def sous_commandes(boutique, clients, nombre, *, confirmee=True, declaree=True, **champs):
    """`nombre` sous-commandes livrées, réparties sur `clients` en tourniquet."""
    maintenant = timezone.now()
    commandes = Commande.objects.bulk_create(
        [
            Commande(numero=f"T-{_n['i'] + i:07d}", acheteur=clients[i % len(clients)], etat=Commande.LIVREE)
            for i in range(nombre)
        ]
    )
    _n["i"] += nombre
    with contexte_boutique(boutique):
        return SousCommande.objects.bulk_create(
            [
                SousCommande(
                    boutique=boutique,
                    commande=c,
                    etat=SousCommande.LIVREE,
                    livree_le=maintenant if declaree else None,
                    livraison_confirmee_le=maintenant if confirmee else None,
                    **champs,
                )
                for c in commandes
            ]
        )


def litiges_perdus(boutique, parts, etat=Litige.TRANCHE_ACHETEUR):
    with contexte_boutique(boutique):
        for sc in parts:
            Litige.objects.create(
                boutique=boutique, sous_commande=sc, motif=Litige.NON_RECUE, description="Rien reçu", etat=etat
            )


class LivraisonsQuiComptentTest(TestCase):
    def setUp(self):
        self.boutique = vieillir(fabrique.creer_boutique("Chez Mballa"), 60)

    def test_une_livraison_declaree_mais_pas_confirmee_ne_compte_pas(self):
        sous_commandes(self.boutique, acheteurs(15), 15, confirmee=False)
        self.assertEqual(mesurer_une(self.boutique).livraisons_confirmees, 0)
        evaluer_paliers()
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.palier_confiance, 0)

    def test_des_auto_commandes_depuis_deux_acheteurs_ne_font_pas_monter(self):
        sous_commandes(self.boutique, acheteurs(2), 30)
        mesure = mesurer_une(self.boutique)
        self.assertEqual((mesure.livraisons_confirmees, mesure.acheteurs_distincts), (30, 2))
        evaluer_paliers()
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.palier_confiance, 0)
        self.assertFalse(ChangementPalier.objects.exists())

    def test_les_commandes_de_la_maison_ne_comptent_pas(self):
        gerant = fabrique.creer_utilisateur("Gérant")
        role, _ = Role.objects.get_or_create(code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE})
        Appartenance.objects.create(utilisateur=gerant, boutique=self.boutique, role=role)
        sous_commandes(self.boutique, [gerant], 12)
        self.assertEqual(mesurer_une(self.boutique).livraisons_confirmees, 0)


class MonteeEtDescenteTest(TestCase):
    def setUp(self):
        self.boutique = vieillir(fabrique.creer_boutique("Quincaillerie Ndoumbé"), 200)

    def test_on_monte_d_un_seul_palier_et_l_evaluation_est_idempotente(self):
        sous_commandes(self.boutique, acheteurs(130), 220)
        maintenant = timezone.now()

        evaluer_paliers(maintenant=maintenant)
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.palier_confiance, 1, "les chiffres justifient 3, on monte d'un cran")
        changement = ChangementPalier.objects.get()
        self.assertEqual((changement.ancien, changement.nouveau), (0, 1))
        self.assertTrue(any("un palier à la fois" in r for r in changement.raisons))

        evaluer_paliers(maintenant=maintenant)
        evaluer_paliers(maintenant=maintenant + timedelta(days=2))
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.palier_confiance, 1, "fenêtre de litige du palier 1 : 5 jours")
        self.assertEqual(ChangementPalier.objects.count(), 1)

        evaluer_paliers(maintenant=maintenant + timedelta(days=6))
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.palier_confiance, 2)
        self.assertEqual(MesureConfiance.objects.get(boutique=self.boutique).livraisons_confirmees, 220)

    def test_la_retrogradation_est_immediate(self):
        parts = sous_commandes(self.boutique, acheteurs(40), 60)
        Boutique.objects.filter(pk=self.boutique.pk).update(palier_confiance=2)
        evaluer_paliers()  # rien à redire : 0 % de litiges perdus
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.palier_confiance, 2)

        litiges_perdus(self.boutique, parts[:5])  # 5 / 60 ≈ 8 % > 5 % du palier 2
        evaluer_paliers()  # le même jour : la descente n'attend aucune fenêtre
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.palier_confiance, 1)
        descente = ChangementPalier.objects.get(nouveau=1)
        self.assertIn("Rétrogradation immédiate", descente.raisons[0])

    def test_un_litige_tranche_pour_le_marchand_ne_compte_pas(self):
        parts = sous_commandes(self.boutique, acheteurs(40), 60)
        litiges_perdus(self.boutique, parts[:10], etat=Litige.TRANCHE_MARCHAND)
        self.assertEqual(mesurer_une(self.boutique).taux_litiges_perdus, 0)

    def test_une_boutique_suspendue_reste_au_palier_0(self):
        sous_commandes(self.boutique, acheteurs(130), 220)
        Boutique.objects.filter(pk=self.boutique.pk).update(etat=Boutique.SUSPENDUE, palier_confiance=2)
        evaluer_paliers(maintenant=timezone.now() + timedelta(days=30))
        self.boutique.refresh_from_db()
        self.assertEqual(self.boutique.palier_confiance, 0)
        self.assertIn("suspendue", ChangementPalier.objects.get().raisons[0])

    def test_le_journal_des_paliers_est_en_ajout_seul(self):
        sous_commandes(self.boutique, acheteurs(10), 12)
        evaluer_paliers()
        changement = ChangementPalier.objects.get()
        with self.assertRaises(ValueError):
            changement.save()
        with self.assertRaises(ValueError):
            changement.delete()


class CommandeDeNuitTest(TestCase):
    def test_la_commande_est_idempotente_et_ne_suspend_rien(self):
        a = vieillir(fabrique.creer_boutique("Alpha"), 120)
        b = fabrique.creer_boutique("Bêta")
        Boutique.objects.filter(pk__in=[a.pk, b.pk]).update(telephone="+237699123456")
        sous_commandes(a, acheteurs(12), 12)

        call_command("evaluer_confiance", verbosity=0)
        etat = (
            ChangementPalier.objects.count(),
            SignalRisque.objects.count(),
            list(Boutique.objects.order_by("pk").values_list("palier_confiance", "etat")),
        )
        call_command("evaluer_confiance", verbosity=0)
        self.assertEqual(
            etat,
            (
                ChangementPalier.objects.count(),
                SignalRisque.objects.count(),
                list(Boutique.objects.order_by("pk").values_list("palier_confiance", "etat")),
            ),
        )
        self.assertTrue(SignalRisque.objects.exists())
        self.assertEqual(set(Boutique.objects.values_list("etat", flat=True)), {Boutique.ACTIVE})


class ConfiancePubliqueTest(TestCase):
    """La vitrine : des faits vérifiables, et seulement s'ils sont vrais."""

    def setUp(self):
        self.boutique = vieillir(fabrique.creer_boutique("Mama Ngono"), 45)
        fabrique.creer_variante(self.boutique, prix="4500", libelle="Savon de Marseille")
        self.gerant = fabrique.creer_utilisateur("Ngono Marie")
        role, _ = Role.objects.get_or_create(code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE})
        Appartenance.objects.create(utilisateur=self.gerant, boutique=self.boutique, role=role)
        self.url = reverse("vitrine_boutique", args=[self.boutique.slug])

    def _piece(self, etat):
        champs = {f.name for f in DossierKyc._meta.get_fields()}
        numero = (
            {"numero_empreinte": "e" * 64, "numero_fin": "3445"} if "numero_empreinte" in champs else {"numero": "112233445"}
        )
        return DossierKyc.objects.create(
            utilisateur=self.gerant, boutique=self.boutique, type_piece=DossierKyc.CNI, etat=etat, **numero
        )

    def test_identite_verifiee_absente_tant_que_ce_n_est_pas_vrai(self):
        self.assertNotContains(self.client.get(self.url), "Identité vérifiée")
        self._piece(DossierKyc.EN_ATTENTE)
        self.assertNotContains(self.client.get(self.url), "Identité vérifiée")
        self._piece(DossierKyc.REJETE)
        self.assertNotContains(self.client.get(self.url), "Identité vérifiée")

    def test_identite_verifiee_affichee_quand_elle_l_est(self):
        self._piece(DossierKyc.VALIDE)
        self.assertContains(self.client.get(self.url), "Identité vérifiée")
        self.assertContains(self.client.get(reverse("vitrine_catalogue")), "Identité vérifiée")

    def test_un_second_gerant_non_verifie_retire_la_mention(self):
        self._piece(DossierKyc.VALIDE)
        associe = fabrique.creer_utilisateur("Associé")
        Appartenance.objects.create(utilisateur=associe, boutique=self.boutique, role_id=Role.GERANT)
        self.assertNotContains(self.client.get(self.url), "Identité vérifiée")

    def test_des_faits_et_la_promesse_du_sequestre(self):
        sous_commandes(self.boutique, acheteurs(12), 12)
        evaluer_paliers()
        reponse = self.client.get(self.url)
        self.assertContains(reponse, "Sur HyperMarché depuis")
        self.assertContains(reponse, "12 livraisons confirmées")
        self.assertContains(reponse, "Aucun litige perdu")
        self.assertContains(reponse, "séquestre")
        self.assertContains(reponse, "numéro personnel")

    def test_la_vitrine_ne_coute_pas_une_requete_par_carte(self):
        """Le nombre de requêtes d'une page de catalogue ne dépend ni du nombre d'articles ni du
        nombre de boutiques."""
        evaluer_paliers()
        with CaptureQueriesContext(connection) as avant:
            self.client.get(reverse("vitrine_catalogue"))
        for i in range(3):
            autre = fabrique.creer_boutique(f"Autre {i}")
            for j in range(4):
                fabrique.creer_variante(autre, prix="1000", libelle=f"Article {i}-{j}")
        evaluer_paliers()
        with self.assertNumQueries(len(avant)):
            reponse = self.client.get(reverse("vitrine_catalogue"))
        self.assertContains(reponse, "Article 2-3")
        with CaptureQueriesContext(connection) as page_boutique:
            self.client.get(self.url)
        for j in range(6):
            fabrique.creer_variante(self.boutique, prix="900", libelle=f"Encore {j}")
        with self.assertNumQueries(len(page_boutique)):
            self.client.get(self.url)
