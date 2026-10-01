"""Les formulaires de la console : une étape d'assistant, ou un geste d'une page.

Écrits à la main plutôt que par `ModelForm`, pour la raison que donne déjà
`apps/backoffice/forms.py` : ces écrans touchent plusieurs modèles à la fois et passent par les
services (`apps/plateforme/services.py`), jamais par un `save()` direct.

Ils **vérifient tôt** ce que le service revérifiera : un refus affiché à l'étape du gérant vaut
mieux qu'un refus au récapitulatif, cinq écrans plus loin. Mais la règle, elle, vit une seule fois
— dans le service ou dans le modèle —, et le formulaire l'appelle au lieu de la recopier.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from apps.accounts.administration import LIBELLES_ROLES_ADMINISTRATION
from apps.accounts.models import validateur_telephone
from apps.marketplace.metiers import CHOIX_METIER, METIER_DEFAUT
from apps.marketplace.models import Boutique, EmplacementPremium, Rayon, TypeEmplacement
from apps.plateforme import services
from apps.plateforme.assistant import Confirmation, FormulaireEtape

CHAMP = {"class": "champ"}
CHAMP_GRAND = {"class": "champ champ--grand"}
CENT = Decimal("100")


# ----------------------------------------------------------------------------
# Champs
# ----------------------------------------------------------------------------
class ChampNombre(forms.DecimalField):
    """Accepte « 45 000 » et « 5,5 » : c'est ainsi qu'on écrit un nombre au Cameroun.

    Le champ est un `TextInput` et non un `number` : un navigateur refuse la virgule dans un champ
    numérique, et le refus est silencieux — la valeur disparaît au lieu d'être corrigée.
    """

    def __init__(self, *args, placeholder="", **kwargs):
        kwargs.setdefault(
            "widget",
            forms.TextInput(attrs={**CHAMP, "inputmode": "decimal", "autocomplete": "off", "placeholder": placeholder}),
        )
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
        return super().to_python(value)


def _telephone(valeur: str) -> str:
    return (valeur or "").strip().replace(" ", "").replace(".", "").replace("-", "")


def _chiffre(valeur) -> str:
    """Un nombre réaffiché dans un champ, sans « .0000 » ni exposant."""
    if valeur is None:
        return ""
    try:
        nombre = Decimal(valeur)
    except (InvalidOperation, TypeError, ValueError):
        return str(valeur)
    entier = nombre.to_integral_value()
    return str(int(entier)) if nombre == entier else f"{nombre.normalize():f}".replace(".", ",")


def pourcent(fraction) -> str:
    """0.0500 devient « 5 % », 0.0750 « 7,5 % » — l'écriture de l'écran, pas celle de Python."""
    return f"{_chiffre(Decimal(fraction) * CENT)}\u202f%"


def _choix_obligatoire(message):
    return {"required": message, "invalid_choice": "Ce choix n'est pas (ou plus) proposé."}


# ----------------------------------------------------------------------------
# Un compte : existant, ou à créer avec un mot de passe initial
# ----------------------------------------------------------------------------
class CompteForm(FormulaireEtape):
    """Désigner un compte par son numéro, ou le créer.

    Le mot de passe initial est saisi deux fois, passé aux validateurs de Django, puis **haché
    aussitôt** : seule l'empreinte va en session. Revenir sur cette étape ne le redemande pas —
    tant que le numéro et le nom n'ont pas changé, puisque la validation (« trop proche du nom »)
    portait sur eux.
    """

    EXISTANT, NOUVEAU = "existant", "nouveau"
    secrets = ("mot_de_passe", "mot_de_passe_confirmation")

    mode = forms.ChoiceField(
        label="Compte",
        choices=[(EXISTANT, "Un compte existant"), (NOUVEAU, "Un nouveau compte")],
        initial=EXISTANT,
        widget=forms.RadioSelect,
        error_messages=_choix_obligatoire("Dites s'il s'agit d'un compte existant ou nouveau."),
    )
    telephone = forms.CharField(
        label="Numéro de téléphone",
        max_length=24,  # saisi avec ses espaces ; normalisé puis validé à 16
        help_text="Le numéro est l'identifiant de connexion. Format : +237699000000.",
        widget=forms.TextInput(attrs={**CHAMP_GRAND, "placeholder": "+237699000000", "inputmode": "tel", "autocomplete": "off"}),
        error_messages={"required": "Le numéro est obligatoire."},
    )
    nom = forms.CharField(
        label="Nom complet",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Marie Ekedi", "autocomplete": "off"}),
    )
    mot_de_passe = forms.CharField(
        label="Mot de passe initial",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={**CHAMP, "autocomplete": "new-password"}),
    )
    mot_de_passe_confirmation = forms.CharField(
        label="Le même, une seconde fois",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={**CHAMP, "autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exigés pour un nouveau compte seulement : ni « facultatif », ni obligatoire toujours.
        for nom in ("nom", "mot_de_passe", "mot_de_passe_confirmation"):
            self.fields[nom].sans_pastille = True
        self.compte = None
        self._hache = ""
        if self.memoire.get("_hache"):
            self.fields["mot_de_passe"].help_text = (
                "Un mot de passe a déjà été saisi. Laissez vide pour le garder."
            )

    def refuser(self, compte) -> str | None:  # pragma: no cover — dérivé
        raise NotImplementedError

    def clean_telephone(self):
        telephone = _telephone(self.cleaned_data["telephone"])
        validateur_telephone(telephone)
        return telephone

    def clean(self):
        donnees = super().clean()
        mode, telephone = donnees.get("mode"), donnees.get("telephone")
        if not mode or not telephone:
            return donnees
        existant = get_user_model().objects.filter(telephone=telephone).first()

        if mode == self.EXISTANT:
            if existant is None:
                self.add_error(
                    "telephone",
                    "Aucun compte à ce numéro. Vérifiez-le, ou choisissez « Un nouveau compte ».",
                )
                return donnees
            refus = self.refuser(existant)
            if refus:
                self.add_error("telephone", refus)
                return donnees
            self.compte = existant
            return donnees

        # --- Un nouveau compte -------------------------------------------------------------
        if existant is not None:
            self.add_error(
                "telephone",
                f"Ce numéro a déjà un compte ({existant.nom_complet}). Choisissez « Un compte existant ».",
            )
            return donnees
        nom = (donnees.get("nom") or "").strip()
        if not nom:
            self.add_error("nom", "Le nom est obligatoire pour un nouveau compte.")
            return donnees

        mdp, confirmation = donnees.get("mot_de_passe") or "", donnees.get("mot_de_passe_confirmation") or ""
        pour = f"{telephone}|{nom}"
        if not mdp and not confirmation and self.memoire.get("_hache") and self.memoire.get("_hache_pour") == pour:
            self._hache = self.memoire["_hache"]
            return donnees
        if not mdp:
            self.add_error("mot_de_passe", "Saisissez le mot de passe initial du compte.")
            return donnees
        if mdp != confirmation:
            self.add_error("mot_de_passe_confirmation", "Les deux saisies ne sont pas identiques.")
            return donnees
        try:
            password_validation.validate_password(
                mdp, user=get_user_model()(telephone=telephone, nom_complet=nom)
            )
        except forms.ValidationError as erreur:
            self.add_error("mot_de_passe", erreur)
            return donnees
        self._hache = make_password(mdp)
        return donnees

    @property
    def mot_de_passe_hache(self) -> str:
        return self._hache

    def extras_session(self) -> dict:
        if self.cleaned_data.get("mode") == self.NOUVEAU and self._hache:
            return {
                "_hache": self._hache,
                "_hache_pour": f"{self.cleaned_data['telephone']}|{self.cleaned_data['nom'].strip()}",
            }
        return {}

    def resume(self) -> list[tuple[str, str]]:
        d = self.cleaned_data
        if self.compte is not None:
            return [
                ("Compte", "Existant"),
                ("Nom", self.compte.nom_complet),
                ("Téléphone", self.compte.telephone),
            ]
        return [
            ("Compte", "Nouveau — créé à la confirmation"),
            ("Nom", d["nom"].strip()),
            ("Téléphone", d["telephone"]),
            ("Mot de passe initial", "Saisi deux fois, conservé haché — à communiquer de vive voix"),
        ]


# ----------------------------------------------------------------------------
# 1. Ouvrir une boutique
# ----------------------------------------------------------------------------
class IdentiteForm(FormulaireEtape):
    enseigne = forms.CharField(
        label="Enseigne",
        max_length=120,
        help_text="Le nom affiché aux acheteurs. L'adresse de la vitrine en est dérivée.",
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Quincaillerie Ateba", "autocomplete": "off"}),
        error_messages={"required": "L'enseigne est obligatoire : c'est le nom que verront les acheteurs."},
    )
    raison_sociale = forms.CharField(
        label="Raison sociale",
        max_length=180,
        help_text="Telle qu'elle figure au registre du commerce.",
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Ets Ateba et Fils SARL", "autocomplete": "off"}),
        error_messages={"required": "La raison sociale est obligatoire : elle figure sur le bail."},
    )
    metier = forms.ChoiceField(
        label="Métier",
        choices=CHOIX_METIER,
        initial=METIER_DEFAUT,
        error_messages=_choix_obligatoire("Choisissez ce que la boutique vend."),
    )
    ville = forms.CharField(
        label="Ville",
        max_length=80,
        initial="Douala",
        widget=forms.TextInput(attrs={**CHAMP, "autocomplete": "address-level2"}),
        error_messages={"required": "La ville est obligatoire."},
    )
    telephone = forms.CharField(
        label="Téléphone de la boutique",
        max_length=24,  # saisi avec ses espaces ; normalisé puis validé à 16
        required=False,
        help_text="Celui que les acheteurs appellent. Peut être celui du gérant.",
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "+237699000000", "inputmode": "tel"}),
    )

    def clean_telephone(self):
        telephone = _telephone(self.cleaned_data.get("telephone"))
        if telephone:
            validateur_telephone(telephone)
        return telephone


# Des explications courtes, tirées de docs/07, §5 — sans taux ni barème : ceux-là changent avec
# les lois de finances, et un chiffre périmé sur un écran de gouvernance est pire qu'aucun.
EXPLICATIONS_REGIMES = {
    Boutique.IGS: (
        "Impôt forfaitaire, libératoire de la patente et de la TVA : la boutique ne facture pas "
        "de TVA et ne la récupère pas. Livre de recettes et de dépenses."
    ),
    Boutique.REEL_SIMPLIFIE: (
        "La boutique collecte la TVA. Comptabilité selon le système allégé SYSCOHADA."
    ),
    Boutique.REEL_NORMAL: (
        "La boutique collecte la TVA. Comptabilité selon le système normal SYSCOHADA, états "
        "financiers complets."
    ),
}


class LegalForm(FormulaireEtape):
    rccm = forms.CharField(
        label="RCCM",
        max_length=64,
        required=False,
        help_text="Numéro au registre du commerce et du crédit mobilier.",
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "RC/DLA/2024/B/1234", "autocomplete": "off"}),
    )
    niu = forms.CharField(
        label="NIU",
        max_length=32,
        required=False,
        help_text="Numéro identifiant unique, attribué par l'administration fiscale.",
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "M012345678901A", "autocomplete": "off"}),
    )
    regime_fiscal = forms.ChoiceField(
        label="Régime fiscal",
        choices=Boutique.REGIMES,
        initial=Boutique.REEL_SIMPLIFIE,
        error_messages=_choix_obligatoire("Choisissez le régime fiscal de la boutique."),
    )

    def clean_rccm(self):
        return self.cleaned_data["rccm"].strip().upper()

    def clean_niu(self):
        return self.cleaned_data["niu"].strip().upper().replace(" ", "")


class OffreForm(FormulaireEtape):
    """L'offre louée et les conditions du bail.

    Le loyer et le taux laissés vides prennent ceux de l'offre : sans JavaScript, on n'a pas à
    recopier ce que la carte affiche déjà. Le taux se saisit en **pourcent** ; un taux qui
    s'écarte de celui de l'offre exige un motif — la règle est `Bail.clean`, rejouée ici pour
    être dite à cette étape plutôt qu'au récapitulatif.
    """

    offre = forms.ChoiceField(label="Offre", error_messages=_choix_obligatoire("Choisissez l'offre louée."))
    rayon = forms.ChoiceField(
        label="Rayon principal",
        help_text="Là où la boutique est rangée dans le marché. Seuls les rayons ouverts accueillent de nouvelles boutiques.",
        widget=forms.Select(attrs=CHAMP),
        error_messages=_choix_obligatoire("Choisissez le rayon de la boutique."),
    )
    debut = forms.DateField(
        label="Début du bail",
        widget=forms.DateInput(attrs={**CHAMP, "type": "date"}, format="%Y-%m-%d"),
        error_messages={"required": "La date de début est obligatoire.", "invalid": "Date invalide."},
    )
    loyer_mensuel = ChampNombre(
        label="Loyer mensuel HT",
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=0,
        help_text="En francs CFA. Vide : le loyer de l'offre.",
    )
    depot_garantie = ChampNombre(
        label="Dépôt de garantie",
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=0,
        placeholder="0",
        help_text="En francs CFA, versé à la signature, restitué à la sortie après l'état des lieux.",
    )
    taux_commission = ChampNombre(
        label="Commission",
        required=False,
        min_value=Decimal("0"),
        max_value=CENT,
        max_digits=5,
        decimal_places=2,
        help_text="En pourcent : « 5 » pour 5 %. Vide : le taux de l'offre.",
    )
    motif_derogation = forms.CharField(
        label="Motif de la dérogation",
        max_length=300,
        required=False,
        help_text="Obligatoire si la commission s'écarte de celle de l'offre. Il sera relu.",
        widget=forms.Textarea(attrs={**CHAMP, "rows": 2, "maxlength": 300, "data-compteur": ""}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.offres = {o.code: o for o in TypeEmplacement.objects.order_by("ordre")}
        self.fields["offre"].choices = [(c, o.libelle) for c, o in self.offres.items()]
        self.rayons = {str(r.pk): r for r in Rayon.objects.filter(ouvert=True).order_by("ordre", "libelle")}
        self.fields["rayon"].choices = [("", "— Choisir un rayon —")] + [
            (pk, f"{r.libelle} · {_chiffre(r.taux_commission * CENT)} %") for pk, r in self.rayons.items()
        ]
        self.fields["debut"].initial = timezone.localdate()
        self.fields["loyer_mensuel"].pastille = "de l'offre"
        self.fields["taux_commission"].pastille = "de l'offre"
        self.fields["motif_derogation"].pastille = "si dérogation"

    def clean(self):
        donnees = super().clean()
        offre = self.offres.get(donnees.get("offre") or "")
        donnees["offre_objet"] = offre
        donnees["rayon_objet"] = self.rayons.get(donnees.get("rayon") or "")
        if offre is None:
            return donnees
        if donnees.get("loyer_mensuel") is None and "loyer_mensuel" not in self.errors:
            donnees["loyer_mensuel"] = offre.loyer_mensuel
        if donnees.get("depot_garantie") is None:
            donnees["depot_garantie"] = Decimal("0")
        if "taux_commission" in self.errors:
            return donnees
        if donnees.get("taux_commission") is None:
            fraction = offre.taux_commission_defaut
        else:
            fraction = (donnees["taux_commission"] / CENT).quantize(Decimal("0.0001"))
        donnees["taux_fraction"] = fraction
        motif = (donnees.get("motif_derogation") or "").strip()
        donnees["motif_derogation"] = motif
        reference = offre.taux_commission_defaut
        donnees["derogation"] = fraction != reference
        if donnees["derogation"] and not motif:
            self.add_error(
                "motif_derogation",
                f"Le taux négocié ({pourcent(fraction)}) s'écarte de celui de l'offre "
                f"({pourcent(reference)}). Dites pourquoi : la dérogation est légitime, son absence "
                "de motif ne l'est pas.",
            )
        return donnees


class OuvertureForm(Confirmation):
    ACTIVE, CANDIDATURE = "active", "candidature"
    ouverture = forms.ChoiceField(
        label="À la confirmation",
        choices=[
            (ACTIVE, "Ouvrir tout de suite"),
            (CANDIDATURE, "Laisser en candidature"),
        ],
        initial=ACTIVE,
        error_messages=_choix_obligatoire("Dites si la boutique ouvre tout de suite."),
    )


class GerantForm(CompteForm):
    def refuser(self, compte):
        return services.refus_gerant(compte, par=self.assistant.request.user if self.assistant else None)


# ----------------------------------------------------------------------------
# 2. Vendre un emplacement premium
# ----------------------------------------------------------------------------
class BoutiqueOccupanteForm(FormulaireEtape):
    boutique = forms.ChoiceField(
        label="Boutique",
        error_messages=_choix_obligatoire("Choisissez la boutique qui occupera l'emplacement."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Toutes les boutiques actives sont admises à la validation ; la page n'en montre qu'une
        # sélection filtrée par la recherche.
        self.fields["boutique"].choices = [
            (str(pk), enseigne)
            for pk, enseigne in Boutique.objects.filter(etat=Boutique.ACTIVE).values_list("pk", "enseigne")
        ]

    def clean_boutique(self):
        return Boutique.objects.select_related("rayon_principal").get(pk=self.cleaned_data["boutique"])


class TypeEmplacementForm(FormulaireEtape):
    type = forms.ChoiceField(
        label="Type d'emplacement",
        choices=EmplacementPremium.TYPES,
        error_messages=_choix_obligatoire("Choisissez le type d'emplacement."),
    )
    rayon = forms.ChoiceField(
        label="Rayon",
        required=False,
        help_text="Pour une tête de gondole ou un bandeau. Ignoré pour la page d'accueil.",
        widget=forms.Select(attrs=CHAMP),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rayons = {str(r.pk): r for r in Rayon.objects.order_by("ordre", "libelle")}
        self.fields["rayon"].choices = [("", "— Choisir un rayon —")] + [
            (pk, r.libelle) for pk, r in self.rayons.items()
        ]
        # Par défaut, le rayon de la boutique choisie : c'est presque toujours là qu'elle veut
        # être vue.
        if self.assistant is not None and not self.is_bound:
            boutique_id = self.assistant.saisie("boutique").get("boutique")
            rayon_id = (
                Boutique.objects.filter(pk=boutique_id).values_list("rayon_principal_id", flat=True).first()
                if boutique_id
                else None
            )
            if rayon_id:
                self.fields["rayon"].initial = str(rayon_id)

    def clean(self):
        donnees = super().clean()
        type_ = donnees.get("type")
        rayon = self.rayons.get(donnees.get("rayon") or "")
        if type_ in services.TYPES_A_RAYON and rayon is None:
            self.add_error("rayon", "Une tête de gondole ou un bandeau se place dans un rayon : choisissez-le.")
        donnees["rayon_objet"] = rayon if type_ in services.TYPES_A_RAYON else None
        return donnees


class PeriodeForm(FormulaireEtape):
    debut = forms.DateField(
        label="Premier jour",
        widget=forms.DateInput(attrs={**CHAMP, "type": "date"}, format="%Y-%m-%d"),
        error_messages={"required": "La date de début est obligatoire.", "invalid": "Date invalide."},
    )
    fin = forms.DateField(
        label="Dernier jour",
        help_text="Inclus. L'emplacement est compté jusqu'au soir de ce jour.",
        widget=forms.DateInput(attrs={**CHAMP, "type": "date"}, format="%Y-%m-%d"),
        error_messages={"required": "La date de fin est obligatoire.", "invalid": "Date invalide."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aujourdhui = timezone.localdate()
        self.fields["debut"].initial = aujourdhui
        self.fields["fin"].initial = aujourdhui + timezone.timedelta(days=6)

    def clean(self):
        donnees = super().clean()
        debut, fin = donnees.get("debut"), donnees.get("fin")
        if debut and fin:
            if fin <= debut:
                self.add_error("fin", "La fin doit venir après le début.")
            else:
                donnees["jours"] = (fin - debut).days + 1
        return donnees


class TarifForm(FormulaireEtape):
    tarif = ChampNombre(
        label="Tarif HT de la période",
        max_digits=12,
        decimal_places=0,
        placeholder="75 000",
        help_text="En francs CFA, pour toute la période.",
        error_messages={"required": "Le tarif est obligatoire.", "invalid": "Saisissez un montant en francs."},
    )

    def clean_tarif(self):
        tarif = self.cleaned_data["tarif"]
        if tarif <= 0:
            # Court ici : la règle et sa raison sont affichées juste en dessous du champ.
            raise forms.ValidationError(
                "Un emplacement ne se cède jamais à zéro, même à une boutique de l'exploitant : saisissez son prix."
            )
        return tarif


# ----------------------------------------------------------------------------
# 3. Nommer un administrateur du marché
# ----------------------------------------------------------------------------
class AdministrateurCompteForm(CompteForm):
    def refuser(self, compte):
        return services.refus_administrateur(compte)


class RoleForm(FormulaireEtape):
    role = forms.ChoiceField(
        label="Rôle",
        choices=list(LIBELLES_ROLES_ADMINISTRATION.items()),
        error_messages=_choix_obligatoire("Choisissez le rôle confié."),
    )
    motif = forms.CharField(
        label="Motif",
        max_length=300,
        min_length=10,
        help_text="Pourquoi cette personne exploite le marché. Utile le jour où on se le demande.",
        widget=forms.Textarea(attrs={**CHAMP, "rows": 3, "maxlength": 300, "data-compteur": ""}),
        error_messages={
            "required": "Le motif est obligatoire : un auditeur le relira.",
            "min_length": "Une phrase, s'il vous plaît : un auditeur doit pouvoir la comprendre.",
        },
    )

    def clean(self):
        donnees = super().clean()
        role = donnees.get("role")
        if role and self.assistant is not None:
            telephone = self.assistant.saisie("compte").get("telephone")
            compte = get_user_model().objects.filter(telephone=telephone).first() if telephone else None
            if compte is not None and compte.roles_plateforme.filter(actif=True, role_id=role).exists():
                self.add_error("role", "Ce compte porte déjà ce rôle.")
        return donnees


# ----------------------------------------------------------------------------
# Les gestes d'une page
# ----------------------------------------------------------------------------
class MotifForm(FormulaireEtape):
    """Un motif, et rien d'autre : suspendre, résilier, retirer un rôle."""

    motif = forms.CharField(
        label="Motif",
        max_length=300,
        min_length=10,
        widget=forms.Textarea(attrs={**CHAMP, "rows": 3, "maxlength": 300, "data-compteur": ""}),
        error_messages={
            "required": "Le motif est obligatoire : cette décision sera relue.",
            "min_length": "Une phrase, s'il vous plaît : elle sera relue, peut-être par le commerçant.",
        },
    )

    def __init__(self, *args, obligatoire=True, aide="", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["motif"].required = obligatoire
        if not obligatoire:
            self.fields["motif"].min_length = None
            self.fields["motif"].validators = [
                v for v in self.fields["motif"].validators if v.code != "min_length"
            ]
            self.fields["motif"].label = "Note"
        if aide:
            self.fields["motif"].help_text = aide


class TauxRayonForm(FormulaireEtape):
    pourcent = ChampNombre(
        label="Nouveau taux (%)",
        min_value=Decimal("0"),
        # La borne du modèle (`Rayon.taux_commission`, MaxValueValidator 0.30) : au-delà, c'est
        # presque toujours une fraction saisie comme un pourcentage, ou l'inverse.
        max_value=Decimal("30"),
        max_digits=5,
        decimal_places=2,
        help_text="En pourcent : « 5 » pour 5 %, « 7,5 » pour 7,5 %. De 0 à 30 %.",
        error_messages={
            "required": "Saisissez le nouveau taux.",
            "invalid": "Saisissez un nombre : « 5 » pour 5 %.",
            "max_value": "Au plus 30 %% : c'est la borne du rayon. Un « 0,05 » voulait-il dire 5 %% ?",
            "min_value": "Un taux ne peut pas être négatif.",
        },
    )
    motif = forms.CharField(
        label="Motif",
        max_length=240,
        min_length=10,
        help_text="Le taux d'un rayon gouverne la rentabilité de toutes ses boutiques. Dites pourquoi.",
        widget=forms.Textarea(attrs={**CHAMP, "rows": 3, "maxlength": 240, "data-compteur": ""}),
        error_messages={
            "required": "Le motif est obligatoire : ce changement sera relu.",
            "min_length": "Une phrase, s'il vous plaît : ce changement sera relu.",
        },
    )
