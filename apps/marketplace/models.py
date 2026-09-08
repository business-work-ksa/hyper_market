"""Le marché, ses rayons et ses emplacements.

La `Boutique` est le **tenant** : toute donnée métier lui appartient. Le `Bail` matérialise la
métaphore centrale du produit — on ne vend pas un abonnement logiciel, on loue un emplacement,
avec loyer, dépôt de garantie, préavis et résiliation (docs/01, §4.1).
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel
from apps.core.uuid7 import uuid7


class Rayon(models.Model):
    """Rayon du marché. C'est lui qui porte le taux de commission (docs/06, §4.3)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    code = models.SlugField(max_length=48, unique=True)
    libelle = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="sous_rayons"
    )
    taux_commission = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("0.30"))],
        help_text="Part du montant HT revenant à la plateforme (0.05 = 5 %).",
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rayons_geres",
        help_text="Responsable de rayon (category manager) côté plateforme.",
    )
    ouvert = models.BooleanField(
        default=True,
        help_text="Un rayon fermé n'accepte plus de nouvelles boutiques (arbitrage A8).",
    )
    ordre = models.PositiveSmallIntegerField(default=100)

    class Meta:
        verbose_name = "rayon"
        ordering = ["ordre", "libelle"]

    def __str__(self):
        return self.libelle


class TypeEmplacement(models.Model):
    """Offre commerciale : Étal, Boutique, Grande surface (grille du docs/03, §1.1)."""

    ETAL = "ETAL"
    BOUTIQUE = "BOUTIQUE"
    GRANDE_SURFACE = "GRANDE_SURFACE"

    code = models.CharField(max_length=32, primary_key=True)
    libelle = models.CharField(max_length=64)
    loyer_mensuel = models.DecimalField(max_digits=12, decimal_places=2)
    taux_commission_defaut = models.DecimalField(max_digits=5, decimal_places=4)
    quota_utilisateurs = models.PositiveSmallIntegerField(default=1)
    quota_depots = models.PositiveSmallIntegerField(default=1)
    modules_inclus = models.JSONField(
        default=list, blank=True, help_text='Ex. ["catalogue", "stock", "caisse", "comptabilite"]'
    )
    ordre = models.PositiveSmallIntegerField(default=100)

    class Meta:
        verbose_name = "type d'emplacement"
        verbose_name_plural = "types d'emplacement"
        ordering = ["ordre"]

    def __str__(self):
        return f"{self.libelle} — {self.loyer_mensuel:,.0f} FCFA/mois".replace(",", " ")

    def module_inclus(self, code_module: str) -> bool:
        return code_module in (self.modules_inclus or [])


class Boutique(BaseModel):
    """Le tenant. Toute donnée métier du produit lui est rattachée."""

    CANDIDATURE = "candidature"
    ACTIVE = "active"
    SUSPENDUE = "suspendue"
    RESILIEE = "resiliee"
    ETATS = [
        (CANDIDATURE, "Candidature"),
        (ACTIVE, "Active"),
        (SUSPENDUE, "Suspendue"),
        (RESILIEE, "Résiliée"),
    ]

    # L'impôt libératoire et l'ancien régime simplifié ont été fusionnés dans l'IGS
    # (loi n° 2024/020, structurée par la loi de finances 2026) — voir docs/07, §5.
    IGS = "igs"
    REEL_SIMPLIFIE = "reel_simplifie"
    REEL_NORMAL = "reel_normal"
    REGIMES = [
        (IGS, "IGS — impôt général synthétique (CA ≤ 50 M)"),
        (REEL_SIMPLIFIE, "Réel simplifié (CA 50-100 M)"),
        (REEL_NORMAL, "Réel normal (CA > 100 M)"),
    ]

    raison_sociale = models.CharField(max_length=180)
    enseigne = models.CharField(max_length=120, help_text="Nom commercial affiché aux acheteurs.")
    slug = models.SlugField(max_length=140, unique=True)
    rccm = models.CharField(max_length=64, blank=True, verbose_name="RCCM")
    niu = models.CharField(max_length=32, blank=True, verbose_name="NIU")
    regime_fiscal = models.CharField(max_length=24, choices=REGIMES, default=REEL_SIMPLIFIE)
    rayon_principal = models.ForeignKey(
        Rayon, on_delete=models.PROTECT, related_name="boutiques", null=True, blank=True
    )
    telephone = models.CharField(max_length=16, blank=True)
    ville = models.CharField(max_length=80, default="Douala")
    pays = models.CharField(max_length=2, default="CM")
    devise = models.CharField(max_length=3, default="XAF")
    etat = models.CharField(max_length=16, choices=ETATS, default=CANDIDATURE, db_index=True)

    class Meta:
        verbose_name = "boutique"
        ordering = ["enseigne"]

    def __str__(self):
        return self.enseigne

    @property
    def bail_actif(self):
        return self.baux.filter(etat=Bail.ACTIF).order_by("-debut").first()

    @property
    def peut_vendre(self) -> bool:
        """Une boutique suspendue conserve son back-office mais disparaît de la vitrine.

        C'est un choix produit : couper la gestion d'un marchand en retard de loyer reviendrait à
        lui couper l'accès à sa propre comptabilité (docs/05, M02).
        """
        return self.etat == self.ACTIVE and self.bail_actif is not None


class Bail(BaseModel):
    """Contrat de location d'un emplacement."""

    BROUILLON = "brouillon"
    ACTIF = "actif"
    RESILIE = "resilie"
    ETATS = [(BROUILLON, "Brouillon"), (ACTIF, "Actif"), (RESILIE, "Résilié")]

    boutique = models.ForeignKey(Boutique, on_delete=models.PROTECT, related_name="baux")
    type_emplacement = models.ForeignKey(TypeEmplacement, on_delete=models.PROTECT)
    debut = models.DateField(default=timezone.localdate)
    fin = models.DateField(null=True, blank=True)
    loyer_mensuel = models.DecimalField(max_digits=12, decimal_places=2)
    depot_garantie = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    taux_commission = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        help_text="Négocié au contrat ; prime sur le taux du rayon.",
    )
    preavis_jours = models.PositiveSmallIntegerField(default=30)
    etat = models.CharField(max_length=16, choices=ETATS, default=BROUILLON, db_index=True)
    motif_resiliation = models.TextField(blank=True)

    class Meta:
        verbose_name = "bail"
        verbose_name_plural = "baux"
        ordering = ["-debut"]

    def __str__(self):
        return f"Bail {self.boutique} · {self.type_emplacement.libelle}"


class FactureLoyer(BaseModel):
    """Facture mensuelle de loyer. L'impayé déclenche la suspension (docs/08, §8)."""

    EMISE = "emise"
    PAYEE = "payee"
    IMPAYEE = "impayee"
    ANNULEE = "annulee"
    ETATS = [(EMISE, "Émise"), (PAYEE, "Payée"), (IMPAYEE, "Impayée"), (ANNULEE, "Annulée")]

    bail = models.ForeignKey(Bail, on_delete=models.PROTECT, related_name="factures")
    periode = models.DateField(help_text="Premier jour du mois facturé.")
    montant_ht = models.DecimalField(max_digits=12, decimal_places=2)
    taux_tva = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.1925"))
    echeance = models.DateField()
    etat = models.CharField(max_length=16, choices=ETATS, default=EMISE, db_index=True)
    paye_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "facture de loyer"
        verbose_name_plural = "factures de loyer"
        ordering = ["-periode"]
        constraints = [
            models.UniqueConstraint(fields=["bail", "periode"], name="loyer_unique_par_periode")
        ]

    def __str__(self):
        return f"Loyer {self.periode:%m/%Y} · {self.bail.boutique}"

    @property
    def montant_tva(self) -> Decimal:
        return (self.montant_ht * self.taux_tva).quantize(Decimal("0.01"))

    @property
    def montant_ttc(self) -> Decimal:
        return self.montant_ht + self.montant_tva


class EtatDesLieux(BaseModel):
    """Audit d'entrée ou de sortie d'un emplacement.

    À l'entrée : reprise du stock existant et des soldes comptables de départ. À la sortie :
    constat contradictoire avant restitution du dépôt de garantie.
    """

    ENTREE = "entree"
    SORTIE = "sortie"
    TYPES = [(ENTREE, "Entrée"), (SORTIE, "Sortie")]

    bail = models.ForeignKey(Bail, on_delete=models.CASCADE, related_name="etats_des_lieux")
    type = models.CharField(max_length=8, choices=TYPES)
    stock_initial = models.JSONField(default=list, blank=True)
    comptes_initiaux = models.JSONField(default=list, blank=True)
    constate_le = models.DateTimeField(default=timezone.now)
    commentaire = models.TextField(blank=True)

    class Meta:
        verbose_name = "état des lieux"
        verbose_name_plural = "états des lieux"

    def __str__(self):
        return f"État des lieux {self.get_type_display().lower()} · {self.bail.boutique}"


class EmplacementPremium(BaseModel):
    """Emplacement de mise en avant loué à la semaine (tête de gondole, bandeau de rayon).

    Première recette de retail media, avant le module publicitaire complet du lot 5.
    """

    TETE_DE_GONDOLE = "tete_de_gondole"
    BANDEAU_RAYON = "bandeau_rayon"
    ACCUEIL = "accueil"
    TYPES = [
        (TETE_DE_GONDOLE, "Tête de gondole"),
        (BANDEAU_RAYON, "Bandeau de rayon"),
        (ACCUEIL, "Page d'accueil"),
    ]

    rayon = models.ForeignKey(
        Rayon, null=True, blank=True, on_delete=models.CASCADE, related_name="emplacements_premium"
    )
    type = models.CharField(max_length=24, choices=TYPES)
    debut = models.DateField()
    fin = models.DateField()
    tarif = models.DecimalField(max_digits=12, decimal_places=2)
    boutique_occupante = models.ForeignKey(
        Boutique, null=True, blank=True, on_delete=models.SET_NULL, related_name="emplacements_premium"
    )

    class Meta:
        verbose_name = "emplacement premium"
        verbose_name_plural = "emplacements premium"
        ordering = ["-debut"]

    def __str__(self):
        return f"{self.get_type_display()} {self.debut:%d/%m} → {self.fin:%d/%m}"
