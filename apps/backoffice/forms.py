"""Formulaires du back-office.

Écrits à la main plutôt que par `ModelForm` : les écrans de reprise de stock et
d'ouverture de caisse touchent plusieurs modèles à la fois et passent par les
services (`entrer_stock`, `ouvrir_session`), jamais par un `save()` direct. Un
`ModelForm` donnerait l'illusion qu'on peut écrire le stock sans passer par son
journal — c'est exactement ce qu'il faut empêcher.
"""

from decimal import Decimal

from django import forms

from apps.accounts.models import validateur_telephone
from apps.catalog.models import Produit
from apps.marketplace import metiers

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

    # Champs de métier : présents seulement là où le métier les active. Ils sont
    # déclarés ici et retirés dans `__init__` — la même mécanique que les droits
    # côté API : ce qui n'est pas ouvert n'est pas affiché, pas grisé.
    date_peremption = forms.DateField(
        label="Date de péremption",
        required=False,
        help_text="Laissez vide si cet article ne périme pas.",
        widget=forms.DateInput(attrs={**CHAMP, "type": "date"}),
    )
    numero_lot = forms.CharField(
        label="Numéro de lot",
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Lot du fabricant"}),
    )
    unite = forms.ChoiceField(
        label="Unité de vente",
        choices=Produit.UNITES,
        required=False,
        widget=forms.Select(attrs=CHAMP),
    )

    def __init__(self, *args, boutique=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.boutique = boutique
        self.metier = boutique.metier_choisi if boutique is not None else metiers.metier_de(None)
        self._composer()

    def _composer(self) -> None:
        """Compose le formulaire pour le métier de la boutique.

        Trois choses en découlent, et aucune n'est cosmétique :

        * le **vocabulaire** — un pharmacien saisit un médicament, pas un article ;
        * les **valeurs par défaut** — unité et régime de TVA du métier, parce
          qu'un défaut qu'il faut corriger à chaque ligne finit par être subi ;
        * les **champs présents** — la date de péremption n'apparaît que là où
          elle a un sens, et le numéro de lot seulement là où il est suivi.
        """
        metier = self.metier

        self.fields["libelle"].label = f"Nom {'du' if metier.article != 'pièce' else 'de la'} {metier.article}"
        if metier.exemples:
            self.fields["libelle"].widget.attrs["placeholder"] = metier.exemples[0]

        self.fields["regime_tva"].initial = metier.regime_tva_defaut
        self.fields["unite"].initial = metier.unite_defaut

        if not metier.a(metiers.PEREMPTION):
            del self.fields["date_peremption"]
        if not metier.a(metiers.LOT):
            del self.fields["numero_lot"]
        if metier.unite_defaut == "U" and not metier.a(metiers.POIDS_VARIABLE):
            # L'unité ne se pose pas dans un commerce où tout se vend à la pièce.
            del self.fields["unite"]

    def clean_unite(self):
        return self.cleaned_data.get("unite") or self.metier.unite_defaut

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
        if (
            self.metier.a(metiers.PEREMPTION)
            and donnees.get("quantite")
            and not donnees.get("date_peremption")
        ):
            # Un stock initial saisi sans date dans un métier qui périme est une
            # perte annoncée : l'alerte ne pourra jamais se déclencher dessus.
            self.add_error(
                "date_peremption",
                "Ce métier suit les péremptions : indiquez la date, ou saisissez "
                "une quantité nulle et faites une réception ensuite.",
            )

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


class TransfertStockForm(forms.Form):
    """Déplacement d'un article d'un dépôt vers un autre.

    Le dépôt source n'est pas un champ : c'est le dépôt d'exploitation courant,
    celui affiché dans l'en-tête. Le proposer au choix ouvrirait la porte au
    transfert saisi depuis le mauvais bout — on sort la marchandise du dépôt où
    l'on se trouve, pas d'un dépôt qu'on désigne de loin.
    """

    cible = forms.ChoiceField(label="Vers le dépôt", widget=forms.Select(attrs=CHAMP))
    quantite = forms.DecimalField(
        label="Quantité transférée", min_value=Decimal("0.0001"), decimal_places=4,
        widget=forms.NumberInput(attrs={**CHAMP_GRAND, "inputmode": "decimal", "step": "1"}),
    )
    commentaire = forms.CharField(
        label="Motif", max_length=255, required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Réassort du comptoir"}),
    )

    def __init__(self, *args, depots=None, source=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.depots = {str(d.pk): d for d in (depots or []) if source is None or d.pk != source.pk}
        self.fields["cible"].choices = [(cle, d.libelle) for cle, d in self.depots.items()]

    def clean_cible(self):
        depot = self.depots.get(self.cleaned_data["cible"])
        if depot is None:
            raise forms.ValidationError("Ce dépôt n'existe pas dans votre boutique.")
        return depot


class DepotForm(forms.Form):
    """Ouverture d'un dépôt supplémentaire (réserve, second point de vente)."""

    libelle = forms.CharField(
        label="Nom du dépôt", max_length=120,
        widget=forms.TextInput(attrs={**CHAMP_GRAND, "placeholder": "Réserve Akwa"}),
    )
    type = forms.ChoiceField(label="Type", widget=forms.Select(attrs=CHAMP))
    adresse = forms.CharField(
        label="Adresse", max_length=255, required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Facultative"}),
    )

    def __init__(self, *args, **kwargs):
        from apps.inventory.models import Depot

        super().__init__(*args, **kwargs)
        # L'entrepôt mutualisé appartient à la plateforme : un marchand ne peut
        # pas s'en ouvrir un depuis son back-office.
        self.fields["type"].choices = [
            (code, libelle)
            for code, libelle in Depot.TYPES
            if code != Depot.ENTREPOT_PLATEFORME
        ]
        self.fields["type"].initial = Depot.RESERVE


class MembreEquipeForm(forms.Form):
    """Rattachement d'une personne à la boutique, avec son rôle.

    Le numéro de téléphone est l'identifiant : si la personne a déjà un compte
    HyperMarché — le comptable d'un groupe, un vendeur qui change de boutique —
    on la rattache, on ne recrée rien. Un même numéro n'ouvre jamais deux
    comptes, sans quoi l'historique d'un employé se scinderait en deux.
    """

    telephone = forms.CharField(
        label="Numéro de téléphone",
        max_length=16,
        validators=[validateur_telephone],
        widget=forms.TextInput(attrs={**CHAMP_GRAND, "placeholder": "+237699000000"}),
    )
    nom_complet = forms.CharField(
        label="Nom complet", max_length=150, required=False,
        help_text="Ignoré si la personne a déjà un compte.",
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Marie Ekedi"}),
    )
    role = forms.ChoiceField(label="Rôle", widget=forms.Select(attrs=CHAMP))

    def __init__(self, *args, roles=None, boutique=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.boutique = boutique
        self.roles = {r.code: r for r in (roles or [])}
        self.fields["role"].choices = [(code, r.libelle) for code, r in self.roles.items()]

    def clean_telephone(self):
        return self.cleaned_data["telephone"].strip().replace(" ", "")

    def clean_role(self):
        role = self.roles.get(self.cleaned_data["role"])
        if role is None:
            raise forms.ValidationError("Ce rôle ne peut pas être attribué dans une boutique.")
        return role

    def clean(self):
        donnees = super().clean()
        telephone = donnees.get("telephone")
        if not telephone:
            return donnees

        from apps.accounts.models import Appartenance, Utilisateur

        existant = Utilisateur.objects.filter(telephone=telephone).first()
        self.utilisateur_existant = existant

        if existant is not None and self.boutique is not None:
            deja = Appartenance.objects.filter(
                utilisateur=existant, boutique=self.boutique, actif=True
            ).exists()
            if deja:
                self.add_error("telephone", "Cette personne fait déjà partie de votre équipe.")
        elif existant is None and not donnees.get("nom_complet"):
            self.add_error("nom_complet", "Le nom est obligatoire pour un nouveau compte.")
        return donnees


class ChangementDeRoleForm(forms.Form):
    role = forms.ChoiceField(label="Rôle")

    def __init__(self, *args, roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.roles = {r.code: r for r in (roles or [])}
        self.fields["role"].choices = [(code, r.libelle) for code, r in self.roles.items()]

    def clean_role(self):
        role = self.roles.get(self.cleaned_data["role"])
        if role is None:
            raise forms.ValidationError("Rôle inconnu.")
        return role


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


class CharteForm(forms.ModelForm):
    """Logo, couleur de marque et police.

    Le champ de couleur est un sélecteur natif : sur un téléphone d'entrée de
    gamme, c'est la seule roue chromatique qui s'ouvre instantanément et que
    l'utilisateur connaît déjà. Un composant maison coûterait du JavaScript pour
    faire moins bien.
    """

    class Meta:
        from apps.marketplace.models import IdentiteVisuelle

        model = IdentiteVisuelle
        fields = ["logo", "couleur_marque", "police"]
        labels = {
            "logo": "Votre logo",
            "couleur_marque": "Couleur principale",
            "police": "Caractère",
        }
        help_texts = {
            "logo": "PNG ou JPEG. Ses couleurs vous seront proposées après enregistrement.",
            "couleur_marque": (
                "Elle sera vérifiée et corrigée si elle n'est pas lisible sur un "
                "bouton ou un graphique — la correction vous sera montrée."
            ),
            "police": "Aucun fichier n'est téléchargé : ces caractères sont déjà sur l'appareil.",
        }
        widgets = {
            "couleur_marque": forms.TextInput(attrs={"class": "champ champ--couleur", "type": "color"}),
            "logo": forms.ClearableFileInput(attrs={"class": "champ", "accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        from apps.marketplace.charte import CHOIX_POLICES

        super().__init__(*args, **kwargs)
        self.fields["police"] = forms.ChoiceField(
            label="Caractère",
            choices=CHOIX_POLICES,
            initial=self.instance.police if self.instance else "systeme",
            help_text=self.Meta.help_texts["police"],
            widget=forms.Select(attrs=CHAMP),
        )

    def clean_couleur_marque(self):
        couleur = (self.cleaned_data.get("couleur_marque") or "").strip()
        from apps.marketplace.charte import _vers_rvb

        try:
            _vers_rvb(couleur)
        except ValueError:
            raise forms.ValidationError("Couleur illisible : attendu un code de la forme #1E88E5.")
        # Minuscules : `<input type="color">` n'accepte pas les majuscules et
        # repartirait du noir en rouvrant la page.
        return couleur.lower()


class LienMarketingForm(forms.Form):
    """Création d'un lien court."""

    libelle = forms.CharField(
        label="À quoi sert ce lien",
        max_length=120,
        widget=forms.TextInput(
            attrs={**CHAMP, "placeholder": "Flyer marché central, statut WhatsApp…"}
        ),
    )
    article = forms.ChoiceField(
        label="Vers", required=False, widget=forms.Select(attrs=CHAMP)
    )
    code_apporteur = forms.CharField(
        label="Code apporteur (facultatif)",
        max_length=12,
        required=False,
        help_text="Rattache les commandes venues de ce lien à un apporteur.",
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "HM-XXXXXX"}),
    )

    def __init__(self, *args, boutique=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.catalog.models import Variante

        articles = Variante.objects.filter(actif=True).select_related("produit")[:200]
        self.fields["article"].choices = [("", "Ma vitrine complète")] + [
            (str(v.pk), v.produit.libelle) for v in articles
        ]


# ----------------------------------------------------------------------------
# Fiches techniques et production — métiers qui fabriquent
# ----------------------------------------------------------------------------
# Le vocabulaire de ces formulaires suit le métier : un restaurateur compose un
# plat, un boulanger une fournée. Les libellés sont donc posés dans `__init__`
# et non en dur, comme dans `ArticleForm`.
class FicheForm(forms.Form):
    """Ouverture d'une fiche technique sur un produit fini déjà au catalogue.

    Le produit fabriqué n'est pas créé ici : c'est un article ordinaire, avec son
    prix, son stock et son CMP. Une fiche ne fait qu'expliquer **d'où il vient**.
    En créer un second par la fiche donnerait deux baguettes au catalogue, dont
    une invendable.
    """

    variante = forms.ChoiceField(label="Produit fabriqué", widget=forms.Select(attrs=CHAMP_GRAND))
    rendement = forms.DecimalField(
        label="Rendement",
        min_value=Decimal("0.0001"),
        decimal_places=4,
        initial=Decimal("1"),
        help_text="Combien d'unités une fiche complète produit. Une fournée, pas une pièce.",
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "decimal", "step": "1"}),
    )
    duree_conservation_jours = forms.IntegerField(
        label="Conservation (jours)",
        min_value=0,
        max_value=3650,
        required=False,
        help_text="La date de péremption sera calculée à chaque production.",
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "numeric", "step": "1"}),
    )
    note = forms.CharField(
        label="Mode opératoire",
        required=False,
        widget=forms.Textarea(attrs={**CHAMP, "rows": 3, "placeholder": "Pétrissage 12 min, repos 1 h…"}),
    )

    def __init__(self, *args, boutique=None, metier=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.catalog.models import Recette, Variante

        self.metier = metier or metiers.metier_de(boutique)
        deja = Recette.objects.values_list("variante_id", flat=True)
        candidats = (
            Variante.objects.filter(actif=True)
            .exclude(pk__in=list(deja))
            .select_related("produit")
            .order_by("produit__libelle")[:300]
        )
        self.disponibles = {str(v.pk): v for v in candidats}
        self.fields["variante"].choices = [("", "Choisir…")] + [
            (cle, str(v)) for cle, v in self.disponibles.items()
        ]
        self.fields["variante"].label = f"{self.metier.article.capitalize()} fabriqué"

    def clean_variante(self):
        variante = self.disponibles.get(self.cleaned_data["variante"])
        if variante is None:
            raise forms.ValidationError(
                "Cet article n'existe pas dans votre boutique, ou il a déjà une fiche."
            )
        return variante


class IngredientForm(forms.Form):
    """Ajout d'un ingrédient à une fiche.

    L'ingrédient est un article du stock, pas un texte libre : c'est ce qui
    permet au coût de revient d'être un vrai coût, calculé sur le CMP, et à la
    production de sortir réellement la marchandise du dépôt.
    """

    ingredient = forms.ChoiceField(label="Ingrédient", widget=forms.Select(attrs=CHAMP_GRAND))
    quantite = forms.DecimalField(
        label="Quantité",
        min_value=Decimal("0.0001"),
        decimal_places=4,
        help_text="Pour une fiche complète, dans l'unité de l'ingrédient.",
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "decimal", "step": "0.01"}),
    )

    def __init__(self, *args, recette=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.catalog.models import Variante

        self.recette = recette
        deja = []
        exclus = []
        if recette is not None:
            deja = list(recette.lignes.values_list("ingredient_id", flat=True))
            # Un produit ne peut pas être son propre ingrédient : la production
            # consommerait ce qu'elle fabrique, et le stock ne voudrait plus rien
            # dire.
            exclus = deja + [recette.variante_id]
        candidats = (
            Variante.objects.filter(actif=True)
            .exclude(pk__in=exclus)
            .select_related("produit")
            .order_by("produit__libelle")[:300]
        )
        self.disponibles = {str(v.pk): v for v in candidats}
        self.fields["ingredient"].choices = [("", "Choisir…")] + [
            (cle, str(v)) for cle, v in self.disponibles.items()
        ]

    def clean_ingredient(self):
        variante = self.disponibles.get(self.cleaned_data["ingredient"])
        if variante is None:
            raise forms.ValidationError(
                "Cet ingrédient n'est pas disponible : il est déjà dans la fiche, "
                "c'est le produit fabriqué lui-même, ou il n'existe pas ici."
            )
        return variante


class ProductionForm(forms.Form):
    """Lancement d'une fabrication.

    La quantité demandée est celle du **produit fini** — quarante baguettes — et
    non un nombre de fiches. C'est ce que le boulanger sait avant de commencer ;
    le rapport au rendement est l'affaire du logiciel.
    """

    quantite = forms.DecimalField(
        label="Quantité produite",
        min_value=Decimal("0.0001"),
        decimal_places=4,
        widget=forms.NumberInput(attrs={**CHAMP_GRAND, "inputmode": "decimal", "step": "1"}),
    )
    commentaire = forms.CharField(
        label="Commentaire", max_length=255, required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Fournée du matin"}),
    )


class InvenduForm(forms.Form):
    """Déclaration d'invendus en fin de journée.

    Un invendu est une **perte**, pas un ajustement d'inventaire : la marchandise
    a existé, elle a coûté, et elle ne sera pas vendue. L'écrire comme un écart
    de comptage effacerait la seule information qui vaille — combien la journée a
    jeté, et sur quel produit.
    """

    variante = forms.ChoiceField(label="Produit", widget=forms.Select(attrs=CHAMP_GRAND))
    quantite = forms.DecimalField(
        label="Quantité jetée",
        min_value=Decimal("0.0001"),
        decimal_places=4,
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "decimal", "step": "1"}),
    )
    motif = forms.CharField(
        label="Motif", max_length=255, required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Invendus du soir"}),
    )

    def __init__(self, *args, recettes=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Restreint aux produits fabriqués : les invendus d'une journée portent
        # sur ce qui est sorti du four, pas sur les bouteilles en rayon — celles-là
        # se régularisent à l'inventaire.
        self.disponibles = {str(r.variante_id): r.variante for r in (recettes or [])}
        self.fields["variante"].choices = [("", "Choisir…")] + [
            (cle, str(v)) for cle, v in self.disponibles.items()
        ]

    def clean_variante(self):
        variante = self.disponibles.get(self.cleaned_data["variante"])
        if variante is None:
            raise forms.ValidationError("Ce produit n'est pas fabriqué dans votre boutique.")
        return variante
