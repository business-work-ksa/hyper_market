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
    sur_ordonnance = models.BooleanField(
        default=False,
        help_text="Ne se délivre que sur ordonnance, et ne se vend pas en ligne.",
    )
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
    reference_constructeur = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Référence d'origine du fabricant. Ex. 90915-YZZD4.",
    )
    # Porté par la variante et non par le produit, parce que c'est la variante
    # qui porte le stock : un exemplaire est une unité d'une variante, pas d'un
    # modèle. Un téléphone 128 Go et le même en 64 Go ont des IMEI distincts et
    # des stocks distincts — c'est le même objet de gestion.
    suivi_unitaire = models.BooleanField(
        default=False,
        help_text="Chaque exemplaire porte un numéro de série ou un IMEI, suivi individuellement.",
    )
    garantie_mois = models.PositiveSmallIntegerField(
        default=0,
        help_text="Durée de garantie offerte à l'acheteur, en mois. Zéro : aucune garantie.",
    )

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


class CompatibiliteVehicule(TenantScopedModel):
    """Sur quels véhicules cette pièce se monte.

    Réservée au métier qui l'active. C'est la question que **tout** client de
    pièces détachées pose en entrant, et la seule que le catalogue ne savait pas
    entendre : on ne cherche pas « un filtre à huile », on cherche « le filtre à
    huile de ma Corolla de 2015 ».

    **Une pièce se monte sur plusieurs véhicules, et un véhicule accepte
    plusieurs pièces.** D'où une table à part plutôt que trois colonnes sur la
    variante : mettre « Toyota Corolla » dans un champ texte marcherait pour la
    première pièce, et deviendrait illisible à la troisième compatibilité.

    **Les bornes d'années sont facultatives des deux côtés.** Vide à gauche
    signifie « depuis toujours », vide à droite « toujours d'actualité » — et
    c'est le cas le plus fréquent, parce qu'un vendeur ne connaît presque jamais
    l'année où le constructeur arrêtera une pièce. Exiger les deux produirait des
    bornes inventées, donc des compatibilités fausses.

    Aucune contrainte d'unicité : une déclaration de compatibilité en double est
    inoffensive — elle s'affiche deux fois — là où un SKU en double casse le
    stock. Le doublon exact est écarté à la saisie, ce qui suffit.
    """

    variante = models.ForeignKey(
        Variante, on_delete=models.CASCADE, related_name="compatibilites"
    )
    marque = models.CharField(max_length=60, db_index=True)
    modele = models.CharField(
        max_length=80, blank=True, help_text="Vide si la pièce va sur toute la marque."
    )
    motorisation = models.CharField(
        max_length=60, blank=True, help_text="Ex. 1.4 D-4D. Vide si indifférent."
    )
    annee_debut = models.PositiveSmallIntegerField(null=True, blank=True)
    annee_fin = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "compatibilité véhicule"
        verbose_name_plural = "compatibilités véhicule"
        ordering = ["marque", "modele", "annee_debut"]
        indexes = [models.Index(fields=["boutique", "marque", "modele"])]
        constraints = [
            # Une borne de fin antérieure au début décrirait un intervalle vide :
            # la pièce ne serait compatible avec rien, et personne ne le verrait.
            models.CheckConstraint(
                condition=models.Q(annee_fin__isnull=True)
                | models.Q(annee_debut__isnull=True)
                | models.Q(annee_fin__gte=models.F("annee_debut")),
                name="compatibilite_annees_dans_l_ordre",
            )
        ]

    def __str__(self):
        return f"{self.marque} {self.modele}".strip() + (f" ({self.annees})" if self.annees else "")

    @property
    def annees(self) -> str:
        """Intervalle lisible : « 2012–2018 », « depuis 2012 », « jusqu'en 2018 »."""
        if self.annee_debut and self.annee_fin:
            return f"{self.annee_debut}–{self.annee_fin}"
        if self.annee_debut:
            return f"depuis {self.annee_debut}"
        if self.annee_fin:
            return f"jusqu'en {self.annee_fin}"
        return ""

    def couvre(self, annee: int | None) -> bool:
        """L'année demandée tombe-t-elle dans l'intervalle ?

        Une année non fournie couvre tout : un client qui ne connaît pas l'année
        de sa voiture — le cas courant — doit voir la pièce, quitte à vérifier
        ensuite. L'absence d'information ne doit jamais se traduire par une
        absence de résultat.
        """
        if annee is None:
            return True
        if self.annee_debut and annee < self.annee_debut:
            return False
        if self.annee_fin and annee > self.annee_fin:
            return False
        return True


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
