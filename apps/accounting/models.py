"""Comptabilité SYSCOHADA révisé.

Règle fondatrice (ADR-003) : **le journal est en ajout seul.** Une écriture validée n'est jamais
modifiée ni supprimée ; on ne corrige que par contre-passation. Trois protections cumulées :

1. `save()` et `delete()` refusent toute atteinte à une écriture validée ;
2. un trigger PostgreSQL rejette `UPDATE` et `DELETE` même en SQL brut (migration 0002) ;
3. une contrainte de base garantit l'équilibre débit = crédit.
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel, TenantScopedModel
from apps.core.uuid7 import uuid7
from django.utils.translation import gettext_lazy

CENTIME = Decimal("0.01")


class PlanComptable(models.Model):
    """Référentiel plateforme. Un seul plan couvre les 17 pays OHADA."""

    code = models.CharField(max_length=32, primary_key=True)
    libelle = models.CharField(max_length=120)
    version = models.CharField(max_length=16, default="2018")

    class Meta:
        verbose_name = "plan comptable"
        verbose_name_plural = "plans comptables"

    def __str__(self):
        return self.libelle


class CompteGeneral(models.Model):
    """Compte modèle du plan comptable, commun à toutes les boutiques."""

    ACTIF = "actif"
    PASSIF = "passif"
    CHARGE = "charge"
    PRODUIT = "produit"
    TYPES = [(ACTIF, gettext_lazy("Actif")), (PASSIF, gettext_lazy("Passif")), (CHARGE, gettext_lazy("Charge")), (PRODUIT, gettext_lazy("Produit"))]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    plan = models.ForeignKey(PlanComptable, on_delete=models.CASCADE, related_name="comptes")
    numero = models.CharField(max_length=12)
    intitule = models.CharField(max_length=180)
    classe = models.PositiveSmallIntegerField()
    type = models.CharField(max_length=12, choices=TYPES)
    collectif = models.BooleanField(default=False)

    class Meta:
        verbose_name = "compte du plan"
        verbose_name_plural = "comptes du plan"
        ordering = ["numero"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "numero"], name="compte_general_unique")
        ]

    def __str__(self):
        return f"{self.numero} — {self.intitule}"


class CompteBoutique(TenantScopedModel):
    """Compte du plan personnalisé d'une boutique."""

    numero = models.CharField(max_length=12)
    intitule = models.CharField(max_length=180)
    compte_modele = models.ForeignKey(
        CompteGeneral, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    type = models.CharField(max_length=12, choices=CompteGeneral.TYPES)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "compte"
        ordering = ["numero"]
        constraints = [
            models.UniqueConstraint(fields=["boutique", "numero"], name="compte_unique_par_boutique")
        ]

    def __str__(self):
        return f"{self.numero} — {self.intitule}"

    @property
    def classe(self) -> int:
        return int(self.numero[0])


class Exercice(TenantScopedModel):
    OUVERT = "ouvert"
    CLOTURE = "cloture"
    ETATS = [(OUVERT, gettext_lazy("Ouvert")), (CLOTURE, gettext_lazy("Clôturé"))]

    debut = models.DateField()
    fin = models.DateField()
    etat = models.CharField(max_length=16, choices=ETATS, default=OUVERT)

    class Meta:
        verbose_name = "exercice"
        ordering = ["-debut"]
        constraints = [
            models.UniqueConstraint(fields=["boutique", "debut"], name="exercice_unique_par_debut")
        ]

    def __str__(self):
        return f"Exercice {self.debut:%Y}"


class Journal(TenantScopedModel):
    VENTES = "VTE"
    ACHATS = "ACH"
    BANQUE = "BQE"
    CAISSE = "CAI"
    PAIE = "PAI"
    STOCK = "STK"
    OPERATIONS_DIVERSES = "OD"
    CODES = [
        (VENTES, gettext_lazy("Journal des ventes")),
        (ACHATS, gettext_lazy("Journal des achats")),
        (BANQUE, gettext_lazy("Journal de banque")),
        (CAISSE, gettext_lazy("Journal de caisse")),
        (PAIE, gettext_lazy("Journal de paie")),
        (STOCK, gettext_lazy("Journal des stocks")),
        (OPERATIONS_DIVERSES, gettext_lazy("Opérations diverses")),
    ]

    code = models.CharField(max_length=8, choices=CODES)
    libelle = models.CharField(max_length=120)

    class Meta:
        verbose_name = "journal"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["boutique", "code"], name="journal_unique_par_boutique")
        ]

    def __str__(self):
        return self.libelle


class EcritureComptable(TenantScopedModel):
    """Écriture en partie double. **Immuable une fois validée.**"""

    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="ecritures")
    exercice = models.ForeignKey(Exercice, on_delete=models.PROTECT, related_name="ecritures")
    date_ecriture = models.DateField(default=timezone.localdate, db_index=True)
    piece = models.CharField(max_length=32, help_text=gettext_lazy("Séquence continue par journal et exercice."))
    libelle = models.CharField(max_length=255)
    validee = models.BooleanField(default=False, db_index=True)
    contrepassee_par = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="contrepasse"
    )
    origine_type = models.CharField(
        max_length=64, blank=True, help_text=gettext_lazy('Traçabilité descendante : "pos.Ticket", "orders.SousCommande"…')
    )
    origine_id = models.UUIDField(null=True, blank=True)

    class Meta:
        verbose_name = "écriture comptable"
        verbose_name_plural = "écritures comptables"
        ordering = ["-date_ecriture", "-cree_le"]
        indexes = [
            models.Index(fields=["boutique", "date_ecriture"]),
            models.Index(fields=["origine_type", "origine_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["boutique", "exercice", "journal", "piece"], name="piece_unique"
            )
        ]

    def __str__(self):
        return f"{self.journal.code} {self.piece} · {self.libelle}"

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            ancienne = EcritureComptable.objects_all_tenants.filter(pk=self.pk).values("validee").first()
            if ancienne and ancienne["validee"]:
                raise ValueError(
                    "Une écriture validée est immuable. Utilisez une contre-passation."
                )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.validee:
            raise ValueError("Une écriture validée ne peut pas être supprimée.")
        return super().delete(*args, **kwargs)

    @property
    def total_debit(self) -> Decimal:
        return sum(
            (l.debit for l in LigneEcriture.objects_all_tenants.filter(ecriture=self)),
            Decimal("0"),
        )

    @property
    def total_credit(self) -> Decimal:
        return sum(
            (l.credit for l in LigneEcriture.objects_all_tenants.filter(ecriture=self)),
            Decimal("0"),
        )

    @property
    def equilibree(self) -> bool:
        return self.total_debit == self.total_credit


class LigneEcriture(TenantScopedModel):
    ecriture = models.ForeignKey(EcritureComptable, on_delete=models.CASCADE, related_name="lignes")
    compte = models.ForeignKey(CompteBoutique, on_delete=models.PROTECT, related_name="lignes")
    libelle = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    lettrage = models.CharField(max_length=16, blank=True, db_index=True)

    class Meta:
        verbose_name = "ligne d'écriture"
        verbose_name_plural = "lignes d'écriture"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(debit__gte=0) & models.Q(credit__gte=0),
                name="ligne_montants_positifs",
            ),
            models.CheckConstraint(
                condition=models.Q(debit=0) | models.Q(credit=0),
                name="ligne_debit_ou_credit",
            ),
        ]

    def __str__(self):
        sens = f"D {self.debit}" if self.debit else f"C {self.credit}"
        return f"{self.compte.numero} {sens}"


class DeclarationTva(TenantScopedModel):
    BROUILLON = "brouillon"
    DEPOSEE = "deposee"
    ETATS = [(BROUILLON, gettext_lazy("Brouillon")), (DEPOSEE, gettext_lazy("Déposée"))]

    periode = models.DateField(help_text=gettext_lazy("Premier jour du mois déclaré."))
    collectee = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    deductible = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    credit_anterieur = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    etat = models.CharField(max_length=16, choices=ETATS, default=BROUILLON)

    class Meta:
        verbose_name = "déclaration de TVA"
        verbose_name_plural = "déclarations de TVA"
        ordering = ["-periode"]
        constraints = [
            models.UniqueConstraint(fields=["boutique", "periode"], name="tva_unique_par_periode")
        ]

    def __str__(self):
        return f"TVA {self.periode:%m/%Y}"

    @property
    def solde(self) -> Decimal:
        """Positif : TVA à payer. Négatif : crédit reportable sur la période suivante."""
        return (self.collectee - self.deductible - self.credit_anterieur).quantize(CENTIME)
