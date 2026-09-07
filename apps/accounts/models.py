"""Identité, rôles et appartenances.

Le **numéro de téléphone** est l'identifiant principal : au Cameroun, l'adresse électronique n'est
pas un identifiant fiable pour un commerçant (docs/05-perimetre-fonctionnel.md, M01).
"""

import secrets

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from apps.core.uuid7 import uuid7

# Alphabet sans caractères ambigus : ni O/0, ni I/1. Le code est dicté oralement ou saisi à la
# main par un filleul, la lisibilité prime sur l'entropie.
ALPHABET_CODE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

validateur_telephone = RegexValidator(
    r"^\+?[0-9]{8,15}$",
    "Numéro de téléphone invalide. Format attendu : +237699000000.",
)


def generer_code_apporteur() -> str:
    """Code d'apporteur unique, court et prononçable (voir docs/06, §2.1)."""
    from django.db import IntegrityError  # noqa: F401  (documentaire : unicité en base)

    return "HM-" + "".join(secrets.choice(ALPHABET_CODE) for _ in range(6))


class UtilisateurManager(BaseUserManager):
    def create_user(self, telephone, password=None, **extra):
        if not telephone:
            raise ValueError("Le numéro de téléphone est obligatoire.")
        utilisateur = self.model(telephone=telephone, **extra)
        utilisateur.set_password(password)
        utilisateur.save(using=self._db)
        return utilisateur

    def create_superuser(self, telephone, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("nom_complet", "Administrateur")
        return self.create_user(telephone, password, **extra)


class Utilisateur(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    telephone = models.CharField(
        max_length=16, unique=True, validators=[validateur_telephone], verbose_name="téléphone"
    )
    email = models.EmailField(blank=True)
    nom_complet = models.CharField(max_length=150)
    code_apporteur = models.CharField(
        max_length=12,
        unique=True,
        default=generer_code_apporteur,
        editable=False,
        help_text="Code de parrainage, immuable pour la vie du compte.",
    )
    telephone_verifie = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, verbose_name="accès à l'administration")
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UtilisateurManager()

    USERNAME_FIELD = "telephone"
    REQUIRED_FIELDS = ["nom_complet"]

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        ordering = ["nom_complet"]

    def __str__(self):
        return f"{self.nom_complet} ({self.telephone})"

    def boutiques_actives(self):
        from apps.marketplace.models import Boutique

        ids = self.appartenances.filter(actif=True).values_list("boutique_id", flat=True)
        return Boutique.objects.filter(id__in=ids)

    def a_role(self, code_role, boutique=None) -> bool:
        qs = self.appartenances.filter(actif=True, role__code=code_role)
        if boutique is not None:
            qs = qs.filter(boutique_id=getattr(boutique, "pk", boutique))
        return qs.exists()


class Role(models.Model):
    """Rôle applicatif. La portée distingue les rôles de boutique des rôles plateforme."""

    BOUTIQUE = "boutique"
    PLATEFORME = "plateforme"
    PORTEES = [(BOUTIQUE, "Boutique"), (PLATEFORME, "Plateforme")]

    # Rôles de boutique
    GERANT = "GERANT"
    VENDEUR = "VENDEUR"
    CAISSIER = "CAISSIER"
    MAGASINIER = "MAGASINIER"
    COMPTABLE = "COMPTABLE"
    RH = "RH"
    # Rôles plateforme
    RESP_RAYON = "RESP_RAYON"
    ADMIN_MARCHE = "ADMIN_MARCHE"
    CABINET = "CABINET"

    code = models.CharField(max_length=32, primary_key=True)
    libelle = models.CharField(max_length=64)
    portee = models.CharField(max_length=16, choices=PORTEES, default=BOUTIQUE)
    permissions = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "rôle"
        ordering = ["portee", "code"]

    def __str__(self):
        return self.libelle


class Appartenance(models.Model):
    """Rattachement d'un utilisateur à une boutique, avec un rôle.

    Un même utilisateur peut travailler dans plusieurs boutiques : le comptable d'un groupe, ou le
    gérant qui exploite deux enseignes.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.CASCADE, related_name="appartenances"
    )
    boutique = models.ForeignKey(
        "marketplace.Boutique", on_delete=models.CASCADE, related_name="appartenances"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="appartenances")
    actif = models.BooleanField(default=True)
    depuis = models.DateField(default=timezone.localdate)
    jusqu_a = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "appartenance"
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "boutique", "role"],
                condition=models.Q(actif=True),
                name="appartenance_unique_active",
            )
        ]

    def __str__(self):
        return f"{self.utilisateur.nom_complet} · {self.role.libelle} · {self.boutique}"


class DossierKyc(models.Model):
    """Vérification d'identité d'un marchand ou d'un affilié (docs/08, §5.3)."""

    CNI = "CNI"
    PASSEPORT = "PASSEPORT"
    RCCM = "RCCM"
    NIU = "NIU"
    TYPES_PIECE = [
        (CNI, "Carte nationale d'identité"),
        (PASSEPORT, "Passeport"),
        (RCCM, "Registre du commerce"),
        (NIU, "Numéro identifiant unique"),
    ]

    EN_ATTENTE = "en_attente"
    VALIDE = "valide"
    REJETE = "rejete"
    ETATS = [(EN_ATTENTE, "En attente"), (VALIDE, "Validé"), (REJETE, "Rejeté")]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    utilisateur = models.ForeignKey(
        Utilisateur, null=True, blank=True, on_delete=models.CASCADE, related_name="dossiers_kyc"
    )
    boutique = models.ForeignKey(
        "marketplace.Boutique",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="dossiers_kyc",
    )
    type_piece = models.CharField(max_length=16, choices=TYPES_PIECE)
    numero = models.CharField(max_length=64)
    etat = models.CharField(max_length=16, choices=ETATS, default=EN_ATTENTE)
    verifie_par = models.ForeignKey(
        Utilisateur, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verifie_le = models.DateTimeField(null=True, blank=True)
    motif_rejet = models.TextField(blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "dossier KYC"
        verbose_name_plural = "dossiers KYC"

    def __str__(self):
        return f"{self.get_type_piece_display()} {self.numero} · {self.get_etat_display()}"
