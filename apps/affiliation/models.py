"""Affiliation, filiation et comptes revendeurs.

Les garde-fous juridiques du docs/06, §2.3 ne sont pas des règles de gestion paramétrables : ils
sont **codés en dur**, précisément pour qu'aucune décision commerciale ne puisse les contourner.

* profondeur de filiation limitée à 2 niveaux (`Apporteur.rattacher`) ;
* commission assise exclusivement sur du chiffre d'affaires encaissé et non annulé ;
* cumul des reversements plafonné à 35 % de la commission plateforme ;
* aucun droit d'entrée, aucun achat obligatoire, aucun stock imposé au revendeur.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

CENTIME = Decimal("0.01")


class FiliationInvalide(ValueError):
    """Rattachement refusé : auto-parrainage, cycle, ou profondeur supérieure à 2."""


class Apporteur(BaseModel):
    """Compte d'affiliation. `parrain_n2` est dénormalisé et figé au rattachement.

    Ce choix de modélisation n'est pas une optimisation : il rend la profondeur de 3 niveaux
    **structurellement impossible**, puisqu'aucun champ ne peut la représenter.
    """

    ACTIF = "actif"
    SUSPENDU = "suspendu"
    ETATS = [(ACTIF, _l("Actif")), (SUSPENDU, _l("Suspendu"))]

    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="apporteur"
    )
    code = models.CharField(max_length=12, unique=True)
    parrain_n1 = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="filleuls_n1"
    )
    parrain_n2 = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="filleuls_n2"
    )
    etat = models.CharField(max_length=16, choices=ETATS, default=ACTIF, db_index=True)
    kyc_renforce = models.BooleanField(
        default=False, help_text=_l("Requis au-delà de 500 000 FCFA de gains mensuels (docs/06, §6).")
    )

    class Meta:
        verbose_name = "apporteur"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.utilisateur.nom_complet} [{self.code}]"

    def rattacher(self, parrain: "Apporteur | None") -> None:
        """Rattache cet apporteur à un parrain, en propageant au plus un niveau au-dessus."""
        if parrain is None:
            return
        if parrain.pk == self.pk:
            raise FiliationInvalide(_("Un apporteur ne peut pas se parrainer lui-même."))
        if parrain.parrain_n1_id == self.pk or parrain.parrain_n2_id == self.pk:
            raise FiliationInvalide(_("Rattachement circulaire."))
        if self.parrain_n1_id is not None:
            raise FiliationInvalide(_("Cet apporteur a déjà un parrain : la filiation est définitive."))

        self.parrain_n1 = parrain
        # Le parrain du parrain, et rien au-delà : la chaîne s'arrête ici (arbitrage A11).
        self.parrain_n2 = parrain.parrain_n1
        self.save(update_fields=["parrain_n1", "parrain_n2", "modifie_le"])


class Attribution(BaseModel):
    """Rattachement d'un acheteur, d'un marchand ou d'un revendeur à un apporteur.

    Non reconductible : la fenêtre de 12 mois évite la constitution de rentes perpétuelles qui
    grèveraient la marge à mesure que la base grandit (docs/06, §3.2).
    """

    ACHETEUR = "acheteur"
    MARCHAND = "marchand"
    REVENDEUR = "revendeur"
    CIBLES = [(ACHETEUR, _l("Acheteur")), (MARCHAND, _l("Marchand")), (REVENDEUR, _l("Revendeur"))]

    CODE = "code"
    CLIC = "clic"
    RATTACHEMENT = "rattachement"
    ORIGINES = [
        (CODE, _l("Code saisi explicitement")),
        (CLIC, _l("Dernier clic non direct")),
        (RATTACHEMENT, _l("Rattachement permanent du compte")),
    ]

    apporteur = models.ForeignKey(Apporteur, on_delete=models.CASCADE, related_name="attributions")
    cible_type = models.CharField(max_length=16, choices=CIBLES)
    cible_id = models.UUIDField()
    origine = models.CharField(max_length=16, choices=ORIGINES)
    debut = models.DateTimeField(default=timezone.now)
    fin = models.DateTimeField()
    preuve = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "attribution"
        ordering = ["-debut"]
        indexes = [models.Index(fields=["cible_type", "cible_id"])]
        constraints = [
            models.UniqueConstraint(
                fields=["cible_type", "cible_id"], name="une_attribution_active_par_cible"
            )
        ]

    def __str__(self):
        return f"{self.get_cible_type_display()} → {self.apporteur.code}"

    @property
    def valide(self) -> bool:
        return self.debut <= timezone.now() <= self.fin


class Revendeur(BaseModel):
    """Force de vente distribuée : vend le catalogue d'autrui, sans jamais porter de stock.

    Le revendeur **ne manipule jamais l'argent de la commande** : l'encaissement passe
    exclusivement par la plateforme (docs/06, §5.3).
    """

    ACTIF = "actif"
    SUSPENDU = "suspendu"
    ETATS = [(ACTIF, _l("Actif")), (SUSPENDU, _l("Suspendu"))]

    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="revendeur"
    )
    slug_vitrine = models.SlugField(max_length=80, unique=True)
    etat = models.CharField(max_length=16, choices=ETATS, default=ACTIF)
    plafond_remise = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        help_text=_l("Remise maximale que le revendeur peut consentir, prise sur sa propre marge."),
    )

    class Meta:
        verbose_name = "revendeur"
        ordering = ["slug_vitrine"]

    def __str__(self):
        return f"{self.utilisateur.nom_complet} (/{self.slug_vitrine})"


class CatalogueRevendeur(BaseModel):
    """Liste blanche des produits qu'un revendeur est autorisé à pousser.

    Liste blanche et jamais liste noire : un produit interdit qu'on aurait oublié d'exclure serait
    vendable, ce qui est le mauvais sens du risque.
    """

    revendeur = models.ForeignKey(Revendeur, on_delete=models.CASCADE, related_name="catalogue")
    variante = models.ForeignKey(
        "catalog.Variante", on_delete=models.CASCADE, related_name="revendeurs"
    )
    marge = models.DecimalField(max_digits=5, decimal_places=4)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "produit du catalogue revendeur"
        verbose_name_plural = "catalogue revendeur"
        constraints = [
            models.UniqueConstraint(
                fields=["revendeur", "variante"], name="catalogue_revendeur_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(marge__gte=0) & models.Q(marge__lte=1),
                name="catalogue_revendeur_marge_entre_0_et_1",
            ),
        ]

    def __str__(self):
        return f"{self.revendeur} · {self.variante}"


class Commission(BaseModel):
    """Commission d'affiliation ou de revente.

    Cycle de vie : `attendue` → `acquise` → `payable` → `payee`, avec sorties `annulee` et
    `reprise`. **Aucune commission n'est payée avant l'expiration du délai de retour** : c'est la
    protection principale contre la fraude par commande fictive (docs/06, §4.2).
    """

    N1 = "N1"
    N2 = "N2"
    REVENDEUR = "REVENDEUR"
    ROLES = [(N1, _l("Apporteur direct")), (N2, _l("Apporteur indirect")), (REVENDEUR, _l("Revendeur"))]

    ATTENDUE = "attendue"
    ACQUISE = "acquise"
    PAYABLE = "payable"
    PAYEE = "payee"
    ANNULEE = "annulee"
    REPRISE = "reprise"
    ETATS = [
        (ATTENDUE, _l("Attendue")),
        (ACQUISE, _l("Acquise")),
        (PAYABLE, _l("Payable")),
        (PAYEE, _l("Payée")),
        (ANNULEE, _l("Annulée")),
        (REPRISE, _l("Reprise sur gains futurs")),
    ]

    beneficiaire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commissions"
    )
    role = models.CharField(max_length=16, choices=ROLES)
    sous_commande = models.ForeignKey(
        "orders.SousCommande", on_delete=models.PROTECT, related_name="commissions"
    )
    assiette = models.DecimalField(
        max_digits=14, decimal_places=2, help_text=_l("Commission plateforme sur laquelle est prélevée la part.")
    )
    taux = models.DecimalField(max_digits=5, decimal_places=4)
    montant = models.DecimalField(max_digits=14, decimal_places=2)
    etat = models.CharField(max_length=16, choices=ETATS, default=ATTENDUE, db_index=True)
    acquise_le = models.DateTimeField(null=True, blank=True)
    payee_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "commission"
        ordering = ["-cree_le"]
        constraints = [
            models.UniqueConstraint(
                fields=["sous_commande", "beneficiaire", "role"], name="commission_unique"
            )
        ]

    def __str__(self):
        return f"{self.get_role_display()} · {self.montant:.0f} FCFA · {self.get_etat_display()}"


class SignalFraude(BaseModel):
    AUTO_PARRAINAGE = "auto_parrainage"
    COMPTES_MULTIPLES = "comptes_multiples"
    COMMANDES_FICTIVES = "commandes_fictives"
    RETOURS_SYSTEMATIQUES = "retours_systematiques"
    VOL_ATTRIBUTION = "vol_attribution"
    TYPES = [
        (AUTO_PARRAINAGE, _l("Auto-parrainage")),
        (COMPTES_MULTIPLES, _l("Comptes multiples")),
        (COMMANDES_FICTIVES, _l("Commandes fictives")),
        (RETOURS_SYSTEMATIQUES, _l("Retours systématiques")),
        (VOL_ATTRIBUTION, _l("Vol d'attribution")),
    ]

    apporteur = models.ForeignKey(Apporteur, on_delete=models.CASCADE, related_name="signaux_fraude")
    type = models.CharField(max_length=32, choices=TYPES)
    score = models.PositiveSmallIntegerField(default=0)
    preuve = models.JSONField(default=dict, blank=True)
    traite_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decision = models.TextField(blank=True)

    class Meta:
        verbose_name = "signal de fraude"
        verbose_name_plural = "signaux de fraude"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.get_type_display()} · {self.apporteur.code} · score {self.score}"
