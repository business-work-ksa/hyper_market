"""Recalcule les paliers de confiance et les signaux de risque. Pensée pour tourner chaque nuit.

Idempotente : la relancer le même jour ne fait monter aucune boutique une seconde fois (fenêtre
de litige entre deux montées, `apps/confiance/paliers.py`) et ne duplique aucun signal (un signal
ouvert est mis à jour, `apps/confiance/signaux.py`). On peut donc la relancer après une panne sans
se demander si la première passe avait abouti.

Elle ne suspend **aucune** boutique. Elle prépare le travail d'un humain.
"""

from django.core.management.base import BaseCommand

from apps.confiance.paliers import evaluer_paliers
from apps.confiance.signaux import evaluer_signaux


class Command(BaseCommand):
    help = "Recalcule les paliers de confiance des boutiques et les signaux de risque (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sans-signaux", action="store_true", help="Recalculer seulement les paliers."
        )

    def handle(self, *args, **options):
        # Les paliers d'abord : les détecteurs lisent le palier à jour (plafond de séquestre).
        bavard = options.get("verbosity", 1) > 0
        paliers = evaluer_paliers()
        if bavard:
            self.stdout.write(
                f"Paliers : {paliers['evaluees']} boutique(s) évaluée(s), "
                f"{paliers['montees']} montée(s), {paliers['descentes']} rétrogradation(s)."
            )
        if options["sans_signaux"]:
            return
        signaux = evaluer_signaux()
        if bavard:
            self.stdout.write(
                f"Signaux : {signaux['crees']} nouveau(x), {signaux['mis_a_jour']} mis à jour, "
                f"{signaux['deja_juges']} déjà jugé(s) et non rouvert(s)."
            )
