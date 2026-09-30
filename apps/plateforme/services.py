"""Les gestes de la console, écrits une fois, testables sans HTTP.

Les vues ne font que recueillir une saisie et l'afficher ; **tout ce qui décide est ici**. Pour
trois raisons :

* un geste de gouvernance s'exécute en **une** transaction — ouvrir une boutique crée cinq
  choses, et une boutique sans plan comptable ou un gérant sans boutique est pire qu'une boutique
  qui n'existe pas encore ;
* chaque geste **revérifie** ce que l'assistant a déjà vérifié. Entre la première étape et la
  confirmation, la session a pu vieillir, un autre administrateur a pu prendre le même numéro, et
  un formulaire n'est jamais la dernière barrière ;
* chaque geste **laisse une trace** dans le journal en ajout seul (`AccesPlateforme`), comme
  `gouvernance.fixer_taux_rayon` le fait déjà : une ouverture, une suspension ou une nomination
  sans trace est une décision que personne ne pourra relire.

Les refus métier sont des `ValidationError` (une saisie à corriger) ; les refus de droit sont des
`PermissionDenied` (un geste qui n'est pas le sien) — la même distinction que `gouvernance.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.administration import (
    LIBELLES_ROLES_ADMINISTRATION,
    poser_administrateur_du_marche,
    retirer_role_plateforme,
)
from apps.accounts.models import Appartenance, Role, RolePlateforme
from apps.accounts.permissions import (
    PLATEFORME_BOUTIQUES,
    PLATEFORME_COMMISSIONS,
    PLATEFORME_EMPLACEMENTS,
)
from apps.confiance import verification
from apps.core.models import AccesPlateforme
from apps.core.tenancy import contexte_boutique
from apps.marketplace.models import (
    Bail,
    Boutique,
    EmplacementPremium,
    FactureLoyer,
    Rayon,
    TypeEmplacement,
)
from apps.plateforme.acces import CONSOLE_ADMINISTRATEURS, droits_console_de

CENT = Decimal("100")


# ----------------------------------------------------------------------------
# Socle : droits et trace
# ----------------------------------------------------------------------------
def _exiger(par, droit: str) -> None:
    """La porte de la vue a déjà filtré ; le service refiltre. Un service appelé d'ailleurs — une
    commande, un test, une future API — ne doit pas hériter d'un droit qu'il n'a pas vérifié."""
    if droit not in droits_console_de(par):
        raise PermissionDenied("Ce geste n'est pas ouvert à votre compte.")


def tracer(par, *, ecran: str, motif: str, boutique_id=None) -> AccesPlateforme:
    """Une ligne au journal des accès, en ajout seul (ADR-012).

    Le motif est tronqué, pas refusé : il a déjà été exigé en amont, et perdre la trace parce
    qu'une raison était longue serait le pire des deux échecs.
    """
    return AccesPlateforme.objects.create(
        utilisateur=par,
        boutique_id=getattr(boutique_id, "pk", boutique_id),
        ecran=ecran[:120],
        motif=motif.strip()[:300],
    )


def _motif_obligatoire(motif: str, message: str) -> str:
    motif = (motif or "").strip()
    if len(motif) < 5:
        raise ValidationError({"motif": message})
    return motif


# ----------------------------------------------------------------------------
# Deux casquettes, deux comptes (ADR-012, §5)
# ----------------------------------------------------------------------------
def refus_gerant(compte, *, par) -> str | None:
    """Pourquoi ce compte ne peut pas devenir gérant — ou `None` s'il le peut.

    Un compte d'administration ne tient pas une boutique : chaque ligne du journal deviendrait
    ambiguë — agissait-il comme exploitant, ou comme concurrent ? L'exploitant qui vend a un
    **second** compte, ordinaire, et c'est celui-là qu'on rattache.
    """
    if compte.pk == getattr(par, "pk", None):
        return (
            "C'est votre propre compte d'administration. Deux casquettes, deux comptes : si vous "
            "tenez aussi cette boutique, rattachez votre compte de commerçant, pas celui-ci."
        )
    if compte.is_superuser:
        return (
            "Ce compte est superadministrateur. Il ne tient pas de boutique : rattachez un compte "
            "de commerçant distinct (ADR-012, deux casquettes, deux comptes)."
        )
    if compte.is_staff or compte.roles_plateforme.filter(actif=True).exists():
        return (
            "Ce compte administre le marché. Il ne peut pas tenir une boutique du même marché : "
            "rattachez un compte de commerçant distinct (ADR-012, deux casquettes, deux comptes)."
        )
    if not compte.is_active:
        return "Ce compte est désactivé. Réactivez-le d'abord, ou créez un nouveau compte."
    return None


def refus_administrateur(compte) -> str | None:
    """Pourquoi ce compte ne peut pas être nommé administrateur du marché — ou `None`."""
    if compte.is_superuser:
        return (
            "Ce compte est superadministrateur : il administre déjà tout. Un administrateur du "
            "marché est un autre compte, sans ce drapeau — c'est ce qui rend son journal lisible."
        )
    if not compte.is_active:
        return "Ce compte est désactivé : on ne confie pas l'exploitation à un compte fermé."
    boutiques = list(
        compte.appartenances.filter(actif=True).values_list("boutique__enseigne", flat=True)[:3]
    )
    if boutiques:
        return (
            f"Ce compte travaille dans une boutique ({', '.join(boutiques)}). Deux casquettes, "
            "deux comptes : créez-lui un compte d'administration distinct, avec un autre numéro "
            "(ADR-012, §5)."
        )
    return None


def _compte_nouveau(*, telephone: str, nom: str, mot_de_passe_hache: str):
    """Un compte créé depuis la console, avec le mot de passe **déjà haché** par l'assistant.

    Le mot de passe en clair n'a jamais quitté la requête qui l'a saisi : la session ne garde que
    son empreinte (`make_password`), et c'est elle qu'on pose ici.
    """
    Utilisateur = get_user_model()
    if not mot_de_passe_hache:
        raise ValidationError({"mot_de_passe": "Le mot de passe initial manque : saisissez-le à nouveau."})
    if Utilisateur.objects.filter(telephone=telephone).exists():
        raise ValidationError(
            {"telephone": "Ce numéro a déjà un compte. Choisissez « compte existant »."}
        )
    compte = Utilisateur(telephone=telephone, nom_complet=nom.strip())
    compte.password = mot_de_passe_hache
    compte.full_clean(exclude=["password", "code_apporteur"])
    compte.save()
    return compte


# ----------------------------------------------------------------------------
# 1. Ouvrir une boutique
# ----------------------------------------------------------------------------
def slug_libre(enseigne: str, *, exclure=None) -> str:
    """Un identifiant d'adresse dérivé de l'enseigne, rendu unique par un suffixe.

    Dérivé et non saisi : un administrateur qui tape un slug à la main en invente un par
    boutique, et la vitrine finit avec des adresses que personne ne sait reconstituer.
    """
    base = slugify(enseigne)[:120] or "boutique"
    candidat, n = base, 2
    existants = Boutique.objects.all()
    if exclure is not None:
        existants = existants.exclude(pk=exclure)
    while existants.filter(slug=candidat).exists():
        candidat = f"{base}-{n}"
        n += 1
    return candidat


@dataclass
class DemandeOuverture:
    """Tout ce que l'assistant a recueilli, déjà nettoyé par ses formulaires."""

    # Identité
    enseigne: str
    raison_sociale: str
    metier: str
    ville: str
    telephone: str
    # Légal
    rccm: str
    niu: str
    regime_fiscal: str
    # Offre et bail
    offre: TypeEmplacement
    rayon: Rayon
    debut: date
    loyer_mensuel: Decimal
    depot_garantie: Decimal
    taux_commission: Decimal  # en fraction : 0.05 = 5 %
    motif_derogation: str
    # Gérant : un compte existant, ou de quoi en créer un
    gerant_existant: object | None
    gerant_telephone: str
    gerant_nom: str
    gerant_mot_de_passe_hache: str
    # Ouvrir tout de suite, ou laisser en candidature
    activer: bool


@transaction.atomic
def ouvrir_boutique(demande: DemandeOuverture, *, par) -> Boutique:
    """Crée la boutique et tout ce sans quoi elle ne fonctionne pas — ou rien.

    Cinq créations, dans l'ordre où elles se supposent : la boutique, son bail, son gérant, son
    plan comptable, son dépôt principal. C'est la naissance décrite par `tests/fabrique.py` et
    `charger_demo._creer_boutique` ; une boutique née autrement serait une boutique à réparer.

    « Laisser en candidature » crée la même chose, avec la boutique en `candidature` et le bail
    en `brouillon` : la valider plus tard (`changer_etat_boutique`) n'aura rien à fabriquer.

    « Ouvrir tout de suite » passe par le verrou d'activation (`verification.exiger_activable`),
    **après** que tout est créé : c'est alors seulement que la liste des manques est juste — le
    gérant est rattaché, et on peut dire que c'est *sa* pièce qui manque. Le refus annule toute
    la transaction. En pratique, une boutique qui naît n'a encore ni pièce vérifiée ni compte de
    versement : elle naît en candidature, et le verrou n'est là que pour qu'aucun chemin ne le
    contourne.
    """
    from apps.accounting.referentiel import initialiser_boutique
    from apps.inventory.models import Depot

    _exiger(par, PLATEFORME_BOUTIQUES)

    if not demande.rayon.ouvert:
        # Arbitrage A8 : un rayon fermé n'accepte plus de nouvelles boutiques.
        raise ValidationError({"rayon": f"Le rayon « {demande.rayon} » est fermé aux nouvelles boutiques."})

    # --- Le gérant, d'abord vérifié : s'il est refusé, rien d'autre ne doit exister ----------
    if demande.gerant_existant is not None:
        gerant = get_user_model().objects.select_for_update().get(pk=demande.gerant_existant.pk)
        refus = refus_gerant(gerant, par=par)
        if refus:
            raise ValidationError({"telephone": refus})
    else:
        gerant = _compte_nouveau(
            telephone=demande.gerant_telephone,
            nom=demande.gerant_nom,
            mot_de_passe_hache=demande.gerant_mot_de_passe_hache,
        )

    # --- La boutique -------------------------------------------------------------------------
    boutique = Boutique(
        enseigne=demande.enseigne.strip(),
        raison_sociale=demande.raison_sociale.strip(),
        slug=slug_libre(demande.enseigne),
        metier=demande.metier,
        ville=demande.ville.strip(),
        telephone=demande.telephone,
        rccm=demande.rccm.strip(),
        niu=demande.niu.strip(),
        regime_fiscal=demande.regime_fiscal,
        rayon_principal=demande.rayon,
        # Toujours en candidature à la naissance : l'activation, s'il y a lieu, passe plus bas
        # par le verrou, une fois le gérant rattaché.
        etat=Boutique.CANDIDATURE,
        cree_par=par,
    )
    boutique.full_clean()
    boutique.save()

    # --- Le bail : `full_clean` porte la règle de la dérogation motivée (`Bail.clean`) -------
    bail = Bail(
        boutique=boutique,
        type_emplacement=demande.offre,
        debut=demande.debut,
        loyer_mensuel=demande.loyer_mensuel,
        depot_garantie=demande.depot_garantie,
        taux_commission=demande.taux_commission,
        motif_derogation_commission=demande.motif_derogation.strip(),
        etat=Bail.ACTIF if demande.activer else Bail.BROUILLON,
        cree_par=par,
    )
    bail.full_clean()
    bail.save()

    # --- Le gérant, rattaché ---------------------------------------------------------------
    role_gerant, _ = Role.objects.get_or_create(
        code=Role.GERANT, defaults={"libelle": "Gérant de boutique", "portee": Role.BOUTIQUE}
    )
    Appartenance.objects.create(utilisateur=gerant, boutique=boutique, role=role_gerant)

    # --- Le plan comptable et le dépôt : sans eux, la première vente échoue ----------------
    initialiser_boutique(boutique)
    with contexte_boutique(boutique):
        Depot.objects.create(
            boutique=boutique, libelle="Magasin principal", type=Depot.BOUTIQUE, principal=True
        )

    if demande.activer:
        verification.exiger_activable(boutique)
        boutique.etat = Boutique.ACTIVE
        boutique.save(update_fields=["etat", "modifie_le"])

    tracer(
        par,
        ecran="assistant_boutique",
        boutique_id=boutique.pk,
        motif=(
            f"Ouverture de la boutique « {boutique.enseigne} » "
            f"({'active' if demande.activer else 'candidature'}), offre {demande.offre.libelle}, "
            f"commission {demande.taux_commission:.2%}, gérant {gerant.nom_complet}"
            + (f". Dérogation : {demande.motif_derogation.strip()}" if demande.motif_derogation.strip() else "")
        ),
    )
    return boutique


# ----------------------------------------------------------------------------
# 2. Vendre un emplacement premium
# ----------------------------------------------------------------------------
TYPES_A_RAYON = frozenset({EmplacementPremium.TETE_DE_GONDOLE, EmplacementPremium.BANDEAU_RAYON})


@transaction.atomic
def vendre_emplacement(*, par, boutique, type_emplacement: str, rayon, debut: date, fin: date, tarif) -> EmplacementPremium:
    """Enregistre la vente d'un emplacement premium, **à son prix**.

    Le tarif nul est refusé ici avec une phrase, avant que la base ne le refuse avec une
    contrainte (`emplacement_premium_tarif_non_nul`) : même une attribution interne — à une
    boutique de l'exploitant — s'enregistre à son prix, sinon le compte de résultat de la
    plateforme ment sur la rentabilité du retail media (ADR-012, garde-fou 1).
    """
    _exiger(par, PLATEFORME_EMPLACEMENTS)

    boutique = Boutique.objects.select_for_update().get(pk=boutique.pk)
    if boutique.etat != Boutique.ACTIVE:
        raise ValidationError(
            {"boutique": "Seule une boutique active peut occuper un emplacement : les autres ne sont pas en vitrine."}
        )
    if type_emplacement not in dict(EmplacementPremium.TYPES):
        raise ValidationError({"type": "Type d'emplacement inconnu."})
    if type_emplacement in TYPES_A_RAYON and rayon is None:
        raise ValidationError({"rayon": "Une tête de gondole ou un bandeau se place dans un rayon : choisissez-le."})
    if type_emplacement not in TYPES_A_RAYON:
        rayon = None
    if fin <= debut:
        raise ValidationError({"fin": "La fin doit venir après le début."})
    tarif = Decimal(tarif)
    if tarif <= 0:
        raise ValidationError({"tarif": MESSAGE_TARIF_NUL})

    emplacement = EmplacementPremium.objects.create(
        rayon=rayon,
        type=type_emplacement,
        debut=debut,
        fin=fin,
        tarif=tarif,
        boutique_occupante=boutique,
        cree_par=par,
    )
    tracer(
        par,
        ecran="assistant_emplacement",
        boutique_id=boutique.pk,
        motif=(
            f"Vente d'un emplacement « {emplacement.get_type_display()} »"
            + (f" (rayon {rayon})" if rayon else "")
            + f" à « {boutique.enseigne} », du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}, {tarif:.0f} FCFA HT"
        ),
    )
    return emplacement


MESSAGE_TARIF_NUL = (
    "Un emplacement ne se cède jamais à zéro, même en attribution interne à une boutique de "
    "l'exploitant : il s'enregistre à son prix, sinon le compte de résultat de la plateforme "
    "montrerait un emplacement occupé qui ne rapporte rien (ADR-012)."
)


# ----------------------------------------------------------------------------
# 3 et 4. Nommer et retirer un administrateur du marché
# ----------------------------------------------------------------------------
@transaction.atomic
def nommer_administrateur(
    *,
    par,
    code_role: str,
    motif: str,
    compte_existant=None,
    telephone: str = "",
    nom: str = "",
    mot_de_passe_hache: str = "",
) -> RolePlateforme:
    """Confie l'exploitation du marché à un compte — réservé au superadministrateur.

    `is_staff`, le groupe et le `RolePlateforme` sont posés par la fonction partagée avec la
    commande `preparer_administrateur` ; `is_superuser` ne l'est jamais.
    """
    _exiger(par, CONSOLE_ADMINISTRATEURS)
    if code_role not in LIBELLES_ROLES_ADMINISTRATION:
        raise ValidationError({"role": "Choisissez l'un des deux rôles d'exploitation."})
    motif = _motif_obligatoire(
        motif, "Dites pourquoi vous confiez l'exploitation à ce compte : un auditeur le relira."
    )

    if compte_existant is not None:
        compte = get_user_model().objects.select_for_update().get(pk=compte_existant.pk)
        refus = refus_administrateur(compte)
        if refus:
            raise ValidationError({"telephone": refus})
    else:
        compte = _compte_nouveau(telephone=telephone, nom=nom, mot_de_passe_hache=mot_de_passe_hache)

    if compte.roles_plateforme.filter(actif=True, role_id=code_role).exists():
        raise ValidationError({"role": "Ce compte porte déjà ce rôle."})

    pose = poser_administrateur_du_marche(compte, code_role=code_role, motif=motif)
    tracer(
        par,
        ecran="assistant_administrateur",
        motif=(
            f"Nomination de {compte.nom_complet} ({compte.telephone}) — "
            f"{LIBELLES_ROLES_ADMINISTRATION[code_role]}. {motif}"
        ),
    )
    return pose.role_plateforme


@transaction.atomic
def retirer_administrateur(role_plateforme: RolePlateforme, *, par, motif: str) -> bool:
    """Retire un rôle de plateforme, sans rien supprimer. Renvoie `True` si l'accès est tombé.

    Le motif du retrait va au journal, pas sur la ligne du rôle : `RolePlateforme.motif` dit
    pourquoi on l'a confié, et l'écraser effacerait la moitié de l'histoire.
    """
    _exiger(par, CONSOLE_ADMINISTRATEURS)
    motif = _motif_obligatoire(motif, "Dites pourquoi vous retirez ce rôle : un auditeur le relira.")
    role_plateforme = (
        RolePlateforme.objects.select_for_update().select_related("utilisateur", "role").get(pk=role_plateforme.pk)
    )
    if not role_plateforme.actif:
        raise ValidationError({"motif": "Ce rôle est déjà retiré."})
    if role_plateforme.utilisateur_id == par.pk:
        raise ValidationError(
            {"motif": "On ne se retire pas soi-même son rôle : demandez-le à un autre superadministrateur."}
        )
    acces_retire = retirer_role_plateforme(role_plateforme)
    compte = role_plateforme.utilisateur
    tracer(
        par,
        ecran="administrateur_retirer",
        motif=f"Retrait de {compte.nom_complet} ({compte.telephone}) — {role_plateforme.role.libelle}. {motif}",
    )
    return acces_retire


# ----------------------------------------------------------------------------
# 5. Changer l'état d'une boutique
# ----------------------------------------------------------------------------
VALIDER, SUSPENDRE, REACTIVER, RESILIER = "valider", "suspendre", "reactiver", "resilier"

# action → (états de départ admis, état d'arrivée). Toute autre combinaison est refusée : une
# boutique résiliée ne se « réactive » pas, elle se rouvre par un nouveau bail.
TRANSITIONS = {
    VALIDER: ({Boutique.CANDIDATURE}, Boutique.ACTIVE),
    SUSPENDRE: ({Boutique.ACTIVE}, Boutique.SUSPENDUE),
    REACTIVER: ({Boutique.SUSPENDUE}, Boutique.ACTIVE),
    RESILIER: ({Boutique.ACTIVE, Boutique.SUSPENDUE, Boutique.CANDIDATURE}, Boutique.RESILIEE),
}


class TransitionInterdite(ValidationError):
    """Un changement d'état que le cycle de vie d'une boutique n'admet pas."""


def verifier_transition(boutique: Boutique, action: str) -> str:
    """Renvoie l'état d'arrivée, ou lève `TransitionInterdite` avec une phrase qui dit pourquoi."""
    if action not in TRANSITIONS:
        raise TransitionInterdite(
            "Action inconnue. Les gestes possibles sont : valider, suspendre, réactiver, résilier."
        )
    depart, arrivee = TRANSITIONS[action]
    if boutique.etat not in depart:
        etat = boutique.get_etat_display().lower()
        raisons = {
            VALIDER: f"Seule une candidature se valide ; cette boutique est {etat}.",
            SUSPENDRE: f"Seule une boutique active se suspend ; celle-ci est {etat}.",
            REACTIVER: f"Seule une boutique suspendue se réactive ; celle-ci est {etat}.",
            RESILIER: "Cette boutique est déjà résiliée : son bail est clos, et rien ne se résilie deux fois.",
        }
        raise TransitionInterdite(raisons[action])
    return arrivee


@transaction.atomic
def changer_etat_boutique(boutique: Boutique, action: str, *, par, motif: str = "") -> Boutique:
    """Valide, suspend, réactive ou résilie — et écrit pourquoi.

    * **Valider** active aussi le bail en brouillon laissé par l'assistant : sans bail actif, la
      boutique serait « active » sans jamais paraître en vitrine (`boutiques_en_vitrine`).
    * **Résilier** clôt le bail actif (`resilie`, avec `fin` et `motif_resiliation`). Rien n'est
      supprimé : une boutique porte tout ce qu'elle a vendu.

    Le motif est obligatoire pour tout sauf la validation — suspendre ou résilier un commerçant
    sans l'écrire, c'est une décision qu'on ne pourra pas lui expliquer.

    **Valider** et **réactiver** passent par le verrou d'activation : une boutique ne devient
    active que vérifiée (`verification.exiger_activable`). Une boutique suspendue avant que la
    règle existe ne revient donc en vitrine qu'une fois son dossier régularisé.
    """
    _exiger(par, PLATEFORME_BOUTIQUES)
    boutique = Boutique.objects.select_for_update().get(pk=boutique.pk)
    arrivee = verifier_transition(boutique, action)
    if arrivee == Boutique.ACTIVE:
        verification.exiger_activable(boutique)

    motif = (motif or "").strip()
    if action != VALIDER:
        motif = _motif_obligatoire(
            motif, "Dites pourquoi : ce motif sera relu, et peut-être par le commerçant lui-même."
        )

    aujourdhui = timezone.localdate()
    if action == VALIDER and not boutique.baux.filter(etat=Bail.ACTIF).exists():
        brouillon = boutique.baux.filter(etat=Bail.BROUILLON).order_by("-debut").first()
        if brouillon is None:
            raise ValidationError(
                {"motif": "Cette candidature n'a aucun bail à activer : ouvrez-la par l'assistant."}
            )
        brouillon.etat = Bail.ACTIF
        brouillon.save()
    if action == RESILIER:
        for bail in boutique.baux.filter(etat__in=[Bail.ACTIF, Bail.BROUILLON]):
            bail.etat = Bail.RESILIE
            bail.fin = aujourdhui
            bail.motif_resiliation = motif
            bail.save()

    ancien = boutique.get_etat_display()
    boutique.etat = arrivee
    boutique.save()

    tracer(
        par,
        ecran="boutique_etat",
        boutique_id=boutique.pk,
        motif=f"{ancien} → {boutique.get_etat_display()} : « {boutique.enseigne} »" + (f". {motif}" if motif else ""),
    )
    return boutique


# ----------------------------------------------------------------------------
# 6. Encaisser un loyer
# ----------------------------------------------------------------------------
ENCAISSABLES = frozenset({FactureLoyer.EMISE, FactureLoyer.IMPAYEE})


def refus_encaissement(facture: FactureLoyer) -> str | None:
    if facture.etat == FactureLoyer.PAYEE:
        quand = f" le {timezone.localtime(facture.paye_le):%d/%m/%Y}" if facture.paye_le else ""
        return f"Cette facture est déjà payée{quand} : l'encaisser deux fois compterait le loyer deux fois."
    if facture.etat == FactureLoyer.ANNULEE:
        return "Cette facture est annulée : il n'y a rien à encaisser."
    return None


@transaction.atomic
def encaisser_loyer(facture: FactureLoyer, *, par) -> FactureLoyer:
    """Marque une facture de loyer payée, et le trace.

    Aucune écriture comptable n'est passée : le dépôt n'en prévoit aucune pour le loyer, ni côté
    plateforme ni côté boutique, et en inventer une ici serait décider seul d'un schéma comptable.
    """
    _exiger(par, PLATEFORME_BOUTIQUES)
    facture = FactureLoyer.objects.select_for_update().select_related("bail__boutique").get(pk=facture.pk)
    refus = refus_encaissement(facture)
    if refus:
        raise ValidationError(refus)
    facture.etat = FactureLoyer.PAYEE
    facture.paye_le = timezone.now()
    facture.save()
    boutique = facture.bail.boutique
    tracer(
        par,
        ecran="loyer_encaisser",
        boutique_id=boutique.pk,
        motif=(
            f"Encaissement du loyer {facture.periode:%m/%Y} de « {boutique.enseigne} » : "
            f"{facture.montant_ttc:.0f} FCFA TTC"
        ),
    )
    return facture


# ----------------------------------------------------------------------------
# 7. Fixer le taux d'un rayon
# ----------------------------------------------------------------------------
def effet_du_taux(rayon: Rayon) -> dict:
    """Ce que change réellement le taux d'un rayon — ce qui n'est pas ce qu'on croit.

    `orders.services._taux_de_commission` prend d'abord le taux **du bail actif**, qui prime ; le
    taux du rayon ne s'applique qu'aux boutiques sans bail actif. Afficher « 12 boutiques
    concernées » alors que 11 ont un taux négocié serait mentir sur la portée du geste.
    """
    boutiques = Boutique.objects.filter(rayon_principal=rayon).exclude(etat=Boutique.RESILIEE)
    total = boutiques.count()
    avec_bail = boutiques.filter(baux__etat=Bail.ACTIF).distinct().count()
    return {"total": total, "avec_bail": avec_bail, "sans_bail": total - avec_bail}


def fixer_taux_rayon(rayon: Rayon, pourcent, *, par, motif: str) -> Rayon:
    """Saisie en pourcent (« 5 » = 5 %), convertie, puis confiée à `gouvernance.fixer_taux_rayon`.

    La gouvernance porte les trois refus (conflit d'intérêts, motif, plage) et écrit la trace :
    les refaire ici en ferait deux versions. On ne fait que la conversion — c'est elle qui évite
    le « 8 » saisi pour 8 % et lu comme 800 %.
    """
    from apps.marketplace import gouvernance

    _exiger(par, PLATEFORME_COMMISSIONS)
    taux = (Decimal(pourcent) / CENT).quantize(Decimal("0.0001"))
    return gouvernance.fixer_taux_rayon(rayon, taux, par=par, motif=motif)
