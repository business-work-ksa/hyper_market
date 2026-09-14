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
    PRODUCTION = "PRODUCTION"
    TYPES = [
        (ENTREE, "Entrée"),
        (SORTIE, "Sortie"),
        (TRANSFERT, "Transfert"),
        (AJUSTEMENT, "Ajustement d'inventaire"),
        (PERTE, "Perte"),
        (CASSE, "Casse"),
        (PRODUCTION, "Production"),
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


class LotStock(TenantScopedModel):
    """Ce qui périme, et quand.

    Réservé aux métiers qui l'activent (`apps/marketplace/metiers.py`) : une
    quincaillerie n'a pas de dates de péremption, et lui en demander serait une
    saisie de plus pour rien. Là où la fonction n'est pas activée, aucun lot
    n'existe et tout le mécanisme est inerte.

    **La décision de conception qui compte : un lot ne porte pas de coût.** La
    valorisation reste au niveau `(dépôt, variante)`, en coût moyen pondéré —
    le lot répond à « qu'est-ce qui périme quand », le CMP à « combien ça a
    coûté ». Les mêler aurait imposé une valorisation par lot (FIFO réel), qui
    est un autre modèle comptable, plus juste sur le papier et impraticable pour
    un commerçant qui reprend un stock existant sans connaître le coût
    d'acquisition ligne à ligne (voir l'en-tête de `apps/inventory/services.py`).

    Deux réceptions du même lot à la même date **alimentent la même ligne** : un
    numéro de lot désigne une fabrication, pas une livraison.
    """

    depot = models.ForeignKey(Depot, on_delete=models.CASCADE, related_name="lots")
    variante = models.ForeignKey("catalog.Variante", on_delete=models.CASCADE, related_name="lots")
    numero = models.CharField(
        max_length=64,
        blank=True,
        help_text="Numéro de lot du fabricant. Vide quand seule la date compte.",
    )
    date_peremption = models.DateField(db_index=True)
    quantite = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))

    class Meta:
        verbose_name = "lot"
        verbose_name_plural = "lots"
        ordering = ["date_peremption", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["depot", "variante", "numero", "date_peremption"], name="lot_unique"
            )
        ]
        indexes = [models.Index(fields=["boutique", "date_peremption"])]

    def __str__(self):
        marque = f" lot {self.numero}" if self.numero else ""
        return f"{self.variante}{marque} — {self.date_peremption:%d/%m/%Y}"

    def jours_restants(self, aujourd_hui=None) -> int:
        aujourd_hui = aujourd_hui or timezone.localdate()
        return (self.date_peremption - aujourd_hui).days

    def etat(self, aujourd_hui=None, seuil_alerte: int = 30) -> str:
        """`perime`, `bientot` ou `bon`.

        Le seuil par défaut est de 30 jours. Ce n'est pas une valeur universelle
        — un yaourt et une boîte d'amoxicilline n'ont pas le même horizon — mais
        c'est le délai à partir duquel un commerçant peut encore agir : écouler,
        remiser, retourner au grossiste. En deçà, l'alerte ne sert plus qu'à
        constater la perte.
        """
        jours = self.jours_restants(aujourd_hui)
        if jours < 0:
            return "perime"
        if jours <= seuil_alerte:
            return "bientot"
        return "bon"


class NumeroSerie(TenantScopedModel):
    """Un exemplaire, nommé — numéro de série ou IMEI.

    Réservé aux métiers qui l'activent (`apps/marketplace/metiers.py`), et même
    là, seulement aux variantes marquées `suivi_unitaire` : une boutique
    d'électronique vend des téléphones **et** des câbles, et demander un IMEI
    pour un câble serait la meilleure façon de faire abandonner la fonction.

    **Ce n'est pas un lot.** Un `LotStock` compte des quantités qui périment ; un
    `NumeroSerie` nomme un objet unique. La différence porte toute la valeur de
    la fonction : le lot répond à « combien me reste-t-il », l'exemplaire répond
    à « ce téléphone-là, d'où vient-il et qui l'a acheté » — la question que pose
    un client qui revient avec un appareil en panne, six mois après.

    **Le numéro n'est pas un stock parallèle.** La quantité reste portée par
    `NiveauStock`, valorisée au CMP, et c'est elle qui fait foi. Les exemplaires
    la doublent nominativement, sans jamais la contredire : un appareil reçu sans
    numéro n'est pas un appareil manquant, c'est un appareil non nommé, et
    `apps/inventory/series.py` sait dire combien il y en a. Faire du numéro la
    source de vérité aurait imposé de refuser une réception mal saisie, donc de
    refuser de la marchandise physiquement présente.

    **Le numéro est unique dans la boutique, et sa ligne se réemploie.** Un
    appareil vendu puis repris d'occasion repasse `EN_STOCK` sur la même ligne :
    c'est le même objet, et son histoire — vente, garantie, passages à l'atelier —
    vaut précisément parce qu'elle ne s'interrompt pas.

    Le lien vers la vente est un identifiant nu, pas une clé étrangère : `pos`
    est au-dessus d'`inventory` dans le graphe de dépendances (docs/09, §2), et
    le stock ne remonte jamais vers la caisse. C'est la même construction que
    `MouvementStock.origine_id`. Le numéro du ticket est recopié à côté pour que
    l'écran du SAV se lise sans requête supplémentaire — et pour qu'il reste
    lisible même si le ticket disparaissait.
    """

    EN_STOCK = "en_stock"
    VENDU = "vendu"
    ATELIER = "atelier"
    SORTI = "sorti"
    ETATS = [
        (EN_STOCK, "En stock"),
        (VENDU, "Vendu"),
        (ATELIER, "À l'atelier"),
        (SORTI, "Sorti du parc"),
    ]

    variante = models.ForeignKey(
        "catalog.Variante", on_delete=models.PROTECT, related_name="exemplaires"
    )
    depot = models.ForeignKey(Depot, on_delete=models.PROTECT, related_name="exemplaires")
    numero = models.CharField(max_length=64, db_index=True, verbose_name="numéro de série")
    etat = models.CharField(max_length=16, choices=ETATS, default=EN_STOCK, db_index=True)
    recu_le = models.DateField(default=timezone.localdate)
    vendu_le = models.DateTimeField(null=True, blank=True)
    garantie_fin = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Échéance figée le jour de la vente. Raccourcir la garantie du "
            "catalogue ne doit pas raccourcir celles déjà vendues."
        ),
    )
    ticket_id = models.UUIDField(null=True, blank=True)
    ticket_numero = models.CharField(max_length=32, blank=True)
    client = models.CharField(max_length=180, blank=True)
    commentaire = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "exemplaire"
        verbose_name_plural = "exemplaires"
        ordering = ["-recu_le", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["boutique", "numero"], name="numero_serie_unique_par_boutique"
            )
        ]
        indexes = [models.Index(fields=["boutique", "etat"])]

    def __str__(self):
        return f"{self.variante} · {self.numero}"

    def sous_garantie(self, jour=None) -> bool:
        """La garantie court-elle encore ?

        Sans échéance, la réponse est non : un appareil jamais vendu n'a pas de
        garantie en cours, et un appareil vendu sans durée n'en avait pas. Dire
        « oui » par défaut ferait offrir des réparations que personne n'a promises.
        """
        if self.garantie_fin is None:
            return False
        return self.garantie_fin >= (jour or timezone.localdate())

    def jours_de_garantie(self, jour=None) -> int | None:
        if self.garantie_fin is None:
            return None
        return (self.garantie_fin - (jour or timezone.localdate())).days


class PassageAtelier(TenantScopedModel):
    """Un appareil entré en réparation, et ce qu'il en est ressorti.

    Un simple état sur l'exemplaire aurait suffi à savoir qu'il est à l'atelier
    aujourd'hui. Il n'aurait pas suffi à savoir que c'est son troisième passage
    en quatre mois — et c'est cette information-là qui fait décider un commerçant
    d'échanger l'appareil plutôt que de le réparer une fois de plus.

    **La couverture est figée à l'entrée.** Un appareil déposé la veille de
    l'échéance est réparé sous garantie, même si l'atelier le rend trois semaines
    plus tard : ce qui compte est la date à laquelle la panne a été déclarée, pas
    celle où le technicien a fini. Recalculer à la sortie ferait basculer en
    payant une réparation déjà promise gratuite.
    """

    exemplaire = models.ForeignKey(
        NumeroSerie, on_delete=models.CASCADE, related_name="passages"
    )
    entre_le = models.DateTimeField(default=timezone.now)
    motif = models.CharField(max_length=255)
    sous_garantie = models.BooleanField(
        default=False, help_text="Figé à l'entrée : c'est la date du dépôt qui décide."
    )
    sorti_le = models.DateTimeField(null=True, blank=True)
    resultat = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "passage à l'atelier"
        verbose_name_plural = "passages à l'atelier"
        ordering = ["-entre_le"]
        indexes = [models.Index(fields=["boutique", "sorti_le"])]

    def __str__(self):
        return f"{self.exemplaire.numero} — {self.motif}"

    @property
    def en_cours(self) -> bool:
        return self.sorti_le is None


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
