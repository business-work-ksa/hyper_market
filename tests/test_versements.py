"""Versements : le dernier mètre de l'argent, là où se loge l'abus de confiance interne.

Ce que ces tests protègent :

* **aucun versement sans compte vérifié et sorti de carence** — et jamais vers
  `PortefeuilleMarchand.numero_momo`, qui n'est pas une destination ;
* **la destination est figée** à la demande : changer de compte ensuite ne déroute rien, et un
  compte retiré entre-temps bloque l'exécution ;
* l'exécution exige une **référence d'opérateur unique** et un exécutant **autre** que les
  membres de la boutique et que le vérificateur du compte ;
* un versement **s'annule, ne se supprime pas**, et l'argent revient au disponible ;
* **l'invariant** tient sur le cycle entier : paiement, libération, versement, exécution.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounting.services import solde_compte
from apps.accounts.models import Appartenance, Role
from apps.core.models import AccesPlateforme
from apps.core.tenancy import contexte_boutique
from apps.marketplace.models import CompteVersement
from apps.payments import sequestre as sequestre_service
from apps.payments import versements as service
from apps.payments.models import PortefeuilleMarchand, Versement
from tests import fabrique
from tests.test_sequestre import NET_DEUX, SocleSequestre


class SocleVersement(SocleSequestre):
    def setUp(self):
        super().setUp()
        self.gerant = fabrique.creer_utilisateur("Gérant")
        role, _ = Role.objects.get_or_create(
            code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
        )
        Appartenance.objects.create(utilisateur=self.gerant, boutique=self.ateba, role=role)
        self.verificateur = fabrique.creer_utilisateur("Vérificatrice")
        self.executant = fabrique.creer_utilisateur("Trésorier")
        call_command("preparer_administrateur", administrateur=self.executant.telephone, verbosity=0)
        self.executant.refresh_from_db()

    def compte(self, *, etat=CompteVersement.VERIFIE, utilisable_dans=timedelta(days=-1), numero="+237677000001"):
        maintenant = timezone.now()
        return CompteVersement.objects.create(
            boutique=self.ateba,
            operateur="MTN_MOMO",
            numero=numero,
            titulaire="Ateba Jeanne",
            etat=etat,
            declare_par=self.gerant,
            verifie_par=self.verificateur if etat == CompteVersement.VERIFIE else None,
            verifie_le=maintenant if etat == CompteVersement.VERIFIE else None,
            utilisable_le=maintenant + utilisable_dans if etat == CompteVersement.VERIFIE else None,
        )

    def disponible(self):
        """Une commande payée, confirmée, libérée : NET_DEUX au disponible."""
        _, part = self.payee()
        part = self.expediee(part)
        service_maintenant = timezone.now()
        sequestre_service.confirmer_par_acheteur(part, maintenant=service_maintenant)
        sequestre_service.liberer_echus(maintenant=service_maintenant + timedelta(days=30))
        self.assertEqual(self.portefeuille().solde_disponible, NET_DEUX)
        return part


class DestinationTest(SocleVersement):
    def test_refuse_sans_compte_verifie(self):
        self.disponible()
        with self.assertRaisesMessage(service.VersementRefuse, "Aucun compte de versement vérifié"):
            service.demander_versement(self.ateba, par=self.gerant)
        self.compte(etat=CompteVersement.EN_ATTENTE)
        with self.assertRaisesMessage(service.VersementRefuse, "attend sa vérification"):
            service.demander_versement(self.ateba, par=self.gerant)
        self.assertFalse(Versement.objects.exists())

    def test_refuse_pendant_la_carence(self):
        self.disponible()
        self.compte(utilisable_dans=timedelta(days=2))
        with self.assertRaisesMessage(service.VersementRefuse, "délai de carence jusqu'au"):
            service.demander_versement(self.ateba, par=self.gerant)
        self.assertEqual(self.portefeuille().solde_disponible, NET_DEUX)

    def test_le_numero_du_portefeuille_n_est_jamais_une_destination(self):
        self.disponible()
        with contexte_boutique(self.ateba):
            PortefeuilleMarchand.objects.filter(boutique=self.ateba).update(numero_momo="+237699999999")
        with self.assertRaises(service.VersementRefuse):
            service.demander_versement(self.ateba, par=self.gerant)  # pas de compte vérifié

        compte = self.compte()
        versement = service.demander_versement(self.ateba, par=self.gerant)
        self.assertEqual(versement.numero, compte.numero)
        self.assertNotEqual(versement.numero, "+237699999999")

    def test_la_destination_est_figee_a_la_demande(self):
        self.disponible()
        ancien = self.compte()
        versement = service.demander_versement(self.ateba, par=self.gerant)

        # Le compte est retiré, un autre est déclaré et vérifié : le versement n'est pas dérouté.
        CompteVersement.objects.filter(pk=ancien.pk).update(etat=CompteVersement.RETIRE)
        self.compte(numero="+237677999999")
        versement.refresh_from_db()
        self.assertEqual(versement.numero, "+237677000001")
        # Et il ne part plus vers un compte retiré : on l'annule.
        with self.assertRaisesMessage(service.VersementRefuse, "n'est plus vérifié"):
            service.executer_versement(versement, reference="MP-0001", par=self.executant)
        service.annuler_versement(versement, motif="Compte de destination retiré", par=self.executant)
        self.assertEqual(self.portefeuille().solde_disponible, NET_DEUX)
        self.verifier_l_invariant()


class CycleTest(SocleVersement):
    def test_demande_execution_et_invariant(self):
        self.disponible()
        self.compte()
        versement = service.demander_versement(self.ateba, par=self.gerant)
        self.assertEqual(versement.montant, NET_DEUX)
        self.assertEqual(self.portefeuille().solde_disponible, Decimal("0.00"))
        with self.assertRaises(service.VersementRefuse):
            service.demander_versement(self.ateba, par=self.gerant)  # rien de plus à verser
        self.verifier_l_invariant()

        with self.assertRaises(service.VersementRefuse):
            service.executer_versement(versement, reference="", par=self.executant)
        service.executer_versement(versement, reference="MP260930.0001", par=self.executant)
        versement.refresh_from_db()
        self.assertEqual(versement.etat, Versement.EXECUTE)
        self.assertEqual(versement.execute_par, self.executant)
        bilan = self.verifier_l_invariant()
        self.assertEqual(bilan["verse"], NET_DEUX)
        # La créance sur la plateforme est soldée, la trésorerie MoMo reçoit.
        self.assertEqual(solde_compte("5313", boutique_id=self.ateba.pk), Decimal("0.00"))
        self.assertEqual(solde_compte("5311", boutique_id=self.ateba.pk), NET_DEUX)

        with self.assertRaises(service.VersementRefuse):
            service.annuler_versement(versement, motif="Trop tard pour annuler", par=self.executant)
        with self.assertRaises(ValueError):
            versement.delete()

    def test_une_reference_ne_justifie_qu_un_versement(self):
        self.compte()
        for _ in range(2):
            self.disponible()
            versement = service.demander_versement(self.ateba, par=self.gerant)
            try:
                service.executer_versement(versement, reference="MP-DOUBLON", par=self.executant)
            except service.VersementRefuse as refus:
                self.assertIn("déjà un autre versement", str(refus))
        self.assertEqual(Versement.objects.filter(etat=Versement.EXECUTE).count(), 1)
        self.verifier_l_invariant()

    def test_quatre_yeux(self):
        self.disponible()
        self.compte()
        versement = service.demander_versement(self.ateba, par=self.gerant)
        with self.assertRaisesMessage(service.VersementRefuse, "membre de cette boutique"):
            service.executer_versement(versement, reference="MP-0002", par=self.gerant)
        with self.assertRaisesMessage(service.VersementRefuse, "vérifié le compte"):
            service.executer_versement(versement, reference="MP-0002", par=self.verificateur)

    def test_l_annulation_rend_au_disponible(self):
        self.disponible()
        self.compte()
        versement = service.demander_versement(self.ateba, par=self.gerant)
        with self.assertRaises(service.VersementRefuse):
            service.annuler_versement(versement, motif="non", par=self.executant)
        service.annuler_versement(versement, motif="Titulaire à revérifier", par=self.executant)
        self.assertEqual(self.portefeuille().solde_disponible, NET_DEUX)
        self.verifier_l_invariant()


class EcransTest(SocleVersement):
    def test_le_gerant_demande_depuis_son_ecran(self):
        self.disponible()
        self.compte()
        self.client.force_login(self.gerant)
        url = reverse("versements_marchand")
        self.assertContains(self.client.get(url), "Demander le versement")
        self.client.post(url)
        self.assertEqual(Versement.objects.filter(boutique=self.ateba).count(), 1)

    def test_la_console_execute_et_trace(self):
        self.disponible()
        self.compte()
        versement = service.demander_versement(self.ateba, par=self.gerant)
        self.client.force_login(self.executant)
        self.assertEqual(self.client.get(reverse("plateforme:versements")).status_code, 302)
        self.client.post(reverse("plateforme:suivi_ouvrir"), {"motif": "commission"})
        self.assertContains(self.client.get(reverse("plateforme:versements")), "Ateba")
        self.assertContains(self.client.get(reverse("plateforme:versement", args=[versement.pk])), "+237677000001")

        self.client.post(
            reverse("plateforme:versement", args=[versement.pk]),
            {"action": "executer", "reference": "MP260930.4242"},
        )
        versement.refresh_from_db()
        self.assertEqual(versement.etat, Versement.EXECUTE)
        self.assertTrue(
            AccesPlateforme.objects.filter(
                utilisateur=self.executant, motif__contains="MP260930.4242"
            ).exists()
        )

    def test_un_commercant_n_entre_pas_dans_la_console_des_versements(self):
        self.client.force_login(self.gerant)
        self.assertEqual(self.client.get(reverse("plateforme:versements")).status_code, 403)
