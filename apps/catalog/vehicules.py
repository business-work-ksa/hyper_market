"""Chercher une pièce par le véhicule sur lequel elle se monte.

Un client de pièces détachées ne cherche pas « un filtre à huile ». Il entre en
disant « il me faut le filtre à huile de ma Corolla de 2015 », et souvent il ne
connaît ni la référence, ni la motorisation, ni parfois l'année exacte. Tout ce
module existe pour que cette phrase-là devienne une recherche.

Deux règles gouvernent l'appariement, et toutes les deux vont dans le même sens :
**l'absence d'information ne doit jamais produire une absence de résultat.**

* Une compatibilité déclarée sur toute une marque, sans modèle, **couvre tous les
  modèles** de cette marque. C'est ce que le vendeur a voulu dire en laissant le
  champ vide.
* Une borne d'année absente ne borne rien, et une année absente dans la recherche
  ne filtre rien. Un vendeur ne sait presque jamais quand le constructeur
  arrêtera une pièce ; un client sait rarement l'année exacte de sa voiture.

Le risque assumé est donc de montrer une pièce de trop plutôt que d'en cacher
une. Au comptoir, un vendeur écarte en trois secondes une pièce qui ne convient
pas ; il ne peut rien contre une pièce qu'on ne lui a pas montrée.
"""

from django.db.models import Q

__all__ = ["compatibles", "marques_connues", "modeles_connus", "normaliser"]


def normaliser(texte: str) -> str:
    """Forme canonique d'une marque ou d'un modèle.

    Sans elle, « toyota », « TOYOTA » et « Toyota » deviennent trois marques dans
    la liste déroulante du vendeur, et la quatrième saisie fragmente encore. La
    recherche, elle, reste insensible à la casse : normaliser à l'écriture sert la
    lisibilité des listes, pas l'appariement.
    """
    return " ".join((texte or "").split()).title()


def compatibles(*, marque: str = "", modele: str = "", annee: int | None = None):
    """Variantes déclarées compatibles avec le véhicule décrit.

    Lit dans le contexte de la boutique courante : c'est une recherche au
    comptoir, faite par quelqu'un qui est déjà chez lui.
    """
    from apps.catalog.models import CompatibiliteVehicule, Variante

    marque = (marque or "").strip()
    modele = (modele or "").strip()
    if not marque and not modele and annee is None:
        return Variante.objects.none()

    lignes = CompatibiliteVehicule.objects.all()
    if marque:
        lignes = lignes.filter(marque__icontains=marque)
    if modele:
        # Une compatibilité sans modèle vaut pour toute la marque : l'exclure
        # ferait disparaître exactement les pièces les plus universelles.
        lignes = lignes.filter(Q(modele__icontains=modele) | Q(modele=""))
    if annee is not None:
        lignes = lignes.filter(
            Q(annee_debut__isnull=True) | Q(annee_debut__lte=annee)
        ).filter(Q(annee_fin__isnull=True) | Q(annee_fin__gte=annee))

    return (
        Variante.objects.filter(pk__in=lignes.values("variante_id"))
        .select_related("produit")
        .order_by("produit__libelle")
    )


def marques_connues() -> list[str]:
    """Marques déjà déclarées dans la boutique, pour la saisie assistée.

    Proposer ce qui existe déjà est le seul moyen d'éviter que « Toyota » et
    « Toyata » vivent côte à côte dans le catalogue — et une faute de frappe dans
    une marque rend la pièce introuvable, ce qui revient à ne pas l'avoir.
    """
    from apps.catalog.models import CompatibiliteVehicule

    # `order_by()` vidé avant le `distinct()` : l'ordre par défaut du modèle
    # ajoute ses colonnes au SELECT, et le distinct porte alors sur (marque,
    # modèle, année) — il rend « Toyota » trois fois sans que rien ne le signale.
    return sorted(
        CompatibiliteVehicule.objects.order_by()
        .values_list("marque", flat=True)
        .distinct()
    )


def modeles_connus(marque: str = "") -> list[str]:
    from apps.catalog.models import CompatibiliteVehicule

    lignes = CompatibiliteVehicule.objects.exclude(modele="")
    if marque:
        lignes = lignes.filter(marque__iexact=marque.strip())
    return sorted(lignes.order_by().values_list("modele", flat=True).distinct())
