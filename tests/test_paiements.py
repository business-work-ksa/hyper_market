"""Routage, idempotence et transitions d'état d'un paiement.

Ce que ces tests protègent est simple à énoncer et coûteux à rater : **on ne
débite jamais deux fois, et on ne fait jamais reculer une transaction tranchée.**
Sur ce marché, un double débit Mobile Money coûte l'argent du client et la
réputation du commerçant — dans cet ordre.

Ils n'attaquent aucun opérateur réel. Les appels HTTP vers MTN, Orange et Camtel
ne sont pas écrits : ils le seront contre un bac à sable, jamais à l'aveugle. Ce
qui est testé ici est tout ce qui reste vrai quels que soient ces appels.
"""

from decimal import Decimal

from django.test import TestCase

from apps.core.tenancy import contexte_boutique
from apps.payments.adaptateurs import (
    Disjoncteur,
    FauxPrestataire,
    PrestataireNonConfigure,
    adaptateur_pour,
    disjoncteur,
)
from apps.payments.models import MouvementPortefeuille, Prestataire, Transaction
from apps.payments.services import (
    AucunPrestataireDisponible,
    TransitionInterdite,
    appliquer_statut,
    choisir_prestataire,
    crediter_portefeuille,
    initier_encaissement,
    normaliser_numero,
)
from tests import fabrique


def creer_prestataires():
    Prestataire.objects.update_or_create(
        code=Prestataire.MTN_MOMO,
        defaults={
            "libelle": "MTN Mobile Money",
            "taux_frais": Decimal("0.0160"),
            "prefixes_numero": ["67", "650", "651"],
        },
    )
    Prestataire.objects.update_or_create(
        code=Prestataire.ORANGE_MONEY,
        defaults={
            "libelle": "Orange Money",
            "taux_frais": Decimal("0.0160"),
            "prefixes_numero": ["69", "655"],
        },
    )
    Prestataire.objects.update_or_create(
        code=Prestataire.CARTE,
        defaults={
            "libelle": "Carte bancaire",
            "taux_frais": Decimal("0.0280"),
            "prefixes_numero": [],
        },
    )


class NormalisationDuNumeroTest(TestCase):
    def test_les_quatre_facons_d_ecrire_un_numero_se_ramenent_a_une(self):
        """Le routage compare des préfixes : il lui faut une forme unique."""
        for saisi in ("+237 6 99 11 00 11", "00237699110011", "699110011", "237699110011"):
            with self.subTest(saisi=saisi):
                self.assertEqual(normaliser_numero(saisi), "699110011")

    def test_un_numero_vide_ne_plante_pas(self):
        self.assertEqual(normaliser_numero(""), "")
        self.assertEqual(normaliser_numero(None), "")


class RoutageTest(TestCase):
    def setUp(self):
        creer_prestataires()
        disjoncteur.reinitialiser()
        self.addCleanup(disjoncteur.reinitialiser)

    def test_le_numero_decide_de_l_operateur(self):
        self.assertEqual(choisir_prestataire("+237677220022").code, Prestataire.MTN_MOMO)
        self.assertEqual(choisir_prestataire("+237699110011").code, Prestataire.ORANGE_MONEY)

    def test_le_prefixe_le_plus_long_l_emporte(self):
        """« 650 » appartient à MTN alors que « 65 » ne dit rien : l'ordre compte."""
        self.assertEqual(choisir_prestataire("+237650112233").code, Prestataire.MTN_MOMO)
        self.assertEqual(choisir_prestataire("+237655112233").code, Prestataire.ORANGE_MONEY)

    def test_un_operateur_en_panne_bascule_sur_un_generaliste(self):
        for _ in range(3):
            disjoncteur.echec(Prestataire.MTN_MOMO)
        self.assertEqual(choisir_prestataire("+237677220022").code, Prestataire.CARTE)

    def test_sans_generaliste_on_refuse_plutot_que_de_se_tromper_d_operateur(self):
        """On ne bascule pas un numéro MTN vers Orange : ce n'est pas un choix."""
        Prestataire.objects.filter(code=Prestataire.CARTE).update(actif=False)
        for _ in range(3):
            disjoncteur.echec(Prestataire.MTN_MOMO)

        with self.assertRaises(AucunPrestataireDisponible) as capture:
            choisir_prestataire("+237677220022")
        self.assertIn("espèces", str(capture.exception))

    def test_un_numero_inconnu_sans_generaliste_est_refuse(self):
        Prestataire.objects.filter(code=Prestataire.CARTE).update(actif=False)
        with self.assertRaises(AucunPrestataireDisponible):
            choisir_prestataire("+33612345678")


class DisjoncteurTest(TestCase):
    def test_il_ouvre_apres_trois_echecs_et_se_referme_apres_un_succes(self):
        d = Disjoncteur(seuil=3, duree_ouverture=60)
        self.assertTrue(d.disponible("X"))

        d.echec("X")
        d.echec("X")
        self.assertTrue(d.disponible("X"), "deux échecs ne suffisent pas")

        d.echec("X")
        self.assertFalse(d.disponible("X"))

        d.succes("X")
        self.assertTrue(d.disponible("X"))

    def test_il_laisse_repasser_un_appel_apres_le_delai(self):
        """Demi-ouverture : sans elle, une panne d'une minute coûterait la journée."""
        d = Disjoncteur(seuil=1, duree_ouverture=0)
        d.echec("X")
        self.assertTrue(d.disponible("X"))


class AdaptateursTest(TestCase):
    def test_le_prestataire_simule_sait_echouer_et_attendre(self):
        """Une démonstration qui ne montre que le cas heureux ne convainc personne."""
        faux = FauxPrestataire()
        montant = Decimal("5000")

        echec = faux.initier(reference="r1", montant=montant, numero="+237699110010")
        self.assertEqual(echec.etat, Transaction.ECHOUEE)

        attente = faux.initier(reference="r2", montant=montant, numero="+237699110019")
        self.assertEqual(attente.etat, Transaction.INITIEE)

        succes = faux.initier(reference="r3", montant=montant, numero="+237699110015")
        self.assertEqual(succes.etat, Transaction.REUSSIE)

    def test_un_operateur_reel_refuse_net_faute_de_configuration(self):
        """L'échec doit être lisible dans un journal, pas déguisé en erreur réseau."""
        for code in (Prestataire.MTN_MOMO, Prestataire.ORANGE_MONEY, Prestataire.CAMTEL):
            with self.subTest(prestataire=code):
                with self.assertRaises(PrestataireNonConfigure) as capture:
                    adaptateur_pour(code).initier(
                        reference="r", montant=Decimal("100"), numero="+237699110011"
                    )
                self.assertIn(code, str(capture.exception))


class EncaissementTest(TestCase):
    def setUp(self):
        creer_prestataires()
        Prestataire.objects.update_or_create(
            code=Prestataire.FAUX,
            defaults={"libelle": "Simulateur", "taux_frais": Decimal("0"), "prefixes_numero": []},
        )
        self.simulateur = Prestataire.objects.get(code=Prestataire.FAUX)
        disjoncteur.reinitialiser()
        self.addCleanup(disjoncteur.reinitialiser)

    def _encaisser(self, cle="paiement-1", numero="+237699110015"):
        return initier_encaissement(
            cle_idempotence=cle,
            montant=Decimal("12000"),
            numero_payeur=numero,
            prestataire=self.simulateur,
        )

    def test_un_encaissement_cree_une_transaction_tracee(self):
        operation = self._encaisser()
        self.assertEqual(operation.etat, Transaction.REUSSIE)
        self.assertTrue(operation.reference_externe)
        self.assertEqual(operation.montant, Decimal("12000.00"))

    def test_la_meme_cle_ne_debite_jamais_deux_fois(self):
        """L'invariant qui justifie tout le module."""
        premier = self._encaisser()
        second = self._encaisser()

        self.assertEqual(premier.pk, second.pk)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_un_montant_nul_est_refuse(self):
        with self.assertRaises(ValueError):
            initier_encaissement(
                cle_idempotence="vide",
                montant=Decimal("0"),
                numero_payeur="+237699110015",
                prestataire=self.simulateur,
            )

    def test_les_frais_du_prestataire_sont_lisibles_sur_la_transaction(self):
        Prestataire.objects.filter(code=Prestataire.FAUX).update(taux_frais=Decimal("0.0160"))
        operation = initier_encaissement(
            cle_idempotence="frais",
            montant=Decimal("100000"),
            numero_payeur="+237699110015",
            prestataire=Prestataire.objects.get(code=Prestataire.FAUX),
        )
        self.assertEqual(operation.frais, Decimal("1600.00"))

    def test_un_prestataire_non_configure_laisse_une_trace_et_ouvre_le_disjoncteur(self):
        with self.assertRaises(PrestataireNonConfigure):
            initier_encaissement(
                cle_idempotence="mtn-1",
                montant=Decimal("5000"),
                numero_payeur="+237677220022",
            )

        operation = Transaction.objects.get(cle_idempotence="mtn-1")
        self.assertEqual(operation.etat, Transaction.ECHOUEE)
        self.assertIn("erreur", operation.charge_utile_psp)


class TransitionsTest(TestCase):
    def setUp(self):
        Prestataire.objects.update_or_create(
            code=Prestataire.FAUX,
            defaults={"libelle": "Simulateur", "taux_frais": Decimal("0"), "prefixes_numero": []},
        )
        self.operation = initier_encaissement(
            cle_idempotence="attente",
            montant=Decimal("3000"),
            numero_payeur="+237699110019",  # se termine par 9 : reste initiée
            prestataire=Prestataire.objects.get(code=Prestataire.FAUX),
        )

    def test_une_transaction_en_attente_peut_aboutir(self):
        self.assertEqual(self.operation.etat, Transaction.INITIEE)
        appliquer_statut(self.operation, Transaction.REUSSIE, message="Notification opérateur")
        self.assertEqual(self.operation.etat, Transaction.REUSSIE)

    def test_une_transaction_reussie_ne_redevient_jamais_echouee(self):
        """Les notifications arrivent en double et en désordre : la dernière ne fait pas loi."""
        appliquer_statut(self.operation, Transaction.REUSSIE)
        with self.assertRaises(TransitionInterdite):
            appliquer_statut(self.operation, Transaction.ECHOUEE)

    def test_rejouer_la_meme_notification_ne_change_rien(self):
        appliquer_statut(self.operation, Transaction.REUSSIE)
        appliquer_statut(self.operation, Transaction.REUSSIE)
        self.assertEqual(self.operation.etat, Transaction.REUSSIE)

    def test_un_etat_inconnu_est_refuse(self):
        with self.assertRaises(TransitionInterdite):
            appliquer_statut(self.operation, "peut-etre")


class PortefeuilleTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Portefeuille")

    def test_le_solde_est_un_agregat_du_journal(self):
        """Comme le stock et la comptabilité : on écrit des lignes, pas un solde."""
        crediter_portefeuille(
            boutique=self.boutique, montant=Decimal("50000"), type_mouvement="encaissement"
        )
        mouvement = crediter_portefeuille(
            boutique=self.boutique, montant=Decimal("-12000"), type_mouvement="reversement"
        )

        self.assertEqual(mouvement.solde_apres, Decimal("38000.00"))
        with contexte_boutique(self.boutique):
            self.assertEqual(MouvementPortefeuille.objects.count(), 2)
            self.assertEqual(
                mouvement.portefeuille.solde_disponible, Decimal("38000.00")
            )

    def test_un_mouvement_nul_est_refuse(self):
        with self.assertRaises(ValueError):
            crediter_portefeuille(
                boutique=self.boutique, montant=Decimal("0"), type_mouvement="rien"
            )

    def test_le_portefeuille_reste_borne_a_sa_boutique(self):
        voisine = fabrique.creer_boutique("Voisine")
        crediter_portefeuille(
            boutique=self.boutique, montant=Decimal("1000"), type_mouvement="encaissement"
        )

        with contexte_boutique(voisine):
            self.assertEqual(MouvementPortefeuille.objects.count(), 0)
