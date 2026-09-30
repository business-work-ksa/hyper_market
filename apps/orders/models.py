"""Commandes en ligne.

Règle centrale : un panier multi-boutiques produit **une `Commande` et N `SousCommande`**.
L'acheteur voit une commande et paie une fois ; chaque marchand ne gère que sa sous-commande.
Toute la comptabilité, la commission et l'affiliation s'appuient sur la `SousCommande`
(docs/10-modele-de-donnees.md, §8).
"""

from decimal import Decimal

from django.db import models
from django.db.models import Max

from apps.core.models import BaseModel, TenantScopedModel

CENTIME = Decimal("0.01")


class Commande(BaseModel):
    """Commande de l'acheteur. **Non scopée à une boutique : elle les traverse.**"""

    BROUILLON = "brouillon"
    CONFIRMEE = "confirmee"
    PAYEE = "payee"
    LIVREE = "livree"
    CLOTUREE = "cloturee"
    ANNULEE = "annulee"
    ETATS = [
        (BROUILLON, "Brouillon"),
        (CONFIRMEE, "Confirmée"),
        (PAYEE, "Payée"),
        (LIVREE, "Livrée"),
        (CLOTUREE, "Clôturée"),
        (ANNULEE, "Annulée"),
    ]

    numero = models.CharField(max_length=32, unique=True)
    acheteur = models.ForeignKey(
        "accounts.Utilisateur", on_delete=models.PROTECT, related_name="commandes"
    )
    total_ht = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_tva = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_ttc = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    frais_livraison = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    etat = models.CharField(max_length=16, choices=ETATS, default=BROUILLON, db_index=True)

    # Attribution d'affiliation, figée à la commande (docs/06, §3).
    code_apporteur = models.CharField(max_length=12, blank=True)
    apporteur_n1 = models.ForeignKey(
        "affiliation.Apporteur", null=True, blank=True, on_delete=models.SET_NULL, related_name="commandes_n1"
    )
    apporteur_n2 = models.ForeignKey(
        "affiliation.Apporteur", null=True, blank=True, on_delete=models.SET_NULL, related_name="commandes_n2"
    )
    revendeur = models.ForeignKey(
        "affiliation.Revendeur", null=True, blank=True, on_delete=models.SET_NULL, related_name="commandes"
    )

    adresse_livraison = models.CharField(
        max_length=255,
        blank=True,
        help_text="Texte libre : le découpage en zones et tarifs relève du lot 2.",
    )
    note = models.TextField(blank=True, help_text="Précisions de l'acheteur pour le marchand.")

    livree_le = models.DateTimeField(null=True, blank=True)
    operation_id = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
        help_text="Clé d'idempotence du tunnel de commande (ADR-004).",
    )

    class Meta:
        verbose_name = "commande"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Commande {self.numero}"

    @staticmethod
    def numero_suivant() -> str:
        dernier = Commande.objects.aggregate(m=Max("numero"))["m"]
        prochain = 1 if dernier is None else int(dernier.split("-")[-1]) + 1
        return f"CMD-{prochain:08d}"


class SousCommande(TenantScopedModel):
    """Part d'une commande revenant à une boutique. **L'unité de travail du marchand.**"""

    EN_ATTENTE = "en_attente"
    ACCEPTEE = "acceptee"
    PREPAREE = "preparee"
    EXPEDIEE = "expediee"
    LIVREE = "livree"
    ANNULEE = "annulee"
    ETATS = [
        (EN_ATTENTE, "En attente"),
        (ACCEPTEE, "Acceptée"),
        (PREPAREE, "Préparée"),
        (EXPEDIEE, "Expédiée"),
        (LIVREE, "Livrée"),
        (ANNULEE, "Annulée"),
    ]

    commande = models.ForeignKey(Commande, on_delete=models.CASCADE, related_name="sous_commandes")
    total_ht = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_tva = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_ttc = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    taux_commission = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0"))
    commission_plateforme = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0")
    )
    etat = models.CharField(max_length=16, choices=ETATS, default=EN_ATTENTE, db_index=True)
    livree_le = models.DateTimeField(null=True, blank=True)
    # La livraison **déclarée** par le marchand (`livree_le`) ne suffit pas à libérer l'argent d'un
    # acheteur : c'est précisément ce qu'une fausse boutique déclarerait. La confirmation vient de
    # l'acheteur — code de remise donné au livreur, ou geste sur sa page de commande (docs/23).
    livraison_confirmee_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "sous-commande"
        verbose_name_plural = "sous-commandes"
        ordering = ["-cree_le"]
        constraints = [
            models.UniqueConstraint(
                fields=["commande", "boutique"], name="une_sous_commande_par_boutique"
            )
        ]

    def __str__(self):
        return f"{self.commande.numero} · {self.boutique}"

    def recalculer(self) -> None:
        lignes = list(LigneCommande.objects_all_tenants.filter(sous_commande=self))
        ttc = sum((l.total_ttc for l in lignes), Decimal("0"))
        ht = sum((l.total_ht for l in lignes), Decimal("0"))
        self.total_ttc = ttc.quantize(CENTIME)
        self.total_ht = ht.quantize(CENTIME)
        self.total_tva = (ttc - ht).quantize(CENTIME)
        self.commission_plateforme = (self.total_ht * self.taux_commission).quantize(CENTIME)
        self.save(
            update_fields=[
                "total_ttc",
                "total_ht",
                "total_tva",
                "commission_plateforme",
                "modifie_le",
            ]
        )


class LigneCommande(TenantScopedModel):
    sous_commande = models.ForeignKey(
        SousCommande, on_delete=models.CASCADE, related_name="lignes"
    )
    variante = models.ForeignKey("catalog.Variante", on_delete=models.PROTECT, related_name="+")
    libelle = models.CharField(max_length=200)
    quantite = models.DecimalField(max_digits=14, decimal_places=4)
    pu_ttc = models.DecimalField(max_digits=12, decimal_places=2)
    taux_tva = models.DecimalField(max_digits=5, decimal_places=4)
    remise = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        verbose_name = "ligne de commande"
        verbose_name_plural = "lignes de commande"

    def __str__(self):
        return f"{self.libelle} × {self.quantite}"

    @property
    def total_ttc(self) -> Decimal:
        return (self.quantite * self.pu_ttc - self.remise).quantize(CENTIME)

    @property
    def total_ht(self) -> Decimal:
        return (self.total_ttc / (1 + self.taux_tva)).quantize(CENTIME)


class Retour(TenantScopedModel):
    """Retour d'une sous-commande. Annule les commissions d'affiliation associées."""

    DEMANDE = "demande"
    ACCEPTE = "accepte"
    REFUSE = "refuse"
    REMBOURSE = "rembourse"
    ETATS = [
        (DEMANDE, "Demandé"),
        (ACCEPTE, "Accepté"),
        (REFUSE, "Refusé"),
        (REMBOURSE, "Remboursé"),
    ]

    sous_commande = models.ForeignKey(
        SousCommande, on_delete=models.PROTECT, related_name="retours"
    )
    motif = models.TextField()
    etat = models.CharField(max_length=16, choices=ETATS, default=DEMANDE)
    montant_rembourse = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))

    class Meta:
        verbose_name = "retour"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Retour {self.sous_commande} · {self.get_etat_display()}"


class Litige(TenantScopedModel):
    """Un acheteur conteste une sous-commande : non reçue, non conforme, incomplète.

    Ouvrir un litige **gèle** la part correspondante du séquestre : ni libérée au marchand, ni
    remboursée, jusqu'à la décision. La plateforme instruit sous 72 heures (docs/08, §8), avec le
    droit `plateforme.litiges`, et chaque consultation est journalisée (ADR-012).

    Scopé par boutique, comme la sous-commande qu'il conteste : c'est une donnée du commerçant,
    protégée par la barrière 3.

    Un litige **perdu** par le marchand — tranché en faveur de l'acheteur, en tout ou partie —
    compte dans son palier de confiance (`apps/marketplace/confiance.py`).
    """

    NON_RECUE = "non_recue"
    NON_CONFORME = "non_conforme"
    INCOMPLETE = "incomplete"
    AUTRE = "autre"
    MOTIFS = [
        (NON_RECUE, "Commande non reçue"),
        (NON_CONFORME, "Article non conforme à l'annonce"),
        (INCOMPLETE, "Commande incomplète"),
        (AUTRE, "Autre"),
    ]

    OUVERT = "ouvert"
    EN_INSTRUCTION = "en_instruction"
    TRANCHE_ACHETEUR = "tranche_acheteur"
    TRANCHE_MARCHAND = "tranche_marchand"
    PARTAGE = "partage"
    ETATS = [
        (OUVERT, "Ouvert"),
        (EN_INSTRUCTION, "En instruction"),
        (TRANCHE_ACHETEUR, "Tranché en faveur de l'acheteur"),
        (TRANCHE_MARCHAND, "Tranché en faveur du marchand"),
        (PARTAGE, "Tranché : remboursement partiel"),
    ]
    ETATS_CLOS = (TRANCHE_ACHETEUR, TRANCHE_MARCHAND, PARTAGE)
    PERDUS_PAR_LE_MARCHAND = (TRANCHE_ACHETEUR, PARTAGE)

    sous_commande = models.ForeignKey(SousCommande, on_delete=models.PROTECT, related_name="litiges")
    motif = models.CharField(max_length=16, choices=MOTIFS)
    description = models.TextField()
    etat = models.CharField(max_length=20, choices=ETATS, default=OUVERT, db_index=True)
    montant_rembourse = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    decision = models.TextField(blank=True)
    tranche_par = models.ForeignKey(
        "accounts.Utilisateur", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tranche_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "litige"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Litige {self.sous_commande} · {self.get_etat_display()}"
