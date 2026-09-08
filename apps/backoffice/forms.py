"""Formulaires du back-office.

Écrits à la main plutôt que par `ModelForm` : les écrans de reprise de stock et
d'ouverture de caisse touchent plusieurs modèles à la fois et passent par les
services (`entrer_stock`, `ouvrir_session`), jamais par un `save()` direct. Un
`ModelForm` donnerait l'illusion qu'on peut écrire le stock sans passer par son
journal — c'est exactement ce qu'il faut empêcher.
"""

from decimal import Decimal

from django import forms

from apps.catalog.models import Produit

CHAMP = {"class": "champ"}
CHAMP_GRAND = {"class": "champ champ--grand"}


class ArticleForm(forms.Form):
    """Création d'un article avec son stock initial — l'écran de l'installation.

    Un seul formulaire produit le produit, la variante, le niveau de stock et le
    mouvement d'entrée valorisé. C'est volontaire : pendant un comptage debout
    dans une réserve, on ne remplit pas quatre écrans par référence.
    """

    libelle = forms.CharField(
        label="Nom de l'article",
        max_length=200,
        widget=forms.TextInput(attrs={**CHAMP_GRAND, "placeholder": "Ciment CIMENCAM 50 kg"}),
    )
    sku = forms.CharField(
        label="Référence",
        max_length=64,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "QUI-CIM-50"}),
    )
    code_barres = forms.CharField(
        label="Code-barres", max_length=32, required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Scannez ou laissez vide"}),
    )
    prix_vente = forms.DecimalField(
        label="Prix de vente TTC", min_value=Decimal("0"), decimal_places=2,
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "numeric", "step": "1"}),
    )
    cout_unitaire = forms.DecimalField(
        label="Coût d'achat unitaire", min_value=Decimal("0"), decimal_places=2,
        help_text="Ce que vous payez au fournisseur. C'est lui qui donne votre marge réelle.",
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "numeric", "step": "1"}),
    )
    quantite = forms.DecimalField(
        label="Quantité comptée", min_value=Decimal("0"), initial=Decimal("0"), decimal_places=4,
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "decimal", "step": "1"}),
    )
    seuil_alerte = forms.DecimalField(
        label="Seuil d'alerte", min_value=Decimal("0"), initial=Decimal("0"), decimal_places=4,
        help_text="En dessous de combien faut-il recommander ?",
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "decimal", "step": "1"}),
    )
    regime_tva = forms.ChoiceField(
        label="Régime de TVA", choices=Produit.REGIMES_TVA, initial=Produit.NORMAL,
        widget=forms.Select(attrs=CHAMP),
    )

    def __init__(self, *args, boutique=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.boutique = boutique

    def clean_sku(self):
        sku = self.cleaned_data["sku"].strip().upper()
        from apps.catalog.models import Variante

        if Variante.objects.filter(sku=sku).exists():
            raise forms.ValidationError("Cette référence existe déjà dans votre boutique.")
        return sku

    def clean(self):
        donnees = super().clean()
        prix = donnees.get("prix_vente")
        cout = donnees.get("cout_unitaire")
        if prix is not None and cout is not None and cout > prix:
            # Avertissement, pas blocage : une vente à perte se décide, elle
            # n'est pas interdite. Mais elle ne doit pas être une surprise.
            self.add_error(
                "cout_unitaire",
                "Le coût d'achat dépasse le prix de vente : vous vendriez à perte.",
            )
        return donnees


class EntreeStockForm(forms.Form):
    """Réception fournisseur sur un article existant."""

    quantite = forms.DecimalField(
        label="Quantité reçue", min_value=Decimal("0.0001"), decimal_places=4,
        widget=forms.NumberInput(attrs={**CHAMP_GRAND, "inputmode": "decimal", "step": "1"}),
    )
    cout_unitaire = forms.DecimalField(
        label="Coût d'achat unitaire", min_value=Decimal("0"), decimal_places=2,
        help_text="Le coût moyen pondéré sera recalculé avec cette entrée.",
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "numeric", "step": "1"}),
    )
    commentaire = forms.CharField(
        label="Commentaire", max_length=255, required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Bon de livraison n° …"}),
    )


class OuvertureCaisseForm(forms.Form):
    fonds_ouverture = forms.DecimalField(
        label="Fonds de caisse au démarrage", min_value=Decimal("0"),
        initial=Decimal("0"), decimal_places=2,
        help_text="Les espèces présentes dans le tiroir avant la première vente.",
        widget=forms.NumberInput(attrs={**CHAMP_GRAND, "inputmode": "numeric", "step": "100"}),
    )


class FermetureCaisseForm(forms.Form):
    fonds_compte = forms.DecimalField(
        label="Espèces comptées dans le tiroir", min_value=Decimal("0"), decimal_places=2,
        help_text="Comptez avant de regarder le montant théorique.",
        widget=forms.NumberInput(attrs={**CHAMP_GRAND, "inputmode": "numeric", "step": "100"}),
    )
