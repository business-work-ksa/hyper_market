"""Les formulaires de la vérification — console et back-office.

Ils ne décident de rien : ils lisent la saisie et la mettent en forme. Les refus — pièce expirée,
identifiant fiscal d'un autre pays, opérateur hors pays, titulaire qui ne correspond pas — sont
dans `apps/confiance/verification.py`, et reviennent ici comme erreurs de champ
(`reporter_erreurs`). Un formulaire n'est jamais la dernière barrière.
"""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import DossierKyc
from apps.confiance import verification
from apps.marketplace import cemac
from django.utils.translation import gettext_lazy as _l

CHAMP = {"class": "champ"}


def reporter_erreurs(formulaire: forms.Form, erreur: ValidationError, *, correspondances=None) -> None:
    """Range les refus du service sous les champs du formulaire, et le reste en tête."""
    correspondances = correspondances or {}
    if hasattr(erreur, "error_dict"):
        for cle, messages in erreur.message_dict.items():
            cle = correspondances.get(cle, cle)
            for message in messages:
                formulaire.add_error(cle if cle in formulaire.fields else None, message)
    else:
        for message in erreur.messages:
            formulaire.add_error(None, message)


class AttestationForm(forms.Form):
    """Ce que l'administrateur a vu sur l'original. Pas de copie, sauf stockage désigné."""

    type_piece = forms.ChoiceField(label=_l("Pièce vue"))
    gerant = forms.ChoiceField(
        label=_l("Gérant"), required=False, help_text=_l("Pour une pièce d'identité : la personne dont c'est la pièce.")
    )
    numero = forms.CharField(
        label=_l("Numéro lu sur la pièce"),
        max_length=64,
        widget=forms.TextInput(attrs={**CHAMP, "autocomplete": "off", "spellcheck": "false"}),
    )
    pays = forms.CharField(
        label=_l("Pays émetteur"),
        max_length=2,
        required=False,
        help_text=_l("Code à deux lettres : CM, GA, CG, TD, CF, GQ… Pour une pièce de la boutique, c'est son pays."),
        widget=forms.TextInput(attrs={**CHAMP, "list": "pays-cemac", "autocomplete": "off", "size": 4}),
    )
    expire_le = forms.DateField(
        label=_l("Date d'expiration"),
        required=False,
        widget=forms.DateInput(attrs={**CHAMP, "type": "date"}, format="%Y-%m-%d"),
        help_text=_l("Obligatoire pour une pièce d'identité ; sans objet pour le RCCM et l'identifiant fiscal."),
    )
    nom_lu = forms.CharField(
        label=_l("Nom tel qu'il figure sur la pièce"),
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={**CHAMP, "autocomplete": "off"}),
        help_text=_l("Recopié lettre à lettre : c'est à lui qu'on comparera le titulaire du compte de versement."),
    )
    mode = forms.ChoiceField(
        label=_l("Comment avez-vous vu l'original ?"),
        choices=[
            (DossierKyc.PRESENTIEL, "En présentiel"),
            (DossierKyc.VISIO, "En visio"),
            (DossierKyc.DOCUMENT_RECU, "Document reçu, puis supprimé"),
        ],
        widget=forms.RadioSelect,
        initial=DossierKyc.PRESENTIEL,
    )
    empreinte = forms.CharField(
        label=_l("Empreinte SHA-256 du document reçu"),
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={**CHAMP, "autocomplete": "off", "spellcheck": "false", "class": "champ v-empreinte"}),
        help_text=(
            _l("Choisissez le fichier ci-dessus : l'empreinte est calculée dans votre navigateur, le fichier "
            "n'est jamais envoyé. Supprimez-le ensuite de votre téléphone ou de votre messagerie.")
        ),
    )
    copie = forms.FileField(
        label=_l("Copie à conserver"),
        required=False,
        help_text=_l("Un stockage persistant et privé est désigné : la copie y sera conservée, et son empreinte calculée."),
    )

    def __init__(self, *args, boutique, **kwargs):
        super().__init__(*args, **kwargs)
        self.boutique = boutique
        self.gerants = verification.gerants(boutique)
        libelles = dict(DossierKyc.TYPES_PIECE)
        choix = [(t, libelles[t]) for t in verification.pieces_admises(boutique.pays) if t in libelles]
        choix += [(DossierKyc.RCCM, libelles[DossierKyc.RCCM])]
        sigle = verification.sigle_fiscal(boutique)
        choix += [(sigle, libelles[sigle])]
        self.fields["type_piece"].choices = choix
        self.fields["type_piece"].widget.attrs.update(CHAMP)
        self.fields["gerant"].choices = [("", "—")] + [(str(g.pk), g.nom_complet) for g in self.gerants]
        self.fields["gerant"].widget.attrs.update(CHAMP)
        if len(self.gerants) == 1:
            self.fields["gerant"].initial = str(self.gerants[0].pk)
        self.fields["pays"].initial = boutique.pays
        # La porte des copies est fermée tant qu'aucun stockage persistant n'est désigné : le
        # champ n'existe pas, et l'écran dit pourquoi.
        self.stockage_ouvert = verification.stockage_des_copies() is not None
        if not self.stockage_ouvert:
            del self.fields["copie"]

    def clean_gerant(self):
        valeur = self.cleaned_data.get("gerant")
        if not valeur:
            return None
        return next((g for g in self.gerants if str(g.pk) == valeur), None)


class AppelForm(forms.Form):
    """L'appel de vérification : pas de SMS, un humain qui appelle et qui l'atteste."""

    gerant = forms.ChoiceField(label=_l("Gérant appelé"))
    confirme = forms.BooleanField(
        label=_l("J'ai appelé ce numéro, et c'est bien le gérant qui a répondu."),
        error_messages={"required": "Cochez l'attestation : c'est elle qui vaut vérification."},
    )
    note = forms.CharField(
        label=_l("Note"),
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={**CHAMP, "autocomplete": "off"}),
        help_text=_l("Facultatif : date convenue, question de contrôle posée…"),
    )

    def __init__(self, *args, boutique, **kwargs):
        super().__init__(*args, **kwargs)
        self.gerants = [g for g in verification.gerants(boutique) if not g.telephone_verifie]
        self.fields["gerant"].choices = [
            (str(g.pk), f"{g.nom_complet} — {verification.masquer(g.telephone, 3)}") for g in self.gerants
        ]
        self.fields["gerant"].widget.attrs.update(CHAMP)

    def clean_gerant(self):
        valeur = self.cleaned_data.get("gerant")
        return next((g for g in self.gerants if str(g.pk) == valeur), None)


class CompteForm(forms.Form):
    """Déclarer un compte de versement. Opérateurs restreints à ceux du pays de la boutique."""

    operateur = forms.ChoiceField(label=_l("Opérateur"), widget=forms.RadioSelect)
    numero = forms.CharField(
        label=_l("Numéro"),
        max_length=40,
        widget=forms.TextInput(attrs={**CHAMP, "autocomplete": "off", "inputmode": "tel", "spellcheck": "false"}),
    )
    titulaire = forms.CharField(
        label=_l("Titulaire, tel que l'opérateur l'affiche"),
        max_length=160,
        widget=forms.TextInput(attrs={**CHAMP, "autocomplete": "off"}),
        help_text=_l("Le nom de la pièce d'identité du gérant, ou la raison sociale de la boutique."),
    )

    def __init__(self, *args, boutique, **kwargs):
        super().__init__(*args, **kwargs)
        p = verification.pays_ou_none(boutique.pays)
        self.fields["operateur"].choices = [
            (o, cemac.LIBELLES_OPERATEURS[o]) for o in verification.operateurs_admis(boutique.pays)
        ]
        if p:
            self.fields["numero"].help_text = (
                f"Mobile Money : {p.indicatif} suivi de {p.longueur_numero} chiffres. Virement : RIB ou IBAN."
            )
            self.fields["numero"].widget.attrs["placeholder"] = f"{p.indicatif}{'6' * p.longueur_numero}"


class DecisionForm(forms.Form):
    VALIDER, REJETER = "valider", "rejeter"
    decision = forms.ChoiceField(choices=[(VALIDER, "Valider"), (REJETER, "Rejeter")])
    motif = forms.CharField(
        label=_l("Motif du rejet"),
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={**CHAMP, "rows": 2, "maxlength": 300}),
        help_text=_l("Le commerçant le lira : dites ce qu'il doit corriger."),
    )
