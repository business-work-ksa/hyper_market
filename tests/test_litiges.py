"""Litiges : l'acheteur conteste, l'argent gèle, la plateforme tranche — motivé, tracé.

Ce que ces tests protègent :

* un litige **gèle** la part : ni libération échue, ni code, ni refus du marchand ne la débloque ;
* les **trois décisions** mènent l'argent où elles disent, et l'invariant tient après chacune ;
* le marchand ne voit qu'un **message neutre** — jamais le mot « litige » (LBC/FT) ;
* la **vitrine** n'offre code, confirmation et réclamation qu'à la session de l'acheteur ;
* la **console** refuse un compte sans droit, exige un motif de suivi, et journalise la décision.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Appartenance, Role
from apps.affiliation.models import Attribution, Commission
from apps.affiliation.services import attribuer, creer_apporteur
from apps.core.models import AccesPlateforme
from apps.core.tenancy import contexte_boutique
from apps.orders.models import Litige
from apps.orders.services import CommandeInvalide, annuler_sous_commande
from apps.payments import sequestre as service
from apps.payments.models import Sequestre
from apps.vitrine.views import CLE_COMMANDES
from tests import fabrique
from tests.test_sequestre import NET_DEUX, SocleSequestre


class SocleLitige(SocleSequestre):
    def ouvrir(self, part, motif=Litige.NON_RECUE):
        return service.ouvrir_litige(
            part, motif=motif, description="Rien reçu, le livreur ne répond plus."
        )

    def administrateur(self):
        admin = fabrique.creer_utilisateur("Médiatrice")
        call_command("preparer_administrateur", administrateur=admin.telephone, verbosity=0)
        admin.refresh_from_db()
        return admin


class GelTest(SocleLitige):
    def test_un_litige_gele_la_part(self):
        _, part = self.payee()
        part = self.expediee(part)
        maintenant = timezone.now()
        self.ouvrir(part)

        # Ni la confirmation implicite, ni la libération échue ne passent.
        service.liberer_echus(maintenant=maintenant + timedelta(days=60))
        self.assertEqual(self.sequestre(part).etat, Sequestre.BLOQUE)
        with self.assertRaisesMessage(service.SequestreRefuse, service.MESSAGE_GEL):
            service.confirmer_par_code(part, service.code_de_remise(part))
        with self.assertRaisesMessage(service.SequestreRefuse, service.MESSAGE_GEL):
            service.liberer(self.sequestre(part), maintenant=maintenant + timedelta(days=60))
        self.verifier_l_invariant()

    def test_le_marchand_ne_peut_pas_clore_le_dossier_en_refusant(self):
        _, part = self.payee()
        self.ouvrir(part)
        with self.assertRaisesMessage(CommandeInvalide, service.MESSAGE_GEL):
            annuler_sous_commande(part, motif="Je rembourse moi-même")

    def test_un_seul_litige_en_cours_par_part(self):
        _, part = self.payee()
        premier = self.ouvrir(part)
        second = self.ouvrir(part, motif=Litige.NON_CONFORME)
        self.assertEqual(premier.pk, second.pk)

    def test_pas_de_litige_sur_une_part_liberee(self):
        _, part = self.payee()
        part = self.expediee(part)
        service.confirmer_par_acheteur(part)
        service.liberer_echus(maintenant=timezone.now() + timedelta(days=30))
        with self.assertRaises(service.SequestreRefuse):
            self.ouvrir(part)


class DecisionsTest(SocleLitige):
    def setUp(self):
        super().setUp()
        self.mediatrice = self.administrateur()
        self.motivation = "Photos et échanges consultés ; le livreur confirme la remise au voisin."

    def test_en_faveur_du_marchand_la_part_est_liberee(self):
        _, part = self.payee()
        litige = self.ouvrir(part)
        service.trancher_litige(
            litige, decision=service.EN_FAVEUR_DU_MARCHAND, motivation=self.motivation, par=self.mediatrice
        )

        with contexte_boutique(self.ateba):
            litige.refresh_from_db()
        self.assertEqual(litige.etat, Litige.TRANCHE_MARCHAND)
        self.assertEqual(litige.tranche_par, self.mediatrice)
        self.assertEqual(self.sequestre(part).etat, Sequestre.LIBERE)
        self.assertEqual(self.portefeuille().solde_disponible, NET_DEUX)
        self.verifier_l_invariant()

    def test_en_faveur_de_l_acheteur_remboursement_total_et_commissions_annulees(self):
        awa = creer_apporteur(fabrique.creer_utilisateur("Awa"))
        attribuer(
            apporteur=awa,
            cible_type=Attribution.ACHETEUR,
            cible_id=self.acheteur.pk,
            origine=Attribution.CODE,
        )
        _, part = self.payee()
        self.assertTrue(Commission.objects.filter(sous_commande=part).exists())
        litige = self.ouvrir(part)
        service.trancher_litige(
            litige, decision=service.EN_FAVEUR_DE_L_ACHETEUR, motivation=self.motivation, par=self.mediatrice
        )

        sequestre = self.sequestre(part)
        self.assertEqual(sequestre.etat, Sequestre.REMBOURSE)
        self.assertEqual(sequestre.rembourse_acheteur, Decimal("23850.00"))
        self.assertEqual(self.portefeuille().solde_bloque, Decimal("0.00"))
        self.assertEqual(self.portefeuille().solde_disponible, Decimal("0.00"))
        etats = set(Commission.objects.filter(sous_commande=part).values_list("etat", flat=True))
        self.assertEqual(etats, {Commission.ANNULEE})
        with contexte_boutique(self.ateba):
            litige.refresh_from_db()
        self.assertIn(litige.etat, Litige.PERDUS_PAR_LE_MARCHAND)
        self.verifier_l_invariant()

    def test_decision_partielle(self):
        _, part = self.payee()
        litige = self.ouvrir(part, motif=Litige.INCOMPLETE)
        service.trancher_litige(
            litige,
            decision=service.PARTIELLE,
            motivation=self.motivation,
            par=self.mediatrice,
            montant="5000",
        )

        sequestre = self.sequestre(part)
        self.assertEqual(sequestre.etat, Sequestre.PARTAGE)
        self.assertEqual(sequestre.rembourse_acheteur, Decimal("5000.00"))
        self.assertEqual(self.portefeuille().solde_disponible, NET_DEUX - Decimal("5000"))
        with contexte_boutique(self.ateba):
            litige.refresh_from_db()
        self.assertEqual(litige.etat, Litige.PARTAGE)
        self.assertEqual(litige.montant_rembourse, Decimal("5000.00"))
        self.verifier_l_invariant()

    def test_une_decision_se_motive_et_ne_se_rend_qu_une_fois(self):
        _, part = self.payee()
        litige = self.ouvrir(part)
        with self.assertRaises(service.SequestreRefuse):
            service.trancher_litige(
                litige, decision=service.EN_FAVEUR_DU_MARCHAND, motivation="ok", par=self.mediatrice
            )
        service.trancher_litige(
            litige, decision=service.EN_FAVEUR_DU_MARCHAND, motivation=self.motivation, par=self.mediatrice
        )
        with self.assertRaises(service.SequestreRefuse):
            service.trancher_litige(
                litige, decision=service.EN_FAVEUR_DE_L_ACHETEUR, motivation=self.motivation, par=self.mediatrice
            )
        self.verifier_l_invariant()

    def test_un_partiel_ne_rend_pas_plus_que_la_part_du_marchand(self):
        _, part = self.payee()
        litige = self.ouvrir(part)
        with self.assertRaises(service.SequestreRefuse):
            service.trancher_litige(
                litige, decision=service.PARTIELLE, motivation=self.motivation,
                par=self.mediatrice, montant=str(NET_DEUX),
            )
        self.assertEqual(self.sequestre(part).etat, Sequestre.BLOQUE)


class VitrineTest(SocleLitige):
    def acheteur_reconnu(self, commande):
        session = self.client.session
        session[CLE_COMMANDES] = [str(commande.pk)]
        session.save()

    def test_le_code_n_est_montre_qu_a_la_session_de_l_acheteur(self):
        commande, part = self.payee()
        code = service.code_de_remise(part)
        url = reverse("vitrine_commande", args=[commande.pk])

        self.assertNotContains(self.client.get(url), code)
        self.acheteur_reconnu(commande)
        self.assertContains(self.client.get(url), code)

    def test_seul_l_acheteur_ouvre_un_litige(self):
        commande, part = self.payee()
        url = reverse("vitrine_litige", args=[commande.pk, part.pk])
        donnees = {"motif": Litige.NON_RECUE, "description": "Rien reçu après dix jours d'attente."}

        self.assertEqual(self.client.post(url, donnees).status_code, 404)
        self.acheteur_reconnu(commande)
        self.assertEqual(self.client.post(url, donnees).status_code, 302)
        with contexte_boutique(self.ateba):
            self.assertEqual(Litige.objects.filter(sous_commande=part).count(), 1)

    def test_l_acheteur_confirme_la_reception(self):
        commande, part = self.payee()
        part = self.expediee(part)
        url = reverse("vitrine_confirmer_reception", args=[commande.pk, part.pk])
        self.assertEqual(self.client.post(url).status_code, 404, "le marchand connaît l'adresse")
        self.acheteur_reconnu(commande)
        self.client.post(url)
        self.recharger(part)
        self.assertIsNotNone(part.livraison_confirmee_le)


class EcranMarchandTest(SocleLitige):
    def test_le_marchand_ne_voit_qu_un_message_neutre(self):
        gerant = fabrique.creer_utilisateur("Gérant")
        role, _ = Role.objects.get_or_create(
            code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
        )
        Appartenance.objects.create(utilisateur=gerant, boutique=self.ateba, role=role)
        _, part = self.payee()
        self.ouvrir(part)
        self.client.force_login(gerant)

        for url in (reverse("commande", args=[part.pk]), reverse("commandes")):
            reponse = self.client.get(url)
            self.assertContains(reponse, "Fonds retenus en attente")
            self.assertNotContains(reponse, "litige")
            self.assertNotContains(reponse, "Litige")


class ConsoleTest(SocleLitige):
    def setUp(self):
        super().setUp()
        _, self.part = self.payee()
        self.litige = self.ouvrir(self.part)

    def test_un_commercant_est_refuse(self):
        commercant = fabrique.creer_utilisateur("Commerçant")
        self.client.force_login(commercant)
        for url in (
            reverse("plateforme:litiges"),
            reverse("plateforme:litige", args=[self.litige.pk]),
            reverse("plateforme:versements"),
        ):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_sans_motif_de_suivi_la_console_le_demande(self):
        self.client.force_login(self.administrateur())
        reponse = self.client.get(reverse("plateforme:litiges"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("plateforme:suivi_ouvrir"), reponse["Location"])

    def test_la_fiche_est_journalisee_et_la_decision_tracee(self):
        admin = self.administrateur()
        self.client.force_login(admin)
        self.client.post(reverse("plateforme:suivi_ouvrir"), {"motif": "litige"})

        avant = AccesPlateforme.objects.count()
        self.assertContains(self.client.get(reverse("plateforme:litiges")), self.part.commande.numero)
        self.assertContains(
            self.client.get(reverse("plateforme:litige", args=[self.litige.pk])), "Rien reçu"
        )
        self.assertEqual(AccesPlateforme.objects.count(), avant + 2)

        motivation = "Le marchand ne produit aucune preuve de remise ; l'acheteur est remboursé."
        self.client.post(
            reverse("plateforme:litige", args=[self.litige.pk]),
            {"action": "trancher", "decision": service.EN_FAVEUR_DE_L_ACHETEUR, "motivation": motivation},
        )
        self.assertEqual(self.sequestre(self.part).etat, Sequestre.REMBOURSE)
        self.assertTrue(AccesPlateforme.objects.filter(utilisateur=admin, motif__contains=motivation[:40]).exists())
        self.verifier_l_invariant()
