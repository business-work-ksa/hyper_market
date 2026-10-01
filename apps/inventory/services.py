"""Moteur de stock : mouvements et valorisation en coût moyen pondéré (CMP).

C'est la méthode de valorisation la plus courante en SYSCOHADA et la seule qui reste calculable
sans historique de lots — donc la seule tenable pour un commerçant qui reprend un stock existant
sans en connaître le coût d'acquisition ligne à ligne.

Règle du CMP :

    à chaque entrée :  cmp = (stock × cmp + qté_entrée × coût_entrée) / (stock + qté_entrée)
    à chaque sortie :  le CMP est inchangé ; seule la quantité diminue.

Le CMP obtenu après chaque mouvement est **historisé sur la ligne** (`cmp_apres`) : il ne pourra
jamais être recalculé a posteriori, y compris si un coût d'achat est corrigé plus tard.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import F

from apps.core.tenancy import contexte_boutique
from apps.inventory.models import (
    QUANTUM,
    QUANTUM_MONETAIRE,
    Depot,
    LigneInventaire,
    MouvementStock,
    NiveauStock,
)
from django.utils.translation import gettext as _

__all__ = [
    "MouvementInvalide",
    "cout_de_revient",
    "lots_a_surveiller",
    "enregistrer_mouvement",
    "entrer_stock",
    "produire",
    "production_du_jour",
    "sortir_stock",
    "transferer_stock",
    "regulariser_inventaire",
    "valeur_stock",
]


class MouvementInvalide(ValueError):
    """Mouvement refusé : quantité nulle, dépôt d'une autre boutique, coût négatif."""


def _niveau_verrouille(depot: Depot, variante) -> NiveauStock:
    """Récupère ou crée le niveau de stock, verrouillé pour la durée de la transaction.

    Le gestionnaire non filtré est utilisé volontairement : ce service est du code de confiance,
    qui connaît son tenant par le dépôt qu'on lui passe. Le filtrage par contexte est une
    protection destinée aux vues, pas aux services (docs/09, §3.2).
    """
    niveau = (
        NiveauStock.objects_all_tenants.select_for_update()
        .filter(boutique_id=depot.boutique_id, depot=depot, variante=variante)
        .first()
    )
    if niveau is None:
        niveau = NiveauStock.objects_all_tenants.create(
            boutique_id=depot.boutique_id, depot=depot, variante=variante
        )
        niveau = NiveauStock.objects_all_tenants.select_for_update().get(pk=niveau.pk)
    return niveau


def enregistrer_mouvement(*, depot: Depot, **arguments) -> MouvementStock:
    """Écrit un mouvement dans le contexte de la boutique du dépôt.

    Le contexte est établi **autour** de la transaction, pas dedans : un `SET`
    PostgreSQL est transactionnel, et le poser à l'intérieur d'un bloc qui peut
    échouer laisserait la restauration se heurter à une transaction en erreur
    (`apps/core/rls.py`).
    """
    with contexte_boutique(depot.boutique_id):
        return _enregistrer_mouvement(depot=depot, **arguments)


@transaction.atomic
def _enregistrer_mouvement(
    *,
    depot: Depot,
    variante,
    type_mouvement: str,
    quantite: Decimal,
    cout_unitaire: Decimal | None = None,
    origine_type: str = "",
    origine_id=None,
    operation_id=None,
    commentaire: str = "",
    cree_par=None,
    date_peremption=None,
    numero_lot: str = "",
) -> MouvementStock:
    """Corps de `enregistrer_mouvement` : mouvement écrit, niveau et CMP mis à jour.

    `quantite` est signée : positive pour une entrée, négative pour une sortie.

    `date_peremption` et `numero_lot` n'ont de sens que pour les métiers qui
    activent la fonction ; ailleurs ils restent vides et le suivi par lot est
    entièrement inerte (voir `_repercuter_sur_les_lots`).
    """
    quantite = Decimal(quantite).quantize(QUANTUM)
    if quantite == 0:
        raise MouvementInvalide(_("Un mouvement de quantité nulle n'a pas de sens."))

    if depot.boutique_id != variante.boutique_id:
        raise MouvementInvalide(
            _("Le dépôt et la variante appartiennent à des boutiques différentes.")
        )

    # Idempotence : une opération hors ligne retransmise ne doit pas dédoubler le mouvement.
    if operation_id is not None:
        existant = MouvementStock.objects_all_tenants.filter(
            operation_id=operation_id, depot=depot, variante=variante
        ).first()
        if existant is not None:
            return existant

    niveau = _niveau_verrouille(depot, variante)

    if quantite > 0:
        cout = Decimal(cout_unitaire if cout_unitaire is not None else niveau.cmp).quantize(QUANTUM)
        if cout < 0:
            raise MouvementInvalide(_("Le coût unitaire d'une entrée ne peut pas être négatif."))
        nouveau_cmp = _cmp_apres_entree(niveau.quantite, niveau.cmp, quantite, cout)
    else:
        # Une sortie ne modifie jamais le CMP : elle est valorisée au CMP courant.
        cout = niveau.cmp
        nouveau_cmp = niveau.cmp

    nouvelle_quantite = (niveau.quantite + quantite).quantize(QUANTUM)

    mouvement = MouvementStock(
        boutique_id=depot.boutique_id,
        depot=depot,
        variante=variante,
        type=type_mouvement,
        quantite=quantite,
        cout_unitaire=cout,
        cmp_apres=nouveau_cmp,
        quantite_apres=nouvelle_quantite,
        origine_type=origine_type,
        origine_id=origine_id,
        operation_id=operation_id,
        commentaire=commentaire,
        cree_par=cree_par,
    )
    mouvement.save()

    niveau.quantite = nouvelle_quantite
    niveau.cmp = nouveau_cmp
    niveau.version = F("version") + 1
    niveau.save(update_fields=["quantite", "cmp", "version", "modifie_le"])

    _repercuter_sur_les_lots(
        depot=depot,
        variante=variante,
        quantite=quantite,
        date_peremption=date_peremption,
        numero_lot=numero_lot,
    )
    return mouvement


def _repercuter_sur_les_lots(*, depot, variante, quantite, date_peremption, numero_lot) -> None:
    """Tient le suivi par lot, **là où il existe**.

    Ce mécanisme est inerte pour les métiers qui n'activent pas la péremption :
    aucune date n'est fournie à l'entrée, donc aucun lot n'est créé, et la sortie
    ne trouve rien à consommer. Une quincaillerie ne paie pas le coût de la
    fonction d'une pharmacie.

    Les sorties consomment en **PEPS par péremption** (premier périmé, premier
    sorti) : c'est ce que fait un commerçant qui range correctement son rayon, et
    c'est le seul ordre qui minimise la perte. L'ordre de réception, lui, n'a
    aucun intérêt ici — deux boîtes reçues le même jour peuvent périmer à six
    mois d'écart.

    Une sortie non couverte par les lots est possible et n'est pas une erreur :
    le stock peut être négatif (ADR-005), et un lot manquant signifie seulement
    qu'une entrée est passée sans date. La quantité restante sort du niveau
    global sans être imputée — refuser la vente serait pire.
    """
    from apps.inventory.models import LotStock

    if quantite > 0:
        if date_peremption is None:
            return
        lot, _cree = LotStock.objects_all_tenants.get_or_create(
            boutique_id=depot.boutique_id,
            depot=depot,
            variante=variante,
            numero=(numero_lot or "")[:64],
            date_peremption=date_peremption,
            defaults={"quantite": Decimal("0")},
        )
        LotStock.objects_all_tenants.filter(pk=lot.pk).update(quantite=F("quantite") + quantite)
        return

    reste = -quantite
    lots = (
        LotStock.objects_all_tenants.select_for_update()
        .filter(
            boutique_id=depot.boutique_id, depot=depot, variante=variante, quantite__gt=0
        )
        .order_by("date_peremption", "numero")
    )
    for lot in lots:
        if reste <= 0:
            break
        pris = min(lot.quantite, reste)
        LotStock.objects_all_tenants.filter(pk=lot.pk).update(quantite=F("quantite") - pris)
        reste -= pris


def _cmp_apres_entree(
    stock_avant: Decimal, cmp_avant: Decimal, quantite: Decimal, cout: Decimal
) -> Decimal:
    """Coût moyen pondéré après une entrée.

    Cas limite : si le stock avant est négatif ou nul, le CMP repart du coût de l'entrée. Pondérer
    par une quantité négative produirait un CMP aberrant, voire négatif.
    """
    total = stock_avant + quantite
    if stock_avant <= 0 or total <= 0:
        return cout.quantize(QUANTUM)
    valeur = stock_avant * cmp_avant + quantite * cout
    return (valeur / total).quantize(QUANTUM)


def entrer_stock(*, depot, variante, quantite, cout_unitaire, **kwargs) -> MouvementStock:
    """Réception fournisseur, retour client, ou reprise de stock à l'entrée dans les lieux."""
    return enregistrer_mouvement(
        depot=depot,
        variante=variante,
        type_mouvement=MouvementStock.ENTREE,
        quantite=abs(Decimal(quantite)),
        cout_unitaire=cout_unitaire,
        **kwargs,
    )


def sortir_stock(*, depot, variante, quantite, type_mouvement=None, **kwargs) -> MouvementStock:
    """Vente, perte ou casse. **Ne bloque pas sur stock insuffisant** (ADR-005)."""
    return enregistrer_mouvement(
        depot=depot,
        variante=variante,
        type_mouvement=type_mouvement or MouvementStock.SORTIE,
        quantite=-abs(Decimal(quantite)),
        **kwargs,
    )


def transferer_stock(*, depot_source, depot_cible, variante, quantite, **kwargs):
    """Transfert entre deux dépôts d'une même boutique.

    La marchandise sort au CMP du dépôt source et entre au même coût dans le dépôt cible : un
    transfert interne ne crée ni ne détruit de valeur.
    """
    with contexte_boutique(depot_source.boutique_id):
        return _transferer_stock(
            depot_source=depot_source,
            depot_cible=depot_cible,
            variante=variante,
            quantite=quantite,
            **kwargs,
        )


@transaction.atomic
def _transferer_stock(*, depot_source, depot_cible, variante, quantite, **kwargs):
    if depot_source.boutique_id != depot_cible.boutique_id:
        raise MouvementInvalide(_("Un transfert ne peut pas franchir la frontière d'une boutique."))
    if depot_source.pk == depot_cible.pk:
        raise MouvementInvalide(_("Les dépôts source et cible sont identiques."))

    niveau_source = _niveau_verrouille(depot_source, variante)
    cout = niveau_source.cmp

    sortie = enregistrer_mouvement(
        depot=depot_source,
        variante=variante,
        type_mouvement=MouvementStock.TRANSFERT,
        quantite=-abs(Decimal(quantite)),
        **kwargs,
    )
    entree = enregistrer_mouvement(
        depot=depot_cible,
        variante=variante,
        type_mouvement=MouvementStock.TRANSFERT,
        quantite=abs(Decimal(quantite)),
        cout_unitaire=cout,
        **kwargs,
    )
    return sortie, entree


def regulariser_inventaire(inventaire, *, cree_par=None) -> list[MouvementStock]:
    """Valide un inventaire : écrit un mouvement d'ajustement par ligne en écart."""
    with contexte_boutique(inventaire.boutique_id):
        return _regulariser_inventaire(inventaire, cree_par=cree_par)


@transaction.atomic
def _regulariser_inventaire(inventaire, *, cree_par=None) -> list[MouvementStock]:
    from django.utils import timezone

    from apps.inventory.models import Inventaire

    if inventaire.etat == Inventaire.VALIDE:
        raise MouvementInvalide(_("Cet inventaire est déjà validé."))

    mouvements = []
    lignes = LigneInventaire.objects_all_tenants.filter(inventaire=inventaire).select_related(
        "variante"
    )
    for ligne in lignes:
        if ligne.ecart == 0:
            continue
        mouvements.append(
            enregistrer_mouvement(
                depot=inventaire.depot,
                variante=ligne.variante,
                type_mouvement=MouvementStock.AJUSTEMENT,
                quantite=ligne.ecart,
                cout_unitaire=None,  # l'ajustement est valorisé au CMP courant
                origine_type="inventory.Inventaire",
                origine_id=inventaire.pk,
                commentaire=ligne.motif or "Régularisation d'inventaire",
                cree_par=cree_par,
            )
        )

    inventaire.etat = Inventaire.VALIDE
    inventaire.valide_le = timezone.now()
    inventaire.save(update_fields=["etat", "valide_le", "modifie_le"])
    return mouvements


# ---------------------------------------------------------------------------
# Production : fabriquer, c'est transformer du stock en stock
# ---------------------------------------------------------------------------
# Une fournée n'est ni une entrée ni une sortie : c'est les deux, et le lien
# entre les deux est ce qui donne son sens au coût de revient. La farine, le sel
# et la levure sortent ; les baguettes entrent — et elles entrent **exactement à
# ce que la farine, le sel et la levure ont coûté**. Aucune valeur n'est créée
# par la cuisson, aucune n'est perdue : c'est la règle comptable, et c'est aussi
# ce qu'un boulanger vérifie de tête.
#
# Rien n'est écrit sur la fiche technique au passage. Le coût de revient est
# porté par le mouvement (`cmp_apres`), comme tous les autres coûts du système :
# il devient un fait daté, et la fournée de mardi garde son coût même quand le
# sac de farine augmente mercredi.


def cout_de_revient(recette, *, depot) -> dict:
    """Ce que coûte une exécution complète de la fiche, aux CMP du jour.

    Renvoie le détail ligne à ligne **et** le total. Annoncer « 12 400 F » sans
    dire d'où ça sort n'aide personne : ce qu'un boulanger cherche quand son coût
    monte, c'est **quel ingrédient** a augmenté.

    Un ingrédient jamais entré en stock a un CMP nul. Il est compté pour zéro
    **et signalé** (`connu=False`) plutôt que passé sous silence : un coût de
    revient faussement bas est exactement ce qui fait fixer un prix de vente à
    perte.

    Lit dans le contexte de la boutique courante, comme `lots_a_surveiller` : la
    fonction est appelée depuis une vue, ou depuis `produire` qui a déjà établi
    le contexte.
    """
    from apps.catalog.models import LigneRecette

    lignes, total, complet = [], Decimal("0"), True
    requete = (
        LigneRecette.objects.filter(recette=recette)
        .select_related("ingredient__produit")
        .order_by("ingredient__produit__libelle")
    )
    niveaux = {
        niveau.variante_id: niveau
        for niveau in NiveauStock.objects.filter(
            depot=depot, variante__in=[ligne.ingredient_id for ligne in requete]
        )
    }
    for ligne in requete:
        niveau = niveaux.get(ligne.ingredient_id)
        connu = niveau is not None and niveau.cmp > 0
        cout = niveau.cmp if niveau is not None else Decimal("0")
        montant = (ligne.quantite * cout).quantize(QUANTUM_MONETAIRE)
        complet = complet and connu
        total += montant
        lignes.append(
            {
                "ligne": ligne,
                "cmp": cout,
                "montant": montant,
                "connu": connu,
                "disponible": niveau.quantite if niveau is not None else Decimal("0"),
            }
        )

    rendement = recette.rendement or Decimal("1")
    return {
        "lignes": lignes,
        "total": total.quantize(QUANTUM_MONETAIRE),
        "unitaire": (total / rendement).quantize(QUANTUM_MONETAIRE),
        "complet": complet,
    }


def produire(*, depot, recette, quantite, cree_par=None, **kwargs):
    """Fabrique `quantite` unités : sort les ingrédients, entre le produit fini."""
    with contexte_boutique(depot.boutique_id):
        return _produire(
            depot=depot, recette=recette, quantite=quantite, cree_par=cree_par, **kwargs
        )


@transaction.atomic
def _produire(*, depot, recette, quantite, cree_par=None, operation_id=None, commentaire=""):
    """Corps de `produire` : les sorties, puis l'entrée valorisée à leur somme.

    Le coût du produit fini n'est pas estimé, il est **constaté** : chaque sortie
    d'ingrédient est valorisée au CMP courant par le moteur de stock, et le
    produit fini entre à la somme de ces sorties. Recalculer le coût séparément
    aurait ouvert la porte à un écart entre ce qui est sorti et ce qui est entré
    — c'est-à-dire à de la valeur créée ou détruite par une erreur d'arrondi.

    Renvoie `(entrée, sorties)`.
    """
    from apps.catalog.models import LigneRecette

    quantite = Decimal(quantite).quantize(QUANTUM)
    if quantite <= 0:
        raise MouvementInvalide(_("Une production porte sur une quantité positive."))
    if not recette.actif:
        raise MouvementInvalide(_("Cette fiche technique est désactivée."))
    if recette.boutique_id != depot.boutique_id:
        raise MouvementInvalide(_("La fiche et le dépôt appartiennent à des boutiques différentes."))

    lignes = list(
        LigneRecette.objects_all_tenants.filter(
            boutique_id=depot.boutique_id, recette=recette
        ).select_related("ingredient")
    )
    if not lignes:
        raise MouvementInvalide(
            _("Cette fiche n'a aucun ingrédient : il n'y a rien à consommer, donc "
            "rien à produire.")
        )

    facteur = quantite / (recette.rendement or Decimal("1"))
    libelle = commentaire or f"Production {recette.variante}"

    sorties, cout_total = [], Decimal("0")
    for ligne in lignes:
        consommee = (ligne.quantite * facteur).quantize(QUANTUM)
        if consommee == 0:
            # Une fraction de fournée peut ramener un ingrédient de trace sous le
            # quantum. Rien ne sort, rien n'est compté : refuser la production
            # entière pour un dixième de gramme de levure serait absurde.
            continue
        sortie = enregistrer_mouvement(
            depot=depot,
            variante=ligne.ingredient,
            type_mouvement=MouvementStock.PRODUCTION,
            quantite=-consommee,
            origine_type="catalog.Recette",
            origine_id=recette.pk,
            commentaire=libelle,
            cree_par=cree_par,
        )
        sorties.append(sortie)
        cout_total += (sortie.cout_unitaire * consommee).quantize(QUANTUM_MONETAIRE)

    if not sorties:
        raise MouvementInvalide(
            _("La quantité demandée est trop faible pour consommer le moindre ingrédient.")
        )

    entree = enregistrer_mouvement(
        depot=depot,
        variante=recette.variante,
        type_mouvement=MouvementStock.PRODUCTION,
        quantite=quantite,
        cout_unitaire=(cout_total / quantite).quantize(QUANTUM),
        origine_type="catalog.Recette",
        origine_id=recette.pk,
        operation_id=operation_id,
        commentaire=libelle,
        cree_par=cree_par,
        # La date de péremption d'un produit fabriqué se calcule au moment où il
        # est fabriqué — c'est la seule date que le boulanger n'a pas à saisir,
        # et donc la seule qu'il ne peut pas se tromper en saisissant.
        date_peremption=_peremption_de(recette),
    )
    return entree, sorties


def _peremption_de(recette):
    from datetime import timedelta

    from django.utils import timezone

    if not recette.duree_conservation_jours:
        return None
    return timezone.localdate() + timedelta(days=recette.duree_conservation_jours)


def production_du_jour(*, depot=None, jour=None):
    """Ce qui est sorti du four aujourd'hui, pour la boutique courante.

    Seules les **entrées** de production sont renvoyées : les sorties
    d'ingrédients de la même fournée sont la contrepartie du même geste, et les
    afficher côte à côte ferait lire « 40 baguettes, 12 kg de farine » comme deux
    productions.
    """
    from django.utils import timezone

    jour = jour or timezone.localdate()
    mouvements = MouvementStock.objects.filter(
        type=MouvementStock.PRODUCTION, quantite__gt=0, cree_le__date=jour
    )
    if depot is not None:
        mouvements = mouvements.filter(depot=depot)
    return mouvements.select_related("variante__produit", "depot").order_by("-cree_le")


def lots_a_surveiller(*, depot=None, jours: int = 30):
    """Lots périmés ou sur le point de l'être, pour la boutique courante.

    Triés par date : le plus urgent d'abord, périmés compris. Les afficher
    ensemble est délibéré — un lot déjà périmé demande une action (retrait,
    destruction, retour), pas moins qu'un lot qui va périmer.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.inventory.models import LotStock

    limite = timezone.localdate() + timedelta(days=jours)
    lots = LotStock.objects.filter(quantite__gt=0, date_peremption__lte=limite)
    if depot is not None:
        lots = lots.filter(depot=depot)
    return lots.select_related("variante__produit", "depot").order_by("date_peremption")


def valeur_stock(depot=None) -> Decimal:
    """Valeur totale du stock au CMP, pour la boutique courante."""
    niveaux = NiveauStock.objects.all()
    if depot is not None:
        niveaux = niveaux.filter(depot=depot)
    total = sum((n.quantite * n.cmp for n in niveaux), Decimal("0"))
    return total.quantize(Decimal("0.01"))
