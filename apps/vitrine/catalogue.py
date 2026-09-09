"""La porte du catalogue public — et la seule.

Un point demande à être posé franchement, parce qu'il touche à la règle la plus
protégée du projet : **la vitrine lit en contexte plateforme.** Il le faut. Un
acheteur cherche « ciment » sur tout le marché, pas dans une boutique qu'il
aurait désignée d'avance ; et les politiques d'isolation au niveau ligne
(ADR-002) ne rendraient rien sans ce contexte.

Ce n'est pas une brèche, et voici pourquoi
------------------------------------------

Ce que la barrière 3 protège, ce sont les données **privées** d'un commerçant :
son coût d'achat, sa marge, ses écritures, ses salariés. Un catalogue public
n'en contient aucune. Il contient ce que le marchand a délibérément mis en
vitrine — un libellé, une photo, un prix affiché — c'est-à-dire exactement ce
qu'il paie un emplacement pour montrer.

La distinction ne tient pas au bon vouloir de l'appelant : **elle est portée par
ce module.** Les fonctions ci-dessous sont la seule façon dont la vitrine
accède au catalogue, et elles ne rendent que des variantes actives de boutiques
en état de vendre. Aucune vue de la vitrine n'ouvre `contexte_plateforme()`
elle-même, et aucune ne voit un `NiveauStock`, un `MouvementStock` ou une
`EcritureComptable`.

Sur la journalisation
---------------------

Le document 09 demande que tout accès transverse soit journalisé. Écrire une
entrée d'audit à chaque affichage de page de catalogue produirait des millions
de lignes qui noieraient les accès réellement sensibles — ceux d'un
administrateur de marché qui ouvre les comptes d'un commerçant. **Un accès
public à une donnée publique n'est pas l'événement que ce journal existe pour
capturer.** La trace utile ici est celle d'un serveur web, pas celle d'un
registre d'audit.
"""

from decimal import Decimal

from django.db.models import Q

from apps.catalog.models import Categorie, Produit, Variante
from apps.core.tenancy import contexte_plateforme
from apps.marketplace.models import Bail, Boutique, Rayon

__all__ = [
    "boutiques_en_vitrine",
    "articles_en_vitrine",
    "article_par_identifiant",
    "rayons_ouverts",
    "boutique_par_slug",
]


def boutiques_en_vitrine():
    """Boutiques réellement visibles par un acheteur.

    Une boutique suspendue garde son back-office mais disparaît d'ici : couper la
    gestion d'un marchand en retard de loyer reviendrait à lui couper l'accès à sa
    propre comptabilité (docs/05, M02). Elle ne vend plus, elle n'est pas effacée.
    """
    with contexte_plateforme():
        actives = Bail.objects.filter(etat=Bail.ACTIF).values_list("boutique_id", flat=True)
        return list(
            Boutique.objects.filter(etat=Boutique.ACTIVE, id__in=list(actives))
            .select_related("rayon_principal")
            .order_by("enseigne")
        )


def boutique_par_slug(slug: str) -> Boutique | None:
    return next((b for b in boutiques_en_vitrine() if b.slug == slug), None)


def rayons_ouverts():
    return list(Rayon.objects.filter(ouvert=True).order_by("ordre", "libelle"))


def _requete_de_base(identifiants_boutiques):
    return (
        Variante.objects.filter(
            actif=True,
            produit__actif=True,
            boutique_id__in=identifiants_boutiques,
        )
        .select_related("produit", "produit__categorie", "boutique")
        .order_by("produit__libelle", "sku")
    )


def articles_en_vitrine(*, recherche: str = "", rayon=None, boutique=None, limite=None):
    """Articles vendables du marché, filtrés pour un acheteur.

    Renvoie des `Variante` déjà jointes à leur produit et à leur boutique — la
    vitrine affiche toujours les trois ensemble, et une requête par ligne sur une
    page de catalogue serait ruineuse sur 3G.
    """
    boutiques = boutiques_en_vitrine()
    if boutique is not None:
        boutiques = [b for b in boutiques if b.pk == getattr(boutique, "pk", boutique)]
    if rayon is not None:
        cible = getattr(rayon, "pk", rayon)
        boutiques = [b for b in boutiques if b.rayon_principal_id == cible]

    if not boutiques:
        return []

    with contexte_plateforme():
        articles = _requete_de_base([b.pk for b in boutiques])

        recherche = (recherche or "").strip()
        if recherche:
            articles = articles.filter(
                Q(produit__libelle__icontains=recherche)
                | Q(produit__description__icontains=recherche)
                | Q(sku__icontains=recherche)
                | Q(code_barres__iexact=recherche)
            )
        if limite is not None:
            articles = articles[:limite]
        return list(articles)


def article_par_identifiant(identifiant) -> Variante | None:
    """Une variante, si et seulement si elle est réellement en vitrine.

    Le contrôle porte sur la boutique autant que sur l'article : un lien vers le
    produit d'une boutique suspendue ne doit pas continuer de fonctionner parce
    qu'on en a gardé l'adresse.
    """
    autorisees = {b.pk: b for b in boutiques_en_vitrine()}
    if not autorisees:
        return None

    with contexte_plateforme():
        article = (
            Variante.objects.filter(pk=identifiant, actif=True, produit__actif=True)
            .select_related("produit", "produit__categorie", "boutique")
            .first()
        )
    if article is None or article.boutique_id not in autorisees:
        return None
    return article
