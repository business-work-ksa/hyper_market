"""Le rapport de la semaine, pour WhatsApp (docs/22, §2.2).

Ce que ces tests protègent :

* **la bonne semaine** : du lundi au dimanche de la dernière semaine complète, quel que soit le
  jour où le rapport est lu ;
* **jamais la marge** : un message WhatsApp se transfère ;
* **chaque ligne suit les droits** : sans `cahier.voir`, pas de cahier ; sans `stock.voir`, pas de
  ruptures — ni en chiffre ni en « Aucune rupture » ;
* **le lien ouvre WhatsApp avec le message**, et un numéro local reçoit l'indicatif.
"""

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts import permissions as droit
from apps.backoffice import rapport_hebdo
from apps.core.tenancy import contexte_boutique
from apps.inventory.services import entrer_stock
from apps.pos.models import Ticket
from tests import fabrique
from tests.test_backoffice import MOT_DE_PASSE, _rattacher


class SemaineTest(TestCase):
    def test_du_lundi_au_dimanche_de_la_semaine_ecoulee(self):
        # Le mercredi 7 octobre 2026 parle de la semaine du 28 septembre au 4 octobre.
        self.assertEqual(
            rapport_hebdo.semaine_ecoulee(date(2026, 10, 7)), (date(2026, 9, 28), date(2026, 10, 4))
        )
        # Le lundi aussi : la semaine qui commence n'a encore rien à dire.
        self.assertEqual(
            rapport_hebdo.semaine_ecoulee(date(2026, 10, 5)), (date(2026, 9, 28), date(2026, 10, 4))
        )
        # Et le dimanche parle de la semaine d'avant, pas de celle qui s'achève à peine.
        self.assertEqual(
            rapport_hebdo.semaine_ecoulee(date(2026, 10, 4)), (date(2026, 9, 21), date(2026, 9, 27))
        )


class LienTest(TestCase):
    def test_le_lien_porte_le_message(self):
        lien = rapport_hebdo.lien_whatsapp("Ventes : 1 000 FCFA\n— HyperMarché")
        self.assertTrue(lien.startswith("https://wa.me/?text="))
        self.assertEqual(unquote(lien.split("text=", 1)[1]), "Ventes : 1 000 FCFA\n— HyperMarché")

    def test_un_numero_local_recoit_l_indicatif(self):
        self.assertTrue(rapport_hebdo.lien_whatsapp("x", "699 00 00 00").startswith("https://wa.me/237699000000?"))
        self.assertTrue(rapport_hebdo.lien_whatsapp("x", "+237699000000").startswith("https://wa.me/237699000000?"))


class RapportTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Ateba")
        self.gerant = fabrique.creer_utilisateur("Gérant")
        _rattacher(self.gerant, self.boutique)
        with contexte_boutique(self.boutique):
            self.depot = fabrique.creer_depot(self.boutique)
            self.variante = fabrique.creer_variante(self.boutique, prix="11925", libelle="Ciment 50 kg")
            self.rare = fabrique.creer_variante(self.boutique, prix="500", libelle="Clou de 8")
            entrer_stock(depot=self.depot, variante=self.variante, quantite=20, cout_unitaire=Decimal("6800"))
            entrer_stock(depot=self.depot, variante=self.rare, quantite=1, cout_unitaire=Decimal("300"))
        self.client.login(telephone=self.gerant.telephone, password=MOT_DE_PASSE)
        self.debut, self.fin = rapport_hebdo.semaine_ecoulee()

    def encaisser(self, variante, quantite, le: date, numero=1):
        reponse = self.client.post(
            reverse("caisse_encaisser"),
            data=json.dumps(
                {
                    "operation_id": f"018f0000-0000-7000-8000-{numero:012d}",
                    "lignes": [{"variante": str(variante.pk), "quantite": quantite}],
                    "moyen": "especes",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(reponse.status_code, 200, reponse.content)
        moment = timezone.make_aware(datetime.combine(le, time(10)))
        with contexte_boutique(self.boutique):
            Ticket.objects.filter(numero=reponse.json()["numero"]).update(cloture_le=moment)

    def test_le_message_dit_la_semaine_et_la_compare(self):
        self.encaisser(self.variante, 2, self.debut + timedelta(days=1), numero=1)
        self.encaisser(self.rare, 1, self.debut + timedelta(days=2), numero=2)
        self.encaisser(self.variante, 1, self.debut - timedelta(days=3), numero=3)

        rapport = rapport_hebdo.rapport_de_la_semaine(self.boutique, droits=droit.TOUS)
        self.assertEqual(rapport.chiffre_affaires, Decimal("24350"))
        self.assertEqual(rapport.precedent, Decimal("11925"))
        self.assertEqual(rapport.tickets, 2)
        self.assertEqual(rapport.evolution, 104)
        self.assertEqual(rapport.articles[0][0], "Ciment 50 kg", "classés par montant")
        self.assertEqual(rapport.ruptures, ["Clou de 8"])

        message = rapport_hebdo.texte(rapport)
        self.assertIn("24 350 FCFA (2 tickets)", message)
        self.assertIn("+104 %", message)
        self.assertIn("En rupture : Clou de 8", message)
        self.assertIn("Cahier de crédit : 0 FCFA", message)
        self.assertLessEqual(len(message.splitlines()), 6)
        self.assertNotIn("arge", message, "jamais la marge dans un message qui se transfère")

    def test_chaque_ligne_suit_les_droits(self):
        rapport = rapport_hebdo.rapport_de_la_semaine(
            self.boutique, droits={droit.TABLEAU_DE_BORD, droit.VENTES_VOIR}
        )
        message = rapport_hebdo.texte(rapport)
        self.assertIsNone(rapport.cahier)
        self.assertNotIn("Cahier", message)
        self.assertNotIn("rupture", message.lower(), "pas même « Aucune rupture » sans stock.voir")

    def test_l_ecran_propose_l_envoi(self):
        self.encaisser(self.variante, 1, self.debut, numero=4)
        reponse = self.client.get(reverse("rapport_semaine"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "https://wa.me/")
        self.assertContains(reponse, "Envoyer sur WhatsApp")
        self.assertContains(reponse, "11 925 FCFA (1 ticket)")
        self.assertContains(self.client.get(reverse("tableau_de_bord")), reverse("rapport_semaine"))

    def test_la_semaine_d_avant(self):
        self.encaisser(self.variante, 1, self.debut - timedelta(days=7), numero=5)
        reponse = self.client.get(reverse("rapport_semaine") + "?precedente=1")
        self.assertContains(reponse, "11 925 FCFA (1 ticket)")
