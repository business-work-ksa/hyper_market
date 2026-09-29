"""Poser l'administrateur de la plateforme, et son compte de commerçant s'il en veut un.

Le besoin, tel qu'il a été formulé : « l'administrateur administre les administrateurs des
boutiques, et il peut être lui-même propriétaire de boutiques ».

Les deux moitiés de cette phrase ne se posent pas sur le même compte, et l'ADR-012 dit pourquoi :
**deux casquettes, deux comptes.** Ce n'est pas de la bureaucratie, c'est ce qui rend le journal
des accès lisible. Avec un compte unique, chaque ligne du journal est ambiguë — cette personne
agissait-elle comme exploitant du marché ou comme concurrent des autres boutiques ? Avec deux, la
question ne se pose plus, et le jour où un commerçant la pose, la réponse existe.

Cette commande pose donc, séparément :

* **l'administrateur de la plateforme** — `is_staff`, rôle `ADMIN_MARCHE`, et **aucun droit sur
  aucune boutique**. Il administre les comptes et les rattachements depuis `/admin/`, c'est-à-dire
  qu'il administre bien les gérants des boutiques. Il ne voit pas leurs marges ;
* **son compte de commerçant**, s'il est demandé — un compte ordinaire, avec une `Appartenance`
  de gérant sur une boutique. C'est avec celui-là qu'il entre dans le back-office.

Tout vient de l'environnement, jamais du dépôt, et tout est idempotent : la commande est faite
pour tourner à chaque mise en ligne sans rien abîmer.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Appartenance, Role, RolePlateforme
from apps.core.tenancy import contexte_plateforme
from apps.marketplace.models import Boutique


class Command(BaseCommand):
    help = "Pose le rôle plateforme de l'administrateur, et son compte de commerçant."

    def add_arguments(self, parser):
        parser.add_argument(
            "--telephone",
            required=True,
            help="Numéro de l'administrateur de la plateforme. Le compte doit déjà exister.",
        )
        parser.add_argument(
            "--commercant",
            default="",
            help=(
                "Numéro du **second** compte, celui de commerçant. Créé s'il manque, et "
                "rattaché comme gérant. Laisser vide si l'administrateur ne vend pas."
            ),
        )
        parser.add_argument(
            "--nom-commercant",
            default="",
            help="Nom affiché du compte de commerçant. Défaut : celui de l'administrateur.",
        )
        parser.add_argument(
            "--boutique",
            default="",
            help=(
                "Raison sociale de la boutique à lui confier. Vide : la première de la base, "
                "ce qui n'a de sens que sur une démonstration."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        Utilisateur = get_user_model()

        administrateur = Utilisateur.objects.filter(telephone=options["telephone"]).first()
        if administrateur is None:
            self.stderr.write(
                self.style.ERROR(
                    f"Aucun compte au numéro {options['telephone']}. Créez-le d'abord "
                    "(createsuperuser), puis relancez : cette commande pose des rôles, "
                    "elle ne fabrique pas d'administrateur."
                )
            )
            return

        self._poser_le_role_plateforme(administrateur)

        if options["commercant"]:
            self._poser_le_compte_de_commercant(
                administrateur,
                telephone=options["commercant"],
                nom=options["nom_commercant"],
                raison_sociale=options["boutique"],
            )

    def _poser_le_role_plateforme(self, administrateur) -> None:
        """`ADMIN_MARCHE` : les cinq droits d'exploitation, et aucun droit de boutique."""
        role, cree = Role.objects.get_or_create(
            code=Role.ADMIN_MARCHE,
            defaults={"libelle": "Gestionnaire du marché", "portee": Role.PLATEFORME},
        )
        if cree:
            self.stdout.write(
                "  rôle ADMIN_MARCHE absent des référentiels : créé "
                "(lancez `initialiser_referentiels` pour le reste)."
            )

        _, nouveau = RolePlateforme.objects.get_or_create(
            utilisateur=administrateur,
            role=role,
            actif=True,
            defaults={"motif": "Exploitant de la place de marché."},
        )
        verbe = "posé" if nouveau else "déjà en place"
        self.stdout.write(f"  administrateur de plateforme : {administrateur.nom_complet} — {verbe}")

        if not administrateur.is_staff:
            administrateur.is_staff = True
            administrateur.save(update_fields=["is_staff"])
            self.stdout.write("  is_staff posé : sans lui, /admin/ est fermé.")

    def _poser_le_compte_de_commercant(
        self, administrateur, *, telephone: str, nom: str, raison_sociale: str
    ) -> None:
        Utilisateur = get_user_model()

        if telephone == administrateur.telephone:
            self.stderr.write(
                self.style.ERROR(
                    "Le compte de commerçant doit avoir un numéro distinct de celui de "
                    "l'administrateur : c'est tout l'objet de la séparation (ADR-012)."
                )
            )
            return

        with contexte_plateforme():
            if raison_sociale:
                boutique = Boutique.objects.filter(raison_sociale=raison_sociale).first()
            else:
                boutique = Boutique.objects.order_by("cree_le").first()

        if boutique is None:
            self.stderr.write(
                self.style.ERROR(
                    "Aucune boutique à confier"
                    + (f" sous le nom « {raison_sociale} »" if raison_sociale else "")
                    + ". Chargez d'abord des boutiques, ou créez-en une."
                )
            )
            return

        commercant, cree = Utilisateur.objects.get_or_create(
            telephone=telephone,
            defaults={"nom_complet": nom or f"{administrateur.nom_complet} (commerçant)"},
        )
        if cree:
            # Pas de mot de passe utilisable : il se pose par la réinitialisation, ou par
            # l'administration. Un mot de passe par défaut dans une commande est un mot de
            # passe qui survit en production.
            commercant.set_unusable_password()
            commercant.save(update_fields=["password"])
            self.stdout.write(
                f"  compte de commerçant créé : {telephone} — sans mot de passe utilisable, "
                "à définir depuis /admin/."
            )

        role, _ = Role.objects.get_or_create(
            code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
        )
        _, nouveau = Appartenance.objects.get_or_create(
            utilisateur=commercant, boutique=boutique, role=role, actif=True
        )
        verbe = "rattaché" if nouveau else "déjà rattaché"
        self.stdout.write(f"  gérant de « {boutique.raison_sociale} » : {verbe}")
