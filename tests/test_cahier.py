"""Le cahier de crédit client (docs/22, §2.1).

Ce que ces tests défendent, dans l'ordre de ce qui coûte le plus cher si ça casse :

1. **On ne peut plus vendre à crédit sans savoir qui doit.** C'était la situation d'avant : le
   mode de règlement `CREDIT` existait, le nom du client était du texte libre, et l'encours
   n'était calculable pour personne.
2. **Le plafond refuse au service**, pas à l'écran — parce que l'API et le mode hors ligne ne
   passent par aucun écran.
3. **La comptabilité ne double pas le chiffre d'affaires.** Le règlement d'un cahier solde une
   créance ; reconstater la vente est l'erreur classique, et elle gonfle le résultat de tout ce
   qui a été vendu à crédit.
4. **L'écran des soldes ne s'écroule pas** : le nombre de requêtes ne dépend pas du nombre de
   clients.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.test import TestCase

from apps.accounting.models import LigneEcriture
from apps.accounts.models import Appartenance, Role
from apps.accounts.permissions import CAHIER_ENCAISSER, CAHIER_VOIR, droits_de
from apps.core.tenancy import contexte_boutique
from apps.inventory.services import entrer_stock
from apps.pos import cahier as cahier_service
from apps.pos import services as caisse_service
from apps.pos.models import ClientCahier, ReglementCahier, ReglementTicket, SessionCaisse, Ticket
from tests import fabrique


def _rattacher(utilisateur, boutique, code=Role.GERANT, libelle="Gérant"):
    role, _ = Role.objects.get_or_create(
        code=code, defaults={"libelle": libelle, "portee": Role.BOUTIQUE}
    )
    return Appartenance.objects.create(utilisateur=utilisateur, boutique=boutique, role=role)


class BaseCahierTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Quincaillerie")
        self.gerant = fabrique.creer_utilisateur("Gérante")
        _rattacher(self.gerant, self.boutique)
        with contexte_boutique(self.boutique):
            self.depot = fabrique.creer_depot(self.boutique)
            self.variante = fabrique.creer_variante(self.boutique, prix="5000")
            entrer_stock(
                depot=self.depot,
                variante=self.variante,
                quantite=Decimal("100"),
                cout_unitaire=Decimal("3000"),
            )
            self.session = caisse_service.ouvrir_session(
                depot=self.depot, caissier=self.gerant, fonds_ouverture=Decimal("0")
            )
            self.client_cahier = ClientCahier.objects.create(
                boutique=self.boutique,
                nom="Mama Ngo",
                telephone="+237699112233",
                plafond_credit=Decimal("20000"),
            )

    def _vendre_au_cahier(self, quantite="1", client=None):
        with contexte_boutique(self.boutique):
            ticket, _ = caisse_service.encaisser(
                session=self.session,
                lignes=[(self.variante, Decimal(quantite), Decimal("0"))],
                moyen=ReglementTicket.CREDIT,
                client=client if client is not None else self.client_cahier,
                cree_par=self.gerant,
            )
        return ticket


class CreditSansClientTest(BaseCahierTest):
    def test_le_credit_sans_client_est_refuse(self):
        """La situation d'avant le cahier ne peut plus être créée."""
        with contexte_boutique(self.boutique):
            with self.assertRaises(ValidationError) as leve:
                caisse_service.encaisser(
                    session=self.session,
                    lignes=[(self.variante, Decimal("1"), Decimal("0"))],
                    moyen=ReglementTicket.CREDIT,
                    cree_par=self.gerant,
                )
        self.assertIn("client du cahier", str(leve.exception))

    def test_les_autres_moyens_ne_demandent_pas_de_client(self):
        """Le contrôle ne doit pas gêner la vente comptant, qui est le cas courant."""
        with contexte_boutique(self.boutique):
            ticket, _ = caisse_service.encaisser(
                session=self.session,
                lignes=[(self.variante, Decimal("1"), Decimal("0"))],
                moyen=ReglementTicket.ESPECES,
                cree_par=self.gerant,
            )
            self.assertEqual(ticket.etat, Ticket.CLOTURE)
            self.assertIsNone(ticket.client_id)


class SoldeTest(BaseCahierTest):
    def test_le_solde_est_une_difference(self):
        self._vendre_au_cahier("2")  # 2 × 5 000 = 10 000
        with contexte_boutique(self.boutique):
            self.assertEqual(cahier_service.solde_de(self.client_cahier), Decimal("10000.00"))

            cahier_service.enregistrer_reglement(
                client=self.client_cahier,
                moyen=ReglementCahier.ESPECES,
                montant=Decimal("4000"),
                recu_par=self.gerant,
            )
            self.assertEqual(cahier_service.solde_de(self.client_cahier), Decimal("6000.00"))

    def test_un_ticket_annule_ne_compte_pas(self):
        """Une vente annulée n'est pas une dette : elle n'a pas eu lieu."""
        ticket = self._vendre_au_cahier("2")
        with contexte_boutique(self.boutique):
            self.assertEqual(cahier_service.solde_de(self.client_cahier), Decimal("10000.00"))
            Ticket.objects.filter(pk=ticket.pk).update(etat=Ticket.ANNULE)
            self.assertEqual(cahier_service.solde_de(self.client_cahier), Decimal("0.00"))

    def test_une_avance_rend_le_solde_negatif_et_ne_l_ecrase_pas(self):
        """Un trop-perçu se voit. L'écraser à zéro cacherait une erreur de caisse."""
        with contexte_boutique(self.boutique):
            cahier_service.enregistrer_reglement(
                client=self.client_cahier,
                moyen=ReglementCahier.ESPECES,
                montant=Decimal("3000"),
                recu_par=self.gerant,
            )
            self.assertEqual(cahier_service.solde_de(self.client_cahier), Decimal("-3000.00"))


class PlafondTest(BaseCahierTest):
    def test_le_plafond_refuse_au_service(self):
        """Le plafond est à 20 000 : quatre articles à 5 000 passent, le cinquième non."""
        self._vendre_au_cahier("4")
        with contexte_boutique(self.boutique):
            self.assertEqual(cahier_service.solde_de(self.client_cahier), Decimal("20000.00"))
            with self.assertRaises(cahier_service.PlafondDepasse):
                self._vendre_au_cahier("1")

    def test_le_message_dit_ce_qui_reste(self):
        """Un refus utile dit combien il reste, pas seulement « refusé »."""
        self._vendre_au_cahier("3")  # 15 000 sur 20 000
        with contexte_boutique(self.boutique):
            with self.assertRaises(cahier_service.PlafondDepasse) as leve:
                cahier_service.verifier_plafond(self.client_cahier, Decimal("9000"))
        self.assertIn("5000", str(leve.exception).replace(" ", ""))

    def test_un_plafond_a_zero_interdit_le_credit(self):
        """Zéro signifie « pas de crédit », jamais « illimité »."""
        with contexte_boutique(self.boutique):
            sans_credit = ClientCahier.objects.create(
                boutique=self.boutique, nom="Passant", plafond_credit=Decimal("0")
            )
            with self.assertRaises(cahier_service.PlafondDepasse):
                cahier_service.verifier_plafond(sans_credit, Decimal("1"))

    def test_un_cahier_clos_refuse_la_vente(self):
        with contexte_boutique(self.boutique):
            self.client_cahier.actif = False
            self.client_cahier.save(update_fields=["actif"])
            with self.assertRaises(cahier_service.PlafondDepasse) as leve:
                cahier_service.verifier_plafond(self.client_cahier, Decimal("1000"))
        self.assertIn("clos", str(leve.exception))


class ComptabiliteDuCahierTest(BaseCahierTest):
    def test_le_reglement_solde_la_creance_sans_recreer_de_produit(self):
        """L'erreur à ne pas commettre : reconstater la vente à l'encaissement."""
        self._vendre_au_cahier("2")
        with contexte_boutique(self.boutique):
            produits_avant = LigneEcriture.objects.filter(compte__numero="701").aggregate(
                t=Sum("credit")
            )["t"] or Decimal("0")

            cahier_service.enregistrer_reglement(
                client=self.client_cahier,
                moyen=ReglementCahier.ESPECES,
                montant=Decimal("10000"),
                recu_par=self.gerant,
            )

            produits_apres = LigneEcriture.objects.filter(compte__numero="701").aggregate(
                t=Sum("credit")
            )["t"] or Decimal("0")
            self.assertEqual(produits_avant, produits_apres, "le règlement a recréé du produit")

            # La créance est soldée : 411 débité de 10 000 à la vente, crédité de 10 000 ici.
            lignes_411 = LigneEcriture.objects.filter(compte__numero="411")
            debit = lignes_411.aggregate(t=Sum("debit"))["t"]
            credit = lignes_411.aggregate(t=Sum("credit"))["t"]
            self.assertEqual(debit - credit, Decimal("0.00"))

    def test_la_caisse_est_debitee(self):
        self._vendre_au_cahier("1")
        with contexte_boutique(self.boutique):
            cahier_service.enregistrer_reglement(
                client=self.client_cahier,
                moyen=ReglementCahier.ESPECES,
                montant=Decimal("5000"),
                recu_par=self.gerant,
            )
            caisse = LigneEcriture.objects.filter(compte__numero="571").aggregate(
                t=Sum("debit")
            )["t"]
            self.assertEqual(caisse, Decimal("5000.00"))


class DroitsDuCahierTest(BaseCahierTest):
    def test_le_comptable_voit_sans_encaisser(self):
        """Il tient la balance, il ne tient pas la caisse."""
        comptable = fabrique.creer_utilisateur("Comptable")
        _rattacher(comptable, self.boutique, code=Role.COMPTABLE, libelle="Comptable")
        droits = droits_de(comptable, self.boutique)
        self.assertIn(CAHIER_VOIR, droits)
        self.assertNotIn(CAHIER_ENCAISSER, droits)

    def test_le_magasinier_ne_voit_rien_du_cahier(self):
        magasinier = fabrique.creer_utilisateur("Magasinier")
        _rattacher(magasinier, self.boutique, code=Role.MAGASINIER, libelle="Magasinier")
        droits = droits_de(magasinier, self.boutique)
        self.assertNotIn(CAHIER_VOIR, droits)
        self.assertNotIn(CAHIER_ENCAISSER, droits)

    def test_encaisser_sans_le_droit_est_refuse(self):
        magasinier = fabrique.creer_utilisateur("Magasinier")
        _rattacher(magasinier, self.boutique, code=Role.MAGASINIER, libelle="Magasinier")
        with contexte_boutique(self.boutique):
            with self.assertRaises(PermissionDenied):
                cahier_service.enregistrer_reglement(
                    client=self.client_cahier,
                    moyen=ReglementCahier.ESPECES,
                    montant=Decimal("1000"),
                    recu_par=magasinier,
                )


class EcranDesSoldesTest(BaseCahierTest):
    def test_le_nombre_de_requetes_ne_depend_pas_du_nombre_de_clients(self):
        """Sinon l'écran s'affiche en développement et s'écroule chez le commerçant."""
        with contexte_boutique(self.boutique):
            with self.assertNumQueries(1):
                list(cahier_service.avec_soldes())

            for i in range(40):
                ClientCahier.objects.create(
                    boutique=self.boutique, nom=f"Client {i}", plafond_credit=Decimal("5000")
                )
            with self.assertNumQueries(1):
                lignes = list(cahier_service.avec_soldes())
            self.assertEqual(len(lignes), 41)

    def test_un_client_sans_credit_a_un_encours_a_zero_et_non_nul(self):
        """`NULL` au lieu de zéro fausserait le tri et les totaux."""
        with contexte_boutique(self.boutique):
            ligne = cahier_service.avec_soldes().get(pk=self.client_cahier.pk)
            self.assertEqual(ligne.encours, Decimal("0"))


class ReleveTest(BaseCahierTest):
    def test_le_releve_mele_achats_et_paiements_dans_une_seule_chronologie(self):
        """C'est la pièce qu'on montre quand le client conteste."""
        self._vendre_au_cahier("2")
        with contexte_boutique(self.boutique):
            cahier_service.enregistrer_reglement(
                client=self.client_cahier,
                moyen=ReglementCahier.ESPECES,
                montant=Decimal("4000"),
                recu_par=self.gerant,
            )
            lignes = cahier_service.releve_de(self.client_cahier)

        self.assertEqual([ligne["nature"] for ligne in lignes], ["achat", "paiement"])
        self.assertEqual(lignes[0]["solde"], Decimal("10000.00"))
        self.assertEqual(lignes[-1]["solde"], Decimal("6000.00"))


class PasDInteretTest(TestCase):
    def test_aucun_taux_ni_penalite_dans_le_module(self):
        """Un cahier est une facilité de paiement. Facturer le temps en ferait un prêt.

        Ce test est une barrière contre une bonne intention : quelqu'un finira par vouloir
        « inciter » au paiement. Facturer un intérêt ou une pénalité rend l'activité
        réglementée (agrément COBAC), c'est-à-dire un autre métier. Voir docs/08.
        """
        import pathlib

        source = pathlib.Path("apps/pos/cahier.py").read_text()
        for interdit in ("taux_interet", "penalite", "frais_retard", "agios", "escompte"):
            self.assertNotIn(
                interdit,
                source,
                f"« {interdit} » dans le cahier : un cahier n'est pas un prêt (docs/08).",
            )
