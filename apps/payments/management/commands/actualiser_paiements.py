"""Relire les paiements restés en attente, et constater ceux que rien n'a constatés.

Une notification d'opérateur se perd ; un acheteur ferme sa page avant la fin. Sans ce filet, un
paiement réussi resterait sans séquestre et la commande n'avancerait jamais. Idempotent : un paiement
déjà constaté ne l'est pas deux fois. Une demande non validée au bout de 24 heures expire.
"""

from django.core.management.base import BaseCommand

from apps.payments.paiement_en_ligne import actualiser_en_attente
from apps.payments.versements import suivre_envois_en_cours


class Command(BaseCommand):
    help = "Relit les paiements et les versements en attente chez l'opérateur."

    def handle(self, *args, **options):
        bilan = actualiser_en_attente()
        envois = suivre_envois_en_cours()
        self.stdout.write(
            f"{bilan['relus']} paiement(s) en attente relu(s), {bilan['constates']} constaté(s) ; "
            f"{envois} versement(s) en cours relu(s)."
        )
