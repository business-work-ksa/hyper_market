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

from django.conf import settings
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
    """La part d'une sous-commande prépayée, tant qu'elle n'est ni libérée ni remboursée.

    **Ce que ce modèle est, et ce qu'il n'est pas.** La plateforme n'est pas un établissement de
    monnaie électronique (docs/08, §5.1) : l'argent de l'acheteur est chez un partenaire agréé, sur
    un compte de cantonnement distinct des fonds propres de la plateforme (§5.2). Cette ligne ne
    *détient* donc rien. Elle **constate** qu'une somme est cantonnée pour une sous-commande, et
    elle garde la trace des **ordres** que la plateforme donne ensuite au partenaire : libérer au
    marchand, ou rembourser l'acheteur.

    **Une part par sous-commande, pas une par commande.** Un panier traverse les boutiques : une
    commande de deux marchands se libère marchand par marchand. Un séquestre unique par commande
    ferait attendre le marchand diligent que son confrère ait livré — ou libérerait le négligent
    avec lui.

    **Non scopé par boutique**, comme `Transaction` et `CompteVersement` : c'est le registre des
    ordres de la plateforme au partenaire de cantonnement, pas une donnée de gestion du commerçant.
    Les écrans du marchand le lisent en filtrant explicitement sur ses propres sous-commandes ;
    ce qui est scopé — le journal du portefeuille — reste derrière la barrière 3.

    Les montants, et l'invariant qui les lie :

    * `montant_encaisse` — ce que l'acheteur a payé pour cette part (TTC) ;
    * `commission` — ce que la plateforme retient : la commission de place, TVA comprise, telle
      que la comptabilité du marchand l'enregistre (`comptabiliser_vente_en_ligne`) ;
    * `montant` — la part nette du marchand, celle qui entre dans `solde_bloque`.

    Une fois tranchée : `montant_libere + montant_rembourse == montant`. Rien ne se crée, rien ne
    se perd : c'est vérifié par les tests.
    """

    BLOQUE = "bloque"
    LIBERE = "libere"
    REMBOURSE = "rembourse"
    PARTAGE = "partage"
    ETATS = [
        (BLOQUE, "Bloqué"),
        (LIBERE, "Libéré"),
        (REMBOURSE, "Remboursé"),
        (PARTAGE, "Libéré en partie, remboursé en partie"),
    ]

    # Comment la livraison a été confirmée. La déclaration du marchand n'y figure pas, et ce n'est
    # pas un oubli : c'est exactement ce qu'une fausse boutique déclarerait.
    PAR_CODE = "code"
    PAR_ACHETEUR = "acheteur"
    IMPLICITE = "implicite"
    CONFIRMATIONS = [
        (PAR_CODE, "Code de remise saisi à la livraison"),
        (PAR_ACHETEUR, "Confirmée par l'acheteur"),
        (IMPLICITE, "Réputée confirmée, sans réclamation 7 jours après l'expédition"),
    ]

    commande = models.ForeignKey(
        "orders.Commande", on_delete=models.PROTECT, related_name="sequestres"
    )
    sous_commande = models.OneToOneField(
        "orders.SousCommande", on_delete=models.PROTECT, related_name="sequestre"
    )
    boutique = models.ForeignKey(
        "marketplace.Boutique", on_delete=models.PROTECT, related_name="sequestres"
    )
    montant_encaisse = models.DecimalField(max_digits=14, decimal_places=2)
    commission = models.DecimalField(max_digits=14, decimal_places=2)
    montant = models.DecimalField(
        max_digits=14, decimal_places=2, help_text="Part nette du marchand."
    )
    montant_libere = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    montant_rembourse = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Ce qui, sur la part du marchand, revient à l'acheteur.",
    )
    rembourse_acheteur = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Total à rendre à l'acheteur, commission annulée comprise.",
    )
    etat = models.CharField(max_length=16, choices=ETATS, default=BLOQUE, db_index=True)
    libere_le = models.DateTimeField(null=True, blank=True)
    rembourse_le = models.DateTimeField(null=True, blank=True)
    motif = models.CharField(max_length=255, blank=True)

    # Code de remise : six chiffres donnés par l'acheteur au livreur. **Seule son empreinte est
    # stockée** ; le code lui-même est dérivé à la demande de la clé secrète du serveur
    # (`apps/payments/sequestre.py`), si bien que ni la base ni une sauvegarde ne le contiennent.
    code_remise_hache = models.CharField(max_length=128, blank=True)
    essais_code_echoues = models.PositiveSmallIntegerField(default=0)
    code_verrouille_le = models.DateTimeField(null=True, blank=True)
    confirmation = models.CharField(max_length=12, choices=CONFIRMATIONS, blank=True)

    class Meta:
        verbose_name = "séquestre"
        ordering = ["-cree_le"]
        indexes = [models.Index(fields=["boutique", "etat"], name="sequestre_boutique_etat")]

    def __str__(self):
        return f"Séquestre {self.commande.numero} · {self.boutique} · {self.get_etat_display()}"

    @property
    def tranche(self) -> bool:
        return self.etat != self.BLOQUE

    def delete(self, *args, **kwargs):
        raise ValueError(
            "Un séquestre ne se supprime pas : il se libère ou se rembourse, et la trace reste."
        )


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
    """Ligne de journal du portefeuille. En ajout seul.

    Deux compartiments, parce qu'il y a deux soldes : ce qui attend la livraison (`bloque`) et ce
    que le marchand peut demander à recevoir (`disponible`). Une libération écrit donc **deux**
    lignes — une sortie du bloqué, une entrée au disponible — et jamais une seule qui « déplacerait »
    l'argent : un journal où une ligne vaut deux mouvements ne se rapproche plus.

    Idempotence : une même origine (un séquestre, un versement) ne produit qu'une ligne par type et
    par compartiment. C'est la contrainte d'unicité qui l'impose, pas une lecture préalable — les
    notifications d'opérateur arrivent en double, et la commande de libération peut tourner deux
    fois.
    """

    DISPONIBLE = "disponible"
    BLOQUE = "bloque"
    COMPARTIMENTS = [(DISPONIBLE, "Disponible"), (BLOQUE, "Bloqué")]

    # Types écrits par le séquestre et les versements.
    SEQUESTRE = "sequestre"
    LIBERATION = "liberation"
    REMBOURSEMENT = "remboursement"
    VERSEMENT = "versement"
    VERSEMENT_ANNULE = "versement_annule"
    # La commission d'une vente payée à la livraison, retenue sur ce que la plateforme doit au
    # marchand : l'argent de cette vente n'est jamais passé par elle (`sequestre.compenser_...`).
    COMMISSION_LIVRAISON = "commission_livraison"
    LIBELLES_TYPES = {
        SEQUESTRE: "Paiement en séquestre",
        LIBERATION: "Libération",
        REMBOURSEMENT: "Remboursement de l'acheteur",
        VERSEMENT: "Versement demandé",
        VERSEMENT_ANNULE: "Versement annulé",
        COMMISSION_LIVRAISON: "Commission d'une vente payée à la livraison",
    }

    portefeuille = models.ForeignKey(
        PortefeuilleMarchand, on_delete=models.PROTECT, related_name="mouvements"
    )
    type = models.CharField(max_length=32)
    compartiment = models.CharField(
        max_length=12, choices=COMPARTIMENTS, default=DISPONIBLE, db_index=True
    )
    montant = models.DecimalField(max_digits=16, decimal_places=2)
    solde_apres = models.DecimalField(
        max_digits=16, decimal_places=2, help_text="Solde du compartiment après le mouvement."
    )
    origine_type = models.CharField(max_length=64, blank=True)
    origine_id = models.UUIDField(null=True, blank=True)

    class Meta:
        verbose_name = "mouvement de portefeuille"
        verbose_name_plural = "mouvements de portefeuille"
        ordering = ["-cree_le"]
        constraints = [
            models.UniqueConstraint(
                fields=["type", "compartiment", "origine_id"],
                condition=models.Q(origine_id__isnull=False),
                name="un_mouvement_par_origine",
            )
        ]

    def __str__(self):
        return f"{self.type} {self.montant:+.0f} FCFA"

    @property
    def libelle(self) -> str:
        return self.LIBELLES_TYPES.get(self.type, self.type)


class Versement(BaseModel):
    """L'ordre de verser au marchand ce qui lui revient. **Le chemin de l'argent jusqu'à lui.**

    C'est là que se loge l'abus de confiance interne, et chaque champ ci-dessous en ferme une
    porte :

    * la **destination est figée** au moment de la demande (`operateur`, `numero`, `titulaire`,
      recopiés du `CompteVersement`). Changer le numéro de versement la veille d'un gros versement
      ne détourne rien : le versement déjà demandé part là où il a été demandé, et un compte
      nouvellement déclaré attend sa vérification et son délai de carence ;
    * seul un compte **vérifié et sorti de carence** est une destination possible ;
    * l'exécution exige la **référence de l'opérateur**, unique : une même opération réelle ne peut
      pas justifier deux versements ;
    * un versement **ne se supprime jamais**. Il s'annule, avec un motif, et l'argent revient au
      disponible par une ligne de journal. Dans un an, on doit pouvoir dire où est parti chaque
      franc — et qui l'a décidé.

    Non scopé, comme `CompteVersement` : c'est un ordre de la plateforme au partenaire de paiement.
    """

    DEMANDE = "demande"
    EXECUTE = "execute"
    ANNULE = "annule"
    ETATS = [(DEMANDE, "À exécuter"), (EXECUTE, "Exécuté"), (ANNULE, "Annulé")]

    boutique = models.ForeignKey(
        "marketplace.Boutique", on_delete=models.PROTECT, related_name="versements"
    )
    montant = models.DecimalField(max_digits=16, decimal_places=2)
    etat = models.CharField(max_length=12, choices=ETATS, default=DEMANDE, db_index=True)

    # Destination, figée à la demande.
    compte = models.ForeignKey(
        "marketplace.CompteVersement", on_delete=models.PROTECT, related_name="versements"
    )
    pays = models.CharField(max_length=2)
    operateur = models.CharField(max_length=24)
    numero = models.CharField(max_length=34)
    titulaire = models.CharField(max_length=160)

    demande_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    execute_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    execute_le = models.DateTimeField(null=True, blank=True)
    reference_operateur = models.CharField(max_length=120, blank=True)
    annule_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    annule_le = models.DateTimeField(null=True, blank=True)
    motif_annulation = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "versement"
        ordering = ["-cree_le"]
        constraints = [
            models.UniqueConstraint(
                fields=["reference_operateur"],
                condition=~models.Q(reference_operateur=""),
                name="une_reference_operateur_par_versement",
            ),
            models.CheckConstraint(
                condition=models.Q(montant__gt=0), name="versement_montant_positif"
            ),
        ]

    def __str__(self):
        return f"Versement {self.montant:.0f} FCFA · {self.boutique} · {self.get_etat_display()}"

    @property
    def libelle_operateur(self) -> str:
        from apps.marketplace.cemac import LIBELLES_OPERATEURS

        return LIBELLES_OPERATEURS.get(self.operateur, self.operateur)

    def delete(self, *args, **kwargs):
        raise ValueError("Un versement ne se supprime jamais : il s'annule, avec un motif.")
