"""Représentations JSON.

Une règle gouverne ce module : **un champ qu'un rôle n'a pas le droit de voir
n'est pas présent dans la réponse.** Il n'est ni vidé, ni mis à `null`, ni
remplacé par une valeur neutre — il n'existe pas.

La différence n'est pas cosmétique. Un champ à `null` dit au client qu'il
existe, l'invite à le demander autrement, et fait croire à l'appelant que la
donnée a transité. Un champ absent dit ce qui est vrai : pour ce porteur de
jeton, cette information n'a pas quitté le serveur.

Le mécanisme est `ChampsSelonDroits` : les champs protégés sont retirés du
sérialiseur avant toute lecture de l'objet, à partir des droits passés en
contexte par la vue. Ce sont les mêmes droits que ceux qui gardent la porte
(`apps/accounts/permissions.py`) — jamais une seconde table de correspondance.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.accounts.permissions import COUT_VOIR, MARGE_VOIR
from apps.inventory.models import Depot, MouvementStock, NiveauStock
from apps.orders.models import LigneCommande, SousCommande
from apps.pos.models import LigneTicket, ReglementTicket, Ticket

__all__ = [
    "ChampsSelonDroits",
    "DepotSerialiseur",
    "ArticleSerialiseur",
    "MouvementStockSerialiseur",
    "TicketSerialiseur",
    "TicketDetailSerialiseur",
    "SousCommandeSerialiseur",
    "LigneBalanceSerialiseur",
    "EntreeStockSerialiseur",
    "EncaissementSerialiseur",
]


class ChampsSelonDroits:
    """Retire les champs dont le droit n'est pas acquis.

    `champs_proteges` associe un nom de champ au droit qui l'ouvre. Le retrait a
    lieu dans `get_fields`, c'est-à-dire **avant** que le champ ne lise quoi que
    ce soit sur l'objet : une propriété coûteuse protégée par un droit n'est
    jamais évaluée pour qui ne l'a pas.

    Écrit comme mélange plutôt que comme classe de base, pour s'appliquer aussi
    bien à un `Serializer` qu'à un `ModelSerializer`.
    """

    champs_proteges: dict[str, str] = {}

    def get_fields(self):
        champs = super().get_fields()
        droits = self.context.get("droits") or frozenset()
        for nom, droit in self.champs_proteges.items():
            if droit not in droits:
                champs.pop(nom, None)
        return champs


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
class DepotSerialiseur(serializers.ModelSerializer):
    class Meta:
        model = Depot
        fields = ["id", "libelle", "type", "adresse", "principal", "actif"]


class ArticleSerialiseur(ChampsSelonDroits, serializers.Serializer):
    """Article vendable, vu depuis un dépôt.

    Construit à partir d'un dictionnaire assemblé par la vue plutôt que d'un
    modèle : un « article » n'existe pas en base. C'est une variante, jointe à
    son niveau de stock dans un dépôt donné — et le niveau peut ne pas exister
    encore, pour un produit jamais reçu.
    """

    id = serializers.UUIDField()
    sku = serializers.CharField()
    code_barres = serializers.CharField(allow_blank=True)
    libelle = serializers.CharField()
    categorie = serializers.CharField(allow_blank=True)
    unite = serializers.CharField()
    attributs = serializers.DictField()
    prix_vente = serializers.DecimalField(max_digits=12, decimal_places=2)
    taux_tva = serializers.DecimalField(max_digits=5, decimal_places=4)
    quantite = serializers.DecimalField(max_digits=14, decimal_places=4)
    seuil_alerte = serializers.DecimalField(max_digits=14, decimal_places=4)
    en_alerte = serializers.BooleanField()

    # Protégés : le coût d'achat lu au comptoir circule dans le quartier avant
    # la fin de la journée (`apps/accounts/permissions.py`).
    cmp = serializers.DecimalField(max_digits=14, decimal_places=4, required=False)
    valeur_stock = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)

    champs_proteges = {"cmp": COUT_VOIR, "valeur_stock": COUT_VOIR}

    @staticmethod
    def assembler(variante, niveau: NiveauStock | None) -> dict:
        quantite = niveau.quantite if niveau else Decimal("0")
        seuil = niveau.seuil_alerte if niveau else Decimal("0")
        cmp_ = niveau.cmp if niveau else Decimal("0")
        return {
            "id": variante.id,
            "sku": variante.sku,
            "code_barres": variante.code_barres or "",
            "libelle": str(variante),
            "categorie": (
                variante.produit.categorie.libelle if variante.produit.categorie_id else ""
            ),
            "unite": variante.produit.unite,
            "attributs": variante.attributs or {},
            "prix_vente": variante.prix_vente,
            "taux_tva": variante.taux_tva,
            "quantite": quantite,
            "seuil_alerte": seuil,
            "en_alerte": quantite <= seuil,
            "cmp": cmp_,
            "valeur_stock": (quantite * cmp_).quantize(Decimal("0.01")),
        }


class MouvementStockSerialiseur(ChampsSelonDroits, serializers.ModelSerializer):
    variante_libelle = serializers.SerializerMethodField()
    depot_libelle = serializers.CharField(source="depot.libelle", read_only=True)
    type_libelle = serializers.CharField(source="get_type_display", read_only=True)

    champs_proteges = {"cout_unitaire": COUT_VOIR, "cmp_apres": COUT_VOIR}

    def get_variante_libelle(self, mouvement) -> str:
        return str(mouvement.variante)

    class Meta:
        model = MouvementStock
        fields = [
            "id",
            "cree_le",
            "depot",
            "depot_libelle",
            "variante",
            "variante_libelle",
            "type",
            "type_libelle",
            "quantite",
            "quantite_apres",
            "cout_unitaire",
            "cmp_apres",
            "origine_type",
            "origine_id",
            "operation_id",
            "commentaire",
        ]


class LigneTicketSerialiseur(serializers.ModelSerializer):
    class Meta:
        model = LigneTicket
        fields = ["id", "variante", "libelle", "quantite", "pu_ttc", "taux_tva", "remise"]


class ReglementSerialiseur(serializers.ModelSerializer):
    moyen_libelle = serializers.CharField(source="get_moyen_display", read_only=True)

    class Meta:
        model = ReglementTicket
        fields = ["id", "moyen", "moyen_libelle", "montant", "reference_psp"]


class TicketSerialiseur(serializers.ModelSerializer):
    depot = serializers.UUIDField(source="session.depot_id", read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "numero",
            "etat",
            "client_nom",
            "client_telephone",
            "total_ht",
            "total_tva",
            "total_ttc",
            "cloture_le",
            "cree_le",
            "operation_id",
            "depot",
        ]


class TicketDetailSerialiseur(ChampsSelonDroits, TicketSerialiseur):
    """Ticket complet. Le coût et la marge n'apparaissent qu'avec le droit.

    Ils ne sont pas seulement masqués : `cout_marchandise` interroge les
    mouvements de stock du ticket. Sans le droit, le champ est retiré avant
    lecture et **la requête n'a pas lieu**.
    """

    lignes = LigneTicketSerialiseur(many=True, read_only=True)
    reglements = ReglementSerialiseur(many=True, read_only=True)
    cout_marchandise = serializers.SerializerMethodField()
    marge = serializers.SerializerMethodField()

    champs_proteges = {"cout_marchandise": COUT_VOIR, "marge": MARGE_VOIR}

    class Meta(TicketSerialiseur.Meta):
        fields = TicketSerialiseur.Meta.fields + [
            "lignes",
            "reglements",
            "cout_marchandise",
            "marge",
        ]

    def _cout(self, ticket) -> Decimal:
        mouvements = MouvementStock.objects.filter(
            origine_type="pos.Ticket", origine_id=ticket.pk
        )
        return sum(
            (abs(m.quantite) * m.cout_unitaire for m in mouvements), Decimal("0")
        ).quantize(Decimal("0.01"))

    def get_cout_marchandise(self, ticket) -> Decimal:
        return self._cout(ticket)

    def get_marge(self, ticket) -> Decimal:
        return (ticket.total_ht - self._cout(ticket)).quantize(Decimal("0.01"))


class LigneSousCommandeSerialiseur(serializers.ModelSerializer):
    class Meta:
        model = LigneCommande
        fields = ["id", "variante", "libelle", "quantite", "pu_ttc", "taux_tva", "remise"]


class SousCommandeSerialiseur(serializers.ModelSerializer):
    """Part d'une commande revenant à cette boutique.

    Le numéro de la commande d'ensemble est exposé — le marchand en a besoin pour
    parler à l'acheteur — mais **rien de ce qui a été commandé ailleurs** ne l'est.
    """

    numero = serializers.CharField(source="commande.numero", read_only=True)
    acheteur = serializers.CharField(source="commande.acheteur.nom_complet", read_only=True)
    etat_libelle = serializers.CharField(source="get_etat_display", read_only=True)
    lignes = LigneSousCommandeSerialiseur(many=True, read_only=True)

    class Meta:
        model = SousCommande
        fields = [
            "id",
            "numero",
            "acheteur",
            "etat",
            "etat_libelle",
            "total_ht",
            "total_tva",
            "total_ttc",
            "taux_commission",
            "commission_plateforme",
            "livree_le",
            "cree_le",
            "lignes",
        ]


class LigneBalanceSerialiseur(serializers.Serializer):
    numero = serializers.CharField()
    intitule = serializers.CharField()
    debit = serializers.DecimalField(max_digits=16, decimal_places=2)
    credit = serializers.DecimalField(max_digits=16, decimal_places=2)
    solde = serializers.DecimalField(max_digits=16, decimal_places=2)


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------
class LigneEncaissementSerialiseur(serializers.Serializer):
    variante = serializers.UUIDField()
    quantite = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    remise = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=Decimal("0"), min_value=Decimal("0")
    )
    numeros = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        default=list,
        help_text=(
            "Numéros de série ou IMEI des exemplaires vendus, pour les articles "
            "suivis à l'unité. Ignorés ailleurs."
        ),
    )


class EncaissementSerialiseur(serializers.Serializer):
    """Un encaissement complet, en un appel.

    `operation_id` est facultatif mais fortement recommandé : c'est lui qui rend
    la retransmission sûre (ADR-004). Un client qui ne le fournit pas assume de
    ne pas pouvoir réessayer sans risquer un doublon.
    """

    operation_id = serializers.UUIDField(required=False, allow_null=True)
    depot = serializers.UUIDField(required=False, allow_null=True)
    lignes = LigneEncaissementSerialiseur(many=True, allow_empty=False)
    moyen = serializers.ChoiceField(
        choices=[code for code, _ in ReglementTicket.MOYENS], default=ReglementTicket.ESPECES
    )
    client_nom = serializers.CharField(max_length=180, required=False, allow_blank=True, default="")
    client_telephone = serializers.CharField(
        max_length=16, required=False, allow_blank=True, default=""
    )
    reference_psp = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    encaisse_le = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text=(
            "Heure réelle de la vente. À fournir pour une vente hors ligne : "
            "les écritures comptables la portent, et le journal en ajout seul "
            "refusera de la corriger ensuite."
        ),
    )


class EntreeStockSerialiseur(serializers.Serializer):
    """Réception de marchandise."""

    operation_id = serializers.UUIDField(required=False, allow_null=True)
    depot = serializers.UUIDField(required=False, allow_null=True)
    variante = serializers.UUIDField()
    quantite = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    cout_unitaire = serializers.DecimalField(
        max_digits=14, decimal_places=4, min_value=Decimal("0")
    )
    commentaire = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
