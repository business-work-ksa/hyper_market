"""Le premier aller-retour réel avec un opérateur, contre son bac à sable.

Les clients MTN et Orange sont testés contre des réponses simulées ; seule cette commande prouve
qu'ils parlent vraiment à l'opérateur. **Un opérateur ne s'active pas en production avant qu'elle
ait réussi** (docs/24, §3).

    python manage.py essayer_prestataire mtn --numero 46733123454
    python manage.py essayer_prestataire orange

Elle n'écrit rien en base : pas de transaction, pas de commande. Elle affiche ce que l'opérateur
répond, jamais une clé.

Numéros de test du bac à sable MTN (publiés par MTN) : `46733123454` réussit ; d'autres numéros
simulent l'échec ou l'attente — voir la documentation du bac à sable.
"""

import time
import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.payments.adaptateurs import PaiementIndisponible, PrestataireNonConfigure
from apps.payments.operateurs import AdaptateurMtnMomo, AdaptateurOrangeMoney


class Command(BaseCommand):
    help = "Fait un aller-retour réel avec le bac à sable d'un opérateur (MTN ou Orange)."

    def add_arguments(self, parser):
        parser.add_argument("operateur", choices=["mtn", "orange"])
        parser.add_argument("--numero", default="46733123454", help="Numéro payeur (MTN).")
        parser.add_argument("--montant", default="100")
        parser.add_argument(
            "--retour",
            default="",
            help="Adresse de retour pour Orange (par défaut : URL_PUBLIQUE + /marche/).",
        )

    def handle(self, *args, **options):
        reference = str(uuid.uuid4())
        montant = Decimal(options["montant"])
        try:
            if options["operateur"] == "mtn":
                self._mtn(reference, montant, options["numero"])
            else:
                self._orange(reference, montant, options["retour"])
        except PrestataireNonConfigure as exc:
            raise CommandError(str(exc)) from exc
        except PaiementIndisponible as exc:
            raise CommandError(f"Échec de l'aller-retour : {exc}") from exc

    def _mtn(self, reference, montant, numero):
        mtn = AdaptateurMtnMomo()
        reponse = mtn.initier(reference=reference, montant=montant, numero=numero)
        self.stdout.write(f"Demande : {reponse.etat} — {reponse.message}")
        if reponse.etat != "initiee":
            raise CommandError("MTN a refusé la demande : l'intégration n'est pas validée.")
        # Le bac à sable tranche en quelques secondes ; on relit trois fois.
        for _ in range(3):
            time.sleep(3)
            statut = mtn.statut(reponse.reference_externe)
            self.stdout.write(f"Statut : {statut.etat} — {statut.message}")
            if statut.etat != "initiee":
                break
        if statut.etat == "reussie":
            self.stdout.write(self.style.SUCCESS("Aller-retour MTN réussi : collecte validée."))
        else:
            self.stdout.write(self.style.WARNING("Pas de réussite : relisez le numéro de test."))

    def _orange(self, reference, montant, retour):
        from django.conf import settings

        retour = retour or f"{(settings.URL_PUBLIQUE or '').rstrip('/')}/marche/"
        orange = AdaptateurOrangeMoney()
        reponse = orange.initier(reference=reference, montant=montant, numero="", url_retour=retour)
        self.stdout.write(f"Demande : {reponse.etat} — {reponse.message}")
        if reponse.etat != "initiee":
            raise CommandError("Orange a refusé la demande : l'intégration n'est pas validée.")
        self.stdout.write(
            "Ouvrez cette adresse, payez avec un compte de test Orange, puis relancez la lecture :\n"
            f"  {reponse.charge_utile['payment_url']}"
        )
        statut = orange.statut(reponse.reference_externe, charge_utile=reponse.charge_utile)
        self.stdout.write(f"Statut actuel : {statut.etat} — {statut.message}")
        self.stdout.write(self.style.SUCCESS("Aller-retour Orange réussi : la demande est acceptée."))
