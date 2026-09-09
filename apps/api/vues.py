"""Points d'entrée de l'API v1.

Ce que l'API **ne fait pas**, et pourquoi cela compte : elle ne réimplémente
aucune règle métier. Encaisser passe par `apps.pos.services.encaisser`, recevoir
de la marchandise par `apps.inventory.services.entrer_stock`, lire une balance
par `apps.accounting.services.balance`. Ce sont exactement les fonctions
qu'appelle le back-office.

C'est la seule façon d'éviter la dérive qui guette toute API greffée sur une
application existante : une seconde implémentation, plus simple parce qu'elle
ignore un cas limite, qui produit peu à peu des données que l'interface n'aurait
jamais écrites. Ici, une vue d'API assemble, valide, sérialise — et délègue.
"""

from decimal import Decimal

from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from apps.accounts import permissions as droit
from apps.accounting.services import balance
from apps.api.acces import VueApi
from apps.api.serialiseurs import (
    ArticleSerialiseur,
    DepotSerialiseur,
    EncaissementSerialiseur,
    EntreeStockSerialiseur,
    LigneBalanceSerialiseur,
    MouvementStockSerialiseur,
    TicketDetailSerialiseur,
    TicketSerialiseur,
)
from apps.catalog.models import Variante
from apps.inventory.models import Depot, MouvementStock, NiveauStock
from apps.inventory.services import MouvementInvalide, entrer_stock
from apps.pos import services as caisse
from apps.pos.models import SessionCaisse, Ticket

__all__ = [
    "MoiVue",
    "DepotsVue",
    "ArticlesVue",
    "MouvementsStockVue",
    "EntreesStockVue",
    "VentesVue",
    "VenteDetailVue",
    "BalanceVue",
]


class Pagination(LimitOffsetPagination):
    """Pagination par décalage, plafonnée.

    Le plafond n'est pas un détail de confort : sans lui, un client mal réglé
    demande le catalogue entier à chaque ouverture d'écran, sur une connexion
    facturée au mégaoctet.
    """

    default_limit = 50
    max_limit = 200


def _paginer(vue, queryset, classe_serialiseur):
    paginateur = Pagination()
    page = paginateur.paginate_queryset(queryset, vue.request, view=vue)
    donnees = classe_serialiseur(page, many=True, context={"droits": vue.droits}).data
    return paginateur.get_paginated_response(donnees)


def _depot_demande(vue, identifiant=None) -> Depot | None:
    """Dépôt visé par la requête, à défaut le principal.

    **Un dépôt nommé qui ne se résout pas est une erreur, jamais un repli.**
    `Depot.objects` est filtré sur la boutique courante : l'identifiant d'un
    dépôt voisin ne renvoie rien. Retomber alors silencieusement sur le dépôt
    principal servirait au client le stock d'un dépôt qu'il n'a pas demandé — et
    un comptage fait dans la mauvaise réserve produit des écarts inventés de
    toutes pièces. Répondre des zéros ne vaut pas mieux : cela ressemble à un
    dépôt vide, pas à un dépôt inconnu.

    Le repli sur le principal ne joue donc que pour un client qui n'a **rien**
    demandé.
    """
    demande = identifiant or vue.request.query_params.get("depot")
    if demande:
        depot = Depot.objects.filter(pk=demande, actif=True).first()
        if depot is None:
            raise ValidationError(
                {"depot": "Aucun dépôt actif de cette boutique ne porte cet identifiant."}
            )
        return depot
    return (
        Depot.objects.filter(actif=True, principal=True).first()
        or Depot.objects.filter(actif=True).first()
    )


# ---------------------------------------------------------------------------
# Identité
# ---------------------------------------------------------------------------
class MoiVue(VueApi):
    """Qui suis-je, sur quelle boutique, avec quels droits.

    Premier appel de tout client, et le seul qui n'exige aucun droit
    particulier. Il existe pour la même raison que le tableau de bord composé par
    rôle : un client doit pouvoir **construire son interface à partir de ce que
    le serveur autorise**, plutôt que d'afficher des écrans qui refuseront de
    s'ouvrir.
    """

    droits_requis = ()

    def get(self, requete):
        boutique = self.boutique
        return Response(
            {
                "utilisateur": {
                    "id": requete.user.pk,
                    "nom_complet": requete.user.nom_complet,
                    "telephone": requete.user.telephone,
                },
                "boutique": {
                    "id": boutique.pk,
                    "raison_sociale": boutique.raison_sociale,
                },
                "jeton": {
                    "libelle": requete.auth.libelle,
                    "prefixe": requete.auth.prefixe,
                },
                "droits": sorted(self.droits),
                "roles": sorted(
                    requete.user.appartenances.filter(
                        actif=True, boutique_id=boutique.pk
                    ).values_list("role__libelle", flat=True)
                ),
            }
        )


# ---------------------------------------------------------------------------
# Dépôts et catalogue
# ---------------------------------------------------------------------------
class DepotsVue(VueApi):
    droits_requis = (droit.STOCK_VOIR,)

    def get(self, requete):
        depots = Depot.objects.filter(actif=True).order_by("-principal", "libelle")
        return Response(DepotSerialiseur(depots, many=True).data)


class ArticlesVue(VueApi):
    """Catalogue vendable d'un dépôt, avec son stock.

    Le coût moyen pondéré et la valeur du stock ne sont présents que pour un
    porteur ayant `cout.voir` — sinon les champs sont absents de la réponse, pas
    vides (voir `apps/api/serialiseurs.py`).
    """

    droits_requis = (droit.STOCK_VOIR,)

    def get(self, requete):
        depot = _depot_demande(self)

        variantes = (
            Variante.objects.filter(actif=True)
            .select_related("produit", "produit__categorie")
            .order_by("produit__libelle", "sku")
        )

        recherche = (requete.query_params.get("q") or "").strip()
        if recherche:
            variantes = variantes.filter(
                Q(produit__libelle__icontains=recherche)
                | Q(sku__icontains=recherche)
                | Q(code_barres__icontains=recherche)
            )

        niveaux = {}
        if depot is not None:
            niveaux = {n.variante_id: n for n in NiveauStock.objects.filter(depot=depot)}

        articles = [
            ArticleSerialiseur.assembler(variante, niveaux.get(variante.id))
            for variante in variantes
        ]
        if requete.query_params.get("alerte") in ("1", "true", "vrai"):
            articles = [a for a in articles if a["en_alerte"]]

        return _paginer(self, articles, ArticleSerialiseur)


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------
class MouvementsStockVue(VueApi):
    droits_requis = (droit.STOCK_VOIR,)

    def get(self, requete):
        mouvements = MouvementStock.objects.select_related("variante__produit", "depot")

        if identifiant := requete.query_params.get("depot"):
            mouvements = mouvements.filter(depot_id=identifiant)
        if identifiant := requete.query_params.get("variante"):
            mouvements = mouvements.filter(variante_id=identifiant)
        if type_ := requete.query_params.get("type"):
            mouvements = mouvements.filter(type=type_.upper())

        return _paginer(self, mouvements, MouvementStockSerialiseur)


class EntreesStockVue(VueApi):
    """Réception de marchandise, idempotente.

    Le coût unitaire est obligatoire : c'est lui qui alimente le coût moyen
    pondéré, et une entrée sans coût fausserait la valorisation de tout le stock
    ensuite. L'appel exige donc `cout.voir` en plus de `stock.mouvementer` — on
    ne saisit pas un prix d'achat qu'on n'a pas le droit de lire.
    """

    droits_requis = (droit.STOCK_MOUVEMENTER, droit.COUT_VOIR)

    def post(self, requete):
        formulaire = EntreeStockSerialiseur(data=requete.data)
        formulaire.is_valid(raise_exception=True)
        donnees = formulaire.validated_data

        depot = _depot_demande(self, donnees.get("depot"))
        if depot is None:
            return Response(
                {"detail": "Aucun dépôt actif ne correspond."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        variante = Variante.objects.filter(pk=donnees["variante"], actif=True).first()
        if variante is None:
            return Response(
                {"detail": "Cette référence n'existe pas dans cette boutique."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            mouvement = entrer_stock(
                depot=depot,
                variante=variante,
                quantite=donnees["quantite"],
                cout_unitaire=donnees["cout_unitaire"],
                operation_id=donnees.get("operation_id"),
                origine_type="api.EntreeStock",
                commentaire=donnees.get("commentaire", ""),
                cree_par=requete.user,
            )
        except MouvementInvalide as erreur:
            return Response({"detail": str(erreur)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            MouvementStockSerialiseur(mouvement, context={"droits": self.droits}).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Ventes
# ---------------------------------------------------------------------------
class VentesVue(VueApi):
    """Journal des ventes en lecture, encaissement en écriture.

    Les deux méthodes n'ouvrent pas le même droit : un comptable lit les ventes
    sans jamais pouvoir en créer, un caissier encaisse. C'est exactement la
    séparation de la matrice.
    """

    droits_par_methode = {
        "GET": (droit.VENTES_VOIR,),
        "POST": (droit.CAISSE_ENCAISSER,),
    }

    def get(self, requete):
        tickets = Ticket.objects.select_related("session").order_by("-cree_le")

        if etat := requete.query_params.get("etat"):
            tickets = tickets.filter(etat=etat)
        if identifiant := requete.query_params.get("depot"):
            tickets = tickets.filter(session__depot_id=identifiant)
        if depuis := requete.query_params.get("depuis"):
            tickets = tickets.filter(cree_le__date__gte=depuis)

        return _paginer(self, tickets, TicketSerialiseur)

    def post(self, requete):
        formulaire = EncaissementSerialiseur(data=requete.data)
        formulaire.is_valid(raise_exception=True)
        donnees = formulaire.validated_data

        depot = _depot_demande(self, donnees.get("depot"))
        if depot is None:
            return Response(
                {"detail": "Aucun dépôt actif ne correspond."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Une référence inconnue est refusée, et nommée. Un client d'API n'a
        # personne devant lui pour rattraper un article silencieusement absent
        # du ticket : mieux vaut un refus qu'un encaissement incomplet.
        panier = []
        for ligne in donnees["lignes"]:
            variante = Variante.objects.filter(pk=ligne["variante"], actif=True).first()
            if variante is None:
                return Response(
                    {
                        "detail": "Référence inconnue dans cette boutique.",
                        "variante": str(ligne["variante"]),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            panier.append(
                (variante, ligne["quantite"], ligne.get("remise") or Decimal("0"))
            )

        session = SessionCaisse.objects.filter(
            depot=depot, caissier=requete.user, etat=SessionCaisse.OUVERTE
        ).first() or caisse.ouvrir_session(depot=depot, caissier=requete.user)

        try:
            ticket, rejoue = caisse.encaisser(
                session=session,
                lignes=panier,
                moyen=donnees["moyen"],
                operation_id=donnees.get("operation_id"),
                client_nom=donnees.get("client_nom", ""),
                client_telephone=donnees.get("client_telephone", ""),
                reference_psp=donnees.get("reference_psp", ""),
                encaisse_le=donnees.get("encaisse_le"),
                cree_par=requete.user,
            )
        except caisse.TicketInvalide as erreur:
            return Response({"detail": str(erreur)}, status=status.HTTP_400_BAD_REQUEST)

        corps = TicketDetailSerialiseur(ticket, context={"droits": self.droits}).data
        corps["rejoue"] = rejoue
        # 200 et non 201 sur un rejeu : rien n'a été créé cette fois-ci, et un
        # client qui compte ses créations doit pouvoir s'y fier.
        return Response(
            corps, status=status.HTTP_200_OK if rejoue else status.HTTP_201_CREATED
        )


class VenteDetailVue(VueApi):
    droits_requis = (droit.VENTES_VOIR,)

    def get(self, requete, identifiant):
        ticket = (
            Ticket.objects.filter(pk=identifiant)
            .prefetch_related("lignes", "reglements")
            .select_related("session")
            .first()
        )
        if ticket is None:
            # Le gestionnaire est déjà borné à la boutique : un ticket voisin est
            # introuvable, pas interdit. La distinction est volontaire — un 403
            # confirmerait son existence.
            return Response({"detail": "Ticket introuvable."}, status=status.HTTP_404_NOT_FOUND)
        return Response(TicketDetailSerialiseur(ticket, context={"droits": self.droits}).data)


# ---------------------------------------------------------------------------
# Comptabilité
# ---------------------------------------------------------------------------
class BalanceVue(VueApi):
    droits_requis = (droit.COMPTABILITE_VOIR,)

    def get(self, requete):
        lignes = balance(
            boutique_id=self.boutique.pk, jusqu_au=requete.query_params.get("jusqu_au") or None
        )
        return Response(LigneBalanceSerialiseur(lignes, many=True).data)
