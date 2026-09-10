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


class Recette(TenantScopedModel):
    """Fiche technique : ce qu'il faut pour fabriquer, et combien ça produit.

    Réservée aux métiers qui l'activent (`apps/marketplace/metiers.py`) : une
    boulangerie et un restaurant **fabriquent** ce qu'ils vendent, une
    quincaillerie revend ce qu'elle a acheté. Demander une fiche technique à la
    seconde serait une saisie de plus pour rien.

    Trois décisions de conception, et chacune protège quelque chose.

    **Le coût de revient n'est pas stocké.** Il est recalculé à chaque affichage
    à partir des CMP du jour, et historisé par le mouvement de production
    (`cmp_apres`) au moment où la fabrication a lieu. Un coût figé sur la fiche
    serait faux dès que le sac de farine change de prix — c'est-à-dire tout le
    temps — et un boulanger qui fixe son prix de vente sur un chiffre périmé
    vend à perte sans le voir.

    **Le rendement est explicite.** Une recette produit *quarante* baguettes,
    pas « une ». Un boulanger raisonne en fournée, pas à l'unité, et l'obliger à
    diviser ses quantités par quarante à la saisie est le meilleur moyen
    d'obtenir une fiche fausse.

    **Une fiche ne se cascade pas.** Fabriquer un produit consomme du **stock**,
    pas les recettes de ses ingrédients. Une boulangerie qui fait sa pâte puis
    ses baguettes enregistre deux productions — ce qu'elle fait réellement, à
    deux moments différents de la matinée. Une production en cascade fabriquerait
    de la pâte fantôme jamais pétrie, et le stock cesserait de décrire le fournil.
    """

    variante = models.OneToOneField(
        Variante,
        on_delete=models.CASCADE,
        related_name="recette",
        help_text="Le produit fini que cette fiche fabrique.",
    )
    rendement = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.0001"))],
        help_text="Combien d'unités une exécution de la fiche produit. Ex. 40 baguettes.",
    )
    duree_conservation_jours = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Nombre de jours de conservation. Vide si le produit ne périme pas.",
    )
    note = models.TextField(blank=True, help_text="Mode opératoire, tour de main, température.")
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "fiche technique"
        verbose_name_plural = "fiches techniques"
        ordering = ["variante__produit__libelle"]
        constraints = [
            models.CheckConstraint(condition=models.Q(rendement__gt=0), name="recette_rendement_positif")
        ]

    def __str__(self):
        return f"Fiche technique · {self.variante}"


class LigneRecette(TenantScopedModel):
    """Un ingrédient et sa quantité, pour une exécution complète de la fiche.

    L'ingrédient est une variante ordinaire du stock : la farine que le boulanger
    reçoit du grossiste est un article comme un autre, avec son CMP. C'est ce qui
    permet au coût de revient d'être un vrai coût et non une estimation.
    """

    recette = models.ForeignKey(Recette, on_delete=models.CASCADE, related_name="lignes")
    ingredient = models.ForeignKey(Variante, on_delete=models.PROTECT, related_name="entre_dans")
    quantite = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
        help_text="Quantité pour le rendement complet de la fiche, dans l'unité de l'ingrédient.",
    )

    class Meta:
        verbose_name = "ingrédient"
        verbose_name_plural = "ingrédients"
        ordering = ["ingredient__produit__libelle"]
        constraints = [
            models.UniqueConstraint(
                fields=["recette", "ingredient"], name="ligne_recette_unique_par_ingredient"
            ),
            models.CheckConstraint(condition=models.Q(quantite__gt=0), name="ligne_recette_quantite_positive"),
        ]

    def __str__(self):
        return f"{self.quantite} × {self.ingredient}"


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
