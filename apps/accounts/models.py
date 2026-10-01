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
    # Prévenir cette personne sur WhatsApp de chaque nouvelle commande (`apps/orders/avis.py`).
    # Ne vaut que si son rôle ouvre `commandes.traiter` : l'avis ne donne jamais à voir ce que le
    # rôle ne montre pas. Le gérant le coupe pour qui ne veut pas être dérangé.
    avis_commandes = models.BooleanField(
        default=True, verbose_name="prévenir des commandes sur WhatsApp"
    )

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


class RolePlateforme(models.Model):
    """Rattachement d'un utilisateur à un rôle **de la plateforme**, sans boutique (ADR-012).

    **Pourquoi un modèle distinct et non une `Appartenance` sans boutique.** Une appartenance dit
    « cette personne travaille dans cette boutique ». Un rôle de plateforme dit l'inverse : cette
    personne exploite le marché, elle ne travaille chez personne. Rendre `Appartenance.boutique`
    nullable aurait eu trois effets tous mauvais : chaque `filter(boutique_id=…)` aurait
    silencieusement ignoré ces lignes, la contrainte d'unicité aurait demandé un second index
    partiel, et une ligne à `NULL` aurait pu satisfaire des requêtes qui ne l'attendaient pas.

    Séparé, il répond en une requête à la question que pose un auditeur : **qui exploite cette place
    de marché ?**

    Avant cet ajout, les rôles de portée plateforme existaient dans les référentiels mais
    **personne ne pouvait les porter** — ce qui explique qu'aucune vue ne les consommait.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.CASCADE, related_name="roles_plateforme"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="porteurs_plateforme")
    actif = models.BooleanField(default=True)
    depuis = models.DateField(default=timezone.localdate)
    jusqu_a = models.DateField(null=True, blank=True)
    motif = models.CharField(
        max_length=300,
        blank=True,
        help_text="Pourquoi cette personne exploite le marché. Utile le jour où on se le demande.",
    )

    class Meta:
        verbose_name = "rôle plateforme"
        verbose_name_plural = "rôles plateforme"
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "role"],
                condition=models.Q(actif=True),
                name="role_plateforme_unique_actif",
            )
        ]

    def __str__(self):
        return f"{self.utilisateur.nom_complet} · {self.role.libelle} (plateforme)"

    def clean(self):
        """Refuse un rôle de boutique ici : la portée est la seule chose qui distingue les deux tables."""
        from django.core.exceptions import ValidationError

        if self.role_id and self.role.portee != Role.PLATEFORME:
            raise ValidationError(
                {
                    "role": (
                        f"« {self.role.libelle} » est un rôle de boutique. Un rôle de boutique "
                        "se porte par une appartenance, qui nomme la boutique."
                    )
                }
            )


class DossierKyc(models.Model):
    """Une vérification d'identité **attestée** : ce qu'un administrateur a vu, pas une photocopie.

    Une ligne par pièce : la pièce d'identité d'un gérant, le RCCM ou l'identifiant fiscal d'une
    boutique, l'appel de vérification d'un téléphone (docs/08, §5.3). Les règles qui s'en servent
    — ce qu'il faut pour activer une boutique, qui a le droit de valider — sont dans
    `apps/confiance/verification.py` ; ce modèle ne fait que garder la preuve.

    **Minimisation (loi n° 2024/017, docs/08, §4).** Par défaut, la plateforme ne garde **pas**
    la copie d'une pièce. L'administrateur voit l'original — en face à face, en visio, ou sur une
    photo reçue par un canal sûr, qu'il supprime ensuite — et consigne ce qu'il a lu : type,
    numéro, pays émetteur, date d'expiration, nom tel qu'il est écrit, et comment il l'a vu. Si un
    document lui a été transmis, son **empreinte SHA-256** prouve plus tard qu'on a vu *ce*
    document-là, sans le conserver. Trois raisons :

    * une base de cartes d'identité est la cible la plus rentable d'une fuite, et ce qu'on n'a pas
      ne fuit pas ;
    * la finalité — s'assurer qu'une personne réelle et identifiée tient la boutique — est
      atteinte par l'attestation ; la copie n'ajoute rien à la décision ;
    * la production tourne sans disque durable (ADR-008) : une copie écrite aujourd'hui
      disparaîtrait au prochain démarrage à froid, et une preuve qui s'évapore est pire que pas de
      preuve, parce qu'on croit l'avoir.

    Garder une copie reste possible, **seulement** si un stockage persistant est désigné par un
    réglage explicite (`KYC_STOCKAGE_COPIES`) ; `copie` en garde alors le chemin.

    **Le numéro non plus n'est pas gardé en clair.** On en garde deux choses : une **empreinte à
    clé** (HMAC-SHA256, clé dérivée de `SECRET_KEY` — `verification.empreinte_numero`) et ses
    **quatre derniers caractères**. L'empreinte suffit à tout ce qu'on fait d'un numéro :
    retrouver la même pièce présentée pour deux personnes, vérifier que le RCCM validé est bien
    celui de la fiche. Les quatre caractères suffisent à l'afficher masqué (`••••••4521`). Une
    sauvegarde de la base qui fuit ne livre donc aucun numéro de pièce ; et contrairement à une
    empreinte sans clé, celle-ci ne se retrouve pas en essayant tous les numéros possibles, faute
    de connaître la clé.

    **Quatre yeux.** `declare_par` a consigné l'attestation, `verifie_par` l'a validée : jamais la
    même personne. La base le refuse aussi (contrainte `kyc_quatre_yeux`), pour le jour où un
    script passerait à côté du service.
    """

    # Pièces d'une personne physique — les codes sont ceux de `apps/marketplace/cemac.py`.
    CNI = "CNI"
    PASSEPORT = "PASSEPORT"
    CARTE_CONSULAIRE = "CARTE_CONSULAIRE"
    TITRE_SEJOUR = "TITRE_SEJOUR"
    # Pièces d'une boutique
    # Le RCCM d'une société ou d'un commerçant **et** la déclaration d'un entreprenant (OHADA,
    # AUDCG révisé) : les deux s'inscrivent au registre, sous un numéro qu'on vérifie de même.
    # Refuser l'entreprenant serait refuser une grande part des commerçants visés (docs/23, §4.1).
    RCCM = "RCCM"
    NIU = "NIU"  # Cameroun, Congo
    NIF = "NIF"  # Gabon, Tchad, RCA, Guinée équatoriale
    # Attestation d'un appel de vérification du téléphone du gérant
    TELEPHONE = "TELEPHONE"
    TYPES_PIECE = [
        (CNI, "Carte nationale d'identité"),
        (PASSEPORT, "Passeport"),
        (CARTE_CONSULAIRE, "Carte consulaire"),
        (TITRE_SEJOUR, "Titre de séjour"),
        (RCCM, "RCCM — immatriculation ou déclaration d'entreprenant"),
        (NIU, "Numéro d'identifiant unique (NIU)"),
        (NIF, "Numéro d'identification fiscale (NIF)"),
        (TELEPHONE, "Appel de vérification du téléphone"),
    ]
    PIECES_IDENTITE = frozenset({CNI, PASSEPORT, CARTE_CONSULAIRE, TITRE_SEJOUR})
    PIECES_BOUTIQUE = frozenset({RCCM, NIU, NIF})

    PRESENTIEL = "presentiel"
    VISIO = "visio"
    DOCUMENT_RECU = "document_recu"
    APPEL = "appel"
    MODES = [
        (PRESENTIEL, "Original vu en présentiel"),
        (VISIO, "Original vu en visio"),
        (DOCUMENT_RECU, "Document reçu, puis supprimé"),
        (APPEL, "Appel de vérification"),
    ]

    EN_ATTENTE = "en_attente"
    VALIDE = "valide"
    REJETE = "rejete"
    ETATS = [(EN_ATTENTE, "En attente"), (VALIDE, "Validé"), (REJETE, "Rejeté")]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    utilisateur = models.ForeignKey(
        Utilisateur,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="dossiers_kyc",
        help_text="La personne dont c'est la pièce (le gérant). Vide pour une pièce de boutique.",
    )
    boutique = models.ForeignKey(
        "marketplace.Boutique",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="dossiers_kyc",
        help_text="La boutique pour laquelle la pièce a été présentée.",
    )
    type_piece = models.CharField(max_length=16, choices=TYPES_PIECE)
    numero_empreinte = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name="empreinte du numéro",
        help_text="HMAC-SHA256 du numéro normalisé : compare sans révéler. Le numéro lui-même n'est pas gardé.",
    )
    numero_fin = models.CharField(
        max_length=4, blank=True, verbose_name="fin du numéro", help_text="Les quatre derniers caractères, pour l'affichage masqué."
    )
    pays = models.CharField(
        max_length=2, default="CM", verbose_name="pays émetteur", help_text="Code ISO à deux lettres."
    )
    expire_le = models.DateField(
        null=True, blank=True, verbose_name="date d'expiration", help_text="Vide : pièce sans échéance (RCCM, NIU)."
    )
    nom_lu = models.CharField(
        max_length=160,
        blank=True,
        verbose_name="nom tel qu'il figure",
        help_text="Recopié de la pièce, pas du compte : c'est à lui qu'on compare le titulaire du compte de versement.",
    )
    mode_verification = models.CharField(
        max_length=16, choices=MODES, default=PRESENTIEL, verbose_name="mode de vérification"
    )
    empreinte = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="empreinte SHA-256",
        help_text="Du document reçu, s'il y en a eu un : la preuve qu'on a vu celui-là, sans le garder.",
    )
    copie = models.CharField(
        max_length=255,
        blank=True,
        help_text="Chemin de la copie dans le stockage persistant désigné. Vide par défaut, et c'est voulu.",
    )
    etat = models.CharField(max_length=16, choices=ETATS, default=EN_ATTENTE, db_index=True)
    declare_par = models.ForeignKey(
        Utilisateur, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="déclaré par",
    )
    verifie_par = models.ForeignKey(
        Utilisateur, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="vérifié par",
    )
    verifie_le = models.DateTimeField(null=True, blank=True)
    motif_rejet = models.TextField(blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "dossier KYC"
        verbose_name_plural = "dossiers KYC"
        ordering = ["-cree_le"]
        constraints = [
            # Deux personnes distinctes : celle qui a vu, celle qui valide. Le service le refuse
            # avec une phrase ; la base le refuse pour tout ce qui passerait à côté du service.
            models.CheckConstraint(
                condition=(
                    models.Q(declare_par__isnull=True)
                    | models.Q(verifie_par__isnull=True)
                    | ~models.Q(declare_par=models.F("verifie_par"))
                ),
                name="kyc_quatre_yeux",
            ),
            models.CheckConstraint(
                condition=models.Q(utilisateur__isnull=False) | models.Q(boutique__isnull=False),
                name="kyc_rattache_a_quelqu_un",
            ),
        ]

    def __str__(self):
        # Masqué : `__str__` finit dans les listes de l'administration et dans les journaux.
        return f"{self.get_type_piece_display()} {self.numero_masque} · {self.get_etat_display()}"

    @property
    def numero_masque(self) -> str:
        return "••••••" + (self.numero_fin or "")

    @property
    def est_piece_identite(self) -> bool:
        return self.type_piece in self.PIECES_IDENTITE

    def expire_avant(self, jour) -> bool:
        return self.expire_le is not None and self.expire_le < jour
