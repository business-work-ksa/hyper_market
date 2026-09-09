"""Formulaire du tunnel de commande.

Il demande le strict nécessaire pour qu'un marchand puisse livrer : un nom, un
numéro, une adresse. Chaque champ supplémentaire est un acheteur perdu, et rien
ici ne sert à la plateforme — tout sert au commerçant qui prépare le colis.
"""

from django import forms

from apps.accounts.models import validateur_telephone

CHAMP = {"class": "champ"}
CHAMP_GRAND = {"class": "champ champ--grand"}


class CommandeForm(forms.Form):
    nom_complet = forms.CharField(
        label="Votre nom",
        max_length=150,
        widget=forms.TextInput(attrs={**CHAMP_GRAND, "placeholder": "Marie Ekedi"}),
    )
    telephone = forms.CharField(
        label="Votre téléphone",
        max_length=16,
        validators=[validateur_telephone],
        help_text="C'est par là que le marchand vous joindra pour la livraison.",
        widget=forms.TextInput(
            attrs={**CHAMP_GRAND, "placeholder": "+237699000000", "inputmode": "tel"}
        ),
    )
    adresse_livraison = forms.CharField(
        label="Où livrer",
        max_length=255,
        widget=forms.TextInput(
            attrs={**CHAMP, "placeholder": "Quartier, rue, point de repère"}
        ),
    )
    note = forms.CharField(
        label="Précisions pour le marchand",
        required=False,
        widget=forms.Textarea(
            attrs={**CHAMP, "rows": 3, "placeholder": "Horaire, étage, autre numéro…"}
        ),
    )

    def clean_telephone(self):
        return self.cleaned_data["telephone"].strip().replace(" ", "")
