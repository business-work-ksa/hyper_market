"""Cycle de vie d'une commande en ligne.

Une commande en ligne n'est pas une vente au comptoir écrite autrement. Trois
différences de fond gouvernent tout ce module.

**Un panier traverse les boutiques.** L'acheteur voit une commande et paie une
fois ; chaque marchand ne gère que sa part. D'où l'éclatement en `SousCommande`,
qui est l'unité de travail du marchand et l'assiette de tout le reste —
comptabilité, commission de place, affiliation.

**L'argent n'arrive pas chez le marchand.** Il arrive sur le séquestre de la
plateforme, qui reversera net de sa commission. Le marchand voit donc une
créance, pas de la trésorerie (docs/07, §3.2).

**Le temps s'écoule entre la commande et la livraison.** Au comptoir, tout est
simultané : le client paie, prend sa marchandise, s'en va. En ligne, une
commande est acceptée, préparée, expédiée, livrée — et peut être refusée à
chaque étape. Chacune de ces étapes déclenche des effets différents, et les
mettre au mauvais moment produit des comptes faux.

Où tombent les effets, et pourquoi
----------------------------------

| Étape | Effet |
|---|---|
| Commande | Éclatement, taux de commission figé, attribution d'affiliation figée |
| Paiement | Écritures de vente, séquestre et commission ; commissions d'affiliation calculées (à l'état *attendue*) ; **séquestre ouvert, part nette au bloqué** — pour les parts prépayées seulement |
| Expédition | **Sortie de stock au CMP**, et son écriture ; départ du délai de confirmation implicite |
| Livraison | Démarrage du délai de retour, au terme duquel les commissions s'acquièrent. **Déclarée par le marchand, elle ne libère rien** : seule la livraison *confirmée* par l'acheteur ouvre le délai de libération (`apps/payments/sequestre.py`) |

**Le stock sort à l'expédition, pas à la commande.** C'est le choix le plus
discutable du module, et il est assumé : réserver le stock dès la commande le
rendrait indisponible au comptoir alors que rien n'est parti, et une réservation
jamais libérée est un stock fantôme que personne ne retrouve. Le prix de ce
choix est la survente — le comptoir peut vendre le dernier article avant que la
commande ne soit préparée. Le marchand refuse alors la sous-commande, ce qui est
un geste explicite plutôt qu'un compteur silencieusement faux (ADR-005).
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.affiliation.models import Apporteur, Attribution
from apps.affiliation.services import (
    annuler_commissions,
    attribuer,
    calculer_commissions,
    resoudre_apporteurs,
)
from apps.core.tenancy import contexte_boutique, contexte_plateforme
from apps.inventory.models import Depot, MouvementStock
from apps.inventory.services import entrer_stock, sortir_stock
from apps.marketplace.models import Bail
from apps.orders.models import CENTIME, Commande, LigneCommande, Retour, SousCommande

__all__ = [
    "CommandeInvalide",
    "PrepaiementRefuse",
    "passer_commande",
    "marquer_payee",
    "accepter",
    "preparer",
    "expedier",
    "livrer",
    "annuler_sous_commande",
    "demander_retour",
    "accepter_retour",
]


class CommandeInvalide(ValueError):
    """Commande refusée : panier vide, transition impossible, boutique inactive."""


class PrepaiementRefuse(CommandeInvalide):
    """Le prépaiement dépasserait le plafond de séquestre d'une ou plusieurs boutiques.

    `refus` associe à chaque boutique refusée le message à montrer à l'acheteur. La vitrine
    propose alors le paiement à la livraison pour ces boutiques-là, et pour elles seules.
    """

    def __init__(self, refus: dict):
        self.refus = refus
        super().__init__(" ".join(refus.values()))


# ---------------------------------------------------------------------------
# Passer une commande
# ---------------------------------------------------------------------------
def passer_commande(
    *,
    acheteur,
    lignes,
    code_apporteur: str = "",
    revendeur=None,
    frais_livraison: Decimal = Decimal("0"),
    operation_id=None,
    mode_paiement: str = SousCommande.PREPAYE,
    a_la_livraison=(),
) -> Commande:
    """Crée une commande confirmée, éclatée en sous-commandes par boutique.

    `mode_paiement` vaut pour toute la commande ; `a_la_livraison` nomme les boutiques chez qui
    l'acheteur paiera à la livraison malgré tout — celles dont le plafond de séquestre refuse le
    prépaiement. Pour chaque part prépayée, le plafond du palier est vérifié : s'il serait dépassé,
    **rien n'est créé** et `PrepaiementRefuse` dit chez qui. Refuser en silence et basculer la part
    au paiement à la livraison changerait ce que l'acheteur a accepté sans le lui dire.

    `lignes` est une suite de `(variante, quantite)` pouvant couvrir plusieurs
    boutiques. Chaque variante porte sa boutique : c'est elle qui décide de la
    sous-commande à laquelle la ligne se rattache, jamais un paramètre.

    Idempotent par `operation_id` : un double clic sur « Commander » ne crée pas
    deux commandes. Comme partout ailleurs, c'est la contrainte d'unicité qui
    arbitre et non la lecture préalable (ADR-004).
    """
    lignes = list(lignes)
    if not lignes:
        raise CommandeInvalide("Un panier vide ne se commande pas.")

    if operation_id is not None:
        existante = Commande.objects.filter(operation_id=operation_id).first()
        if existante is not None:
            return existante

    try:
        with transaction.atomic():
            return _passer_commande(
                acheteur=acheteur,
                lignes=lignes,
                code_apporteur=code_apporteur,
                revendeur=revendeur,
                frais_livraison=Decimal(frais_livraison),
                operation_id=operation_id,
                mode_paiement=mode_paiement,
                a_la_livraison={str(b) for b in a_la_livraison},
            )
    except IntegrityError:
        # Course perdue sur la clé d'idempotence : l'autre appel a inséré, sa
        # commande fait foi. Toute autre violation d'unicité — un numéro de
        # commande attribué deux fois, par exemple — reste une erreur.
        if operation_id is not None:
            existante = Commande.objects.filter(operation_id=operation_id).first()
            if existante is not None:
                return existante
        raise


def _passer_commande(
    *,
    acheteur,
    lignes,
    code_apporteur,
    revendeur,
    frais_livraison,
    operation_id,
    mode_paiement,
    a_la_livraison,
) -> Commande:
    if mode_paiement not in dict(SousCommande.MODES_PAIEMENT):
        raise CommandeInvalide("Mode de paiement inconnu.")
    n1, n2 = _attribuer_et_resoudre(acheteur, code_apporteur)

    commande = Commande.objects.create(
        numero=Commande.numero_suivant(),
        acheteur=acheteur,
        frais_livraison=frais_livraison,
        etat=Commande.CONFIRMEE,
        code_apporteur=code_apporteur or "",
        apporteur_n1=n1,
        apporteur_n2=n2,
        revendeur=revendeur,
        operation_id=operation_id,
        cree_par=acheteur,
    )

    par_boutique: dict = {}
    for variante, quantite in lignes:
        par_boutique.setdefault(variante.boutique_id, []).append((variante, Decimal(quantite)))

    parts = []
    for boutique_id, articles in par_boutique.items():
        mode = (
            SousCommande.A_LA_LIVRAISON
            if mode_paiement == SousCommande.A_LA_LIVRAISON or str(boutique_id) in a_la_livraison
            else SousCommande.PREPAYE
        )
        parts.append(_creer_sous_commande(commande, boutique_id, articles, mode))

    _verifier_les_plafonds(parts)
    _recalculer_commande(commande)
    return commande


def _verifier_les_plafonds(parts) -> None:
    """Refuse la commande si une part prépayée ferait dépasser le plafond de sa boutique.

    Le plafond borne ce qu'une boutique qui n'a encore rien prouvé peut avoir **en séquestre à la
    fois** (`apps/marketplace/confiance.py`) : c'est lui qui rend l'escroquerie à la fausse
    boutique non rentable. Il est lu sur les séquestres encore bloqués, au moment de commander.

    Limite connue et assumée : deux commandes passées au même instant, non encore payées, ne se
    voient pas l'une l'autre — le séquestre ne naît qu'au paiement. Le dépassement possible reste
    de l'argent **bloqué**, pas de l'argent parti.
    """
    from apps.marketplace.models import Boutique
    from apps.payments.sequestre import refus_de_prepaiement

    refus = {}
    for part in parts:
        if part.mode_paiement != SousCommande.PREPAYE:
            continue
        boutique = Boutique.objects.get(pk=part.boutique_id)
        message = refus_de_prepaiement(boutique, part.total_ttc)
        if message:
            refus[str(part.boutique_id)] = message
    if refus:
        raise PrepaiementRefuse(refus)


def _creer_sous_commande(commande, boutique_id, articles, mode_paiement) -> SousCommande:
    """Part d'une boutique, avec son taux de commission **figé**.

    Le taux est recopié du bail au moment de la commande, et ne bouge plus. Une
    renégociation de bail ne doit pas changer rétroactivement ce que la
    plateforme a prélevé sur des commandes déjà passées — sinon la comptabilité
    du marchand et celle de la plateforme divergent sur des mois clos.
    """
    with contexte_boutique(boutique_id):
        sous_commande = SousCommande.objects.create(
            boutique_id=boutique_id,
            commande=commande,
            taux_commission=_taux_de_commission(boutique_id),
            mode_paiement=mode_paiement,
        )
        for variante, quantite in articles:
            LigneCommande.objects.create(
                boutique_id=boutique_id,
                sous_commande=sous_commande,
                variante=variante,
                libelle=str(variante),
                quantite=quantite,
                pu_ttc=variante.prix_vente,
                taux_tva=variante.taux_tva,
            )
        sous_commande.recalculer()
    return sous_commande


def _taux_de_commission(boutique_id) -> Decimal:
    """Taux du bail actif ; à défaut, celui du rayon principal de la boutique.

    Le repli n'est pas une commodité : une boutique sans bail actif est une
    anomalie d'exploitation, et prélever zéro serait un cadeau silencieux. Le
    taux du rayon est la valeur par défaut du contrat.
    """
    with contexte_plateforme():
        bail = (
            Bail.objects.filter(boutique_id=boutique_id, etat=Bail.ACTIF)
            .order_by("-debut")
            .first()
        )
        if bail is not None:
            return bail.taux_commission

        from apps.marketplace.models import Boutique

        boutique = Boutique.objects.filter(pk=boutique_id).select_related("rayon_principal").first()
        return boutique.rayon_principal.taux_commission if boutique else Decimal("0")


def _attribuer_et_resoudre(acheteur, code_apporteur):
    """Fige l'attribution d'affiliation sur l'acheteur, puis lit N1 et N2.

    Un code présenté au moment de la commande crée l'attribution s'il n'en existe
    pas. S'il en existe une, **elle n'est pas écrasée** : le rattachement est
    définitif, c'est la protection contre le vol d'attribution (docs/06, §6).
    """
    if code_apporteur:
        apporteur = Apporteur.objects.filter(
            code=code_apporteur, etat=Apporteur.ACTIF
        ).first()
        if apporteur is not None:
            attribuer(
                apporteur=apporteur,
                cible_type=Attribution.ACHETEUR,
                cible_id=acheteur.pk,
                origine=Attribution.CODE,
                preuve={"code": code_apporteur},
            )
    return resoudre_apporteurs(acheteur)


def _recalculer_commande(commande) -> None:
    with contexte_plateforme():
        parts = list(SousCommande.objects.filter(commande=commande))
    commande.total_ht = sum((p.total_ht for p in parts), Decimal("0")).quantize(CENTIME)
    commande.total_tva = sum((p.total_tva for p in parts), Decimal("0")).quantize(CENTIME)
    commande.total_ttc = (
        sum((p.total_ttc for p in parts), Decimal("0")) + commande.frais_livraison
    ).quantize(CENTIME)
    commande.save(update_fields=["total_ht", "total_tva", "total_ttc", "modifie_le"])


# ---------------------------------------------------------------------------
# Paiement
# ---------------------------------------------------------------------------
def marquer_payee(commande, *, date_ecriture=None) -> Commande:
    """Constate l'encaissement : écritures par boutique, commissions calculées, séquestre ouvert.

    Idempotent : une notification d'opérateur reçue deux fois ne comptabilise pas
    la vente deux fois. C'est la même règle que pour les transactions de
    paiement — les notifications arrivent en double et en désordre. Deux
    notifications **simultanées** ne passent pas non plus toutes les deux : la
    commande est verrouillée le temps du constat.

    Les commissions d'affiliation naissent ici, à l'état *attendue*, parce que
    l'invariant 3 du document 06 exige du **chiffre d'affaires encaissé**. Elles
    ne s'acquerront qu'après la livraison et l'expiration du délai de retour.

    **Seules les parts prépayées sont concernées.** Une part payée à la livraison
    n'a rien encaissé au moment où l'acheteur paie le reste du panier : l'argent
    passe de sa main à celle du livreur, jamais par la plateforme. Chaque part
    prépayée ouvre son séquestre, part nette de commission au `solde_bloque` de
    son marchand — la plateforme constate, elle ne détient pas (docs/08, §5).
    """
    from apps.accounting.services import comptabiliser_vente_en_ligne
    from apps.payments.sequestre import ouvrir_sequestre

    origine = commande
    with transaction.atomic():
        commande = Commande.objects.select_for_update().get(pk=commande.pk)
        if commande.etat == Commande.PAYEE:
            origine.etat = commande.etat
            return origine
        if commande.etat != Commande.CONFIRMEE:
            raise CommandeInvalide(
                f"Une commande {commande.get_etat_display().lower()} ne peut pas être payée."
            )

        with contexte_plateforme():
            parts = list(
                SousCommande.objects.filter(commande=commande, mode_paiement=SousCommande.PREPAYE)
            )
        if not parts:
            raise CommandeInvalide(
                "Cette commande se paie entièrement à la livraison : il n'y a rien à constater."
            )

        for sous_commande in parts:
            comptabiliser_vente_en_ligne(sous_commande, date_ecriture=date_ecriture)
            # `calculer_commissions` lit les lignes de la sous-commande pour la part
            # revendeur : sans contexte, la barrière 3 ne lui montrerait rien et la
            # commission serait silencieusement nulle.
            with contexte_boutique(sous_commande.boutique_id):
                calculer_commissions(sous_commande)
            if sous_commande.etat != SousCommande.ANNULEE:
                ouvrir_sequestre(sous_commande)

        commande.etat = Commande.PAYEE
        commande.save(update_fields=["etat", "modifie_le"])
    # L'appelant garde son objet : il doit voir l'état qu'il vient de provoquer.
    origine.etat = commande.etat
    return origine


# ---------------------------------------------------------------------------
# Traitement par le marchand
# ---------------------------------------------------------------------------
# Une sous-commande avance, ou s'annule. Elle ne revient jamais en arrière : un
# état déjà atteint a produit des effets — une sortie de stock, une écriture —
# que reculer ne défait pas.
SUITES = {
    SousCommande.EN_ATTENTE: {SousCommande.ACCEPTEE, SousCommande.ANNULEE},
    SousCommande.ACCEPTEE: {SousCommande.PREPAREE, SousCommande.ANNULEE},
    SousCommande.PREPAREE: {SousCommande.EXPEDIEE, SousCommande.ANNULEE},
    SousCommande.EXPEDIEE: {SousCommande.LIVREE},
    SousCommande.LIVREE: set(),
    SousCommande.ANNULEE: set(),
}


def _avancer(sous_commande, etat: str, **champs) -> SousCommande:
    """Change l'état, en annonçant sa boutique à la base.

    Le contexte n'est pas une précaution de style : sous la barrière 3, un
    `UPDATE` émis hors contexte ne lève aucune erreur — il touche zéro ligne.
    Une transition qu'on croit appliquée et qui ne l'est pas est bien pire qu'un
    refus.
    """
    if etat not in SUITES[sous_commande.etat]:
        raise CommandeInvalide(
            f"Une sous-commande {sous_commande.get_etat_display().lower()} "
            f"ne peut pas passer à « {etat} »."
        )
    sous_commande.etat = etat
    for nom, valeur in champs.items():
        setattr(sous_commande, nom, valeur)
    with contexte_boutique(sous_commande.boutique_id):
        sous_commande.save(update_fields=["etat", *champs, "modifie_le"])
    return sous_commande


def accepter(sous_commande) -> SousCommande:
    """Le marchand s'engage à servir sa part. Aucun effet de stock à ce stade."""
    return _avancer(sous_commande, SousCommande.ACCEPTEE)


def preparer(sous_commande) -> SousCommande:
    return _avancer(sous_commande, SousCommande.PREPAREE)


def expedier(sous_commande, *, depot: Depot | None = None, cree_par=None) -> SousCommande:
    """Sort la marchandise du dépôt et écrit la sortie de stock.

    C'est ici que le stock bouge — voir l'en-tête du module. La sortie est
    idempotente par `operation_id` : une expédition confirmée deux fois ne
    déstocke pas deux fois.
    """
    from apps.accounting.services import comptabiliser_expedition

    with contexte_boutique(sous_commande.boutique_id):
        depot = depot or _depot_d_expedition()
        if depot is None:
            raise CommandeInvalide("Cette boutique n'a aucun dépôt actif pour expédier.")

        deja_sorti = MouvementStock.objects_all_tenants.filter(
            origine_type="orders.SousCommande", origine_id=sous_commande.pk
        ).exists()

        if not deja_sorti:
            lignes = list(
                LigneCommande.objects.filter(sous_commande=sous_commande).select_related("variante")
            )
            for ligne in lignes:
                sortir_stock(
                    depot=depot,
                    variante=ligne.variante,
                    quantite=ligne.quantite,
                    origine_type="orders.SousCommande",
                    origine_id=sous_commande.pk,
                    operation_id=None,
                    commentaire=f"Expédition {sous_commande.commande.numero}",
                    cree_par=cree_par,
                )

    # La date d'expédition fait partir le délai de confirmation implicite : sept jours sans
    # confirmation ni litige, et la livraison est réputée confirmée.
    _avancer(sous_commande, SousCommande.EXPEDIEE, expediee_le=timezone.now())
    if not deja_sorti:
        comptabiliser_expedition(sous_commande)
    return sous_commande


def _depot_d_expedition() -> Depot | None:
    """Dépôt principal de la boutique **courante** — l'appelant a posé le contexte."""
    return (
        Depot.objects.filter(actif=True, principal=True).first()
        or Depot.objects.filter(actif=True).first()
    )


def livrer(sous_commande, *, maintenant=None) -> SousCommande:
    """Marchandise remise. Démarre le délai de retour, pas l'acquisition.

    Rien n'est acquis à la livraison : c'est pendant le délai de retour qu'une
    commande fictive se révèle. `acquerir_commissions` refusera tant que le délai
    court (docs/06, invariant 3).
    """
    maintenant = maintenant or timezone.now()
    _avancer(sous_commande, SousCommande.LIVREE, livree_le=maintenant)
    if sous_commande.mode_paiement == SousCommande.A_LA_LIVRAISON:
        _constater_paiement_a_la_livraison(sous_commande, maintenant)
    _propager_l_etat_de_la_commande(sous_commande.commande, maintenant=maintenant)
    return sous_commande


def _constater_paiement_a_la_livraison(sous_commande, maintenant) -> None:
    """Une part payée à la livraison est encaissée quand elle est remise : c'est là que naissent
    sa vente dans les livres et les commissions d'affiliation — sur du chiffre d'affaires encaissé,
    comme l'exige l'invariant 3 du document 06.

    Un échec comptable ne bloque pas la livraison : la marchandise est chez l'acheteur, et le
    refuser ici ne la ferait pas revenir. Il est journalisé pour le comptable.
    """
    import logging

    from apps.accounting.services import EcritureInvalide, comptabiliser_vente_a_la_livraison

    try:
        with transaction.atomic():
            comptabiliser_vente_a_la_livraison(sous_commande, date_ecriture=timezone.localdate(maintenant))
    except EcritureInvalide as erreur:
        logging.getLogger(__name__).error(
            "Vente à la livraison %s : écritures non passées (%s).", sous_commande.pk, erreur
        )
    with contexte_boutique(sous_commande.boutique_id):
        calculer_commissions(sous_commande)


def _propager_l_etat_de_la_commande(commande, *, maintenant) -> None:
    """La commande suit ses parts : livrée quand toutes le sont ou sont annulées.

    Une commande dont toutes les parts sont annulées est annulée, pas livrée —
    sinon une commande entièrement refusée déclencherait l'acquisition de
    commissions sur du chiffre d'affaires qui n'existe pas.
    """
    with contexte_plateforme():
        etats = set(
            SousCommande.objects.filter(commande=commande).values_list("etat", flat=True)
        )

    if etats <= {SousCommande.ANNULEE}:
        commande.etat = Commande.ANNULEE
        commande.save(update_fields=["etat", "modifie_le"])
        return

    if etats <= {SousCommande.LIVREE, SousCommande.ANNULEE}:
        commande.etat = Commande.LIVREE
        commande.livree_le = maintenant
        commande.save(update_fields=["etat", "livree_le", "modifie_le"])


# ---------------------------------------------------------------------------
# Annulation et retours
# ---------------------------------------------------------------------------
def annuler_sous_commande(sous_commande, *, motif: str = "", cree_par=None) -> SousCommande:
    """Refus du marchand, **avant expédition seulement**.

    Une sous-commande expédiée ne s'annule pas : la marchandise est partie, et le
    chemin qui la fait revenir est le retour, pas l'annulation. C'est pour cela
    qu'aucune réintégration de stock n'a lieu ici — **rien n'est encore sorti du
    dépôt**, la sortie ayant lieu à l'expédition. Réintégrer « au cas où »
    donnerait à ce code l'apparence de couvrir un cas qu'il ne rencontre jamais.

    Les commissions, elles, existent déjà : elles naissent au paiement. Il faut
    donc les annuler.

    Une part prépayée dont le séquestre est ouvert est **remboursée en entier** :
    le marchand refuse de servir, l'acheteur récupère ce qu'il a payé. Un litige
    en cours bloque le refus — c'est alors à la plateforme de trancher, pas au
    marchand de clore le dossier à sa façon.
    """
    from apps.payments.sequestre import MESSAGE_GEL, SequestreRefuse, rembourser

    sequestre = _sequestre_bloque(sous_commande)
    if sequestre is not None and _litige_en_cours(sous_commande):
        # Message neutre, identique à tous les gels : le marchand ne doit pas apprendre
        # d'ici qu'une vérification le vise (`apps/payments/sequestre.py`, MESSAGE_GEL).
        raise CommandeInvalide(MESSAGE_GEL)
    # Le refus et le remboursement vont ensemble, ou pas du tout : une part annulée dont
    # l'argent resterait bloqué serait de l'argent que plus personne ne réclame.
    with transaction.atomic():
        _avancer(sous_commande, SousCommande.ANNULEE)
        if sequestre is not None:
            try:
                rembourser(
                    sequestre,
                    motif=f"Commande refusée par le marchand{' : ' + motif if motif else ''}",
                )
            except SequestreRefuse as refus:
                raise CommandeInvalide(str(refus)) from None
        annuler_commissions(sous_commande, motif=motif)
    _propager_l_etat_de_la_commande(sous_commande.commande, maintenant=timezone.now())
    return sous_commande


def demander_retour(sous_commande, *, motif: str) -> Retour:
    if sous_commande.etat not in (SousCommande.EXPEDIEE, SousCommande.LIVREE):
        raise CommandeInvalide("On ne retourne que ce qui a été expédié.")
    with contexte_boutique(sous_commande.boutique_id):
        return Retour.objects.create(
            boutique_id=sous_commande.boutique_id, sous_commande=sous_commande, motif=motif
        )


def accepter_retour(retour, *, montant_rembourse=None, cree_par=None) -> Retour:
    """Accepte un retour : réintègre le stock et annule les commissions.

    Les commissions déjà **payées** ne sont pas annulées mais *reprises* sur les
    gains futurs du bénéficiaire — on ne récupère pas de l'argent versé, on le
    déduit du prochain versement (docs/06, §4.2). `annuler_commissions` s'en
    charge.
    """
    if retour.etat != Retour.DEMANDE:
        raise CommandeInvalide("Ce retour a déjà été tranché.")

    from apps.payments.sequestre import MESSAGE_GEL

    sous_commande = retour.sous_commande
    sequestre = _sequestre_bloque(sous_commande)
    if sequestre is not None and _litige_en_cours(sous_commande):
        # Message neutre, identique à tous les gels : le marchand ne doit pas apprendre
        # d'ici qu'une vérification le vise (`apps/payments/sequestre.py`, MESSAGE_GEL).
        raise CommandeInvalide(MESSAGE_GEL)
    retour.etat = Retour.ACCEPTE
    retour.montant_rembourse = (
        Decimal(montant_rembourse) if montant_rembourse is not None else sous_commande.total_ttc
    )
    with transaction.atomic():
        with contexte_boutique(retour.boutique_id):
            retour.save(update_fields=["etat", "montant_rembourse", "modifie_le"])

        _reintegrer_le_stock(sous_commande, motif=f"Retour {retour.pk}", cree_par=cree_par)
        annuler_commissions(sous_commande, motif="Retour accepté")
        if sequestre is not None:
            _rembourser_le_retour(sequestre, retour)
    return retour


def _rembourser_le_retour(sequestre, retour) -> None:
    """Un retour accepté pendant que l'argent est encore en séquestre : il en sort pour l'acheteur.

    Le montant du retour dit ce que l'acheteur récupère. Tout le TTC : remboursement total,
    commission de place annulée. Moins : prélevé sur la part du marchand, le reste libéré — sans
    attendre le délai du palier, puisque le litige possible a trouvé sa réponse. Au-delà de la
    part nette du marchand sans aller jusqu'au total, le partage n'a pas de sens : on refuse
    plutôt que de faire payer à la plateforme un retour qu'elle n'a pas décidé.

    Une part déjà libérée ne se rembourse plus par le séquestre : l'argent est au marchand, et le
    remboursement se règle entre lui et l'acheteur.
    """
    from apps.payments.sequestre import SequestreRefuse, rembourser

    rendu = Decimal(retour.montant_rembourse).quantize(CENTIME)
    motif = f"Retour accepté : {retour.motif}"[:250]
    try:
        if rendu >= sequestre.montant_encaisse:
            rembourser(sequestre, motif=motif)
        elif rendu > 0:
            rembourser(sequestre, montant_marchand=rendu, motif=motif)
    except SequestreRefuse as refus:
        raise CommandeInvalide(str(refus)) from None


def _sequestre_bloque(sous_commande):
    from apps.payments.models import Sequestre

    return Sequestre.objects.filter(
        sous_commande=sous_commande, etat=Sequestre.BLOQUE
    ).first()


def _litige_en_cours(sous_commande) -> bool:
    from apps.orders.models import Litige

    with contexte_boutique(sous_commande.boutique_id):
        return Litige.objects.filter(
            sous_commande=sous_commande, etat__in=Litige.ETATS_OUVERTS
        ).exists()


def _reintegrer_le_stock(sous_commande, *, motif: str, cree_par=None) -> None:
    """Fait rentrer ce qui était sorti, au coût auquel c'était sorti.

    Au coût de sortie et non au CMP courant : la marchandise revient telle
    qu'elle est partie, et la valoriser autrement inventerait une plus-value ou
    une perte que rien n'a produite.
    """
    with contexte_boutique(sous_commande.boutique_id):
        sorties = list(
            MouvementStock.objects_all_tenants.filter(
                boutique_id=sous_commande.boutique_id,
                origine_type="orders.SousCommande",
                origine_id=sous_commande.pk,
                quantite__lt=0,
            ).select_related("variante", "depot")
        )
        rentrees = {
            (m.variante_id, m.depot_id)
            for m in MouvementStock.objects_all_tenants.filter(
                boutique_id=sous_commande.boutique_id,
                origine_type="orders.SousCommande.retour",
                origine_id=sous_commande.pk,
            )
        }

        for sortie in sorties:
            if (sortie.variante_id, sortie.depot_id) in rentrees:
                continue  # déjà réintégré : ne pas doubler
            entrer_stock(
                depot=sortie.depot,
                variante=sortie.variante,
                quantite=abs(sortie.quantite),
                cout_unitaire=sortie.cout_unitaire,
                origine_type="orders.SousCommande.retour",
                origine_id=sous_commande.pk,
                commentaire=motif,
                cree_par=cree_par,
            )
