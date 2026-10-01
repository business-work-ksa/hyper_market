"""Formulaire du tunnel de commande.

Il demande le strict nécessaire pour qu'un marchand puisse livrer : un nom, un
numéro, une adresse. Chaque champ supplémentaire est un acheteur perdu, et rien
ici ne sert à la plateforme — tout sert au commerçant qui prépare le colis.
"""

from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import validateur_telephone

# Même règle que celle du compte (`apps.accounts.models`), message dans la langue du marché.
validateur_telephone_marche = RegexValidator(
    validateur_telephone.regex,
    _("Numéro de téléphone invalide. Format attendu : +237699000000."),
)

CHAMP = {"class": "input"}
CHAMP_GRAND = {"class": "input input-lg"}


class CommandeForm(forms.Form):
    nom_complet = forms.CharField(
        label=_("Votre nom"),
        max_length=150,
        widget=forms.TextInput(attrs={**CHAMP_GRAND, "placeholder": "Marie Ekedi", "autocomplete": "name"}),
    )
    telephone = forms.CharField(
        label=_("Votre téléphone"),
        max_length=16,
        validators=[validateur_telephone_marche],
        help_text=_("C'est par là que le marchand vous joindra pour la livraison."),
        widget=forms.TextInput(
            attrs={**CHAMP_GRAND, "placeholder": "+237699000000", "inputmode": "tel", "autocomplete": "tel"}
        ),
    )
    adresse_livraison = forms.CharField(
        label=_("Où livrer"),
        max_length=255,
        widget=forms.TextInput(
            attrs={**CHAMP, "placeholder": _("Quartier, rue, point de repère"), "autocomplete": "street-address"}
        ),
    )
    # Le mode de paiement vaut pour tout le panier ; la vitrine dit, boutique par boutique, où le
    # prépaiement n'est pas encore possible (plafond de séquestre d'une boutique nouvelle).
    mode_paiement = forms.ChoiceField(
        label=_("Comment payer"),
        choices=[
            ("prepaye", _("Payer d'avance par Mobile Money")),
            ("livraison", _("Payer à la livraison")),
        ],
        initial="prepaye",
        widget=forms.RadioSelect,
        # Absent de l'envoi — un client ancien, un formulaire tronqué —, on retombe sur ce que la
        # vitrine promettait avant le séquestre : le paiement à la livraison. Jamais l'inverse :
        # on n'engage pas un acheteur dans un prépaiement qu'il n'a pas choisi.
        required=False,
    )
    note = forms.CharField(
        label=_("Précisions pour le marchand"),
        required=False,
        widget=forms.Textarea(
            attrs={**CHAMP, "rows": 3, "placeholder": _("Horaire, étage, autre numéro…")}
        ),
    )

    # Boutiques chez qui l'acheteur a vu qu'il paierait à la livraison : recopié par la page, pour
    # qu'on n'applique jamais un paiement à la livraison qu'il n'a pas vu annoncé.
    a_la_livraison = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, prepaiement_ouvert: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.prepaiement_ouvert = prepaiement_ouvert
        if not prepaiement_ouvert:
            # Aucun moyen de payer en ligne n'est ouvert : on ne propose pas ce qu'on ne peut pas
            # encaisser. Le choix reste affiché, seul, pour que l'acheteur sache comment il paiera.
            self.fields["mode_paiement"].choices = [("livraison", _("Payer à la livraison"))]
            self.fields["mode_paiement"].initial = "livraison"

    def clean_mode_paiement(self):
        choix = self.cleaned_data.get("mode_paiement") or "livraison"
        # Un envoi forgé ne doit pas engager un prépaiement que la page n'offrait pas.
        return choix if self.prepaiement_ouvert else "livraison"

    def clean_a_la_livraison(self):
        return {v for v in (self.cleaned_data.get("a_la_livraison") or "").split(",") if v}

    def clean_telephone(self):
        return self.cleaned_data["telephone"].strip().replace(" ", "")
