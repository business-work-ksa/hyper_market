"""Confirmations implicites et libérations échues des séquestres.

À lancer **périodiquement** — toutes les heures suffit, une fois par jour au minimum :

    python manage.py liberer_sequestres

Planification suggérée (cron, sur le serveur d'application) :

    17 * * * *  cd /app && python manage.py liberer_sequestres --verbosity 0

Ce qu'elle fait, pour chaque séquestre encore bloqué et sans litige en cours :

1. si la part a été expédiée il y a plus de sept jours sans confirmation de l'acheteur, la
   livraison est **réputée confirmée** à l'échéance (expédition + 7 jours) ;
2. si la livraison est confirmée depuis plus que le délai du palier de la boutique
   (`delai_liberation_jours`), la part est **libérée** : elle passe du bloqué au disponible.

Une livraison seulement *déclarée* par le marchand ne libère jamais rien : sans confirmation ni
délai de sept jours écoulé depuis l'expédition, la part reste bloquée.

**Idempotente.** Relancée, elle ne refait rien de ce qui est fait ; lancée deux fois en même temps,
chaque séquestre est verrouillé avant d'être tranché, et le second passage le trouve libéré. Un
retard de la tâche ne décale rien : les échéances se calculent sur les dates des faits, pas sur
l'heure du passage.

Option `--jusqu-au AAAA-MM-JJ` : rejoue la tâche comme si l'on était à cette date (fin de journée),
pour rattraper une interruption ou vérifier ce qui partira. Une date future est refusée : on ne
libère pas en avance.
"""

from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.payments.sequestre import liberer_echus


class Command(BaseCommand):
    help = "Confirme implicitement les livraisons anciennes et libère les séquestres échus."

    def add_arguments(self, parser):
        parser.add_argument(
            "--jusqu-au",
            dest="jusqu_au",
            help="Date de référence AAAA-MM-JJ (passée ou du jour), par défaut maintenant.",
        )

    def handle(self, *args, **options):
        maintenant = timezone.now()
        if options.get("jusqu_au"):
            try:
                jour = datetime.strptime(options["jusqu_au"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("Date attendue au format AAAA-MM-JJ.") from None
            reference = timezone.make_aware(datetime.combine(jour, time(23, 59, 59)))
            if jour > timezone.localdate():
                raise CommandError("On ne libère pas en avance : la date est dans le futur.")
            maintenant = min(reference, maintenant)

        bilan = liberer_echus(maintenant=maintenant)
        self.stdout.write(
            f"{bilan['confirmees']} livraison(s) réputée(s) confirmée(s), "
            f"{bilan['liberees']} séquestre(s) libéré(s), "
            f"{bilan['gelees']} gelé(s) par un litige, "
            f"{bilan['en_attente']} en attente."
        )
