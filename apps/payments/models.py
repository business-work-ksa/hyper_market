"""Encaissement, séquestre et portefeuille marchand.

Deux exigences non négociables :

* **Aucune dépendance à un opérateur unique.** MTN et Orange se partagent le marché ; le pouvoir
  de négociation qui en découle est le risque externe le plus élevé du projet (docs/02, §3.3). Le
  routage doit pouvoir basculer d'un prestataire à l'autre sans changement de code métier.
* **Clé d'idempotence obligatoire.** Un double débit Mobile Money est l'incident le plus grave
  possible sur ce marché : la contrainte d'unicité est ici la protection principale.

Le `PortefeuilleMarchand` est un **compte de suivi**, pas un dépôt : il retrace une créance du
marchand sur la plateforme, jamais un solde de monnaie électronique (docs/08, §5.2).
"""

from decimal import Decimal

from django.db import models

from apps.core.models import BaseModel, TenantScopedModel

CENTIME = Decimal("0.01")


class Prestataire(models.Model):
    MTN_MOMO = "MTN_MOMO"
    ORANGE_MONEY = "ORANGE_MONEY"
    CAMTEL = "CAMTEL"
    CARTE = "CARTE"
    PAIEMENT_LIVRAISON = "COD"
    FAUX = "FAUX"

    code = models.CharField(max_length=24, primary_key=True)
    libelle = models.CharField(max_length=64)
    actif = models.BooleanField(default=True)
    taux_frais = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.016"), help_text="1,6 % par défaut."
    )
    prefixes_numero = models.JSONField(
        default=list, blank=True, help_text='Ex. ["67", "650", "651"] pour le routage automatique.'
    )

    class Meta:
        verbose_name = "prestataire de paiement"
        verbose_name_plural = "prestataires de paiement"
        ordering = ["code"]

    def __str__(self):
        return self.libelle


class Transaction(BaseModel):
    ENCAISSEMENT = "encaissement"
    VERSEMENT = "versement"
    REMBOURSEMENT = "remboursement"
    SENS = [
        (ENCAISSEMENT, "Encaissement"),
        (VERSEMENT, "Versement"),
        (REMBOURSEMENT, "Remboursement"),
    ]

    INITIEE = "initiee"
    REUSSIE = "reussie"
    ECHOUEE = "echouee"
    EXPIREE = "expiree"
    ETATS = [
        (INITIEE, "Initiée"),
        (REUSSIE, "Réussie"),
        (ECHOUEE, "Échouée"),
        (EXPIREE, "Expirée"),
    ]

    commande = models.ForeignKey(
        "orders.Commande", null=True, blank=True, on_delete=models.PROTECT, related_name="transactions"
    )
    prestataire = models.ForeignKey(Prestataire, on_delete=models.PROTECT, related_name="transactions")
    sens = models.CharField(max_length=16, choices=SENS)
    montant = models.DecimalField(max_digits=14, decimal_places=2)
    numero_payeur = models.CharField(max_length=16, blank=True)
    etat = models.CharField(max_length=16, choices=ETATS, default=INITIEE, db_index=True)
    reference_externe = models.CharField(max_length=120, blank=True)
    cle_idempotence = models.CharField(
        max_length=120,
        unique=True,
        help_text="Unicité globale : protection principale contre le double débit.",
    )
    charge_utile_psp = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "transaction"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.get_sens_display()} {self.montant:.0f} FCFA · {self.get_etat_display()}"

    @property
    def frais(self) -> Decimal:
        return (self.montant * self.prestataire.taux_frais).quantize(CENTIME)


class Sequestre(BaseModel):
    """Fonds bloqués jusqu'à la preuve de livraison.

    Le séquestre est le levier de conversion du paiement à la livraison vers le prépaiement —
    c'est-à-dire du taux d'annulation, poison économique du e-commerce local (docs/04, §6).
    """

    BLOQUE = "bloque"
    LIBERE = "libere"
    REMBOURSE = "rembourse"
    ETATS = [(BLOQUE, "Bloqué"), (LIBERE, "Libéré"), (REMBOURSE, "Remboursé")]

    commande = models.OneToOneField(
        "orders.Commande", on_delete=models.PROTECT, related_name="sequestre"
    )
    montant = models.DecimalField(max_digits=14, decimal_places=2)
    etat = models.CharField(max_length=16, choices=ETATS, default=BLOQUE, db_index=True)
    libere_le = models.DateTimeField(null=True, blank=True)
    motif = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "séquestre"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Séquestre {self.commande.numero} · {self.get_etat_display()}"


class PortefeuilleMarchand(TenantScopedModel):
    """Compte de suivi du marchand. Ce n'est pas un dépôt de monnaie électronique."""

    solde_disponible = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    solde_bloque = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    numero_momo = models.CharField(max_length=16, blank=True)

    class Meta:
        verbose_name = "portefeuille marchand"
        verbose_name_plural = "portefeuilles marchands"

    def __str__(self):
        return f"Portefeuille {self.boutique} · {self.solde_disponible:.0f} FCFA"


class MouvementPortefeuille(TenantScopedModel):
    """Ligne de journal du portefeuille. En ajout seul."""

    portefeuille = models.ForeignKey(
        PortefeuilleMarchand, on_delete=models.PROTECT, related_name="mouvements"
    )
    type = models.CharField(max_length=32)
    montant = models.DecimalField(max_digits=16, decimal_places=2)
    solde_apres = models.DecimalField(max_digits=16, decimal_places=2)
    origine_type = models.CharField(max_length=64, blank=True)
    origine_id = models.UUIDField(null=True, blank=True)

    class Meta:
        verbose_name = "mouvement de portefeuille"
        verbose_name_plural = "mouvements de portefeuille"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.type} {self.montant:+.0f} FCFA"
