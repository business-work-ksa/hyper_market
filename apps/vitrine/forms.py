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
    # Le mode de paiement vaut pour tout le panier ; la vitrine dit, boutique par boutique, où le
    # prépaiement n'est pas encore possible (plafond de séquestre d'une boutique nouvelle).
    mode_paiement = forms.ChoiceField(
        label="Comment payer",
        choices=[
            ("prepaye", "Payer d'avance par Mobile Money"),
            ("livraison", "Payer à la livraison"),
        ],
        initial="prepaye",
        widget=forms.RadioSelect,
        # Absent de l'envoi — un client ancien, un formulaire tronqué —, on retombe sur ce que la
        # vitrine promettait avant le séquestre : le paiement à la livraison. Jamais l'inverse :
        # on n'engage pas un acheteur dans un prépaiement qu'il n'a pas choisi.
        required=False,
    )
    note = forms.CharField(
        label="Précisions pour le marchand",
        required=False,
        widget=forms.Textarea(
            attrs={**CHAMP, "rows": 3, "placeholder": "Horaire, étage, autre numéro…"}
        ),
    )

    # Boutiques chez qui l'acheteur a vu qu'il paierait à la livraison : recopié par la page, pour
    # qu'on n'applique jamais un paiement à la livraison qu'il n'a pas vu annoncé.
    a_la_livraison = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_mode_paiement(self):
        return self.cleaned_data.get("mode_paiement") or "livraison"

    def clean_a_la_livraison(self):
        return {v for v in (self.cleaned_data.get("a_la_livraison") or "").split(",") if v}

    def clean_telephone(self):
        return self.cleaned_data["telephone"].strip().replace(" ", "")
