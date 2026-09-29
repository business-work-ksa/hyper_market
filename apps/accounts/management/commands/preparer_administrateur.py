"""Poser les trois niveaux d'administration, chacun à sa place.

Ils étaient confondus en un seul. La distinction, telle qu'elle a été formulée :

* le **superadministrateur** est celui qui administre tout dans l'application, et qui détient le
  rôle de superutilisateur de Django ;
* l'**administrateur du marché** administre les administrateurs des boutiques, et peut être
  lui-même propriétaire de boutiques ;
* le **gérant** administre une boutique.

Ce ne sont pas trois degrés d'un même pouvoir, ce sont trois métiers. Le superadministrateur est
un recours technique : il existe pour le jour où quelque chose est cassé, et ce jour-là il doit
tout pouvoir. L'administrateur du marché est un métier quotidien : il valide des boutiques,
suspend pour loyer impayé, vend des emplacements. Confondre les deux, c'est faire du geste
quotidien un acte de superutilisateur — et perdre la seule chose qui rende un journal d'accès
utile : savoir que celui qui a regardé n'aurait pas pu regarder autre chose.

Et la seconde moitié de la phrase — « il peut être lui-même propriétaire de boutiques » — ne se
pose pas sur le même compte que la première (ADR-012). Avec un compte unique, chaque ligne du
journal est ambiguë : cette personne agissait-elle comme exploitant du marché ou comme concurrent
des autres boutiques ? Avec deux comptes, la question ne se pose plus.

Tout vient de l'environnement, jamais du dépôt. Tout est idempotent : la commande est faite pour
tourner à chaque mise en ligne sans rien abîmer.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.administration import NOM_GROUPE, synchroniser_le_groupe
from apps.accounts.models import Appartenance, Role, RolePlateforme
from apps.core.tenancy import contexte_plateforme
from apps.marketplace.models import Boutique


class Command(BaseCommand):
    help = "Pose le superadministrateur, l'administrateur du marché et son compte de commerçant."

    def add_arguments(self, parser):
        parser.add_argument(
            "--superadmin",
            default="",
            help=(
                "Numéro du superadministrateur : `is_superuser` et `is_staff`. Il administre "
                "tout, sans exception. Le compte doit déjà exister (createsuperuser)."
            ),
        )
        parser.add_argument(
            "--administrateur",
            default="",
            help=(
                "Numéro de l'administrateur du marché : `is_staff`, rôle ADMIN_MARCHE, et le "
                "groupe de permissions nommé — mais **pas** `is_superuser`. Créé s'il manque."
            ),
        )
        parser.add_argument(
            "--nom-administrateur",
            default="Administrateur du marché",
            help="Nom affiché de l'administrateur du marché, s'il faut le créer.",
        )
        parser.add_argument(
            "--commercant",
            default="",
            help=(
                "Numéro du compte de commerçant de l'administrateur — un **autre** numéro. "
                "Rattaché comme gérant. Vide si l'administrateur ne vend pas."
            ),
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
        groupe = self._synchroniser_les_permissions()

        if options["superadmin"]:
            self._poser_le_superadministrateur(options["superadmin"])

        administrateur = None
        if options["administrateur"]:
            administrateur = self._poser_l_administrateur_du_marche(
                options["administrateur"], options["nom_administrateur"], groupe
            )

        if options["commercant"]:
            self._poser_le_compte_de_commercant(
                telephone=options["commercant"],
                administrateur=administrateur,
                raison_sociale=options["boutique"],
            )

    # -- Le groupe ---------------------------------------------------------------------------

    def _synchroniser_les_permissions(self):
        groupe, manquantes = synchroniser_le_groupe()
        self.stdout.write(
            f"  groupe « {NOM_GROUPE} » : {groupe.permissions.count()} permissions posées"
        )
        if manquantes:
            # Signalé fort, pas tu : un nom de modèle mal orthographié produirait un
            # administrateur qui ne peut pas travailler, sans que rien ne l'explique.
            self.stderr.write(
                self.style.WARNING(
                    "  permissions introuvables (modèle renommé ou faute de frappe) : "
                    + ", ".join(manquantes)
                )
            )
        return groupe

    # -- Les trois personnages ---------------------------------------------------------------

    def _poser_le_superadministrateur(self, telephone: str) -> None:
        """Il administre tout. On ne le **crée** pas ici : `createsuperuser` est fait pour cela.

        La commande se contente de vérifier qu'il porte bien les deux drapeaux — parce qu'un
        superadministrateur sans `is_staff` ne peut pas ouvrir `/admin/`, ce qui est un piège
        discret : le compte a tous les droits et aucune porte.
        """
        Utilisateur = get_user_model()
        compte = Utilisateur.objects.filter(telephone=telephone).first()
        if compte is None:
            self.stderr.write(
                self.style.ERROR(
                    f"  superadministrateur : aucun compte au numéro {telephone}. "
                    "Créez-le par createsuperuser — cette commande pose des rôles, elle ne "
                    "fabrique pas de superutilisateur."
                )
            )
            return

        champs = []
        if not compte.is_superuser:
            compte.is_superuser = True
            champs.append("is_superuser")
        if not compte.is_staff:
            compte.is_staff = True
            champs.append("is_staff")
        if champs:
            compte.save(update_fields=champs)

        self.stdout.write(
            f"  superadministrateur : {compte.nom_complet} — "
            + (f"{', '.join(champs)} posé(s)" if champs else "déjà en place")
        )

    def _poser_l_administrateur_du_marche(self, telephone: str, nom: str, groupe):
        """Il administre les administrateurs des boutiques. Et **rien de ce qu'elles vendent**.

        Trois marques, et l'absence d'une quatrième :

        * `is_staff`, sans quoi `/admin/` est fermé ;
        * le groupe de permissions, sans quoi `/admin/` est **vide** — c'est ce qui rend la
          distinction opérante plutôt que déclarative ;
        * le rôle `ADMIN_MARCHE`, qui porte les cinq droits d'exploitation de l'ADR-012 ;
        * et **pas** `is_superuser`, qui les rendrait tous les trois décoratifs.
        """
        Utilisateur = get_user_model()
        compte, cree = Utilisateur.objects.get_or_create(
            telephone=telephone, defaults={"nom_complet": nom}
        )
        if cree:
            # Sans mot de passe utilisable : il se pose par la réinitialisation ou depuis
            # `/admin/`. Un mot de passe par défaut dans une commande est un mot de passe qui
            # survit en production.
            compte.set_unusable_password()
            compte.save(update_fields=["password"])
            self.stdout.write(
                f"  administrateur du marché créé : {telephone} — sans mot de passe "
                "utilisable, à définir depuis /admin/."
            )

        champs = []
        if not compte.is_staff:
            compte.is_staff = True
            champs.append("is_staff")
        if compte.is_superuser:
            # Le retirer, et le dire : c'est exactement la confusion que cette commande répare.
            compte.is_superuser = False
            champs.append("is_superuser retiré")
            self.stdout.write(
                "  is_superuser retiré de l'administrateur du marché : il aurait rendu "
                "décoratifs son groupe et son rôle (ADR-012)."
            )
        if champs:
            compte.save(update_fields=[c.split()[0] for c in champs])

        compte.groups.add(groupe)

        role, cree_role = Role.objects.get_or_create(
            code=Role.ADMIN_MARCHE,
            defaults={"libelle": "Gestionnaire du marché", "portee": Role.PLATEFORME},
        )
        if cree_role:
            self.stdout.write(
                "  rôle ADMIN_MARCHE absent des référentiels : créé (lancez "
                "`initialiser_referentiels` pour le reste)."
            )
        _, nouveau = RolePlateforme.objects.get_or_create(
            utilisateur=compte,
            role=role,
            actif=True,
            defaults={"motif": "Exploitant de la place de marché."},
        )
        self.stdout.write(
            f"  administrateur du marché : {compte.nom_complet} — rôle "
            + ("posé" if nouveau else "déjà en place")
        )
        return compte

    def _poser_le_compte_de_commercant(self, *, telephone: str, administrateur, raison_sociale):
        """Le second compte de la même personne : celui avec lequel elle vend.

        Il n'a rien de particulier — c'est un compte de gérant ordinaire, et c'est le but. Ce
        qui compte, c'est qu'il soit **distinct**, pour que le journal des accès reste lisible.
        """
        Utilisateur = get_user_model()

        if administrateur is not None and telephone == administrateur.telephone:
            self.stderr.write(
                self.style.ERROR(
                    "  le compte de commerçant doit avoir un numéro distinct de celui de "
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
                    "  aucune boutique à confier"
                    + (f" sous le nom « {raison_sociale} »" if raison_sociale else "")
                    + ". Chargez d'abord des boutiques, ou créez-en une."
                )
            )
            return

        nom = (
            f"{administrateur.nom_complet} (commerçant)"
            if administrateur is not None
            else "Commerçant"
        )
        commercant, cree = Utilisateur.objects.get_or_create(
            telephone=telephone, defaults={"nom_complet": nom}
        )
        if cree:
            commercant.set_unusable_password()
            commercant.save(update_fields=["password"])
            self.stdout.write(
                f"  compte de commerçant créé : {telephone} — sans mot de passe utilisable."
            )

        role, _ = Role.objects.get_or_create(
            code=Role.GERANT, defaults={"libelle": "Gérant", "portee": Role.BOUTIQUE}
        )
        _, nouveau = Appartenance.objects.get_or_create(
            utilisateur=commercant, boutique=boutique, role=role, actif=True
        )
        self.stdout.write(
            f"  gérant de « {boutique.raison_sociale} » : "
            + ("rattaché" if nouveau else "déjà rattaché")
        )
