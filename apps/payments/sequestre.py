"""Le séquestre : l'argent de l'acheteur attend la livraison confirmée, puis va où il doit.

Une fausse boutique vit d'un seul geste : encaisser des commandes prépayées, puis disparaître avant
les livraisons (`apps/marketplace/confiance.py`). Ce module est ce qui rend ce geste inutile.
L'argent d'une commande prépayée n'arrive jamais chez le marchand au paiement : la plateforme
**constate** qu'il est cantonné chez son partenaire agréé, et n'**ordonne** sa libération qu'une
fois la remise prouvée par l'acheteur. La plateforme ne détient rien (docs/08, §5) ; elle tient
le registre des ordres, et ce registre ne ment pas.

Le cycle d'une part, en six temps
---------------------------------

1. **Paiement constaté** (`ouvrir_sequestre`, appelé par `marquer_payee`) : séquestre BLOQUÉ, part
   nette de commission au `solde_bloque` du marchand.
2. **Expédition déclarée** par le marchand : rien ne bouge. Une déclaration n'est pas une preuve.
3. **Livraison confirmée** — par le code de remise que l'acheteur donne au livreur et que le
   marchand saisit, par l'acheteur lui-même sur sa page de commande, ou, sans nouvelle de
   l'acheteur ni litige sept jours après l'expédition, **réputée** confirmée.
4. **Libération** au terme du délai du palier (`liberer`, par `liberer_sequestres`) : la part
   quitte le bloqué pour le disponible.
5. **Litige** (`ouvrir_litige`) : la part est gelée — ni libérée, ni remboursée — jusqu'à la
   décision motivée de la plateforme (`trancher_litige`).
6. **Versement** (`apps/payments/versements.py`) : le disponible part vers le compte vérifié de la
   boutique.

Deux règles transverses
-----------------------

**Chaque transition verrouille le séquestre et revérifie son état.** Les notifications
d'opérateur arrivent en double, la commande de libération peut tourner deux fois, un
administrateur peut cliquer pendant qu'elle tourne. Sans verrou, deux chemins liraient « bloqué »
et libéreraient deux fois.

**Aucun chemin ne crée ni ne détruit d'argent.** Pour chaque boutique :
`bloqué + disponible + versé + remboursé = encaissé net`. `bilan()` le calcule, les tests le
vérifient après chaque scénario.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.core.tenancy import contexte_boutique, contexte_plateforme
from apps.marketplace.confiance import palier_de
from apps.payments.models import CENTIME, MouvementPortefeuille, Sequestre
from apps.payments.services import mouvementer_portefeuille

journal = logging.getLogger(__name__)

__all__ = [
    "DELAI_CONFIRMATION_IMPLICITE",
    "MESSAGE_GEL",
    "ESSAIS_CODE_MAX",
    "SequestreRefuse",
    "CodeIncorrect",
    "CodeVerrouille",
    "commission_ttc",
    "code_de_remise",
    "montant_en_sequestre",
    "refus_de_prepaiement",
    "ouvrir_sequestre",
    "confirmer_par_code",
    "confirmer_par_acheteur",
    "liberer",
    "liberer_echus",
    "rembourser",
    "ouvrir_litige",
    "prendre_en_instruction",
    "trancher_litige",
    "bilan",
]

# Sans confirmation ni litige sept jours après l'expédition déclarée, la livraison est réputée
# confirmée. Sept jours, c'est le temps qu'une livraison à Douala ou Yaoundé arrive, et qu'un
# acheteur qui n'a rien reçu s'en inquiète ; c'est aussi, au palier 0, une semaine de plus avant
# la libération — quatorze jours en tout pour réclamer.
DELAI_CONFIRMATION_IMPLICITE = timedelta(days=7)

# Cinq essais, puis le code est verrouillé **définitivement**. Pas de fenêtre qui se rouvre, comme
# pour les mots de passe (`apps/accounts/limitation.py`) : un code à six chiffres, c'est un million
# de possibilités, et un marchand malhonnête a sept jours devant lui — une fenêtre glissante lui
# laisserait des centaines d'essais. Le verrou ne coûte presque rien à un marchand honnête :
# l'acheteur peut toujours confirmer lui-même, et la confirmation implicite reste acquise.
ESSAIS_CODE_MAX = 5

# Ce que voit le **marchand** d'une part gelée, quelle qu'en soit la raison — litige d'un acheteur,
# décision en cours, contrôle de la plateforme. Un message neutre et toujours identique : le
# dispositif de lutte contre le blanchiment interdit d'avertir la personne visée par une
# vérification, et un message qui dirait « litige » ici et « contrôle » là en dirait déjà trop.
# Le détail n'est lisible que dans la console, sous motif et avec une trace.
MESSAGE_GEL = "Fonds retenus en attente d'une vérification."

# Les états d'une part où une livraison peut avoir eu lieu.
_ETATS_LIVRABLES = ("expediee", "livree")


class SequestreRefuse(ValueError):
    """Geste refusé sur un séquestre : état incompatible, litige en cours, montant invalide."""


class CodeIncorrect(SequestreRefuse):
    def __init__(self, message: str, restants: int):
        super().__init__(message)
        self.restants = restants


class CodeVerrouille(SequestreRefuse):
    """Trop d'essais : le code ne s'accepte plus, l'acheteur doit confirmer lui-même."""


# ---------------------------------------------------------------------------
# Montants
# ---------------------------------------------------------------------------
def commission_ttc(sous_commande) -> Decimal:
    """Ce que la plateforme retient sur la part : commission de place **et sa TVA**.

    Même calcul que l'écriture de commission de `comptabiliser_vente_en_ligne` (dette `401` du
    marchand). S'il divergeait, le portefeuille et la comptabilité du marchand raconteraient deux
    histoires ; un test les rapproche.
    """
    commission = Decimal(sous_commande.commission_plateforme).quantize(CENTIME)
    if commission <= 0:
        return Decimal("0.00")
    tva = (commission * Decimal(settings.TAUX_TVA_DEFAUT) / 100).quantize(CENTIME)
    return (commission + tva).quantize(CENTIME)


def montant_en_sequestre(boutique) -> Decimal:
    """Total TTC des séquestres encore bloqués d'une boutique : ce que le plafond borne."""
    total = Sequestre.objects.filter(
        boutique_id=getattr(boutique, "pk", boutique), etat=Sequestre.BLOQUE
    ).aggregate(t=Sum("montant_encaisse"))["t"]
    return (total or Decimal("0")).quantize(CENTIME)


def montant_lisible(montant) -> str:
    """Montant lisible sans dépendre des gabarits : « 150 000 »."""
    entier = int(Decimal(montant).quantize(Decimal("1")))
    return f"{entier:,}".replace(",", " ")


def refus_de_prepaiement(boutique, montant_ttc) -> str | None:
    """Le message qui refuse le prépaiement chez cette boutique, ou `None` s'il est accepté.

    Le message dit la vérité à l'acheteur sans rien livrer du commerce de la boutique : le plafond
    de son palier est une règle publique, ce qu'elle a déjà en séquestre ne l'est pas.
    """
    palier = palier_de(boutique)
    if palier.plafond_sequestre is None:
        return None
    montant_ttc = Decimal(montant_ttc).quantize(CENTIME)
    if montant_en_sequestre(boutique) + montant_ttc <= palier.plafond_sequestre:
        return None
    return (
        f"« {boutique.enseigne} » ({palier.libelle.lower()}) ne peut pas encore recevoir ce "
        f"prépaiement : tant qu'une boutique n'a pas fait ses preuves sur le marché, l'argent "
        f"qu'elle peut avoir en séquestre est plafonné à {montant_lisible(palier.plafond_sequestre)} FCFA, "
        "et votre commande le dépasserait. Chez elle, vous paierez à la livraison, en recevant "
        "la marchandise."
    )


# ---------------------------------------------------------------------------
# Code de remise
# ---------------------------------------------------------------------------
def code_de_remise(sous_commande) -> str:
    """Les six chiffres que l'acheteur donne au livreur.

    **Dérivé, pas stocké.** Le code est une empreinte de l'identifiant de la sous-commande par la
    clé secrète du serveur. La base n'en garde qu'un haché (`code_remise_hache`), si bien que ni un
    accès en lecture à la base, ni une sauvegarde égarée, ni un administrateur curieux n'y trouvent
    le code — et que la page de l'acheteur peut pourtant le lui réafficher à chaque visite, sans
    qu'il ait eu à le noter.

    Ce qui protège ensuite l'affichage, c'est la vitrine : le code n'est montré qu'à la session
    qui a passé la commande, jamais à qui connaîtrait seulement l'adresse de la page — le marchand
    la connaît, et c'est précisément lui qui ne doit pas pouvoir lire le code.
    """
    identifiant = str(getattr(sous_commande, "pk", sous_commande))
    empreinte = salted_hmac(
        "hypermarche.sequestre.code-remise", identifiant, algorithm="sha256"
    ).hexdigest()
    return f"{int(empreinte, 16) % 1_000_000:06d}"


def _normaliser_code(saisie: str) -> str:
    return "".join(c for c in (saisie or "") if c.isdigit())


# ---------------------------------------------------------------------------
# Lectures
# ---------------------------------------------------------------------------
def _litige_en_cours(sous_commande):
    from apps.orders.models import Litige

    with contexte_boutique(sous_commande.boutique_id):
        return (
            Litige.objects.filter(sous_commande=sous_commande, etat__in=Litige.ETATS_OUVERTS)
            .order_by("cree_le")
            .first()
        )


def _verrouiller(sequestre) -> Sequestre:
    """Relit le séquestre sous verrou : la vérité est en base, pas dans l'objet reçu.

    La jointure sur la sous-commande traverse une table scopée : sans le contexte de la boutique,
    la barrière 3 la rendrait vide et le séquestre « introuvable ». Seule sa ligne est verrouillée.
    """
    with contexte_boutique(sequestre.boutique_id):
        return (
            Sequestre.objects.select_for_update(of=("self",))
            .select_related("sous_commande", "commande", "boutique")
            .get(pk=sequestre.pk)
        )


def _journaliser(boutique_id, compartiment, montant, type_mouvement, sequestre) -> None:
    mouvementer_portefeuille(
        boutique=boutique_id,
        compartiment=compartiment,
        montant=montant,
        type_mouvement=type_mouvement,
        origine_type="payments.Sequestre",
        origine_id=sequestre.pk,
    )


# ---------------------------------------------------------------------------
# 1. Ouverture, au paiement constaté
# ---------------------------------------------------------------------------
def ouvrir_sequestre(sous_commande, *, maintenant=None) -> Sequestre:
    """Constate que la part est cantonnée, et la porte au `solde_bloque` du marchand.

    **Idempotent.** Les notifications d'opérateur arrivent en double : la seconde retrouve le
    séquestre de la première, sans seconde ligne de journal. C'est l'unicité de la sous-commande
    sur le séquestre qui arbitre, pas la lecture préalable.
    """
    if not sous_commande.prepayee:
        raise SequestreRefuse("Une part payée à la livraison ne passe pas par le séquestre.")

    existant = Sequestre.objects.filter(sous_commande=sous_commande).first()
    if existant is not None:
        return existant

    commission = commission_ttc(sous_commande)
    encaisse = Decimal(sous_commande.total_ttc).quantize(CENTIME)
    net = (encaisse - commission).quantize(CENTIME)
    if net <= 0:
        raise SequestreRefuse("La part nette du marchand serait nulle : commande incohérente.")

    try:
        with contexte_boutique(sous_commande.boutique_id):
            with transaction.atomic():
                sequestre = Sequestre.objects.create(
                    commande_id=sous_commande.commande_id,
                    sous_commande=sous_commande,
                    boutique_id=sous_commande.boutique_id,
                    montant_encaisse=encaisse,
                    commission=commission,
                    montant=net,
                    code_remise_hache=make_password(code_de_remise(sous_commande)),
                )
                _journaliser(
                    sous_commande.boutique_id,
                    MouvementPortefeuille.BLOQUE,
                    net,
                    MouvementPortefeuille.SEQUESTRE,
                    sequestre,
                )
    except IntegrityError:
        # Course perdue contre une notification jumelle : son séquestre fait foi.
        return Sequestre.objects.get(sous_commande=sous_commande)
    return sequestre


# ---------------------------------------------------------------------------
# 3. Confirmation de la livraison
# ---------------------------------------------------------------------------
def _marquer_confirmee(sous_commande, quand) -> None:
    """Pose `livraison_confirmee_le`, et fait passer la part à « livrée » si elle ne l'était pas.

    Une remise prouvée par l'acheteur vaut déclaration : on ne laisse pas une part « expédiée »
    alors que l'acheteur a dit l'avoir reçue.
    """
    from apps.orders.models import SousCommande
    from apps.orders.services import livrer

    if sous_commande.etat == SousCommande.EXPEDIEE:
        livrer(sous_commande, maintenant=quand)
    sous_commande.livraison_confirmee_le = quand
    with contexte_boutique(sous_commande.boutique_id):
        SousCommande.objects.filter(pk=sous_commande.pk).update(
            livraison_confirmee_le=quand, modifie_le=timezone.now()
        )


def _controler_confirmable(sous_commande, sequestre, *, pour_l_acheteur: bool) -> None:
    if sous_commande.etat not in _ETATS_LIVRABLES:
        raise SequestreRefuse(
            "La livraison ne se confirme qu'une fois la commande expédiée : "
            f"elle est « {sous_commande.get_etat_display().lower()} »."
        )
    if sequestre is not None and sequestre.etat != Sequestre.BLOQUE:
        raise SequestreRefuse("Ce séquestre est déjà tranché.")
    if _litige_en_cours(sous_commande) is not None:
        raise SequestreRefuse(
            "Votre réclamation est en cours d'examen : la plateforme tranchera."
            if pour_l_acheteur
            else MESSAGE_GEL
        )


def confirmer_par_code(sous_commande, code: str, *, par=None, maintenant=None) -> Sequestre:
    """Le marchand prouve la remise avec le code que l'acheteur a donné au livreur.

    Chaque échec est compté **en base**, sous verrou, et survit à un redémarrage ou à un cache
    vidé : c'est la seule chose qui sépare un code à six chiffres d'un million d'essais.
    L'échec est enregistré hors de toute transaction qui l'annulerait — l'exception n'est levée
    qu'après.
    """
    maintenant = maintenant or timezone.now()
    sequestre = Sequestre.objects.filter(sous_commande=sous_commande).first()
    if sequestre is None:
        raise SequestreRefuse(
            "Cette commande n'a pas de séquestre : elle n'est pas prépayée, ou son paiement n'a "
            "pas encore été constaté."
        )
    if sous_commande.livraison_confirmee_le is not None:
        return sequestre
    _controler_confirmable(sous_commande, sequestre, pour_l_acheteur=False)

    echec = None
    with transaction.atomic():
        sequestre = _verrouiller(sequestre)
        if sequestre.code_verrouille_le is not None:
            raise CodeVerrouille(
                "Code verrouillé après trop d'essais. L'acheteur peut confirmer la réception "
                "depuis sa page de commande ; sans litige, elle sera de toute façon réputée "
                "confirmée sept jours après l'expédition."
            )
        if check_password(_normaliser_code(code), sequestre.code_remise_hache):
            sequestre.confirmation = Sequestre.PAR_CODE
            sequestre.save(update_fields=["confirmation", "modifie_le"])
        else:
            sequestre.essais_code_echoues += 1
            champs = ["essais_code_echoues", "modifie_le"]
            if sequestre.essais_code_echoues >= ESSAIS_CODE_MAX:
                sequestre.code_verrouille_le = maintenant
                champs.append("code_verrouille_le")
            sequestre.save(update_fields=champs)
            restants = max(ESSAIS_CODE_MAX - sequestre.essais_code_echoues, 0)
            echec = CodeIncorrect(
                "Code incorrect."
                + (
                    f" Encore {restants} essai{'s' if restants > 1 else ''} avant verrouillage."
                    if restants
                    else " Le code est maintenant verrouillé : l'acheteur doit confirmer lui-même."
                ),
                restants,
            )
    if echec is not None:
        journal.warning(
            "Code de remise erroné pour la sous-commande %s (%s essai(s) échoué(s)).",
            sous_commande.pk,
            sequestre.essais_code_echoues,
        )
        raise echec

    _marquer_confirmee(sous_commande, maintenant)
    return sequestre


def confirmer_par_acheteur(sous_commande, *, maintenant=None):
    """L'acheteur dit avoir reçu sa commande, depuis sa page. Vaut aussi sans séquestre.

    Pour une part payée à la livraison, il n'y a pas d'argent à libérer, mais la confirmation
    reste une preuve de livraison — de celles qui font monter une boutique de palier.
    """
    from apps.orders.models import SousCommande

    maintenant = maintenant or timezone.now()
    if sous_commande.livraison_confirmee_le is not None:
        return sous_commande
    if sous_commande.etat == SousCommande.ANNULEE:
        raise SequestreRefuse("Cette commande a été annulée.")
    sequestre = Sequestre.objects.filter(sous_commande=sous_commande).first()
    _controler_confirmable(sous_commande, sequestre, pour_l_acheteur=True)

    if sequestre is not None:
        with transaction.atomic():
            sequestre = _verrouiller(sequestre)
            if sequestre.etat != Sequestre.BLOQUE:
                raise SequestreRefuse("Ce séquestre est déjà tranché.")
            sequestre.confirmation = Sequestre.PAR_ACHETEUR
            sequestre.save(update_fields=["confirmation", "modifie_le"])
    _marquer_confirmee(sous_commande, maintenant)
    return sous_commande


def _confirmer_implicitement(sequestre, *, maintenant) -> bool:
    """Réputée confirmée sept jours après l'expédition, sans confirmation ni litige.

    La date posée est l'échéance elle-même — expédition + sept jours — et non l'heure à laquelle
    la tâche est passée : relancer la tâche en retard ne doit pas retarder la libération, ni la
    rejouer la décaler.
    """
    part = sequestre.sous_commande
    if part.livraison_confirmee_le is not None or part.etat not in _ETATS_LIVRABLES:
        return False
    depart = part.expediee_le or part.livree_le
    if depart is None or depart + DELAI_CONFIRMATION_IMPLICITE > maintenant:
        return False
    if _litige_en_cours(part) is not None:
        return False

    echeance = depart + DELAI_CONFIRMATION_IMPLICITE
    with transaction.atomic():
        verrouille = _verrouiller(sequestre)
        if verrouille.etat != Sequestre.BLOQUE or verrouille.confirmation:
            return False
        verrouille.confirmation = Sequestre.IMPLICITE
        verrouille.save(update_fields=["confirmation", "modifie_le"])
    # La part reste dans l'état que le marchand a déclaré : rien n'a été prouvé, seul le délai
    # de réclamation est passé.
    from apps.orders.models import SousCommande

    with contexte_boutique(part.boutique_id):
        SousCommande.objects.filter(pk=part.pk).update(livraison_confirmee_le=echeance)
    part.livraison_confirmee_le = echeance
    return True


# ---------------------------------------------------------------------------
# 4. Libération
# ---------------------------------------------------------------------------
def echeance_de_liberation(sequestre):
    """Quand la part sera libérée si rien ne s'y oppose ; `None` tant que rien n'est confirmé."""
    confirmee = sequestre.sous_commande.livraison_confirmee_le
    if confirmee is None:
        return None
    return confirmee + timedelta(days=palier_de(sequestre.boutique).delai_liberation_jours)


def liberer(sequestre, *, maintenant=None, motif: str = "", apres_decision: bool = False) -> Sequestre:
    """La part passe du bloqué au disponible. Deux lignes de journal, un seul geste.

    Hors décision de litige, trois conditions, revérifiées sous verrou : la livraison est
    **confirmée** (jamais seulement déclarée), le délai du palier est écoulé, aucun litige n'est en
    cours. Une décision en faveur du marchand (`apres_decision`) libère sans attendre : le délai
    servait à laisser l'acheteur réclamer, et sa réclamation vient d'être tranchée.
    """
    maintenant = maintenant or timezone.now()
    boutique_id = sequestre.boutique_id
    with contexte_boutique(boutique_id):
        with transaction.atomic():
            sequestre = _verrouiller(sequestre)
            if sequestre.etat != Sequestre.BLOQUE:
                return sequestre  # déjà tranché : rejouer ne fait rien
            if not apres_decision:
                if _litige_en_cours(sequestre.sous_commande) is not None:
                    raise SequestreRefuse(MESSAGE_GEL)
                echeance = echeance_de_liberation(sequestre)
                if echeance is None:
                    raise SequestreRefuse(
                        "La livraison n'est pas confirmée : une livraison déclarée ne libère rien."
                    )
                if echeance > maintenant:
                    raise SequestreRefuse(
                        f"Le délai du palier court jusqu'au {timezone.localtime(echeance):%d/%m/%Y}."
                    )
            _liberer_montant(sequestre, sequestre.montant)
            sequestre.montant_libere = sequestre.montant
            sequestre.etat = Sequestre.LIBERE
            sequestre.libere_le = maintenant
            sequestre.motif = (motif or sequestre.motif)[:255]
            sequestre.save(
                update_fields=["montant_libere", "etat", "libere_le", "motif", "modifie_le"]
            )
            _comptabiliser_liberation(sequestre, maintenant)
    return sequestre


def _liberer_montant(sequestre, montant) -> None:
    if montant <= 0:
        return
    _journaliser(
        sequestre.boutique_id,
        MouvementPortefeuille.BLOQUE,
        -montant,
        MouvementPortefeuille.LIBERATION,
        sequestre,
    )
    _journaliser(
        sequestre.boutique_id,
        MouvementPortefeuille.DISPONIBLE,
        montant,
        MouvementPortefeuille.LIBERATION,
        sequestre,
    )


def _comptabiliser_liberation(sequestre, maintenant) -> None:
    """La commission devient acquise : compensation `401` / `5313` chez le marchand.

    Un échec comptable (exercice clôturé, plan non initialisé) **ne bloque pas** la libération :
    l'argent du marchand ne doit pas rester gelé pour une raison qui ne tient pas à sa livraison.
    L'échec est journalisé pour que le comptable passe l'écriture à la main. Le point de reprise
    est explicite pour que l'échec n'emporte pas la transaction qui l'entoure.
    """
    from apps.accounting.services import EcritureInvalide, comptabiliser_liberation_sequestre

    try:
        with transaction.atomic():
            comptabiliser_liberation_sequestre(
                sequestre, date_ecriture=timezone.localdate(maintenant)
            )
    except EcritureInvalide as erreur:
        journal.error(
            "Libération du séquestre %s : écriture de commission non passée (%s).",
            sequestre.pk,
            erreur,
        )


def liberer_echus(*, maintenant=None) -> dict:
    """Confirmations implicites et libérations échues, pour toutes les boutiques.

    **Tâche technique, sans demandeur humain** : c'est le domaine de `contexte_plateforme()`
    (ADR-012), et c'est pour elle seule qu'il est ouvert ici — pour trouver les candidats. Chaque
    geste se fait ensuite dans le contexte de sa boutique, sous verrou, et revérifie tout.

    Idempotente : relancée, elle ne trouve plus rien à faire sur ce qu'elle a déjà fait.
    """
    maintenant = maintenant or timezone.now()
    with contexte_plateforme():
        candidats = list(
            Sequestre.objects.filter(etat=Sequestre.BLOQUE).select_related(
                "sous_commande", "boutique", "commande"
            )
        )

    bilan_tache = {"confirmees": 0, "liberees": 0, "gelees": 0, "en_attente": 0}
    for sequestre in candidats:
        if _litige_en_cours(sequestre.sous_commande) is not None:
            bilan_tache["gelees"] += 1
            continue
        if _confirmer_implicitement(sequestre, maintenant=maintenant):
            bilan_tache["confirmees"] += 1
        echeance = echeance_de_liberation(sequestre)
        if echeance is None or echeance > maintenant:
            bilan_tache["en_attente"] += 1
            continue
        try:
            liberer(sequestre, maintenant=maintenant, motif="Délai du palier écoulé")
        except SequestreRefuse as refus:
            # Un litige ouvert entre la lecture et le verrou : exactement ce que le verrou protège.
            journal.info("Séquestre %s non libéré : %s", sequestre.pk, refus)
            bilan_tache["gelees"] += 1
            continue
        bilan_tache["liberees"] += 1
    return bilan_tache


# ---------------------------------------------------------------------------
# Remboursement
# ---------------------------------------------------------------------------
def rembourser(
    sequestre,
    *,
    montant_marchand=None,
    motif: str,
    maintenant=None,
    malgre_litige: bool = False,
) -> Sequestre:
    """Ordonne le remboursement de l'acheteur, en tout ou en partie.

    * **Total** (`montant_marchand` absent) : la part nette quitte le bloqué, la commission de la
      plateforme est annulée — l'acheteur récupère exactement ce qu'il a payé —, et les
      commissions d'affiliation tombent, comme pour un retour.
    * **Partiel** (`montant_marchand` = ce que l'acheteur récupère) : prélevé sur la part du
      marchand, strictement inférieur à elle ; le reste est libéré. La vente subsiste, la
      commission de place aussi.

    Ce qui n'est pas fait ici : le virement réel vers l'acheteur. Il sera ordonné à l'agrégateur
    quand l'intégration existera ; aujourd'hui, le séquestre constate la décision et la somme due
    (`rembourse_acheteur`), et rien ne prétend qu'elle est partie.
    """
    from apps.affiliation.services import annuler_commissions

    maintenant = maintenant or timezone.now()
    motif = (motif or "").strip()
    if not motif:
        raise SequestreRefuse("Un remboursement se motive.")

    with contexte_boutique(sequestre.boutique_id):
        with transaction.atomic():
            sequestre = _verrouiller(sequestre)
            if sequestre.etat != Sequestre.BLOQUE:
                raise SequestreRefuse(
                    f"Ce séquestre est déjà {sequestre.get_etat_display().lower()} : "
                    "il ne se rembourse plus."
                )
            if not malgre_litige and _litige_en_cours(sequestre.sous_commande) is not None:
                raise SequestreRefuse(MESSAGE_GEL)

            if montant_marchand is None:
                rendu = sequestre.montant
                _journaliser(
                    sequestre.boutique_id,
                    MouvementPortefeuille.BLOQUE,
                    -rendu,
                    MouvementPortefeuille.REMBOURSEMENT,
                    sequestre,
                )
                sequestre.montant_rembourse = rendu
                sequestre.rembourse_acheteur = sequestre.montant_encaisse
                sequestre.etat = Sequestre.REMBOURSE
                sequestre.rembourse_le = maintenant
                sequestre.motif = motif[:255]
                sequestre.save(
                    update_fields=[
                        "montant_rembourse",
                        "rembourse_acheteur",
                        "etat",
                        "rembourse_le",
                        "motif",
                        "modifie_le",
                    ]
                )
                annuler_commissions(sequestre.sous_commande, motif=motif[:200])
                return sequestre

            rendu = Decimal(montant_marchand).quantize(CENTIME)
            if rendu <= 0 or rendu >= sequestre.montant:
                raise SequestreRefuse(
                    f"Un remboursement partiel est compris entre 0 et la part du marchand "
                    f"({montant_lisible(sequestre.montant)} FCFA), bornes exclues. Pour tout rendre, "
                    "tranchez en faveur de l'acheteur."
                )
            reste = (sequestre.montant - rendu).quantize(CENTIME)
            _journaliser(
                sequestre.boutique_id,
                MouvementPortefeuille.BLOQUE,
                -rendu,
                MouvementPortefeuille.REMBOURSEMENT,
                sequestre,
            )
            _liberer_montant(sequestre, reste)
            sequestre.montant_rembourse = rendu
            sequestre.montant_libere = reste
            sequestre.rembourse_acheteur = rendu
            sequestre.etat = Sequestre.PARTAGE
            sequestre.rembourse_le = maintenant
            sequestre.libere_le = maintenant
            sequestre.motif = motif[:255]
            sequestre.save(
                update_fields=[
                    "montant_rembourse",
                    "montant_libere",
                    "rembourse_acheteur",
                    "etat",
                    "rembourse_le",
                    "libere_le",
                    "motif",
                    "modifie_le",
                ]
            )
            _comptabiliser_liberation(sequestre, maintenant)
            return sequestre


# ---------------------------------------------------------------------------
# 5. Litiges
# ---------------------------------------------------------------------------
LONGUEUR_MIN_DESCRIPTION = 15
LONGUEUR_MIN_MOTIVATION = 20

EN_FAVEUR_DU_MARCHAND = "marchand"
EN_FAVEUR_DE_L_ACHETEUR = "acheteur"
PARTIELLE = "partielle"
DECISIONS = [
    (EN_FAVEUR_DU_MARCHAND, "En faveur du marchand — la part est libérée"),
    (EN_FAVEUR_DE_L_ACHETEUR, "En faveur de l'acheteur — remboursement total"),
    (PARTIELLE, "Partielle — l'acheteur récupère un montant, le reste est libéré"),
]


def ouvrir_litige(sous_commande, *, motif: str, description: str, par=None):
    """L'acheteur conteste sa part : elle est **gelée** jusqu'à la décision.

    Seulement tant que la part n'est pas libérée — après, l'argent est au marchand, et la
    réclamation relève du retour. Un seul litige en cours par part : c'est une contrainte en base,
    pas un contrôle d'écran.
    """
    from apps.orders.models import Litige

    description = (description or "").strip()
    if motif not in dict(Litige.MOTIFS):
        raise SequestreRefuse("Choisissez le motif du litige.")
    if len(description) < LONGUEUR_MIN_DESCRIPTION:
        raise SequestreRefuse(
            "Décrivez ce qui ne va pas en une ou deux phrases : c'est ce que la plateforme lira."
        )
    sequestre = Sequestre.objects.filter(sous_commande=sous_commande).first()
    if sequestre is None:
        raise SequestreRefuse(
            "Seule une commande prépayée, dont le paiement a été constaté, se conteste ici. "
            "Pour une commande payée à la livraison, voyez directement le commerçant."
        )
    if sequestre.etat != Sequestre.BLOQUE:
        raise SequestreRefuse(
            "L'argent de cette commande n'est plus en séquestre : il a été "
            f"{sequestre.get_etat_display().lower()}."
        )
    existant = _litige_en_cours(sous_commande)
    if existant is not None:
        return existant

    try:
        with contexte_boutique(sous_commande.boutique_id):
            with transaction.atomic():
                verrouille = _verrouiller(sequestre)
                if verrouille.etat != Sequestre.BLOQUE:
                    raise SequestreRefuse("L'argent de cette commande n'est plus en séquestre.")
                return Litige.objects.create(
                    boutique_id=sous_commande.boutique_id,
                    sous_commande=sous_commande,
                    motif=motif,
                    description=description[:4000],
                    cree_par=par if getattr(par, "is_authenticated", False) else None,
                )
    except IntegrityError:
        return _litige_en_cours(sous_commande)


def prendre_en_instruction(litige, *, par):
    from apps.orders.models import Litige

    if litige.etat != Litige.OUVERT:
        return litige
    with contexte_boutique(litige.boutique_id):
        Litige.objects.filter(pk=litige.pk, etat=Litige.OUVERT).update(
            etat=Litige.EN_INSTRUCTION, modifie_le=timezone.now()
        )
    litige.etat = Litige.EN_INSTRUCTION
    return litige


def trancher_litige(
    litige, *, decision: str, motivation: str, par, montant=None, maintenant=None
):
    """La décision motivée de la plateforme, et l'ordre qui en découle sur le séquestre.

    La motivation est obligatoire et consignée sur le litige avec son auteur : c'est la décision
    « motivée et opposable » que promettent les conditions (docs/08, §8). Le litige et le
    séquestre sont tranchés dans la même transaction — un litige clos sur un séquestre resté gelé
    serait de l'argent que personne ne réclame plus.
    """
    from apps.orders.models import Litige

    maintenant = maintenant or timezone.now()
    motivation = (motivation or "").strip()
    if decision not in dict(DECISIONS):
        raise SequestreRefuse("Choisissez une décision.")
    if len(motivation) < LONGUEUR_MIN_MOTIVATION:
        raise SequestreRefuse(
            "Une décision se motive : quelques phrases, que l'acheteur et le marchand liront."
        )
    if not getattr(par, "is_authenticated", False):
        raise SequestreRefuse("Une décision a un auteur identifié.")

    sous_commande = litige.sous_commande
    sequestre = Sequestre.objects.filter(sous_commande=sous_commande).first()
    if sequestre is None:
        raise SequestreRefuse("Cette commande n'a pas de séquestre à trancher.")

    with contexte_boutique(litige.boutique_id):
        with transaction.atomic():
            verrouille = Litige.objects.select_for_update().get(pk=litige.pk)
            if verrouille.etat not in Litige.ETATS_OUVERTS:
                raise SequestreRefuse("Ce litige est déjà tranché.")

            if decision == EN_FAVEUR_DU_MARCHAND:
                liberer(
                    sequestre,
                    maintenant=maintenant,
                    motif="Litige tranché en faveur du marchand",
                    apres_decision=True,
                )
                etat, rendu = Litige.TRANCHE_MARCHAND, Decimal("0")
            elif decision == EN_FAVEUR_DE_L_ACHETEUR:
                resultat = rembourser(
                    sequestre,
                    motif="Litige tranché en faveur de l'acheteur",
                    maintenant=maintenant,
                    malgre_litige=True,
                )
                etat, rendu = Litige.TRANCHE_ACHETEUR, resultat.rembourse_acheteur
            else:
                if montant in (None, ""):
                    raise SequestreRefuse("Indiquez le montant remboursé à l'acheteur.")
                try:
                    montant = Decimal(str(montant).replace(" ", "").replace(",", "."))
                except Exception:  # noqa: BLE001 — une saisie illisible est un refus, pas une panne
                    raise SequestreRefuse("Montant illisible.") from None
                resultat = rembourser(
                    sequestre,
                    montant_marchand=montant,
                    motif="Litige tranché : remboursement partiel",
                    maintenant=maintenant,
                    malgre_litige=True,
                )
                etat, rendu = Litige.PARTAGE, resultat.rembourse_acheteur

            verrouille.etat = etat
            verrouille.montant_rembourse = rendu
            verrouille.decision = motivation[:4000]
            verrouille.tranche_par = par
            verrouille.tranche_le = maintenant
            verrouille.save(
                update_fields=[
                    "etat",
                    "montant_rembourse",
                    "decision",
                    "tranche_par",
                    "tranche_le",
                    "modifie_le",
                ]
            )
    return verrouille


# ---------------------------------------------------------------------------
# Bilan : l'invariant de l'argent
# ---------------------------------------------------------------------------
def bilan(boutique) -> dict:
    """Où est l'argent d'une boutique, et la preuve qu'il n'en manque pas.

    `ecart` doit toujours valoir zéro : ce que le séquestre a constaté (encaissé net) se retrouve,
    au franc près, dans le bloqué, le disponible, le versé et le remboursé.
    """
    from apps.payments.models import PortefeuilleMarchand, Versement

    boutique_id = getattr(boutique, "pk", boutique)
    sequestres = Sequestre.objects.filter(boutique_id=boutique_id)
    sommes = sequestres.aggregate(
        encaisse=Sum("montant_encaisse"),
        net=Sum("montant"),
        libere=Sum("montant_libere"),
        rembourse=Sum("montant_rembourse"),
    )
    bloque_sequestres = sequestres.filter(etat=Sequestre.BLOQUE).aggregate(t=Sum("montant"))["t"]
    verse = Versement.objects.filter(
        boutique_id=boutique_id, etat__in=[Versement.DEMANDE, Versement.EXECUTE]
    ).aggregate(t=Sum("montant"))["t"]
    en_attente = Versement.objects.filter(
        boutique_id=boutique_id, etat=Versement.DEMANDE
    ).aggregate(t=Sum("montant"))["t"]
    with contexte_boutique(boutique_id):
        portefeuille = PortefeuilleMarchand.objects.filter(boutique_id=boutique_id).first()

    zero = Decimal("0.00")
    resultat = {
        "encaisse_net": (sommes["net"] or zero).quantize(CENTIME),
        "bloque": portefeuille.solde_bloque if portefeuille else zero,
        "bloque_sequestres": (bloque_sequestres or zero).quantize(CENTIME),
        "disponible": portefeuille.solde_disponible if portefeuille else zero,
        "libere": (sommes["libere"] or zero).quantize(CENTIME),
        "verse": (verse or zero).quantize(CENTIME),
        "en_attente_de_versement": (en_attente or zero).quantize(CENTIME),
        "rembourse": (sommes["rembourse"] or zero).quantize(CENTIME),
    }
    resultat["ecart"] = (
        resultat["encaisse_net"]
        - resultat["bloque"]
        - resultat["disponible"]
        - resultat["verse"]
        - resultat["rembourse"]
    ).quantize(CENTIME)
    return resultat
