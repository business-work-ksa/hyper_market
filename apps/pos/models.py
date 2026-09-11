"""Caisse (point de vente).

★ Brique critique (docs/04, §9). La majorité du chiffre d'affaires du marchand cible se fait au
comptoir : sans la caisse, la plateforme ne voit qu'une fraction de son activité et sa
comptabilité est fausse.

Contrainte de conception imposée : **saisie d'une ligne en moins de 4 secondes**, hors ligne
compris (docs/04, §3).
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import TenantScopedModel

CENTIME = Decimal("0.01")


class SessionCaisse(TenantScopedModel):
    OUVERTE = "ouverte"
    FERMEE = "fermee"
    ETATS = [(OUVERTE, "Ouverte"), (FERMEE, "Fermée")]

    depot = models.ForeignKey("inventory.Depot", on_delete=models.PROTECT, related_name="sessions")
    caissier = models.ForeignKey(
        "accounts.Utilisateur", on_delete=models.PROTECT, related_name="sessions_caisse"
    )
    ouverte_le = models.DateTimeField(default=timezone.now)
    fonds_ouverture = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    fermee_le = models.DateTimeField(null=True, blank=True)
    fonds_compte = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    etat = models.CharField(max_length=16, choices=ETATS, default=OUVERTE, db_index=True)

    class Meta:
        verbose_name = "session de caisse"
        verbose_name_plural = "sessions de caisse"
        ordering = ["-ouverte_le"]

    def __str__(self):
        return f"Caisse {self.depot} · {self.ouverte_le:%d/%m/%Y %H:%M}"

    @property
    def total_especes(self) -> Decimal:
        agg = ReglementTicket.objects_all_tenants.filter(
            ticket__session=self, moyen=ReglementTicket.ESPECES
        ).aggregate(total=models.Sum("montant"))
        return agg["total"] or Decimal("0")

    @property
    def fonds_theorique(self) -> Decimal:
        return self.fonds_ouverture + self.total_especes

    @property
    def ecart(self) -> Decimal | None:
        if self.fonds_compte is None:
            return None
        return (self.fonds_compte - self.fonds_theorique).quantize(CENTIME)


class Ticket(TenantScopedModel):
    """Ticket de caisse. La numérotation est continue par boutique (exigence fiscale)."""

    BROUILLON = "brouillon"
    CLOTURE = "cloture"
    ANNULE = "annule"
    ETATS = [(BROUILLON, "Brouillon"), (CLOTURE, "Clôturé"), (ANNULE, "Annulé")]

    session = models.ForeignKey(SessionCaisse, on_delete=models.PROTECT, related_name="tickets")
    numero = models.CharField(max_length=32)
    client_nom = models.CharField(max_length=180, blank=True)
    client_telephone = models.CharField(max_length=16, blank=True)
    total_ht = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_tva = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_ttc = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    etat = models.CharField(max_length=16, choices=ETATS, default=BROUILLON, db_index=True)
    cloture_le = models.DateTimeField(null=True, blank=True)
    mention_ordonnance = models.CharField(
        max_length=180,
        blank=True,
        help_text="Prescripteur et date de l'ordonnance, pour l'ordonnancier.",
    )
    operation_id = models.UUIDField(
        null=True, blank=True, unique=True, help_text="Clé d'idempotence du mode hors ligne."
    )

    class Meta:
        verbose_name = "ticket"
        ordering = ["-cree_le"]
        constraints = [
            models.UniqueConstraint(fields=["boutique", "numero"], name="ticket_numero_unique")
        ]

    def __str__(self):
        return f"Ticket {self.numero} · {self.total_ttc:.0f} FCFA"

    @property
    def reste_a_payer(self) -> Decimal:
        regle = ReglementTicket.objects_all_tenants.filter(ticket=self).aggregate(
            total=models.Sum("montant")
        )["total"] or Decimal("0")
        return (self.total_ttc - regle).quantize(CENTIME)


class LigneTicket(TenantScopedModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="lignes")
    variante = models.ForeignKey("catalog.Variante", on_delete=models.PROTECT, related_name="+")
    libelle = models.CharField(max_length=200, help_text="Figé à la vente : le produit peut changer.")
    quantite = models.DecimalField(max_digits=14, decimal_places=4)
    pu_ttc = models.DecimalField(max_digits=12, decimal_places=2)
    taux_tva = models.DecimalField(max_digits=5, decimal_places=4)
    remise = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    sur_ordonnance = models.BooleanField(
        default=False,
        help_text=(
            "Figé à la vente, comme le libellé et le prix : un médicament reclassé "
            "l'an prochain ne doit pas réécrire l'ordonnancier de cette année."
        ),
    )

    class Meta:
        verbose_name = "ligne de ticket"
        verbose_name_plural = "lignes de ticket"

    def __str__(self):
        return f"{self.libelle} × {self.quantite}"

    @property
    def total_ttc(self) -> Decimal:
        return (self.quantite * self.pu_ttc - self.remise).quantize(CENTIME)

    @property
    def total_ht(self) -> Decimal:
        return (self.total_ttc / (1 + self.taux_tva)).quantize(CENTIME)

    @property
    def total_tva(self) -> Decimal:
        return self.total_ttc - self.total_ht


class ReglementTicket(TenantScopedModel):
    ESPECES = "especes"
    MOBILE_MONEY = "mobile_money"
    CARTE = "carte"
    CREDIT = "credit"
    MOYENS = [
        (ESPECES, "Espèces"),
        (MOBILE_MONEY, "Mobile Money"),
        (CARTE, "Carte bancaire"),
        (CREDIT, "À crédit"),
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="reglements")
    moyen = models.CharField(max_length=16, choices=MOYENS)
    montant = models.DecimalField(max_digits=14, decimal_places=2)
    reference_psp = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "règlement"
        verbose_name_plural = "règlements"

    def __str__(self):
        return f"{self.get_moyen_display()} · {self.montant:.0f} FCFA"
