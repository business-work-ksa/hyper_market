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

from django.db.models import Prefetch, Q

from apps.catalog.models import Categorie, MediaProduit, Produit, Variante
from apps.confiance.paliers import expression_identite_verifiee
from apps.core.tenancy import contexte_plateforme
from apps.marketplace.models import Bail, Boutique, Rayon

__all__ = [
    "boutiques_en_vitrine",
    "articles_en_vitrine",
    "article_par_identifiant",
    "rayons_ouverts",
    "boutique_par_slug",
    "Filtres",
    "rechercher",
    "menu_rayons",
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
            # La confiance publique voyage avec la boutique, dans la même requête : une page de
            # vitrine ne relit rien boutique par boutique (`apps/confiance/templatetags`).
            .select_related("rayon_principal", "mesure_confiance")
            .annotate(identite_verifiee=expression_identite_verifiee("pk"))
            .order_by("enseigne")
        )


def boutique_par_slug(slug: str) -> Boutique | None:
    return next((b for b in boutiques_en_vitrine() if b.slug == slug), None)


def rayons_ouverts():
    return list(Rayon.objects.filter(ouvert=True).order_by("ordre", "libelle"))


def _requete_de_base(identifiants_boutiques):
    """Ce qui est vendable en ligne, et rien d'autre.

    Le filtre sur `sur_ordonnance` est **ici et pas dans les vues** : c'est une
    règle, pas une préférence d'affichage. Un médicament qui ne se délivre que
    sur ordonnance ne se commande pas sur un site — le pharmacien doit voir
    l'ordonnance, et un panier ne la montre pas. Posé à la seule porte du
    catalogue, il couvre du même geste la liste, la recherche, la page d'un
    article et l'ajout au panier ; posé dans chaque vue, il aurait fini par
    manquer à l'une d'elles.
    """
    return (
        Variante.objects.filter(
            actif=True,
            produit__actif=True,
            produit__sur_ordonnance=False,
            boutique_id__in=identifiants_boutiques,
        )
        .select_related("produit", "produit__categorie", "boutique", "boutique__mesure_confiance")
        # La première photo de chaque produit, en une requête pour toute la page.
        .prefetch_related(
            Prefetch(
                "produit__medias",
                queryset=MediaProduit.objects_all_tenants.order_by("ordre"),
                to_attr="medias_vues",
            )
        )
        # « Identité vérifiée » sur chaque carte, sans une requête par carte : c'est une colonne
        # de plus dans la requête qui lit déjà les articles.
        .annotate(vendeur_identite_verifiee=expression_identite_verifiee("boutique_id"))
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
        # `_requete_de_base` porte les conditions de vente en ligne, dont le
        # retrait des médicaments sur ordonnance : les répéter ici les ferait
        # diverger le jour où l'une change.
        article = _requete_de_base(list(autorisees)).filter(pk=identifiant).first()
    return article


def compatibilites_de(article) -> list:
    """Véhicules sur lesquels cet article se monte, pour la page publique.

    Ce n'est pas une donnée privée du commerçant : c'est l'argument de vente
    lui-même. Un acheteur en ligne qui ne peut pas vérifier que la pièce va sur
    sa voiture n'achète pas — il vient au comptoir demander, ou il va ailleurs.

    Vide dès que le métier n'active pas la fonction : aucune ligne n'existe, la
    requête ne renvoie rien, et la page n'affiche pas de section.
    """
    from apps.catalog.models import CompatibiliteVehicule

    if article is None:
        return []
    with contexte_plateforme():
        return list(CompatibiliteVehicule.objects.filter(variante=article))


# ---------------------------------------------------------------------------
# Recherche filtrée, facettes et mégamenu
# ---------------------------------------------------------------------------
# Les filtres sont lus d'une requête GET et seulement d'elle : une adresse filtrée se partage
# sur WhatsApp et se rouvre à l'identique. Aucun filtre ne touche à une donnée privée — le
# stock reste hors de la vitrine, et le tri « nouveautés » lit la date de mise en vente, pas
# le rythme des ventes.

PAR_PAGE = 24
TRIS = ("pertinence", "prix-croissant", "prix-decroissant", "nouveautes")
_ORDRES = {
    "pertinence": ("produit__libelle", "sku"),
    "prix-croissant": ("prix_vente", "produit__libelle"),
    "prix-decroissant": ("-prix_vente", "produit__libelle"),
    "nouveautes": ("-cree_le", "produit__libelle"),
}


def _decimal(valeur):
    try:
        nombre = Decimal(str(valeur).replace(" ", "").replace(" ", ""))
    except (ArithmeticError, ValueError, TypeError):
        return None
    return nombre if nombre >= 0 else None


class Filtres:
    """Ce que l'acheteur a demandé, nettoyé. Une valeur inconnue est ignorée, jamais une erreur."""

    def __init__(self, donnees, rayons):
        self.recherche = (donnees.get("q") or "").strip()[:120]
        code = donnees.get("rayon") or ""
        self.rayon = next((r for r in rayons if r.code == code), None)
        self.categorie = (donnees.get("categorie") or "").strip()[:140]
        self.boutique = (donnees.get("boutique") or "").strip()[:140]
        self.ville = (donnees.get("ville") or "").strip()[:80]
        self.prix_min = _decimal(donnees.get("prix_min")) if donnees.get("prix_min") else None
        self.prix_max = _decimal(donnees.get("prix_max")) if donnees.get("prix_max") else None
        self.verifie = donnees.get("verifie") in ("1", "on", "true")
        tri = donnees.get("tri") or "pertinence"
        self.tri = tri if tri in TRIS else "pertinence"
        try:
            self.page = max(1, min(int(donnees.get("page") or 1), 500))
        except ValueError:
            self.page = 1

    @property
    def nombre_actifs(self) -> int:
        return sum(
            bool(x)
            for x in (self.categorie, self.boutique, self.ville, self.prix_min is not None,
                      self.prix_max is not None, self.verifie)
        )


class Resultat:
    def __init__(self, articles, total, page, par_page, facettes):
        self.articles = articles
        self.total = total
        self.page = page
        self.par_page = par_page
        self.facettes = facettes

    @property
    def suivante(self):
        return self.page + 1 if self.page * self.par_page < self.total else None


def rechercher(filtres: Filtres, *, par_page: int = PAR_PAGE) -> Resultat:
    """Articles filtrés et triés, une page, et les facettes de la portée courante.

    Les facettes (catégories, commerçants, villes, fourchette de prix) sont comptées sur la
    portée « recherche + rayon » seulement : cocher un commerçant ne fait pas disparaître les
    autres de la liste, on peut changer d'avis sans tout recommencer.
    """
    from django.db.models import Count, Max, Min

    boutiques = boutiques_en_vitrine()
    if filtres.rayon is not None:
        boutiques = [b for b in boutiques if b.rayon_principal_id == filtres.rayon.pk]
    vides = {"categories": [], "boutiques": [], "villes": [], "prix": (None, None)}
    if not boutiques:
        return Resultat([], 0, 1, par_page, vides)
    par_id = {b.pk: b for b in boutiques}

    with contexte_plateforme():
        portee = _requete_de_base(list(par_id))
        if filtres.recherche:
            q = filtres.recherche
            portee = portee.filter(
                Q(produit__libelle__icontains=q)
                | Q(produit__description__icontains=q)
                | Q(sku__icontains=q)
                | Q(code_barres__iexact=q)
            )

        base = portee.order_by()
        par_boutique = dict(base.values_list("boutique_id").annotate(n=Count("id")))
        par_categorie = list(
            base.exclude(produit__categorie=None)
            .values("produit__categorie__slug", "produit__categorie__libelle")
            .annotate(n=Count("id"))
            .order_by("produit__categorie__libelle")
        )
        bornes = base.aggregate(bas=Min("prix_vente"), haut=Max("prix_vente"))

        articles = portee
        if filtres.categorie:
            articles = articles.filter(produit__categorie__slug=filtres.categorie)
        if filtres.boutique:
            articles = articles.filter(boutique__slug=filtres.boutique)
        if filtres.ville:
            articles = articles.filter(boutique__ville__iexact=filtres.ville)
        if filtres.prix_min is not None:
            articles = articles.filter(prix_vente__gte=filtres.prix_min)
        if filtres.prix_max is not None:
            articles = articles.filter(prix_vente__lte=filtres.prix_max)
        if filtres.verifie:
            articles = articles.filter(vendeur_identite_verifiee=True)
        articles = articles.order_by(*_ORDRES[filtres.tri])

        total = articles.count()
        debut = (filtres.page - 1) * par_page
        page = list(articles[debut : debut + par_page])

    villes: dict[str, int] = {}
    for boutique_id, n in par_boutique.items():
        ville = par_id[boutique_id].ville
        villes[ville] = villes.get(ville, 0) + n
    facettes = {
        "categories": [
            {"slug": c["produit__categorie__slug"], "libelle": c["produit__categorie__libelle"], "n": c["n"]}
            for c in par_categorie
        ],
        "boutiques": sorted(
            ({"slug": par_id[i].slug, "libelle": par_id[i].enseigne, "n": n} for i, n in par_boutique.items()),
            key=lambda b: b["libelle"],
        ),
        "villes": sorted(({"libelle": v, "n": n} for v, n in villes.items()), key=lambda v: v["libelle"]),
        "prix": (bornes["bas"], bornes["haut"]),
    }
    return Resultat(page, total, filtres.page, par_page, facettes)


def menu_rayons() -> list[dict]:
    """Le mégamenu : chaque rayon ouvert, ses catégories, ses commerçants, son nombre d'articles.

    Trois requêtes pour tout le menu, quel que soit le nombre de rayons : il s'affiche sur chaque
    page du marché.
    """
    from django.db.models import Count

    rayons = rayons_ouverts()
    boutiques = boutiques_en_vitrine()
    if not rayons:
        return []
    with contexte_plateforme():
        comptes = dict(
            _requete_de_base([b.pk for b in boutiques])
            .order_by()
            .values_list("boutique__rayon_principal_id")
            .annotate(n=Count("id"))
        ) if boutiques else {}
        categories: dict = {}
        for c in Categorie.objects.filter(rayon__in=rayons).order_by("libelle"):
            categories.setdefault(c.rayon_id, []).append(c)
    menu = []
    for r in rayons:
        siens = [b for b in boutiques if b.rayon_principal_id == r.pk]
        menu.append(
            {
                "rayon": r,
                "nb_articles": comptes.get(r.pk, 0),
                "categories": categories.get(r.pk, [])[:8],
                "boutiques": siens[:6],
                "nb_boutiques": len(siens),
            }
        )
    return menu
