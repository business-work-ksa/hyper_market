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


def nombre_court(valeur):
    """`10.0000` devient `10`, `3200.00` devient `3200`, `0.5` reste `0.5`.

    Les quantités sont stockées à quatre décimales et les prix à deux, parce que
    le stock en a besoin. Les **réafficher** ainsi dans un formulaire donne
    « 10.0000 » dans un champ « Seuil d'alerte » — un chiffre qu'aucun commerçant
    n'écrirait, et qu'il faut effacer entièrement pour en saisir un autre.
    """
    if valeur is None:
        return valeur
    entier = valeur.to_integral_value()
    return entier if valeur == entier else valeur.normalize()


class SocleArticleForm(forms.Form):
    """Ce qu'un article est, indépendamment de son stock.

    Partagé par la création (`ArticleForm`) et la modification
    (`ArticleModifierForm`). La frontière entre les deux n'est pas arbitraire :
    **ce qui décrit l'article** — son nom, son prix, son régime de TVA, ce que
    son métier lui ajoute — se corrige librement ; **ce qui décrit son stock** —
    une quantité, un coût d'achat, une date de péremption — n'est pas un
    attribut mais un mouvement, et se corrige par un autre mouvement.

    Un écran de modification qui proposerait de retaper la quantité écrirait du
    stock sans passer par son journal. C'est précisément ce que l'en-tête de ce
    module interdit.
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
    sur_ordonnance = forms.BooleanField(
        label="Délivré sur ordonnance",
        required=False,
        help_text="Sera consigné à l'ordonnancier, et retiré de la vente en ligne.",
        widget=forms.CheckboxInput(attrs={"class": "case"}),
    )
    reference_constructeur = forms.CharField(
        label="Référence constructeur",
        max_length=64,
        required=False,
        help_text="Celle qui est gravée sur la pièce d'origine.",
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "90915-YZZD4"}),
    )
    suivi_unitaire = forms.BooleanField(
        label="Suivre chaque exemplaire (numéro de série ou IMEI)",
        required=False,
        help_text=(
            "À réserver aux appareils qui en portent un. Un câble n'a pas d'IMEI, "
            "et en réclamer un à chaque réception fait abandonner le suivi."
        ),
        widget=forms.CheckboxInput(attrs={"class": "case"}),
    )
    garantie_mois = forms.IntegerField(
        label="Garantie (mois)",
        min_value=0,
        max_value=120,
        required=False,
        initial=0,
        help_text="Zéro si l'article n'est pas garanti. L'échéance sera figée à la vente.",
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "numeric", "step": "1"}),
    )

    # Ordre d'affichage des champs que le métier ajoute. La liste est ici et non
    # dans le gabarit : un champ composé par `_composer` mais oublié par l'écran
    # est **invisible et pourtant exigé** — c'est ce qui est arrivé à la date de
    # péremption, réclamée par la validation sur un écran qui ne la proposait pas.
    CHAMPS_DE_METIER = (
        "unite",
        "date_peremption",
        "numero_lot",
        "sur_ordonnance",
        "reference_constructeur",
        "suivi_unitaire",
        "garantie_mois",
    )

    # Ce qui ne décrit pas l'article mais son stock initial : retiré là où il n'y
    # a pas de stock initial à saisir, c'est-à-dire à la modification.
    CHAMPS_DE_STOCK = ("date_peremption", "numero_lot")

    def __init__(self, *args, boutique=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.boutique = boutique
        self.metier = boutique.metier_choisi if boutique is not None else metiers.metier_de(None)
        self._composer()

    @property
    def champs_de_metier(self):
        """Les champs que le métier a laissés dans le formulaire, dans l'ordre.

        Le gabarit boucle là-dessus plutôt que de les nommer un à un : ajouter un
        champ de métier ne doit plus demander de penser à deux endroits.
        """
        return [self[nom] for nom in self.CHAMPS_DE_METIER if nom in self.fields]

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

        self.fields["libelle"].label = f"Nom {metier.du_article}"
        if metier.exemples:
            self.fields["libelle"].widget.attrs["placeholder"] = metier.exemples[0]

        # La référence proposée suit le métier elle aussi. Montrer « QUI-CIM-50 »
        # à un pharmacien, c'est lui montrer la référence d'un sac de ciment :
        # l'exemple est là pour donner une forme, pas pour dépayser.
        self.fields["sku"].widget.attrs["placeholder"] = f"{metier.code[:3]}-001"

        self.fields["regime_tva"].initial = metier.regime_tva_defaut
        self.fields["unite"].initial = metier.unite_defaut

        if not metier.a(metiers.PEREMPTION):
            del self.fields["date_peremption"]
        if not metier.a(metiers.LOT):
            del self.fields["numero_lot"]
        if not metier.a(metiers.COMPATIBILITE):
            del self.fields["reference_constructeur"]
        if not metier.a(metiers.ORDONNANCE):
            del self.fields["sur_ordonnance"]
        if not metier.a(metiers.SERIE):
            del self.fields["suivi_unitaire"]
        if not metier.a(metiers.GARANTIE):
            del self.fields["garantie_mois"]
        if metier.unite_defaut == "U" and not metier.a(metiers.POIDS_VARIABLE):
            # L'unité ne se pose pas dans un commerce où tout se vend à la pièce.
            del self.fields["unite"]

    def clean_unite(self):
        return self.cleaned_data.get("unite") or self.metier.unite_defaut

    def clean_sku(self):
        """Référence en capitales, et unique dans la boutique.

        `exclut` permet à la modification de ne pas se heurter à sa propre
        référence : sans lui, rouvrir une fiche et l'enregistrer sans rien
        changer serait refusé.
        """
        sku = self.cleaned_data["sku"].strip().upper()
        from apps.catalog.models import Variante

        deja = Variante.objects.filter(sku=sku)
        if self.exclut is not None:
            deja = deja.exclude(pk=self.exclut)
        if deja.exists():
            raise forms.ValidationError("Cette référence existe déjà dans votre boutique.")
        return sku

    # Identifiant de la variante que la validation d'unicité doit ignorer.
    exclut = None


class ArticleForm(SocleArticleForm):
    """Création d'un article avec son stock initial — l'écran de l'installation.

    Un seul formulaire produit le produit, la variante, le niveau de stock et le
    mouvement d'entrée valorisé. C'est volontaire : pendant un comptage debout
    dans une réserve, on ne remplit pas quatre écrans par référence.
    """

    cout_unitaire = forms.DecimalField(
        label="Coût d'achat unitaire", min_value=Decimal("0"), decimal_places=2,
        help_text="Ce que vous payez au fournisseur. C'est lui qui donne votre marge réelle.",
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "numeric", "step": "1"}),
    )
    quantite = forms.DecimalField(
        label="Quantité comptée", min_value=Decimal("0"), initial=Decimal("0"), decimal_places=4,
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "decimal", "step": "1"}),
    )

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


class ArticleModifierForm(SocleArticleForm):
    """Correction d'un article existant.

    Ce qui manque ici est aussi important que ce qui y est : **ni quantité, ni
    coût d'achat**. Les deux sont l'affaire d'un mouvement de stock, et les
    offrir sur un écran de fiche donnerait le moyen d'écrire du stock sans
    journal — l'inverse exact de ce que le moteur garantit.

    `actif` remplace la suppression quand l'article a une histoire : un article
    vendu ne s'efface pas, il se retire du catalogue.
    """

    actif = forms.BooleanField(
        label="En vente",
        required=False,
        initial=True,
        help_text="Décoché, l'article disparaît de la caisse et de la vitrine, et garde son stock.",
        widget=forms.CheckboxInput(attrs={"class": "case"}),
    )

    def __init__(self, *args, variante=None, **kwargs):
        self.variante = variante
        self.exclut = variante.pk if variante is not None else None
        if variante is not None and "initial" not in kwargs and not args:
            kwargs["initial"] = self.valeurs_de(variante)
        super().__init__(*args, **kwargs)

    @staticmethod
    def valeurs_de(variante) -> dict:
        """Ce que la fiche affiche à l'ouverture, lu sur l'objet réel."""
        niveau = variante.niveaux.first()
        return {
            "libelle": variante.produit.libelle,
            "sku": variante.sku,
            "code_barres": variante.code_barres,
            "prix_vente": nombre_court(variante.prix_vente),
            "seuil_alerte": nombre_court(niveau.seuil_alerte if niveau else Decimal("0")),
            "regime_tva": variante.produit.regime_tva,
            "unite": variante.produit.unite,
            "sur_ordonnance": variante.produit.sur_ordonnance,
            "reference_constructeur": variante.reference_constructeur,
            "suivi_unitaire": variante.suivi_unitaire,
            "garantie_mois": variante.garantie_mois,
            "actif": variante.actif,
        }

    def _composer(self) -> None:
        super()._composer()
        # Une date de péremption et un numéro de lot décrivent une **réception**,
        # pas un article : ils se saisissent à l'entrée de marchandise, où ils ont
        # un sens, et pas sur une fiche qu'on rouvre six mois plus tard.
        for nom in self.CHAMPS_DE_STOCK:
            self.fields.pop(nom, None)


class ExemplairesForm(forms.Form):
    """Déclaration de numéros de série, un par ligne.

    Un champ libre plutôt que N cases : une réception d'appareils se saisit en
    collant la liste du bon de livraison, ou en scannant les étiquettes à la
    suite. Une douchette envoie un retour à la ligne après chaque code — c'est
    exactement ce que ce champ attend.
    """

    numeros = forms.CharField(
        label="Numéros de série",
        widget=forms.Textarea(
            attrs={
                **CHAMP,
                "rows": 4,
                "placeholder": "Un numéro par ligne — scannez à la suite",
                "autocomplete": "off",
                "spellcheck": "false",
            }
        ),
    )

    def clean_numeros(self):
        from apps.inventory.series import numeros_propres

        numeros = numeros_propres(self.cleaned_data["numeros"].splitlines())
        if not numeros:
            raise forms.ValidationError("Aucun numéro lisible dans cette saisie.")
        return numeros


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
    numeros_serie = forms.CharField(
        label="Numéros de série reçus",
        required=False,
        help_text="Un par ligne. Facultatifs : ce qui n'est pas nommé reste du stock ordinaire.",
        widget=forms.Textarea(
            attrs={
                **CHAMP,
                "rows": 4,
                "placeholder": "Un numéro par ligne — scannez à la suite",
                "autocomplete": "off",
                "spellcheck": "false",
            }
        ),
    )

    def __init__(self, *args, variante=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.variante = variante
        if variante is None or not variante.suivi_unitaire:
            # Même règle que partout : ce qui ne s'applique pas n'est pas grisé,
            # il est absent.
            del self.fields["numeros_serie"]

    def clean_numeros_serie(self):
        from apps.inventory.series import numeros_propres

        return numeros_propres(self.cleaned_data["numeros_serie"].splitlines())

    def clean(self):
        donnees = super().clean()
        numeros = donnees.get("numeros_serie") or []
        quantite = donnees.get("quantite")
        if numeros and quantite is not None and len(numeros) > quantite:
            # Plus de numéros que d'appareils : c'est une ligne de trop collée,
            # ou la quantité qui est fausse. Les accepter créerait des exemplaires
            # qui ne sont dans aucun carton.
            self.add_error(
                "numeros_serie",
                f"{len(numeros)} numéros pour {quantite:.0f} reçus : "
                "corrigez la quantité ou retirez les numéros en trop.",
            )
        return donnees


class AtelierForm(forms.Form):
    """Dépôt d'un appareil en réparation."""

    motif = forms.CharField(
        label="Panne constatée",
        max_length=255,
        widget=forms.TextInput(
            attrs={**CHAMP, "placeholder": "Écran cassé, ne charge plus, redémarre seul…"}
        ),
    )


class SortieAtelierForm(forms.Form):
    resultat = forms.CharField(
        label="Ce qui a été fait",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Nappe de charge remplacée"}),
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


# ----------------------------------------------------------------------------
# Compatibilité véhicule — pièces détachées
# ----------------------------------------------------------------------------
class CompatibiliteForm(forms.Form):
    """Déclaration : cette pièce se monte sur ce véhicule.

    Le modèle et les années sont facultatifs, et ce n'est pas un relâchement.
    Un vendeur sait « ça va sur les Corolla » ; il ne sait presque jamais en
    quelle année le constructeur a changé la pièce. Exiger les bornes
    produirait des bornes inventées — donc des compatibilités fausses, ce qui
    est pire que des compatibilités larges.
    """

    marque = forms.CharField(
        label="Marque", max_length=60,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Toyota", "list": "marques-connues"}),
    )
    modele = forms.CharField(
        label="Modèle", max_length=80, required=False,
        help_text="Vide si la pièce va sur toute la marque.",
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "Corolla", "list": "modeles-connus"}),
    )
    motorisation = forms.CharField(
        label="Motorisation", max_length=60, required=False,
        widget=forms.TextInput(attrs={**CHAMP, "placeholder": "1.4 D-4D"}),
    )
    annee_debut = forms.IntegerField(
        label="De l'année", min_value=1950, max_value=2100, required=False,
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "numeric", "placeholder": "2012"}),
    )
    annee_fin = forms.IntegerField(
        label="À l'année", min_value=1950, max_value=2100, required=False,
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "numeric", "placeholder": "2018"}),
    )

    def __init__(self, *args, variante=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.variante = variante

    def clean_marque(self):
        from apps.catalog.vehicules import normaliser

        return normaliser(self.cleaned_data["marque"])

    def clean_modele(self):
        from apps.catalog.vehicules import normaliser

        return normaliser(self.cleaned_data.get("modele", ""))

    def clean(self):
        donnees = super().clean()
        debut, fin = donnees.get("annee_debut"), donnees.get("annee_fin")
        if debut and fin and fin < debut:
            # Un intervalle vide rendrait la pièce compatible avec rien, sans que
            # personne ne s'en aperçoive avant qu'un client reparte bredouille.
            self.add_error("annee_fin", "L'année de fin précède l'année de début.")

        if self.variante is not None and not self.errors:
            from apps.catalog.models import CompatibiliteVehicule

            doublon = CompatibiliteVehicule.objects.filter(
                variante=self.variante,
                marque=donnees.get("marque", ""),
                modele=donnees.get("modele", ""),
                motorisation=donnees.get("motorisation", ""),
                annee_debut=debut,
                annee_fin=fin,
            ).exists()
            if doublon:
                self.add_error("marque", "Cette compatibilité est déjà déclarée.")
        return donnees
