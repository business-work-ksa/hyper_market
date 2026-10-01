"""Suivi à l'unité : numéros de série, IMEI, et garantie.

Le stock ordinaire compte : « il me reste quatre téléphones ». Cela suffit pour
réapprovisionner, et cela ne suffit pour rien d'autre le jour où un client revient
avec un appareil en panne. La question qu'il pose — « je l'ai acheté chez vous,
il est encore garanti ? » — ne se répond pas avec une quantité. Elle se répond
avec un exemplaire nommé.

**La quantité reste la source de vérité, les numéros la doublent nominativement.**
`NiveauStock` porte le stock et sa valorisation ; `NumeroSerie` porte l'identité
des exemplaires. Les deux peuvent diverger, et c'est voulu : une réception saisie
sans les IMEI ajoute quatre téléphones au stock et zéro exemplaire nommé.
Refuser la réception aurait été pire — la marchandise est physiquement là, le
camion est reparti. Le module sait dire combien d'exemplaires manquent à l'appel
(`ecarts_de_numerotation`), et c'est ce chiffre qui est affiché plutôt qu'un
blocage.

**Un numéro inconnu à la vente est créé, pas refusé.** Même règle que le stock
négatif (ADR-005) et que l'ordonnancier : l'appareil est parti avec le client, et
refuser d'enregistrer la vente ne le ferait pas revenir — cela ferait seulement
disparaître la trace. L'exemplaire est alors créé directement à l'état vendu, et
son absence de réception se lit à sa date.

**L'échéance de garantie est figée à la vente.** Elle est calculée une fois, le
jour de la vente, à partir de la durée que portait alors l'article — et plus
jamais recalculée. Un commerçant qui ramène sa garantie de douze à six mois le
fait pour ses ventes futures ; réduire rétroactivement celles déjà consenties
serait une promesse reprise.
"""

from calendar import monthrange
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.core.tenancy import contexte_boutique
from apps.inventory.models import NiveauStock, NumeroSerie, PassageAtelier

__all__ = [
    "NumeroInvalide",
    "normaliser",
    "numeros_propres",
    "declarer",
    "vendre",
    "rechercher",
    "exemplaires_de",
    "vendus_recemment",
    "en_atelier",
    "entrer_a_l_atelier",
    "sortir_de_l_atelier",
    "ecarts_de_numerotation",
    "echeance_de_garantie",
]


class NumeroInvalide(ValueError):
    """Numéro refusé : vide, ou déjà porté par un autre exemplaire de la boutique."""


def normaliser(numero: str) -> str:
    """Forme de comparaison d'un numéro : sans espaces, en capitales.

    Un IMEI se lit sur un écran ou sur une étiquette, et se retape avec des
    espaces qui ne sont pas dans le numéro. Les séparateurs internes — tirets,
    points — sont **conservés** : ils appartiennent à la référence du fabricant,
    et les retirer ferait se confondre deux séries distinctes.
    """
    return " ".join((numero or "").split()).replace(" ", "").upper()[:64]


def numeros_propres(numeros) -> list[str]:
    """Normalise, écarte les vides, et dédoublonne en gardant l'ordre de saisie.

    Le doublon est silencieux : coller deux fois le même IMEI dans une réception
    est une maladresse de copier-coller, pas une déclaration de deux appareils.
    """
    vus, propres = set(), []
    for brut in numeros or ():
        numero = normaliser(brut)
        if not numero or numero in vus:
            continue
        vus.add(numero)
        propres.append(numero)
    return propres


# ---------------------------------------------------------------------------
# Réception
# ---------------------------------------------------------------------------
def declarer(*, depot, variante, numeros, recu_le=None, cree_par=None, commentaire=""):
    """Nomme les exemplaires reçus. Renvoie les lignes créées ou réveillées."""
    with contexte_boutique(depot.boutique_id):
        return _declarer(
            depot=depot,
            variante=variante,
            numeros=numeros,
            recu_le=recu_le,
            cree_par=cree_par,
            commentaire=commentaire,
        )


@transaction.atomic
def _declarer(*, depot, variante, numeros, recu_le, cree_par, commentaire):
    if not variante.suivi_unitaire:
        # Nommer les exemplaires d'un article qui n'est pas suivi créerait un
        # stock nominatif qu'aucun écran ne lit et qu'aucune vente ne consomme :
        # une trace qui vieillit sans jamais servir.
        raise NumeroInvalide(
            f"« {variante} » n'est pas suivi à l'unité : activez le suivi sur "
            "l'article avant d'y déclarer des numéros."
        )
    if depot.boutique_id != variante.boutique_id:
        raise NumeroInvalide("Le dépôt et l'article appartiennent à des boutiques différentes.")

    recu_le = recu_le or timezone.localdate()
    declares = []
    for numero in numeros_propres(numeros):
        existant = NumeroSerie.objects_all_tenants.filter(
            boutique_id=depot.boutique_id, numero=numero
        ).first()

        if existant is None:
            declares.append(
                NumeroSerie.objects_all_tenants.create(
                    boutique_id=depot.boutique_id,
                    variante=variante,
                    depot=depot,
                    numero=numero,
                    recu_le=recu_le,
                    commentaire=commentaire[:255],
                    cree_par=cree_par,
                )
            )
            continue

        if existant.variante_id != variante.pk:
            # Un numéro nomme un objet. Le déplacer d'un article à un autre ne
            # corrige pas une erreur de saisie, il efface une histoire.
            raise NumeroInvalide(
                f"Le numéro {numero} est déjà porté par « {existant.variante} »."
            )

        if existant.etat == NumeroSerie.EN_STOCK:
            continue  # déjà en rayon : une réception retransmise ne le double pas

        # Reprise d'occasion, ou retour définitif : le même objet revient. Sa
        # ligne se réemploie, garantie comprise — c'est bien cet appareil-là qui
        # avait été vendu, et son histoire vaut parce qu'elle ne se coupe pas.
        existant.etat = NumeroSerie.EN_STOCK
        existant.depot = depot
        existant.save(update_fields=["etat", "depot", "modifie_le"])
        declares.append(existant)

    return declares


# ---------------------------------------------------------------------------
# Vente
# ---------------------------------------------------------------------------
def echeance_de_garantie(vendu_le, mois: int) -> date | None:
    """Fin de garantie : la date de vente décalée de `mois` mois.

    Le décalage se fait en mois de calendrier et non en jours : une garantie d'un
    an vendue le 29 février finit le 28 février, pas le 1er mars. C'est ce qu'un
    client comprend, et c'est ce qu'un ticket dit.
    """
    if not mois:
        return None
    jour = vendu_le.date() if hasattr(vendu_le, "date") else vendu_le

    total = jour.month - 1 + int(mois)
    annee = jour.year + total // 12
    mois_cible = total % 12 + 1
    # Le 31 d'un mois qui n'en compte que 30 recule au dernier jour réel.
    dernier = monthrange(annee, mois_cible)[1]
    return date(annee, mois_cible, min(jour.day, dernier))


def vendre(
    *,
    depot,
    variante,
    numeros,
    ticket_id=None,
    ticket_numero: str = "",
    client: str = "",
    vendu_le=None,
    cree_par=None,
):
    """Marque les exemplaires vendus, et fige leur échéance de garantie."""
    with contexte_boutique(depot.boutique_id):
        return _vendre(
            depot=depot,
            variante=variante,
            numeros=numeros,
            ticket_id=ticket_id,
            ticket_numero=ticket_numero,
            client=client,
            vendu_le=vendu_le,
            cree_par=cree_par,
        )


@transaction.atomic
def _vendre(*, depot, variante, numeros, ticket_id, ticket_numero, client, vendu_le, cree_par):
    vendu_le = vendu_le or timezone.now()
    echeance = echeance_de_garantie(vendu_le, variante.garantie_mois)
    vendus = []

    for numero in numeros_propres(numeros):
        exemplaire = NumeroSerie.objects_all_tenants.filter(
            boutique_id=depot.boutique_id, numero=numero
        ).first()

        if exemplaire is None:
            # Jamais reçu, et pourtant vendu : l'appareil est parti avec le
            # client. On le nomme au moment où on le voit, plutôt que de perdre
            # la trace (ADR-005). Sa date de réception vaut celle de la vente,
            # et l'écart de numérotation le dira.
            exemplaire = NumeroSerie.objects_all_tenants.create(
                boutique_id=depot.boutique_id,
                variante=variante,
                depot=depot,
                numero=numero,
                recu_le=vendu_le.date() if hasattr(vendu_le, "date") else vendu_le,
                commentaire="Numéro saisi à la vente, sans réception préalable.",
                cree_par=cree_par,
            )
        elif exemplaire.etat == NumeroSerie.VENDU and exemplaire.ticket_id == ticket_id:
            # Encaissement retransmis : déjà consigné, rien à refaire (ADR-004).
            vendus.append(exemplaire)
            continue

        exemplaire.etat = NumeroSerie.VENDU
        exemplaire.depot = depot
        exemplaire.vendu_le = vendu_le
        exemplaire.garantie_fin = echeance
        exemplaire.ticket_id = ticket_id
        exemplaire.ticket_numero = (ticket_numero or "")[:32]
        exemplaire.client = (client or "")[:180]
        exemplaire.save(
            update_fields=[
                "etat", "depot", "vendu_le", "garantie_fin",
                "ticket_id", "ticket_numero", "client", "modifie_le",
            ]
        )
        vendus.append(exemplaire)

    return vendus


# ---------------------------------------------------------------------------
# Consultation — dans le contexte de la boutique courante
# ---------------------------------------------------------------------------
def rechercher(numero: str):
    """Un exemplaire par son numéro, dans la boutique courante.

    C'est la porte du service après-vente : le client tend l'appareil, le
    commerçant tape ou scanne l'IMEI. Rien d'autre n'est demandé, parce que rien
    d'autre n'est connu à cet instant.
    """
    propre = normaliser(numero)
    if not propre:
        return None
    return (
        NumeroSerie.objects.filter(numero=propre)
        .select_related("variante__produit", "depot")
        .first()
    )


def exemplaires_de(variante, *, depot=None, etat=None):
    """Exemplaires connus d'un article, les plus récents d'abord."""
    lignes = NumeroSerie.objects.filter(variante=variante)
    if depot is not None:
        lignes = lignes.filter(depot=depot)
    if etat is not None:
        lignes = lignes.filter(etat=etat)
    return lignes.select_related("depot")


def en_atelier():
    """Appareils actuellement en réparation, le plus ancien dépôt d'abord.

    L'ordre n'est pas neutre : celui qui attend depuis le plus longtemps est
    celui dont le client rappelle.
    """
    return (
        NumeroSerie.objects.filter(etat=NumeroSerie.ATELIER)
        .select_related("variante__produit", "depot")
        .order_by("modifie_le")
    )


def vendus_recemment(limite: int = 50):
    return (
        NumeroSerie.objects.filter(etat=NumeroSerie.VENDU)
        .select_related("variante__produit")
        .order_by("-vendu_le")[:limite]
    )


def ecarts_de_numerotation(*, depot=None):
    """Ce que le stock compte, et ce que les numéros nomment.

    Un écart n'est pas une erreur à corriger de force : c'est une réception
    passée sans les numéros, et la seule chose utile à en faire est de la
    montrer. Tant qu'un exemplaire n'est pas nommé, il sortira du stock sans que
    personne puisse dire lequel est parti — et la garantie de celui-là ne sera
    opposable à rien.

    Renvoie une ligne par article en écart, jamais les articles à jour : une
    liste où tout va bien enseigne à ne plus la lire.
    """
    from apps.catalog.models import Variante

    suivies = Variante.objects.filter(actif=True, suivi_unitaire=True)
    niveaux = NiveauStock.objects.filter(variante__in=suivies)
    if depot is not None:
        niveaux = niveaux.filter(depot=depot)

    nommes: dict[tuple, int] = {}
    exemplaires = NumeroSerie.objects.filter(
        variante__in=suivies, etat=NumeroSerie.EN_STOCK
    ).values_list("variante_id", "depot_id")
    for variante_id, depot_id in exemplaires:
        nommes[(variante_id, depot_id)] = nommes.get((variante_id, depot_id), 0) + 1

    ecarts = []
    for niveau in niveaux.select_related("variante__produit", "depot"):
        compte = nommes.get((niveau.variante_id, niveau.depot_id), 0)
        manquants = int(niveau.quantite) - compte
        if manquants <= 0:
            continue
        ecarts.append(
            {
                "variante": niveau.variante,
                "depot": niveau.depot,
                "en_stock": niveau.quantite,
                "nommes": compte,
                "manquants": manquants,
            }
        )
    return sorted(ecarts, key=lambda e: -e["manquants"])


# ---------------------------------------------------------------------------
# Atelier
# ---------------------------------------------------------------------------
def entrer_a_l_atelier(exemplaire, *, motif: str, cree_par=None) -> PassageAtelier:
    """Dépose un appareil en réparation, et fige sa couverture."""
    motif = (motif or "").strip()[:255]
    if not motif:
        raise NumeroInvalide("Un passage à l'atelier sans motif ne se retrouve pas.")

    with contexte_boutique(exemplaire.boutique_id):
        return _entrer_a_l_atelier(exemplaire, motif=motif, cree_par=cree_par)


@transaction.atomic
def _entrer_a_l_atelier(exemplaire, *, motif, cree_par) -> PassageAtelier:
    ouvert = PassageAtelier.objects_all_tenants.filter(
        exemplaire=exemplaire, sorti_le__isnull=True
    ).first()
    if ouvert is not None:
        # Déjà à l'atelier : un second dépôt du même appareil est un double clic,
        # pas une seconde panne.
        return ouvert

    passage = PassageAtelier.objects_all_tenants.create(
        boutique_id=exemplaire.boutique_id,
        exemplaire=exemplaire,
        motif=motif,
        sous_garantie=exemplaire.sous_garantie(),
        cree_par=cree_par,
    )
    exemplaire.etat = NumeroSerie.ATELIER
    exemplaire.save(update_fields=["etat", "modifie_le"])
    return passage


def sortir_de_l_atelier(exemplaire, *, resultat: str = "") -> PassageAtelier | None:
    with contexte_boutique(exemplaire.boutique_id):
        return _sortir_de_l_atelier(exemplaire, resultat=resultat)


@transaction.atomic
def _sortir_de_l_atelier(exemplaire, *, resultat) -> PassageAtelier | None:
    passage = PassageAtelier.objects_all_tenants.filter(
        exemplaire=exemplaire, sorti_le__isnull=True
    ).first()
    if passage is None:
        return None

    passage.sorti_le = timezone.now()
    passage.resultat = (resultat or "").strip()[:255]
    passage.save(update_fields=["sorti_le", "resultat", "modifie_le"])

    # L'appareil retrouve l'état d'où il venait : rendu à son propriétaire s'il
    # avait été vendu, remis en rayon sinon. Le supposer vendu remettrait en
    # vente un appareil qui n'est plus à la boutique.
    exemplaire.etat = NumeroSerie.VENDU if exemplaire.vendu_le else NumeroSerie.EN_STOCK
    exemplaire.save(update_fields=["etat", "modifie_le"])
    return passage
