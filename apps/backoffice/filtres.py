"""Filtres des écrans de liste, en formulaires Django.

**Les filtres vivent dans l'URL, pas dans le navigateur.** Un panneau qui
garderait son état en mémoire locale produirait deux utilisateurs regardant « la
même liste » sans voir la même chose — et un gérant qui envoie un lien à son
magasinier lui enverrait une liste différente de la sienne. En GET, l'état filtré
se partage, se met en favori, et survit à un retour arrière.

**Un filtre n'est jamais obligatoire.** Une valeur illisible dans l'URL — un
identifiant de dépôt fantaisiste, une date malformée — ne doit pas produire une
page d'erreur mais une liste non filtrée sur ce point-là : ces URL se bricolent à
la main et se collent de travers, et une erreur 500 pour un caractère de trop
serait une panne pour l'utilisateur.

La convention qui fait marcher le compteur de filtres actifs : **la valeur neutre
d'un champ est toujours la chaîne vide**, et le premier choix d'une liste
déroulante est donc `("", "Tous")`. Sans elle, `etat=tous` compterait comme un
filtre posé et la pastille annoncerait un filtrage qui n'a pas lieu.
"""

from django import forms
from django.utils.translation import gettext_lazy

CHAMP = {"class": "champ"}

__all__ = [
    "conserver",
    "FiltreForm",
    "FiltresStockForm",
    "FiltresEquipeForm",
    "FiltresLiensForm",
    "FiltresVentesForm",
    "FiltresMouvementsForm",
    "FiltresExemplairesForm",
    "FiltresPeremptionsForm",
    "FiltresCommandesForm",
    "FiltresEcrituresForm",
    "FiltresOrdonnancierForm",
    "FiltresProductionForm",
]


class ChoixTolerant(forms.ChoiceField):
    """Liste déroulante qui **ignore** une valeur inconnue au lieu de la refuser.

    Sans cela, un `?depot=pas-un-uuid` collé de travers rend le formulaire
    entier invalide — et fait donc tomber **tous** les autres filtres avec lui,
    pas seulement celui qui est illisible. Le résultat serait une liste
    silencieusement différente de ce que l'URL prétend montrer.

    On ne valide donc pas le choix, on le **retient s'il est connu** et on
    l'oublie sinon.
    """

    def validate(self, value):  # noqa: D102 — le refus est précisément ce qu'on retire
        return

    def clean(self, value):
        valeur = super().clean(value)
        connus = {str(cle) for cle, _ in self.choices}
        return valeur if valeur in connus else ""


class DateTolerante(forms.DateField):
    """Date qui s'efface si elle est illisible, pour la même raison.

    « Du 32/13/2026 » ne filtre rien et ne doit rien casser : la liste s'affiche
    sans cette borne plutôt que de refuser la page entière.
    """

    def clean(self, value):
        try:
            return super().clean(value)
        except forms.ValidationError:
            return None


def conserver(request, *cles) -> dict:
    """Paramètres de l'URL qu'un **autre** formulaire GET de la page doit reporter.

    Un écran porte souvent deux formulaires en GET : la recherche visible et la
    boîte de filtres. Soumettre l'un efface les paramètres de l'autre, puisque
    seul son propre contenu part dans l'URL. Ces champs cachés les recollent —
    sans eux, chercher un mot effacerait le dépôt qu'on venait de choisir.
    """
    valeurs = {}
    for cle in cles:
        valeur = (request.GET.get(cle) or "").strip()
        if valeur:
            valeurs[cle] = valeur
    return valeurs


class FiltreForm(forms.Form):
    """Socle commun : tous les champs facultatifs, et un compteur d'actifs."""

    def __init__(self, donnees=None, **kwargs):
        # `donnees or None` : un `QueryDict` vide lierait le formulaire et ferait
        # afficher « ce champ est obligatoire » sur un écran qu'on vient d'ouvrir.
        super().__init__(donnees or None, **kwargs)
        for champ in self.fields.values():
            champ.required = False

    @property
    def valeurs(self) -> dict:
        """Ce que la vue applique. Vide si la saisie est illisible."""
        if not self.is_bound:
            return {}
        return self.cleaned_data if self.is_valid() else {}

    @property
    def actifs(self) -> int:
        """Nombre de filtres réellement posés, pour la pastille de la barre.

        Sans ce chiffre, on cherche pourquoi la liste est vide alors qu'un filtre
        posé la veille est encore dans l'URL.
        """
        return sum(1 for valeur in self.valeurs.values() if valeur not in ("", None, []))

    def _choix_depot(self, depots) -> None:
        """Alimente le champ `depot` à partir des dépôts réellement ouverts.

        Confronter l'identifiant à la liste plutôt que de l'injecter tel quel :
        un dépôt d'une autre boutique collé dans l'URL ne se résout tout
        simplement pas.
        """
        if "depot" not in self.fields:
            return
        depots = list(depots or [])
        if len(depots) < 2:
            # Un commerçant qui n'a qu'un dépôt n'a pas à choisir entre une seule
            # option : le champ disparaît plutôt que d'être grisé.
            del self.fields["depot"]
            return
        self.fields["depot"].choices = [("", "Tous les dépôts")] + [
            (str(d.pk), d.libelle) for d in depots
        ]


class FiltresStockForm(FiltreForm):
    """Liste du stock : ce qu'on cherche, dans quel état, dans quel dépôt."""

    q = forms.CharField(
        label=gettext_lazy("Rechercher"),
        widget=forms.TextInput(
            attrs={**CHAMP, "type": "search", "placeholder": gettext_lazy("Nom, référence, référence constructeur")}
        ),
    )
    etat = ChoixTolerant(
        label=gettext_lazy("État du stock"),
        choices=[
            ("", gettext_lazy("Tous")),
            ("alerte", gettext_lazy("Sous le seuil d'alerte")),
            ("rupture", gettext_lazy("En rupture")),
            ("negatif", gettext_lazy("Stock négatif")),
        ],
        widget=forms.Select(attrs=CHAMP),
    )
    depot = ChoixTolerant(label=gettext_lazy("Dépôt"), choices=[], widget=forms.Select(attrs=CHAMP))
    sans_mouvement = ChoixTolerant(
        label=gettext_lazy("Activité"),
        choices=[("", gettext_lazy("Peu importe")), ("dormant", gettext_lazy("Aucun mouvement depuis 30 jours"))],
        help_text=gettext_lazy("Ce qui dort en rayon immobilise de la trésorerie."),
        widget=forms.Select(attrs=CHAMP),
    )

    def __init__(self, donnees=None, *, depots=None, **kwargs):
        super().__init__(donnees, **kwargs)
        self._choix_depot(depots)


class FiltresEquipeForm(FiltreForm):
    q = forms.CharField(
        label=gettext_lazy("Rechercher"),
        widget=forms.TextInput(attrs={**CHAMP, "type": "search", "placeholder": gettext_lazy("Nom ou téléphone")}),
    )
    role = ChoixTolerant(label=gettext_lazy("Rôle"), choices=[], widget=forms.Select(attrs=CHAMP))
    etat = ChoixTolerant(
        label=gettext_lazy("Accès"),
        choices=[("", gettext_lazy("Tous")), ("actif", gettext_lazy("Actif")), ("retire", gettext_lazy("Retiré"))],
        widget=forms.Select(attrs=CHAMP),
    )

    def __init__(self, donnees=None, *, roles=None, **kwargs):
        super().__init__(donnees, **kwargs)
        self.fields["role"].choices = [("", "Tous les rôles")] + [
            (r.code, r.libelle_affiche) for r in (roles or [])
        ]


class FiltresLiensForm(FiltreForm):
    q = forms.CharField(
        label=gettext_lazy("Rechercher"),
        widget=forms.TextInput(attrs={**CHAMP, "type": "search", "placeholder": gettext_lazy("Usage ou code")}),
    )
    etat = ChoixTolerant(
        label=gettext_lazy("État"),
        choices=[("", gettext_lazy("Tous")), ("actif", gettext_lazy("Actifs")), ("retire", gettext_lazy("Retirés"))],
        widget=forms.Select(attrs=CHAMP),
    )
    portee = ChoixTolerant(
        label=gettext_lazy("Destination"),
        choices=[("", gettext_lazy("Peu importe")), ("vitrine", gettext_lazy("Ma vitrine")), ("article", gettext_lazy("Un article"))],
        widget=forms.Select(attrs=CHAMP),
    )


class FiltresVentesForm(FiltreForm):
    q = forms.CharField(
        label=gettext_lazy("Rechercher"),
        widget=forms.TextInput(attrs={**CHAMP, "type": "search", "placeholder": gettext_lazy("Numéro de ticket ou client")}),
    )
    depuis = DateTolerante(label=gettext_lazy("Du"), widget=forms.DateInput(attrs={**CHAMP, "type": "date"}))
    jusqua = DateTolerante(label=gettext_lazy("Au"), widget=forms.DateInput(attrs={**CHAMP, "type": "date"}))
    moyen = ChoixTolerant(label=gettext_lazy("Règlement"), choices=[], widget=forms.Select(attrs=CHAMP))
    etat = ChoixTolerant(
        label=gettext_lazy("État"),
        choices=[("", gettext_lazy("Tous")), ("cloture", gettext_lazy("Clôturés")), ("annule", gettext_lazy("Annulés"))],
        widget=forms.Select(attrs=CHAMP),
    )

    def __init__(self, donnees=None, **kwargs):
        super().__init__(donnees, **kwargs)
        from apps.pos.models import ReglementTicket

        self.fields["moyen"].choices = [("", "Tous")] + list(ReglementTicket.MOYENS)

    def clean(self):
        donnees = super().clean()
        debut, fin = donnees.get("depuis"), donnees.get("jusqua")
        if debut and fin and fin < debut:
            # Un intervalle à l'envers ne renvoie rien et ne dit pas pourquoi :
            # on le remet à l'endroit plutôt que de refuser la recherche.
            donnees["depuis"], donnees["jusqua"] = fin, debut
        return donnees


class FiltresMouvementsForm(FiltreForm):
    type = ChoixTolerant(label=gettext_lazy("Type de mouvement"), choices=[], widget=forms.Select(attrs=CHAMP))
    depuis = DateTolerante(label=gettext_lazy("Du"), widget=forms.DateInput(attrs={**CHAMP, "type": "date"}))
    jusqua = DateTolerante(label=gettext_lazy("Au"), widget=forms.DateInput(attrs={**CHAMP, "type": "date"}))
    depot = ChoixTolerant(label=gettext_lazy("Dépôt"), choices=[], widget=forms.Select(attrs=CHAMP))

    def __init__(self, donnees=None, *, depots=None, **kwargs):
        super().__init__(donnees, **kwargs)
        from apps.inventory.models import MouvementStock

        self.fields["type"].choices = [("", "Tous")] + list(MouvementStock.TYPES)
        self._choix_depot(depots)


class FiltresExemplairesForm(FiltreForm):
    q = forms.CharField(
        label=gettext_lazy("Numéro de série"),
        widget=forms.TextInput(attrs={**CHAMP, "type": "search", "placeholder": gettext_lazy("IMEI ou numéro")}),
    )
    etat = ChoixTolerant(label=gettext_lazy("État"), choices=[], widget=forms.Select(attrs=CHAMP))
    garantie = ChoixTolerant(
        label=gettext_lazy("Garantie"),
        choices=[("", gettext_lazy("Peu importe")), ("en_cours", gettext_lazy("En cours")), ("expiree", gettext_lazy("Expirée")), ("aucune", gettext_lazy("Aucune"))],
        widget=forms.Select(attrs=CHAMP),
    )

    def __init__(self, donnees=None, **kwargs):
        super().__init__(donnees, **kwargs)
        from apps.inventory.models import NumeroSerie

        self.fields["etat"].choices = [("", "Tous")] + list(NumeroSerie.ETATS)


class FiltresPeremptionsForm(FiltreForm):
    q = forms.CharField(
        label=gettext_lazy("Rechercher"),
        widget=forms.TextInput(attrs={**CHAMP, "type": "search", "placeholder": gettext_lazy("Article ou numéro de lot")}),
    )
    etat = ChoixTolerant(
        label=gettext_lazy("Échéance"),
        choices=[("", gettext_lazy("Tous")), ("perime", gettext_lazy("Déjà périmés")), ("bientot", gettext_lazy("Périment bientôt"))],
        widget=forms.Select(attrs=CHAMP),
    )
    jours = forms.IntegerField(
        label=gettext_lazy("Horizon (jours)"),
        min_value=1,
        max_value=365,
        help_text=gettext_lazy("Trente jours : le délai à partir duquel on peut encore agir."),
        widget=forms.NumberInput(attrs={**CHAMP, "inputmode": "numeric", "placeholder": "30"}),
    )
    depot = ChoixTolerant(label=gettext_lazy("Dépôt"), choices=[], widget=forms.Select(attrs=CHAMP))

    def __init__(self, donnees=None, *, depots=None, **kwargs):
        super().__init__(donnees, **kwargs)
        self._choix_depot(depots)


class FiltresCommandesForm(FiltreForm):
    q = forms.CharField(
        label=gettext_lazy("Rechercher"),
        widget=forms.TextInput(attrs={**CHAMP, "type": "search", "placeholder": gettext_lazy("Numéro ou client")}),
    )
    etat = ChoixTolerant(label=gettext_lazy("État"), choices=[], widget=forms.Select(attrs=CHAMP))
    depuis = DateTolerante(label=gettext_lazy("Passées depuis le"), widget=forms.DateInput(attrs={**CHAMP, "type": "date"}))

    def __init__(self, donnees=None, **kwargs):
        super().__init__(donnees, **kwargs)
        from apps.orders.models import SousCommande

        self.fields["etat"].choices = [("", "Tous")] + list(SousCommande.ETATS)


class FiltresEcrituresForm(FiltreForm):
    q = forms.CharField(
        label=gettext_lazy("Rechercher"),
        widget=forms.TextInput(attrs={**CHAMP, "type": "search", "placeholder": gettext_lazy("Libellé ou pièce")}),
    )
    journal = ChoixTolerant(label=gettext_lazy("Journal"), choices=[], widget=forms.Select(attrs=CHAMP))
    depuis = DateTolerante(label=gettext_lazy("Du"), widget=forms.DateInput(attrs={**CHAMP, "type": "date"}))
    jusqua = DateTolerante(label=gettext_lazy("Au"), widget=forms.DateInput(attrs={**CHAMP, "type": "date"}))

    def __init__(self, donnees=None, *, journaux=None, **kwargs):
        super().__init__(donnees, **kwargs)
        self.fields["journal"].choices = [("", "Tous")] + [
            (j.code, f"{j.code} — {j.libelle}") for j in (journaux or [])
        ]


class FiltresOrdonnancierForm(FiltreForm):
    """Registre des délivrances sur ordonnance.

    « À compléter » est un filtre à part entière : c'est la seule partie du
    registre sur laquelle il reste un geste à faire, et un pharmacien la cherche
    plus souvent qu'il ne cherche une date.
    """

    q = forms.CharField(
        label=gettext_lazy("Rechercher"),
        widget=forms.TextInput(
            attrs={**CHAMP, "type": "search", "placeholder": gettext_lazy("Ticket, client ou prescripteur")}
        ),
    )
    etat = ChoixTolerant(
        label=gettext_lazy("Consignation"),
        choices=[("", gettext_lazy("Toutes")), ("incomplete", gettext_lazy("À compléter")), ("consignee", gettext_lazy("Consignées"))],
        widget=forms.Select(attrs=CHAMP),
    )
    depuis = DateTolerante(label=gettext_lazy("Depuis le"), widget=forms.DateInput(attrs={**CHAMP, "type": "date"}))


class FiltresProductionForm(FiltreForm):
    """Production d'une journée. Le jour est le seul filtre qui compte.

    Un boulanger regarde « aujourd'hui » quatre-vingt-dix-neuf fois sur cent, et
    « hier » le centième — quand il cherche pourquoi il lui manque du pain.
    """

    jour = DateTolerante(
        label=gettext_lazy("Journée"),
        help_text=gettext_lazy("Vide : aujourd'hui."),
        widget=forms.DateInput(attrs={**CHAMP, "type": "date"}),
    )
