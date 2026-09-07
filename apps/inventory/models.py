"""Stock : dépôts, niveaux, mouvements, inventaires.

★ Brique critique du produit (docs/04, §9). Deux principes :

1. **Le `MouvementStock` est la source de vérité, en ajout seul.** `NiveauStock` n'est qu'un
   agrégat matérialisé, reconstructible à tout moment à partir des mouvements.
2. **Le stock peut devenir négatif** (ADR-005). Deux caisses hors ligne vendent le dernier
   article : les deux ventes sont valides, la marchandise est physiquement sortie. Le système
   enregistre l'anomalie et laisse le gérant régulariser — refuser une vente déjà encaissée
   serait pire qu'un compteur temporairement faux.
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import TenantScopedModel

QUANTUM = Decimal("0.0001")
QUANTUM_MONETAIRE = Decimal("0.01")


class Depot(TenantScopedModel):
    BOUTIQUE = "boutique"
    RESERVE = "reserve"
    ENTREPOT_PLATEFORME = "entrepot_plateforme"
    TYPES = [
        (BOUTIQUE, "Point de vente"),
        (RESERVE, "Réserve"),
        (ENTREPOT_PLATEFORME, "Entrepôt mutualisé de la plateforme"),
    ]

    libelle = models.CharField(max_length=120)
    type = models.CharField(max_length=24, choices=TYPES, default=BOUTIQUE)
    adresse = models.CharField(max_length=255, blank=True)
    actif = models.BooleanField(default=True)
    principal = models.BooleanField(default=False)

    class Meta:
        verbose_name = "dépôt"
        ordering = ["libelle"]

    def __str__(self):
        return self.libelle


class NiveauStock(TenantScopedModel):
    """Agrégat matérialisé : quantité et coût moyen pondéré par (dépôt, variante)."""

    depot = models.ForeignKey(Depot, on_delete=models.CASCADE, related_name="niveaux")
    variante = models.ForeignKey(
        "catalog.Variante", on_delete=models.CASCADE, related_name="niveaux"
    )
    quantite = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    cmp = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0"),
        verbose_name="coût moyen pondéré",
    )
    seuil_alerte = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    version = models.PositiveIntegerField(default=0, help_text="Verrou optimiste.")

    class Meta:
        verbose_name = "niveau de stock"
        verbose_name_plural = "niveaux de stock"
        constraints = [
            models.UniqueConstraint(fields=["depot", "variante"], name="niveau_unique_depot_variante")
        ]

    def __str__(self):
        return f"{self.variante} @ {self.depot} : {self.quantite}"

    @property
    def valeur(self) -> Decimal:
        return (self.quantite * self.cmp).quantize(QUANTUM_MONETAIRE)

    @property
    def sous_le_seuil(self) -> bool:
        return self.quantite <= self.seuil_alerte

    @property
    def en_anomalie(self) -> bool:
        """Stock négatif : vente hors ligne non couverte, ou écart d'inventaire à régulariser."""
        return self.quantite < 0


class MouvementStock(TenantScopedModel):
    """Ligne de journal du stock. **Immuable une fois écrite.**"""

    ENTREE = "ENTREE"
    SORTIE = "SORTIE"
    TRANSFERT = "TRANSFERT"
    AJUSTEMENT = "AJUSTEMENT"
    PERTE = "PERTE"
    CASSE = "CASSE"
    TYPES = [
        (ENTREE, "Entrée"),
        (SORTIE, "Sortie"),
        (TRANSFERT, "Transfert"),
        (AJUSTEMENT, "Ajustement d'inventaire"),
        (PERTE, "Perte"),
        (CASSE, "Casse"),
    ]

    depot = models.ForeignKey(Depot, on_delete=models.PROTECT, related_name="mouvements")
    variante = models.ForeignKey(
        "catalog.Variante", on_delete=models.PROTECT, related_name="mouvements"
    )
    type = models.CharField(max_length=16, choices=TYPES, db_index=True)
    quantite = models.DecimalField(
        max_digits=14, decimal_places=4, help_text="Signée : positive en entrée, négative en sortie."
    )
    cout_unitaire = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    cmp_apres = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0"),
        help_text="CMP historisé : il ne peut pas être recalculé a posteriori.",
    )
    quantite_apres = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    origine_type = models.CharField(max_length=64, blank=True, help_text='Ex. "pos.Ticket".')
    origine_id = models.UUIDField(null=True, blank=True)
    operation_id = models.UUIDField(
        null=True, blank=True, help_text="Clé d'idempotence de la synchronisation hors ligne."
    )
    commentaire = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "mouvement de stock"
        verbose_name_plural = "mouvements de stock"
        ordering = ["-cree_le"]
        indexes = [
            models.Index(fields=["boutique", "variante", "cree_le"]),
            models.Index(fields=["origine_type", "origine_id"]),
        ]

    def __str__(self):
        return f"{self.get_type_display()} {self.quantite:+} · {self.variante}"

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            raise ValueError(
                "Un mouvement de stock est immuable. Corrigez par un mouvement d'ajustement."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Un mouvement de stock ne peut pas être supprimé.")


class Inventaire(TenantScopedModel):
    BROUILLON = "brouillon"
    VALIDE = "valide"
    ETATS = [(BROUILLON, "Brouillon"), (VALIDE, "Validé")]

    depot = models.ForeignKey(Depot, on_delete=models.PROTECT, related_name="inventaires")
    date = models.DateField(default=timezone.localdate)
    etat = models.CharField(max_length=16, choices=ETATS, default=BROUILLON)
    valide_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "inventaire"
        ordering = ["-date"]

    def __str__(self):
        return f"Inventaire {self.depot} · {self.date:%d/%m/%Y}"


class LigneInventaire(TenantScopedModel):
    inventaire = models.ForeignKey(Inventaire, on_delete=models.CASCADE, related_name="lignes")
    variante = models.ForeignKey("catalog.Variante", on_delete=models.PROTECT, related_name="+")
    qte_theorique = models.DecimalField(max_digits=14, decimal_places=4)
    qte_comptee = models.DecimalField(max_digits=14, decimal_places=4)
    motif = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "ligne d'inventaire"
        verbose_name_plural = "lignes d'inventaire"
        constraints = [
            models.UniqueConstraint(
                fields=["inventaire", "variante"], name="ligne_inventaire_unique"
            )
        ]

    def __str__(self):
        return f"{self.variante} · écart {self.ecart:+}"

    @property
    def ecart(self) -> Decimal:
        return self.qte_comptee - self.qte_theorique


class Fournisseur(TenantScopedModel):
    nom = models.CharField(max_length=180)
    contact = models.CharField(max_length=120, blank=True)
    telephone = models.CharField(max_length=16, blank=True)
    niu = models.CharField(max_length=32, blank=True)
    delai_paiement_jours = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "fournisseur"
        ordering = ["nom"]

    def __str__(self):
        return self.nom
