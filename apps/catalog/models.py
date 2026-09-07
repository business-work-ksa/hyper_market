"""Catalogue : catégories, référentiel mutualisé, produits et variantes.

Le `ProduitReference` est un référentiel **plateforme**, partagé entre toutes les boutiques et
indexé par code-barres : sans lui, quarante quincailleries ressaisiraient les mêmes quarante mille
articles (docs/05, M03).
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import BaseModel, TenantScopedModel
from apps.core.uuid7 import uuid7


class Categorie(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    rayon = models.ForeignKey("marketplace.Rayon", on_delete=models.PROTECT, related_name="categories")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="enfants"
    )
    libelle = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)

    class Meta:
        verbose_name = "catégorie"
        ordering = ["libelle"]
        constraints = [
            models.UniqueConstraint(fields=["rayon", "slug"], name="categorie_slug_unique_par_rayon")
        ]

    def __str__(self):
        return f"{self.rayon.libelle} › {self.libelle}"


class ProduitReference(models.Model):
    """Fiche produit mutualisée, identifiée par son code-barres (EAN/UPC)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    code_barres = models.CharField(max_length=32, unique=True)
    libelle = models.CharField(max_length=200)
    marque = models.CharField(max_length=120, blank=True)
    categorie = models.ForeignKey(
        Categorie, null=True, blank=True, on_delete=models.SET_NULL, related_name="references"
    )
    fiche = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "référence produit (plateforme)"
        verbose_name_plural = "références produit (plateforme)"
        ordering = ["libelle"]

    def __str__(self):
        return f"{self.libelle} [{self.code_barres}]"


class Produit(TenantScopedModel):
    """Produit d'une boutique."""

    UNITE = "U"
    KILOGRAMME = "KG"
    LITRE = "L"
    METRE = "M"
    UNITES = [(UNITE, "Unité"), (KILOGRAMME, "Kilogramme"), (LITRE, "Litre"), (METRE, "Mètre")]

    NORMAL = "normal"
    EXONERE = "exonere"
    HORS_CHAMP = "hors_champ"
    REGIMES_TVA = [
        (NORMAL, "Taux normal (19,25 %)"),
        (EXONERE, "Exonéré"),
        (HORS_CHAMP, "Hors champ"),
    ]

    reference = models.ForeignKey(
        ProduitReference, null=True, blank=True, on_delete=models.SET_NULL, related_name="produits"
    )
    sku = models.CharField(max_length=64)
    libelle = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    categorie = models.ForeignKey(
        Categorie, null=True, blank=True, on_delete=models.PROTECT, related_name="produits"
    )
    unite = models.CharField(max_length=4, choices=UNITES, default=UNITE)
    regime_tva = models.CharField(max_length=16, choices=REGIMES_TVA, default=NORMAL)
    actif = models.BooleanField(default=True)
    revente_autorisee = models.BooleanField(
        default=False, help_text="Le produit peut être poussé par les revendeurs affiliés."
    )
    marge_revendeur = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Part du HT laissée au revendeur (0.10 = 10 %). Prise sur la marge du marchand.",
    )

    class Meta:
        verbose_name = "produit"
        ordering = ["libelle"]
        constraints = [
            models.UniqueConstraint(fields=["boutique", "sku"], name="produit_sku_unique_par_boutique"),
            # La marge laissée au revendeur est une fraction du HT : elle ne peut pas dépasser 100 %.
            models.CheckConstraint(
                condition=models.Q(marge_revendeur__gte=0) & models.Q(marge_revendeur__lte=1),
                name="produit_marge_revendeur_entre_0_et_1",
            ),
        ]

    def __str__(self):
        return self.libelle

    @property
    def taux_tva(self) -> Decimal:
        if self.regime_tva != self.NORMAL:
            return Decimal("0")
        return Decimal(settings.TAUX_TVA_DEFAUT) / 100


class Variante(TenantScopedModel):
    """Déclinaison vendable d'un produit. **C'est la variante qui porte le prix et le stock.**"""

    produit = models.ForeignKey(Produit, on_delete=models.CASCADE, related_name="variantes")
    sku = models.CharField(max_length=64)
    code_barres = models.CharField(max_length=32, blank=True)
    attributs = models.JSONField(
        default=dict, blank=True, help_text='Ex. {"taille": "42", "couleur": "noir"}'
    )
    prix_vente = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    prix_barre = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "variante"
        ordering = ["produit__libelle", "sku"]
        constraints = [
            models.UniqueConstraint(fields=["boutique", "sku"], name="variante_sku_unique_par_boutique"),
            models.CheckConstraint(
                condition=models.Q(prix_vente__gte=0), name="variante_prix_positif"
            ),
        ]

    def __str__(self):
        if self.attributs:
            details = ", ".join(f"{k}: {v}" for k, v in self.attributs.items())
            return f"{self.produit.libelle} ({details})"
        return self.produit.libelle

    @property
    def taux_tva(self) -> Decimal:
        return self.produit.taux_tva

    @property
    def prix_ht(self) -> Decimal:
        """Le prix affiché est TTC : c'est le prix que l'acheteur voit et paie."""
        return (self.prix_vente / (1 + self.taux_tva)).quantize(Decimal("0.01"))


class MediaProduit(TenantScopedModel):
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE, related_name="medias")
    fichier = models.ImageField(upload_to="produits/%Y/%m/")
    alt = models.CharField(max_length=180, blank=True)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "média produit"
        verbose_name_plural = "médias produit"
        ordering = ["ordre"]

    def __str__(self):
        return f"Média {self.ordre} · {self.produit.libelle}"
