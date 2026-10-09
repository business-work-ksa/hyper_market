"""Émission d'un jeton d'API.

    python manage.py creer_jeton_api +237699110011 --boutique <uuid> \
        --libelle "Tablette du comptoir 2"

Le secret n'est affiché qu'ici, une seule fois. Il n'est écrit dans aucun
journal et ne peut pas être relu : la base n'en conserve qu'une empreinte.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Utilisateur
from apps.accounts.permissions import droits_de
from apps.api.models import JetonApi
from apps.core.tenancy import contexte_plateforme
from apps.marketplace.models import Boutique


class Command(BaseCommand):
    help = "Émet un jeton d'API pour un utilisateur sur une boutique."

    def add_arguments(self, parseur):
        parseur.add_argument("telephone", help="Téléphone de l'utilisateur porteur.")
        parseur.add_argument(
            "--boutique",
            help="Identifiant de la boutique. Facultatif si l'utilisateur n'en a qu'une.",
        )
        parseur.add_argument("--libelle", default="Jeton d'API", help="À quoi sert ce jeton.")

    def handle(self, *args, **options):
        utilisateur = Utilisateur.objects.filter(telephone=options["telephone"]).first()
        if utilisateur is None:
            raise CommandError(f"Aucun utilisateur avec le téléphone {options['telephone']}.")

        with contexte_plateforme():
            boutique = self._boutique(utilisateur, options.get("boutique"))
            jeton, secret = JetonApi.emettre(
                utilisateur=utilisateur, boutique=boutique, libelle=options["libelle"]
            )
            droits = droits_de(utilisateur, boutique)

        self.stdout.write(self.style.SUCCESS("Jeton émis."))
        self.stdout.write(f"  Boutique : {boutique.raison_sociale}")
        self.stdout.write(f"  Porteur  : {utilisateur.nom_complet}")
        self.stdout.write(f"  Droits   : {', '.join(sorted(droits)) or '— aucun —'}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("  " + secret))
        self.stdout.write("")
        self.stdout.write(
            "Copiez-le maintenant : il ne sera plus affiché, et la base n'en garde "
            "qu'une empreinte.\n"
            "Usage : en-tête   Authorization: Bearer <jeton>"
        )
        if not droits:
            self.stdout.write(
                self.style.NOTICE(
                    "Ce porteur n'a aucun droit sur cette boutique : le jeton "
                    "s'authentifiera mais tout appel sera refusé."
                )
            )

    @staticmethod
    def _boutique(utilisateur, identifiant) -> Boutique:
        if identifiant:
            boutique = Boutique.objects.filter(pk=identifiant).first()
            if boutique is None:
                raise CommandError(f"Aucune boutique avec l'identifiant {identifiant}.")
            return boutique

        appartenances = list(utilisateur.appartenances.filter(actif=True).select_related("boutique")[:2])
        if len(appartenances) != 1:
            raise CommandError(
                "Cet utilisateur appartient à zéro ou plusieurs boutiques : "
                "précisez --boutique."
            )
        return appartenances[0].boutique
