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
from django.utils.translation import gettext_lazy

CENTIME = Decimal("0.01")


class SessionCaisse(TenantScopedModel):
    OUVERTE = "ouverte"
    FERMEE = "fermee"
    ETATS = [(OUVERTE, gettext_lazy("Ouverte")), (FERMEE, gettext_lazy("Fermée"))]

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


class ClientCahier(TenantScopedModel):
    """Client habituel du comptoir, celui qui a un cahier (docs/22, §2.1).

    **Pourquoi ce modèle manquait, et ce que son absence coûtait.** `ReglementTicket.CREDIT`
    existait déjà, et la comptabilité savait parquer la créance au compte 411. On pouvait donc
    **vendre à crédit sans savoir qui devait** : `Ticket.client_nom` est du texte libre, et
    `reste_a_payer` se calcule par ticket. « Combien me doit Mama Ngo ? » n'avait pas de réponse,
    et c'est exactement la question que le cahier papier sait traiter depuis toujours.

    **Pourquoi le texte libre reste sur le ticket.** `client_nom` et `client_telephone` ne
    disparaissent pas : ils sont figés à la vente, comme `LigneTicket.libelle` et `pu_ttc`. Le
    client peut être renommé, corrigé, fusionné ; le ticket de mardi dernier ne doit pas changer.
    La clé étrangère porte l'identité, le texte porte l'histoire — et ce n'est pas une redondance,
    ce sont deux faits différents.

    **Ce que ce modèle n'est pas.** Ce n'est pas un compte utilisateur : le client du comptoir ne
    s'inscrit pas, il achète. Les acheteurs en ligne sont des `Utilisateur`, avec un mot de passe
    et un panier. Ici, quelqu'un entre, prend un sac de riz et dit « note-le ».
    """

    nom = models.CharField(max_length=180)
    telephone = models.CharField(
        max_length=16,
        blank=True,
        help_text=gettext_lazy("Facultatif : beaucoup de clients de quartier n'en donnent pas. Sert de clé."),
    )
    plafond_credit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text=(
            gettext_lazy("Encours maximal autorisé. Zéro signifie « pas de crédit » et non « illimité » : "
            "un plafond oublié ne doit pas ouvrir un crédit sans limite.")
        ),
    )
    actif = models.BooleanField(default=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "client du cahier"
        verbose_name_plural = "clients du cahier"
        ordering = ["nom"]
        constraints = [
            # Unicité sur le téléphone **quand il est renseigné**. Une contrainte simple
            # rendrait impossible d'avoir deux clients sans téléphone, ce qui est le cas
            # courant au comptoir.
            models.UniqueConstraint(
                fields=["boutique", "telephone"],
                condition=~models.Q(telephone=""),
                name="client_cahier_telephone_unique",
            )
        ]
        indexes = [models.Index(fields=["boutique", "nom"])]

    def __str__(self):
        return f"{self.nom}" + (f" · {self.telephone}" if self.telephone else "")


class ReglementCahier(TenantScopedModel):
    """Paiement d'un client **sur son cahier**, sans être rattaché à un ticket.

    C'est la façon dont cela se passe réellement : le client ne vient pas payer le ticket n° 412,
    il vient « déposer 10 000 sur son compte ». Rattacher chaque franc à un ticket précis
    obligerait le caissier à faire une imputation que le client n'a pas faite, et produirait des
    affectations inventées.

    Le solde se calcule donc par différence — ce que les tickets à crédit ont mis au débit moins
    ce que les règlements ont remboursé — et non en soldant des tickets un à un.
    """

    ESPECES = "especes"
    MOBILE_MONEY = "mobile_money"
    CARTE = "carte"
    # Pas de `CREDIT` ici, et ce n'est pas un oubli : payer son crédit à crédit n'est rien.
    MOYENS = [
        (ESPECES, gettext_lazy("Espèces")),
        (MOBILE_MONEY, gettext_lazy("Mobile Money")),
        (CARTE, gettext_lazy("Carte bancaire")),
    ]

    client = models.ForeignKey(
        ClientCahier, on_delete=models.PROTECT, related_name="reglements_cahier"
    )
    moyen = models.CharField(max_length=16, choices=MOYENS)
    montant = models.DecimalField(max_digits=14, decimal_places=2)
    recu_le = models.DateTimeField(default=timezone.now, db_index=True)
    reference_psp = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "règlement du cahier"
        verbose_name_plural = "règlements du cahier"
        ordering = ["-recu_le"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(montant__gt=0),
                name="reglement_cahier_montant_positif",
            )
        ]
        indexes = [models.Index(fields=["client", "-recu_le"])]

    def __str__(self):
        return f"{self.get_moyen_display()} · {self.montant:.0f} FCFA · {self.client.nom}"


class Ticket(TenantScopedModel):
    """Ticket de caisse. La numérotation est continue par boutique (exigence fiscale)."""

    BROUILLON = "brouillon"
    CLOTURE = "cloture"
    ANNULE = "annule"
    ETATS = [(BROUILLON, gettext_lazy("Brouillon")), (CLOTURE, gettext_lazy("Clôturé")), (ANNULE, gettext_lazy("Annulé"))]

    session = models.ForeignKey(SessionCaisse, on_delete=models.PROTECT, related_name="tickets")
    numero = models.CharField(max_length=32)
    client = models.ForeignKey(
        ClientCahier,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="tickets",
        help_text=(
            gettext_lazy("Renseigné seulement pour une vente au cahier. PROTECT : on ne supprime pas un "
            "client dont des ventes portent la trace.")
        ),
    )
    # Figés à la vente, comme le libellé et le prix d'une ligne : le client peut être renommé,
    # corrigé ou fusionné, le ticket de mardi dernier ne doit pas changer.
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
        help_text=gettext_lazy("Prescripteur et date de l'ordonnance, pour l'ordonnancier."),
    )
    operation_id = models.UUIDField(
        null=True, blank=True, unique=True, help_text=gettext_lazy("Clé d'idempotence du mode hors ligne.")
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
    libelle = models.CharField(max_length=200, help_text=gettext_lazy("Figé à la vente : le produit peut changer."))
    quantite = models.DecimalField(max_digits=14, decimal_places=4)
    pu_ttc = models.DecimalField(max_digits=12, decimal_places=2)
    taux_tva = models.DecimalField(max_digits=5, decimal_places=4)
    remise = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    sur_ordonnance = models.BooleanField(
        default=False,
        help_text=(
            gettext_lazy("Figé à la vente, comme le libellé et le prix : un médicament reclassé "
            "l'an prochain ne doit pas réécrire l'ordonnancier de cette année.")
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
        (ESPECES, gettext_lazy("Espèces")),
        (MOBILE_MONEY, gettext_lazy("Mobile Money")),
        (CARTE, gettext_lazy("Carte bancaire")),
        (CREDIT, gettext_lazy("À crédit")),
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
