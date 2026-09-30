"""Le séquestre : l'argent de l'acheteur n'arrive chez le marchand qu'après la livraison prouvée.

Ce que ces tests protègent :

* **l'ouverture au paiement**, une fois et une seule, part par part, nette de commission ;
* **le plafond du palier**, qui refuse le prépaiement chez une boutique qui n'a rien prouvé ;
* **le code de remise** : juste, faux, verrouillé, et jamais écrit en clair ;
* **une livraison déclarée ne libère rien** ; seule la livraison confirmée — ou réputée l'être
  sept jours après l'expédition — ouvre le délai du palier ;
* **l'invariant de l'argent** : bloqué + disponible + versé + remboursé = encaissé net, et le
  bloqué du portefeuille est la somme des séquestres bloqués, après chaque scénario.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from apps.accounting.services import solde_compte
from apps.core.tenancy import contexte_boutique, contexte_plateforme
from apps.inventory.services import entrer_stock
from apps.marketplace.confiance import palier_de
from apps.marketplace.models import Boutique
from apps.orders.models import Commande, SousCommande
from apps.orders.services import (
    CommandeInvalide,
    PrepaiementRefuse,
    accepter,
    accepter_retour,
    annuler_sous_commande,
    demander_retour,
    expedier,
    livrer,
    marquer_payee,
    passer_commande,
    preparer,
)
from apps.payments import sequestre as service
from apps.payments.models import MouvementPortefeuille, PortefeuilleMarchand, Sequestre
from tests import fabrique

# 11 925 F TTC l'unité, soit 10 000 F HT ; commission de 5 % sur le HT.
# Deux unités : 23 850 TTC, commission 1 000 + TVA 192,50 = 1 192,50 ; part nette 22 657,50.
PRIX = "11925"
NET_DEUX = Decimal("22657.50")


class SocleSequestre(TestCase):
    """Deux boutiques en stock, un acheteur ; des raccourcis pour chaque étape."""

    def setUp(self):
        self.acheteur = fabrique.creer_utilisateur("Acheteuse")
        self.ateba = fabrique.creer_boutique("Ateba")
        self.depot_ateba = fabrique.creer_depot(self.ateba)
        self.brouette = fabrique.creer_variante(self.ateba, prix=PRIX)
        entrer_stock(
            depot=self.depot_ateba,
            variante=self.brouette,
            quantite=Decimal("100"),
            cout_unitaire=Decimal("7000"),
        )
        self.bella = fabrique.creer_boutique("Bella")
        self.depot_bella = fabrique.creer_depot(self.bella)
        self.creme = fabrique.creer_variante(self.bella, prix="5962.50")
        entrer_stock(
            depot=self.depot_bella,
            variante=self.creme,
            quantite=Decimal("100"),
            cout_unitaire=Decimal("3000"),
        )

    # --- raccourcis ------------------------------------------------------------------------
    def commander(self, lignes=None, **options):
        lignes = lignes or [(self.brouette, Decimal("2"))]
        return passer_commande(acheteur=self.acheteur, lignes=lignes, **options)

    def part(self, commande, boutique=None):
        with contexte_plateforme():
            return SousCommande.objects.get(commande=commande, boutique=boutique or self.ateba)

    def payee(self, lignes=None, **options):
        commande = self.commander(lignes, **options)
        marquer_payee(commande)
        return commande, self.part(commande)

    def expediee(self, part):
        accepter(part)
        preparer(part)
        expedier(part)
        self.recharger(part)
        return part

    def recharger(self, part):
        # Barrière 3 : même un rechargement annonce sa boutique.
        with contexte_boutique(part.boutique_id):
            part.refresh_from_db()
        return part

    def sequestre(self, part) -> Sequestre:
        return Sequestre.objects.get(sous_commande=part)

    def portefeuille(self, boutique=None):
        with contexte_boutique(boutique or self.ateba):
            return PortefeuilleMarchand.objects.get(boutique=boutique or self.ateba)

    def verifier_l_invariant(self, boutique=None):
        """Rien ne se crée, rien ne se perd — et le journal fait les soldes."""
        boutique = boutique or self.ateba
        bilan = service.bilan(boutique)
        self.assertEqual(bilan["ecart"], Decimal("0.00"), bilan)
        self.assertEqual(bilan["bloque"], bilan["bloque_sequestres"], bilan)
        with contexte_boutique(boutique):
            portefeuille = PortefeuilleMarchand.objects.filter(boutique=boutique).first()
            if portefeuille is None:
                return bilan
            for compartiment, solde in (
                (MouvementPortefeuille.BLOQUE, portefeuille.solde_bloque),
                (MouvementPortefeuille.DISPONIBLE, portefeuille.solde_disponible),
            ):
                somme = MouvementPortefeuille.objects.filter(
                    boutique=boutique, compartiment=compartiment
                ).aggregate(t=Sum("montant"))["t"] or Decimal("0")
                self.assertEqual(somme, solde, f"journal ≠ solde {compartiment}")
        return bilan


class OuvertureTest(SocleSequestre):
    def test_le_paiement_ouvre_un_sequestre_bloque_net_de_commission(self):
        commande, part = self.payee()
        sequestre = self.sequestre(part)

        self.assertEqual(sequestre.etat, Sequestre.BLOQUE)
        self.assertEqual(sequestre.montant_encaisse, Decimal("23850.00"))
        self.assertEqual(sequestre.commission, Decimal("1192.50"))
        self.assertEqual(sequestre.montant, NET_DEUX)
        self.assertEqual(self.portefeuille().solde_bloque, NET_DEUX)
        self.assertEqual(self.portefeuille().solde_disponible, Decimal("0.00"))
        self.verifier_l_invariant()

    def test_une_notification_en_double_n_ouvre_qu_un_sequestre(self):
        commande, part = self.payee()
        marquer_payee(commande)
        service.ouvrir_sequestre(part)

        self.assertEqual(Sequestre.objects.filter(sous_commande=part).count(), 1)
        with contexte_boutique(self.ateba):
            self.assertEqual(MouvementPortefeuille.objects.count(), 1)
        self.assertEqual(self.portefeuille().solde_bloque, NET_DEUX)

    def test_une_commande_multi_boutiques_ouvre_une_part_par_boutique(self):
        commande = self.commander([(self.brouette, Decimal("1")), (self.creme, Decimal("2"))])
        marquer_payee(commande)

        self.assertEqual(Sequestre.objects.filter(commande=commande).count(), 2)
        self.assertEqual(
            self.sequestre(self.part(commande, self.bella)).montant_encaisse, Decimal("11925.00")
        )
        self.verifier_l_invariant(self.ateba)
        self.verifier_l_invariant(self.bella)

    def test_la_part_nette_concorde_avec_la_comptabilite_du_marchand(self):
        """Créance 5313 moins dette 401 = ce que le portefeuille dit bloqué."""
        self.payee()
        creance = solde_compte("5313", boutique_id=self.ateba.pk)
        dette = -solde_compte("401", boutique_id=self.ateba.pk)
        self.assertEqual(creance - dette, self.portefeuille().solde_bloque)

    def test_le_paiement_a_la_livraison_ne_passe_pas_par_le_sequestre(self):
        commande = self.commander(
            [(self.brouette, Decimal("1")), (self.creme, Decimal("1"))],
            a_la_livraison=[self.bella.pk],
        )
        marquer_payee(commande)
        self.assertFalse(Sequestre.objects.filter(boutique=self.bella).exists())
        self.assertTrue(Sequestre.objects.filter(boutique=self.ateba).exists())
        self.assertEqual(self.part(commande, self.bella).mode_paiement, SousCommande.A_LA_LIVRAISON)

    def test_une_commande_toute_a_la_livraison_n_a_rien_a_constater(self):
        commande = self.commander(mode_paiement=SousCommande.A_LA_LIVRAISON)
        with self.assertRaises(CommandeInvalide):
            marquer_payee(commande)
        self.assertFalse(Sequestre.objects.exists())


class PlafondTest(SocleSequestre):
    def test_le_plafond_du_palier_zero_refuse_le_prepaiement(self):
        plafond = palier_de(self.ateba).plafond_sequestre
        quantite = (plafond / Decimal(PRIX)).to_integral_value() + 1  # juste au-dessus
        with self.assertRaises(PrepaiementRefuse) as refus:
            self.commander([(self.brouette, quantite)])

        self.assertIn(str(self.ateba.pk), refus.exception.refus)
        self.assertIn("à la livraison", refus.exception.refus[str(self.ateba.pk)])
        self.assertEqual(Commande.objects.count(), 0, "rien n'est créé")

    def test_la_livraison_est_proposee_pour_la_boutique_refusee(self):
        plafond = palier_de(self.ateba).plafond_sequestre
        quantite = (plafond / Decimal(PRIX)).to_integral_value() + 1
        commande = self.commander([(self.brouette, quantite)], a_la_livraison=[self.ateba.pk])
        self.assertEqual(self.part(commande).mode_paiement, SousCommande.A_LA_LIVRAISON)

    def test_accepte_au_palier_superieur(self):
        plafond = palier_de(self.ateba).plafond_sequestre
        quantite = (plafond / Decimal(PRIX)).to_integral_value() + 1
        Boutique.objects.filter(pk=self.ateba.pk).update(palier_confiance=1)
        commande = self.commander([(self.brouette, quantite)])
        self.assertEqual(self.part(commande).mode_paiement, SousCommande.PREPAYE)

    def test_les_sequestres_encore_bloques_comptent_dans_le_plafond(self):
        # 8 × 11 925 = 95 400 F bloqués ; 5 de plus porteraient le total à 155 025 F > 150 000.
        self.payee([(self.brouette, Decimal("8"))])
        with self.assertRaises(PrepaiementRefuse):
            self.commander([(self.brouette, Decimal("5"))])
        # Une part d'un autre marchand n'est pas concernée par le plafond d'Ateba.
        self.commander([(self.creme, Decimal("5"))])


class PlafondEnVitrineTest(SocleSequestre):
    def test_la_vitrine_annonce_le_refus_et_propose_la_livraison(self):
        from django.urls import reverse

        plafond = palier_de(self.ateba).plafond_sequestre
        quantite = int((plafond / Decimal(PRIX)).to_integral_value()) + 1
        self.client.post(
            reverse("vitrine_panier_ajouter", args=[self.brouette.pk]), {"quantite": quantite}
        )
        page = self.client.get(reverse("vitrine_commander"))
        self.assertContains(page, "plafonné")
        self.assertContains(page, "Paiement à la livraison")

        self.client.post(
            reverse("vitrine_commander"),
            {
                "nom_complet": "Marie Ekedi",
                "telephone": "+237699000123",
                "adresse_livraison": "Akwa, rue Joss",
                "mode_paiement": "prepaye",
                "a_la_livraison": str(self.ateba.pk),
            },
        )
        commande = Commande.objects.get()
        self.assertEqual(self.part(commande).mode_paiement, SousCommande.A_LA_LIVRAISON)


class CodeDeRemiseTest(SocleSequestre):
    def test_le_bon_code_confirme_la_livraison(self):
        _, part = self.payee()
        part = self.expediee(part)

        service.confirmer_par_code(part, service.code_de_remise(part))

        self.recharger(part)
        self.assertIsNotNone(part.livraison_confirmee_le)
        self.assertEqual(part.etat, SousCommande.LIVREE)
        self.assertEqual(self.sequestre(part).confirmation, Sequestre.PAR_CODE)

    def test_un_faux_code_est_compte_puis_le_code_se_verrouille(self):
        _, part = self.payee()
        part = self.expediee(part)
        bon = service.code_de_remise(part)
        faux = "000000" if bon != "000000" else "111111"

        for _ in range(service.ESSAIS_CODE_MAX):
            with self.assertRaises(service.CodeIncorrect):
                service.confirmer_par_code(part, faux)
        # Verrouillé : même le bon code est refusé désormais.
        with self.assertRaises(service.CodeVerrouille):
            service.confirmer_par_code(part, bon)

        self.recharger(part)
        self.assertIsNone(part.livraison_confirmee_le)
        sequestre = self.sequestre(part)
        self.assertEqual(sequestre.essais_code_echoues, service.ESSAIS_CODE_MAX)
        self.assertIsNotNone(sequestre.code_verrouille_le)
        # L'acheteur, lui, peut toujours confirmer.
        service.confirmer_par_acheteur(part)
        self.recharger(part)
        self.assertIsNotNone(part.livraison_confirmee_le)

    def test_le_code_n_est_jamais_stocke_en_clair(self):
        commande, part = self.payee()
        code = service.code_de_remise(part)
        sequestre = self.sequestre(part)

        self.assertTrue(sequestre.code_remise_hache)
        self.assertNotIn(code, sequestre.code_remise_hache)
        valeurs = [str(v) for v in Sequestre.objects.filter(pk=sequestre.pk).values().first().values()]
        valeurs += [str(v) for v in Commande.objects.filter(pk=commande.pk).values().first().values()]
        with contexte_boutique(self.ateba):
            valeurs += [str(v) for v in SousCommande.objects.filter(pk=part.pk).values().first().values()]
        self.assertFalse(any(v == code for v in valeurs))

    def test_pas_de_code_avant_l_expedition(self):
        _, part = self.payee()
        with self.assertRaises(service.SequestreRefuse):
            service.confirmer_par_code(part, service.code_de_remise(part))


class LiberationTest(SocleSequestre):
    def test_une_livraison_seulement_declaree_ne_libere_rien(self):
        _, part = self.payee()
        part = self.expediee(part)
        livrer(part)
        sequestre = self.sequestre(part)

        with self.assertRaises(service.SequestreRefuse):
            service.liberer(sequestre, maintenant=timezone.now() + timedelta(days=6))
        service.liberer_echus(maintenant=timezone.now() + timedelta(days=6))

        self.assertEqual(self.sequestre(part).etat, Sequestre.BLOQUE)
        self.assertEqual(self.portefeuille().solde_disponible, Decimal("0.00"))

    def test_liberation_au_terme_du_delai_du_palier(self):
        _, part = self.payee()
        part = self.expediee(part)
        maintenant = timezone.now()
        service.confirmer_par_code(part, service.code_de_remise(part), maintenant=maintenant)
        delai = timedelta(days=palier_de(self.ateba).delai_liberation_jours)

        service.liberer_echus(maintenant=maintenant + delai - timedelta(minutes=1))
        self.assertEqual(self.sequestre(part).etat, Sequestre.BLOQUE)

        bilan = service.liberer_echus(maintenant=maintenant + delai + timedelta(minutes=1))
        self.assertEqual(bilan["liberees"], 1)
        self.assertEqual(self.sequestre(part).etat, Sequestre.LIBERE)
        self.assertEqual(self.portefeuille().solde_bloque, Decimal("0.00"))
        self.assertEqual(self.portefeuille().solde_disponible, NET_DEUX)

        # Rejouée, elle ne refait rien.
        service.liberer_echus(maintenant=maintenant + delai + timedelta(days=1))
        self.assertEqual(self.portefeuille().solde_disponible, NET_DEUX)
        self.verifier_l_invariant()

    def test_le_delai_suit_le_palier(self):
        Boutique.objects.filter(pk=self.ateba.pk).update(palier_confiance=2)
        self.ateba.refresh_from_db()
        _, part = self.payee()
        part = self.expediee(part)
        maintenant = timezone.now()
        service.confirmer_par_acheteur(part, maintenant=maintenant)
        delai = palier_de(self.ateba).delai_liberation_jours

        service.liberer_echus(maintenant=maintenant + timedelta(days=delai, minutes=1))
        self.assertEqual(self.sequestre(part).etat, Sequestre.LIBERE)

    def test_la_liberation_compense_la_commission_en_comptabilite(self):
        _, part = self.payee()
        part = self.expediee(part)
        maintenant = timezone.now()
        service.confirmer_par_acheteur(part, maintenant=maintenant)
        service.liberer_echus(maintenant=maintenant + timedelta(days=30))

        self.assertEqual(solde_compte("401", boutique_id=self.ateba.pk), Decimal("0.00"))
        self.assertEqual(solde_compte("5313", boutique_id=self.ateba.pk), NET_DEUX)


class ConfirmationImpliciteTest(SocleSequestre):
    def test_sept_jours_apres_l_expedition_la_livraison_est_reputee_confirmee(self):
        _, part = self.payee()
        part = self.expediee(part)
        expedition = part.expediee_le

        service.liberer_echus(maintenant=expedition + timedelta(days=6, hours=23))
        self.recharger(part)
        self.assertIsNone(part.livraison_confirmee_le)

        service.liberer_echus(maintenant=expedition + timedelta(days=7, hours=1))
        self.recharger(part)
        self.assertEqual(part.livraison_confirmee_le, expedition + service.DELAI_CONFIRMATION_IMPLICITE)
        self.assertEqual(self.sequestre(part).confirmation, Sequestre.IMPLICITE)
        self.assertEqual(self.sequestre(part).etat, Sequestre.BLOQUE, "le délai du palier court")

        delai = palier_de(self.ateba).delai_liberation_jours
        service.liberer_echus(maintenant=expedition + timedelta(days=7 + delai, hours=1))
        self.assertEqual(self.sequestre(part).etat, Sequestre.LIBERE)
        self.verifier_l_invariant()

    def test_la_commande_de_gestion_est_idempotente(self):
        _, part = self.payee()
        part = self.expediee(part)
        with contexte_boutique(self.ateba):
            SousCommande.objects.filter(pk=part.pk).update(
                expediee_le=timezone.now() - timedelta(days=40)
            )
        call_command("liberer_sequestres", verbosity=0)
        call_command("liberer_sequestres", verbosity=0)
        self.assertEqual(self.sequestre(part).etat, Sequestre.LIBERE)
        self.assertEqual(self.portefeuille().solde_disponible, NET_DEUX)
        self.verifier_l_invariant()


class AnnulationEtRetourTest(SocleSequestre):
    def test_le_refus_du_marchand_rembourse_l_acheteur(self):
        _, part = self.payee()
        annuler_sous_commande(part, motif="Rupture")

        sequestre = self.sequestre(part)
        self.assertEqual(sequestre.etat, Sequestre.REMBOURSE)
        self.assertEqual(sequestre.rembourse_acheteur, Decimal("23850.00"))
        self.assertEqual(self.portefeuille().solde_bloque, Decimal("0.00"))
        self.verifier_l_invariant()

    def test_un_retour_accepte_rembourse_depuis_le_sequestre(self):
        _, part = self.payee()
        part = self.expediee(part)
        livrer(part)
        accepter_retour(demander_retour(part, motif="Abîmé"))

        self.assertEqual(self.sequestre(part).etat, Sequestre.REMBOURSE)
        self.verifier_l_invariant()
