"""Garnir une instance de démonstration, une seule fois, sans jamais écraser.

Une démonstration qui s'ouvre sur un écran de connexion vide ne démontre rien :
le visiteur n'a pas de compte, ne peut pas en créer, et repart. Il faut donc que
la première mise en route charge les référentiels et le jeu de six boutiques.

Mais elle doit le faire **une fois**. Les hébergeurs gratuits redémarrent
l'application à la moindre inactivité — plusieurs fois par jour — et rejouer le
chargement à chaque réveil rajouterait vingt jours de ventes par-dessus les
précédents, jusqu'à ce que la base gratuite soit pleine.

D'où une commande distincte de `charger_demo` plutôt qu'un drapeau ajouté à
celle-ci : le geste n'est pas le même. `charger_demo` **charge**, et quelqu'un
qui la lance sait ce qu'il fait. Celle-ci **s'assure qu'il y a quelque chose**,
et c'est ce qu'on met dans une commande de démarrage.

Elle refuse de travailler sur une base qui contient déjà des boutiques. C'est
la seule protection qui vaille : une instance de démonstration finit toujours
par être confondue avec une vraie, et le jour où cette commande atterrit dans le
démarrage d'une instance réelle, elle ne doit rien faire du tout.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.core.tenancy import contexte_plateforme
from apps.marketplace.models import Boutique


class Command(BaseCommand):
    help = "Charge le jeu de démonstration si, et seulement si, la base est vierge."

    def add_arguments(self, parser):
        parser.add_argument(
            "--jours",
            type=int,
            default=None,
            help=(
                "Transmis à `charger_demo`. Sert à charger un jeu plus court quand la base "
                "est lente : vingt jours de ventes simulées représentent plus de neuf mille "
                "requêtes, et une construction sans serveur a un délai maximal. Voir "
                "docs/20, §2 bis."
            ),
        )

    def handle(self, *args, **options):
        with contexte_plateforme():
            deja = Boutique.objects.exists()

        if deja:
            # Pas une erreur, et le code de sortie reste nul : c'est le cas
            # normal à tous les redémarrages sauf le premier.
            self.stdout.write("Des boutiques existent déjà : rien à charger.")
            return

        self.stdout.write("Base vierge — chargement du jeu de démonstration.")
        call_command("initialiser_referentiels")
        if options["jours"] is None:
            call_command("charger_demo")
        else:
            call_command("charger_demo", jours=options["jours"])
        self.stdout.write(self.style.SUCCESS("Démonstration prête."))
