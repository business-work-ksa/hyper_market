"""La vérification d'une boutique : ce qu'on exige avant qu'elle vende, et qui a le droit de le dire.

**La règle.** Aucune boutique ne passe à l'état `active` tant que son identité et son compte de
versement n'ont pas été vérifiés, par deux personnes distinctes (docs/08, §5.3). Ce module est le
seul endroit où cette règle est écrite ; les quatre chemins qui activent une boutique — l'assistant
« ouvrir tout de suite », `valider`, `réactiver` et l'administration Django (`Boutique.clean`) —
l'appellent tous par `exiger_activable`, et le disent avec la même liste de manques.

**Ce qu'on vérifie** (`controles`) :

* le pays de la boutique est ouvert (`cemac.PAYS_OUVERTS`) — on ne vérifie pas un NIF gabonais
  qu'aucun juriste n'a encore relu ;
* chaque gérant a une pièce d'identité validée **et non expirée**, d'un type admis dans le pays ;
* chaque gérant a un téléphone vérifié — faute de passerelle SMS, par un **appel** de
  l'administration, attesté ici ; rien n'envoie de SMS, et rien ne prétend le faire ;
* le RCCM de la boutique est vérifié, **et c'est bien celui de la fiche** : un RCCM changé depuis
  sa vérification redevient un manque ;
* l'identifiant fiscal **du pays** est vérifié : NIU au Cameroun et au Congo, NIF ailleurs ;
* un compte de versement est vérifié, et son **titulaire** est la personne dont on a lu la pièce,
  ou la raison sociale (comparaison sans accents, sans casse, sans ordre des mots).

**Ce qu'on garde** : une attestation, pas une photocopie (voir `DossierKyc`). Une copie ne
s'enregistre que si un stockage persistant et privé est désigné par `KYC_STOCKAGE_COPIES`.

**Qui décide** (`refus_quatre_yeux`) : celui qui valide n'est ni celui qui a déclaré, ni celui qui
a ouvert la boutique dans la console, ni un membre de son équipe. Le superadministrateur compte
comme second regard ordinaire : il n'est pas exempté des règles, il est seulement admis à les
appliquer. Rejeter, en revanche, reste ouvert au déclarant : un refus n'ouvre rien, et celui qui
s'aperçoit de sa propre erreur doit pouvoir la retirer.

**Les boutiques déjà actives ne sont pas coupées.** Le verrou porte sur la *transition* vers
`active`. Celles qui vendaient avant cette règle paraissent dans la file « à régulariser » : les
couper d'un coup priverait des commerçants honnêtes de leurs ventes pour un dossier que personne
ne leur avait demandé.

Les refus métier sont des `ValidationError` ; les refus de droit des `PermissionDenied` — la même
distinction que `apps/plateforme/services.py`.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Appartenance, DossierKyc, Role
from apps.core.models import AccesPlateforme
from apps.marketplace import cemac
from apps.marketplace.models import Boutique, CompteVersement
from django.utils.translation import gettext as _

# Un changement de compte la veille d'un gros versement ne doit rien emporter : entre la
# vérification et le premier versement, deux jours pendant lesquels le gérant — prévenu — peut
# crier si ce n'est pas lui.
DELAI_DE_CARENCE = timedelta(hours=48)
# Une pièce qui expire dans le mois se renouvelle maintenant, pas le jour où elle bloque.
PREAVIS_EXPIRATION = timedelta(days=30)
# Au-delà, une photo de pièce n'est plus une photo de pièce.
TAILLE_MAX_COPIE = 5 * 1024 * 1024

# L'écran de l'assistant dont la trace désigne celui qui a ouvert la boutique.
ECRAN_OUVERTURE = "assistant_boutique"

_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")
_IBAN = re.compile(r"^[0-9A-Z]{10,34}$")
PUCES = "••••••"


# ----------------------------------------------------------------------------
# Petits outils : masquer, normaliser, comparer
# ----------------------------------------------------------------------------
def masquer(numero: str, visibles: int = 4) -> str:
    """`••••••4521` : assez pour reconnaître, trop peu pour usurper.

    Toujours six puces, quelle que soit la longueur : le nombre de puces ne doit pas trahir le
    type de pièce ni la longueur du numéro.
    """
    brut = re.sub(r"\s", "", numero or "")
    if len(brut) <= visibles:
        return PUCES
    return PUCES + brut[-visibles:]


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in decompose if not unicodedata.combining(c))


def normaliser_identifiant(numero: str) -> str:
    """`rc/dla/2024/b/1234` et `RC-DLA 2024 B 1234` sont le même RCCM."""
    return re.sub(r"[^0-9A-Z]", "", _sans_accents(numero).upper())


def empreinte_numero(numero: str) -> str:
    """L'empreinte **à clé** d'un numéro de pièce : ce qu'on garde à la place du numéro.

    HMAC-SHA256 du numéro normalisé, avec une clé dérivée de `SECRET_KEY` (ou de
    `KYC_CLE_NUMEROS`, si on veut pouvoir changer l'une sans perdre l'autre). Pourquoi une clé :
    un numéro de CNI a peu de chiffres, et une empreinte sans clé se retrouverait en essayant
    tous les numéros possibles en quelques minutes. Avec la clé, une sauvegarde volée ne livre
    rien ; et deux présentations de la même pièce donnent toujours la même empreinte, ce qui
    suffit à détecter une identité partagée.

    **À savoir avant de changer la clé :** les empreintes déjà en base ne se recalculent pas —
    on n'a plus les numéros. D'où la clé propre `KYC_CLE_NUMEROS`, qu'on ne tourne pas avec
    `SECRET_KEY`.
    """
    from django.utils.crypto import salted_hmac

    cle = getattr(settings, "KYC_CLE_NUMEROS", "") or settings.SECRET_KEY
    return salted_hmac(
        "hypermarche.confiance.numero-de-piece", normaliser_identifiant(numero), secret=cle, algorithm="sha256"
    ).hexdigest()


def fin_de_numero(numero: str) -> str:
    """Les quatre derniers caractères : de quoi reconnaître, pas de quoi usurper."""
    return normaliser_identifiant(numero)[-4:]


def normaliser_nom(nom: str) -> tuple[str, ...]:
    """Les mots d'un nom, sans accents ni casse, **triés**.

    Une carte d'identité écrit « NGONO MBARGA Marie-Claire », l'opérateur « Marie Claire Ngono
    Mbarga » : c'est la même personne. L'ordre des mots ne dit rien, les accents non plus — les
    systèmes des opérateurs les perdent souvent.
    """
    mots = re.sub(r"[^0-9a-z]+", " ", _sans_accents(nom).casefold()).split()
    return tuple(sorted(mots))


def noms_concordent(a: str, b: str) -> bool:
    na, nb = normaliser_nom(a), normaliser_nom(b)
    return bool(na) and na == nb


def pays_ou_none(code: str):
    try:
        return cemac.pays(code)
    except KeyError:
        return None


def sigle_fiscal(boutique) -> str:
    """NIU ou NIF, selon le pays : c'est le seul identifiant fiscal qu'on sait vérifier."""
    p = pays_ou_none(boutique.pays)
    return p.identifiant_fiscal if p else DossierKyc.NIU


def pieces_admises(code_pays: str) -> tuple[str, ...]:
    p = pays_ou_none(code_pays)
    return p.pieces if p else tuple(sorted(DossierKyc.PIECES_IDENTITE))


def operateurs_admis(code_pays: str) -> tuple[str, ...]:
    p = pays_ou_none(code_pays)
    return p.operateurs if p else ()


# ----------------------------------------------------------------------------
# Le stockage des copies : fermé par défaut
# ----------------------------------------------------------------------------
def stockage_des_copies():
    """Le stockage désigné pour garder les copies de pièces, ou `None` — le cas normal.

    Il faut un réglage **explicite**, `KYC_STOCKAGE_COPIES`, qui nomme une entrée de `STORAGES`.
    Le stockage `default` est refusé même s'il est nommé : en production, c'est le disque
    éphémère d'une fonction sans serveur (ADR-008), et en développement il est servi en clair
    sous `/media/`. Ni persistant ni privé : exactement ce qu'il ne faut pas pour une pièce
    d'identité.
    """
    from django.core.files.storage import InvalidStorageError, storages

    alias = getattr(settings, "KYC_STOCKAGE_COPIES", "") or ""
    if not alias or alias in {"default", "staticfiles"}:
        return None
    try:
        return storages[alias]
    except InvalidStorageError:
        return None


def empreinte_de(fichier) -> str:
    h = hashlib.sha256()
    for morceau in fichier.chunks():
        h.update(morceau)
    fichier.seek(0)
    return h.hexdigest()


# ----------------------------------------------------------------------------
# Qui est qui, autour d'une boutique
# ----------------------------------------------------------------------------
def gerants(boutique) -> list:
    """Les gérants en exercice. Chacun a tous les droits sur la boutique : chacun est vérifié."""
    return [
        a.utilisateur
        for a in Appartenance.objects.filter(
            boutique_id=boutique.pk, role_id=Role.GERANT, actif=True
        ).select_related("utilisateur").order_by("depuis", "utilisateur__nom_complet")
    ]


def _boutiques_du_sujet(dossier: DossierKyc) -> set:
    """Les boutiques qu'une pièce engage : celle du dossier, et toutes celles que tient son sujet."""
    ids = {dossier.boutique_id} if dossier.boutique_id else set()
    if dossier.utilisateur_id:
        ids |= set(
            Appartenance.objects.filter(utilisateur_id=dossier.utilisateur_id).values_list(
                "boutique_id", flat=True
            )
        )
    return ids


def refus_quatre_yeux(par, *, declare_par_id=None, boutique_ids=(), sujet_id=None, quoi="cet élément") -> str | None:
    """Pourquoi `par` ne peut pas valider — ou `None` s'il le peut.

    Quatre exclusions, dans l'ordre où on les rencontre :

    * **le déclarant** : celui qui a vu la pièce ou saisi le compte ne se relit pas lui-même ;
    * **le sujet** : on ne valide pas sa propre pièce ;
    * **l'équipe** : quiconque est ou a été rattaché à la boutique — y compris un ancien
      employé, parce qu'un conflit d'intérêts ne s'éteint pas avec le contrat ;
    * **l'ouvreur** : celui qui a ouvert la boutique dans la console (`cree_par`, ou la trace de
      l'assistant). Il l'a défendue une fois ; la relire, c'est le rôle d'un autre.
    """
    if par is None or not getattr(par, "pk", None):
        return "Aucun administrateur identifié : une validation se signe."
    ids = {i for i in boutique_ids if i}
    if declare_par_id and par.pk == declare_par_id:
        return (
            f"Vous avez vous-même déclaré {quoi}. Le second regard doit venir de quelqu'un "
            "d'autre : c'est tout l'intérêt des quatre yeux."
        )
    if sujet_id and par.pk == sujet_id:
        return "C'est votre propre pièce : on ne valide pas sa propre identité."
    if ids and Appartenance.objects.filter(utilisateur_id=par.pk, boutique_id__in=ids).exists():
        return (
            "Vous êtes, ou avez été, membre de l'équipe de cette boutique. Un regard de "
            "l'intérieur n'est pas un second regard : demandez à un autre administrateur."
        )
    if ids and (
        Boutique.objects.filter(pk__in=ids, cree_par_id=par.pk).exists()
        or AccesPlateforme.objects.filter(
            utilisateur_id=par.pk, boutique_id__in=ids, ecran=ECRAN_OUVERTURE
        ).exists()
    ):
        return (
            "Vous avez ouvert cette boutique dans la console. Celui qui a porté la candidature "
            "ne la vérifie pas : demandez à un autre administrateur."
        )
    return None


# ----------------------------------------------------------------------------
# Droits et trace
# ----------------------------------------------------------------------------
def _exiger_droit(par) -> None:
    """Le service revérifie le droit : un appel venu d'ailleurs qu'une vue n'hérite de rien."""
    from apps.accounts.permissions import PLATEFORME_BOUTIQUES
    from apps.plateforme.acces import droits_console_de

    if PLATEFORME_BOUTIQUES not in droits_console_de(par):
        raise PermissionDenied("Vérifier une boutique n'est pas ouvert à votre compte.")


def _tracer(par, *, ecran: str, motif: str, boutique_id=None) -> AccesPlateforme:
    return AccesPlateforme.objects.create(
        utilisateur=par, boutique_id=boutique_id, ecran=ecran[:120], motif=motif.strip()[:300]
    )


def _motif(motif: str, message: str) -> str:
    motif = (motif or "").strip()
    if len(motif) < 5:
        raise ValidationError({"motif": message})
    return motif


# ----------------------------------------------------------------------------
# Ce qui manque pour activer
# ----------------------------------------------------------------------------
@dataclass
class Controle:
    """Une ligne de la liste de contrôle : ce qu'on exige, et si c'est fait."""

    code: str
    titre: str  # ce qu'on exige, dit une fois pour toutes
    fait: bool
    manque: str = ""  # la phrase lisible quand ce n'est pas fait
    detail: str = ""  # ce qui a été vu, quand c'est fait (sans numéro complet)
    sujet: object | None = None  # le gérant concerné, s'il y en a un
    pieces: list = field(default_factory=list)


def _piece_identite_valide(utilisateur, code_pays: str, jour):
    """La pièce d'identité validée la plus lointaine à expirer — ou la dernière expirée."""
    pieces = list(
        DossierKyc.objects.filter(
            utilisateur_id=utilisateur.pk,
            type_piece__in=pieces_admises(code_pays),
            etat=DossierKyc.VALIDE,
        ).order_by("-expire_le", "-verifie_le")
    )
    en_cours = [p for p in pieces if not p.expire_avant(jour)]
    return (en_cours[0] if en_cours else None), (pieces[0] if pieces else None)


def _piece_de_boutique(boutique, type_piece: str, numero_fiche: str):
    """La pièce validée dont le numéro est **celui de la fiche** — et, à défaut, la dernière validée.

    La comparaison se fait sur les empreintes : le numéro validé n'est pas gardé, celui de la
    fiche l'est (il est public, au registre), et son empreinte se recalcule.
    """
    validees = list(
        DossierKyc.objects.filter(
            boutique_id=boutique.pk, type_piece=type_piece, etat=DossierKyc.VALIDE
        ).order_by("-verifie_le")
    )
    cible = empreinte_numero(numero_fiche) if normaliser_identifiant(numero_fiche) else ""
    concordante = next((d for d in validees if cible and d.numero_empreinte == cible), None)
    return concordante, (validees[0] if validees else None)


def noms_de_reference(boutique, *, jour=None) -> list[str]:
    """À quoi le titulaire d'un compte de versement doit correspondre.

    Le nom **lu sur la pièce validée** d'un gérant — pas celui du compte, qui se tape — ou la
    raison sociale, pour un compte ouvert au nom de l'entreprise.
    """
    jour = jour or timezone.localdate()
    noms = []
    for g in gerants(boutique):
        piece, _jour = _piece_identite_valide(g, boutique.pays, jour)
        if piece and piece.nom_lu:
            noms.append(piece.nom_lu)
    if boutique.raison_sociale:
        noms.append(boutique.raison_sociale)
    return noms


def titulaire_concorde(compte, boutique, *, jour=None) -> bool:
    return any(noms_concordent(compte.titulaire, n) for n in noms_de_reference(boutique, jour=jour))


def controles(boutique, *, jour=None) -> list[Controle]:
    """La liste de contrôle complète d'une boutique, faite ou non. Lue par les deux écrans.

    Fonctionne sur une boutique pas encore enregistrée (l'assistant, `Boutique.clean`) : tout y
    est filtré par identifiant, jamais par instance, et une boutique qui n'existe pas encore n'a
    simplement rien de vérifié.
    """
    jour = jour or timezone.localdate()
    p = pays_ou_none(boutique.pays)
    liste: list[Controle] = []

    # --- Le pays -----------------------------------------------------------------------------
    ouvert = boutique.pays in cemac.PAYS_OUVERTS
    nom_pays = p.nom if p else f"« {boutique.pays} »"
    liste.append(
        Controle(
            "pays",
            "Pays de la boutique ouvert sur le marché",
            ouvert,
            manque=(
                f"Le pays de la boutique ({nom_pays}) n'est pas encore ouvert sur le marché : ses "
                "règles d'identification n'ont pas été validées par un juriste local."
                if p
                else f"Le pays de la boutique ({nom_pays}) n'est pas un pays de la CEMAC."
            ),
            detail=nom_pays,
        )
    )

    # --- Les gérants ---------------------------------------------------------------------------
    equipe_gerante = gerants(boutique)
    if not equipe_gerante:
        liste.append(
            Controle(
                "gerant",
                "Un gérant rattaché",
                False,
                manque="Aucun gérant n'est rattaché à la boutique : il faut quelqu'un dont vérifier l'identité.",
            )
        )
    for g in equipe_gerante:
        piece, derniere = _piece_identite_valide(g, boutique.pays, jour)
        if piece:
            detail = f"{piece.get_type_piece_display()} {piece.numero_masque}"
            if piece.expire_le:
                detail += f", valable jusqu'au {piece.expire_le:%d/%m/%Y}"
            liste.append(Controle("identite", f"Pièce d'identité de {g.nom_complet}", True, detail=detail, sujet=g))
        elif derniere and derniere.expire_le:
            liste.append(
                Controle(
                    "identite",
                    f"Pièce d'identité de {g.nom_complet}",
                    False,
                    manque=(
                        f"La pièce d'identité de {g.nom_complet} a expiré le "
                        f"{derniere.expire_le:%d/%m/%Y} : une pièce en cours de validité doit être vérifiée."
                    ),
                    sujet=g,
                )
            )
        else:
            liste.append(
                Controle(
                    "identite",
                    f"Pièce d'identité de {g.nom_complet}",
                    False,
                    manque=f"La pièce d'identité du gérant {g.nom_complet} n'a pas été vérifiée.",
                    sujet=g,
                )
            )
        liste.append(
            Controle(
                "telephone",
                f"Téléphone de {g.nom_complet}",
                bool(g.telephone_verifie),
                manque=(
                    f"Le téléphone du gérant {g.nom_complet} n'a pas été vérifié : un administrateur "
                    "doit l'appeler et l'attester."
                ),
                detail=masquer(g.telephone, 3) if g.telephone_verifie else "",
                sujet=g,
            )
        )

    # --- RCCM ----------------------------------------------------------------------------------
    liste.append(_controle_piece_boutique(boutique, DossierKyc.RCCM, "RCCM", "RCCM de la boutique", boutique.rccm))

    # --- Identifiant fiscal du pays ------------------------------------------------------------
    sigle = sigle_fiscal(boutique)
    libelle = f"{sigle} ({p.libelle_identifiant_fiscal})" if p else sigle
    liste.append(_controle_piece_boutique(boutique, sigle, sigle, f"{libelle} de la boutique", boutique.niu))

    # --- Compte de versement -------------------------------------------------------------------
    liste.append(_controle_compte(boutique, jour))
    return liste


def _controle_piece_boutique(boutique, type_piece, sigle, titre, numero_fiche) -> Controle:
    if not (numero_fiche or "").strip():
        return Controle(type_piece, titre, False, manque=f"Le {sigle} de la boutique n'est pas renseigné.")
    concordante, derniere = _piece_de_boutique(boutique, type_piece, numero_fiche)
    if concordante:
        return Controle(type_piece, titre, True, detail=f"{sigle} {concordante.numero_masque}")
    if derniere:
        return Controle(
            type_piece,
            titre,
            False,
            manque=f"Le {sigle} de la boutique a changé depuis sa vérification : le nouveau numéro doit être vérifié.",
        )
    return Controle(type_piece, titre, False, manque=f"Le {sigle} de la boutique n'a pas été vérifié.")


def _controle_compte(boutique, jour) -> Controle:
    titre = "Compte de versement vérifié, au nom du gérant ou de la société"
    compte = CompteVersement.objects.filter(boutique_id=boutique.pk, etat=CompteVersement.VERIFIE).first()
    if compte is None:
        return Controle("compte", titre, False, manque="Aucun compte de versement vérifié.")
    if compte.operateur not in operateurs_admis(boutique.pays):
        return Controle(
            "compte",
            titre,
            False,
            manque=f"Le compte de versement vérifié ({compte.get_operateur_display()}) n'est pas un opérateur du pays de la boutique.",
        )
    if not titulaire_concorde(compte, boutique, jour=jour):
        return Controle(
            "compte",
            titre,
            False,
            manque=(
                f"Le titulaire du compte de versement (« {compte.titulaire} ») ne correspond ni au "
                "nom lu sur la pièce du gérant, ni à la raison sociale."
            ),
        )
    return Controle(
        "compte", titre, True, detail=f"{compte.get_operateur_display()} {masquer(compte.numero)} · {compte.titulaire}"
    )


def manques_pour_activer(boutique) -> list[str]:
    """Ce qui manque pour que la boutique passe à l'état actif, en phrases. Vide : elle le peut."""
    return [c.manque for c in controles(boutique) if not c.fait]


class VerificationIncomplete(ValidationError):
    """Le refus du verrou d'activation : une `ValidationError` qui garde aussi la liste des manques.

    Une `ValidationError` ordinaire suffirait pour afficher les phrases ; la sous-classe permet à
    un écran de les montrer comme une **liste de contrôle**, avec le lien vers le dossier, plutôt
    que comme une erreur de saisie sous un champ qui n'y est pour rien.
    """

    INTRO = "La boutique ne peut pas être activée tant que sa vérification n'est pas complète."

    def __init__(self, manques: list[str]):
        self.manques = list(manques)
        super().__init__([self.INTRO] + self.manques)


def exiger_activable(boutique) -> None:
    """Le verrou d'activation. Lève `VerificationIncomplete`, qui porte la liste des manques."""
    manques = manques_pour_activer(boutique)
    if manques:
        raise VerificationIncomplete(manques)


# ----------------------------------------------------------------------------
# Les pièces : attester, valider, rejeter
# ----------------------------------------------------------------------------
@transaction.atomic
def attester_piece(
    boutique,
    *,
    par,
    type_piece: str,
    numero: str,
    mode: str,
    utilisateur=None,
    pays: str = "",
    expire_le=None,
    nom_lu: str = "",
    empreinte: str = "",
    copie=None,
) -> DossierKyc:
    """Consigne ce qu'un administrateur a vu. La pièce attend ensuite un **second** regard.

    Ce qui est refusé ici, et pourquoi :

    * une pièce d'identité **déjà expirée** : l'attester serait consigner un refus ;
    * un identifiant fiscal qui n'est pas celui du pays — un « NIU » au Gabon ne veut rien dire ;
    * un RCCM ou un NIU qui diffère de la fiche : c'est la fiche qu'on vérifie, et deux numéros
      pour une même boutique, c'est une question à poser avant, pas un dossier à valider ;
    * un document reçu sans son empreinte : sans elle, rien ne prouvera qu'on l'a vu ;
    * une copie, si aucun stockage persistant n'est désigné.
    """
    _exiger_droit(par)
    boutique = Boutique.objects.select_for_update().get(pk=boutique.pk)
    jour = timezone.localdate()
    erreurs: dict[str, str] = {}
    numero = re.sub(r"\s+", " ", (numero or "").strip()).upper()
    empreinte = (empreinte or "").strip().lower()
    nom_lu = re.sub(r"\s+", " ", (nom_lu or "").strip())
    pays = (pays or "").strip().upper()

    if type_piece not in dict(DossierKyc.TYPES_PIECE) or type_piece == DossierKyc.TELEPHONE:
        raise ValidationError({"type_piece": "Type de pièce inconnu."})
    if mode not in {DossierKyc.PRESENTIEL, DossierKyc.VISIO, DossierKyc.DOCUMENT_RECU}:
        erreurs["mode"] = "Dites comment vous avez vu l'original : en présentiel, en visio, ou sur un document reçu."
    if not numero:
        erreurs["numero"] = "Le numéro lu sur la pièce est obligatoire."

    if type_piece in DossierKyc.PIECES_IDENTITE:
        if type_piece not in pieces_admises(boutique.pays):
            erreurs["type_piece"] = "Cette pièce n'est pas admise dans le pays de la boutique."
        if utilisateur is None or utilisateur not in gerants(boutique):
            erreurs["utilisateur"] = "Une pièce d'identité est celle d'un gérant de la boutique : choisissez-le."
        if not re.fullmatch(r"[A-Z]{2}", pays):
            erreurs["pays"] = "Le pays émetteur s'écrit en deux lettres (CM, GA, CG, TD, CF, GQ…)."
        if expire_le is None:
            erreurs["expire_le"] = "Une pièce d'identité a une date d'expiration : recopiez-la."
        elif expire_le < jour:
            erreurs["expire_le"] = (
                f"Cette pièce a expiré le {expire_le:%d/%m/%Y}. Une pièce expirée ne s'atteste pas : "
                "demandez-en une en cours de validité."
            )
        if len(nom_lu) < 3:
            erreurs["nom_lu"] = "Recopiez le nom tel qu'il figure sur la pièce : c'est lui qu'on comparera au titulaire du compte."
    else:
        utilisateur = None
        pays = boutique.pays
        sigle = sigle_fiscal(boutique)
        if type_piece in {DossierKyc.NIU, DossierKyc.NIF} and type_piece != sigle:
            p = pays_ou_none(boutique.pays)
            erreurs["type_piece"] = (
                f"{'Au ' + p.nom if p else 'Dans ce pays'}, l'identifiant fiscal est le {sigle}, pas le {type_piece}."
            )
        champ = "rccm" if type_piece == DossierKyc.RCCM else "niu"
        fiche = getattr(boutique, champ)
        if numero and fiche and normaliser_identifiant(fiche) != normaliser_identifiant(numero):
            erreurs["numero"] = (
                f"Le numéro lu ({numero}) diffère de celui de la fiche ({fiche}). Corrigez d'abord la "
                "fiche de la boutique, ou demandez le bon document : on vérifie la fiche, pas un autre numéro."
            )
        elif numero and not fiche and "numero" not in erreurs:
            # La fiche était vide : le numéro lu sur l'original la complète.
            setattr(boutique, champ, numero)
            boutique.save(update_fields=[champ, "modifie_le"])

    stockage = None
    if copie is not None:
        stockage = stockage_des_copies()
        if stockage is None:
            erreurs["copie"] = (
                "Aucun stockage persistant n'est désigné pour les pièces : la copie n'est pas "
                "conservée. Attestez ce que vous avez vu, avec l'empreinte du document."
            )
        elif copie.size > TAILLE_MAX_COPIE:
            erreurs["copie"] = "La copie dépasse 5 Mo."
        else:
            empreinte = empreinte_de(copie)
    if mode == DossierKyc.DOCUMENT_RECU and not empreinte and "copie" not in erreurs:
        erreurs["empreinte"] = (
            "Un document reçu laisse son empreinte : calculez-la avant de le supprimer. C'est la "
            "preuve, plus tard, que c'est bien ce document-là que vous avez vu."
        )
    if empreinte and not _EMPREINTE.fullmatch(empreinte):
        erreurs["empreinte"] = "Une empreinte SHA-256 s'écrit en 64 caractères hexadécimaux."

    sujet = {"utilisateur_id": utilisateur.pk} if utilisateur else {"boutique_id": boutique.pk}
    if not erreurs and DossierKyc.objects.filter(type_piece=type_piece, etat=DossierKyc.EN_ATTENTE, **sujet).exists():
        erreurs["type_piece"] = "Une attestation de cette pièce attend déjà sa validation : décidez-la d'abord."
    if erreurs:
        raise ValidationError(erreurs)

    dossier = DossierKyc.objects.create(
        utilisateur=utilisateur,
        boutique=boutique,
        type_piece=type_piece,
        # Le numéro lu ne quitte pas cette fonction : on n'en garde que l'empreinte et la fin.
        numero_empreinte=empreinte_numero(numero),
        numero_fin=fin_de_numero(numero),
        pays=pays,
        expire_le=expire_le if type_piece in DossierKyc.PIECES_IDENTITE else None,
        nom_lu=nom_lu,
        mode_verification=mode,
        empreinte=empreinte,
        declare_par=par,
    )
    if stockage is not None:
        # Nom imprévisible, sans le nom ni le numéro de la personne : le chemin d'un fichier
        # finit dans des journaux.
        dossier.copie = stockage.save(f"kyc/{dossier.pk}/{secrets.token_hex(12)}", copie)
        dossier.save(update_fields=["copie"])

    _tracer(
        par,
        ecran="verification_attester",
        boutique_id=boutique.pk,
        motif=(
            f"Attestation {dossier.get_type_piece_display()} {dossier.numero_masque}"
            + (f" de {utilisateur.nom_complet}" if utilisateur else "")
            + f" — {dossier.get_mode_verification_display().lower()}"
            + (", copie conservée" if dossier.copie else ", sans copie")
        ),
    )
    return dossier


def alertes_piece(dossier: DossierKyc) -> list[str]:
    """Ce qu'un vérificateur doit savoir avant de valider — sans que ce soit un refus automatique."""
    alertes = []
    autres = DossierKyc.objects.filter(
        type_piece=dossier.type_piece, etat=DossierKyc.VALIDE, numero_empreinte=dossier.numero_empreinte
    ).exclude(pk=dossier.pk)
    if dossier.est_piece_identite:
        if autres.exclude(utilisateur_id=dossier.utilisateur_id).exists():
            alertes.append(
                "Ce numéro de pièce est déjà validé pour une autre personne. Une même pièce pour deux "
                "comptes est le signe d'une usurpation : la validation est bloquée."
            )
        if dossier.utilisateur_id and dossier.nom_lu and not noms_concordent(dossier.nom_lu, dossier.utilisateur.nom_complet):
            alertes.append(
                f"Le nom lu (« {dossier.nom_lu} ») diffère du nom du compte (« {dossier.utilisateur.nom_complet} »). "
                "Ce n'est pas forcément une fraude — un surnom, un nom d'usage — mais vérifiez-le."
            )
        if dossier.expire_le and dossier.expire_le < timezone.localdate() + PREAVIS_EXPIRATION:
            alertes.append(f"Cette pièce expire le {dossier.expire_le:%d/%m/%Y}, dans moins d'un mois.")
    else:
        if autres.exclude(boutique_id=dossier.boutique_id).exists():
            alertes.append(
                "Ce numéro est déjà vérifié pour une autre boutique. Deux enseignes d'une même société, "
                "c'est possible ; une société qui ne le sait pas, non : vérifiez."
            )
    return alertes


def _usurpation(dossier: DossierKyc) -> bool:
    """La même pièce déjà validée pour une autre personne : comparée par empreinte, en base."""
    if not dossier.est_piece_identite:
        return False
    return (
        DossierKyc.objects.filter(
            type_piece=dossier.type_piece, etat=DossierKyc.VALIDE, numero_empreinte=dossier.numero_empreinte
        )
        .exclude(pk=dossier.pk)
        .exclude(utilisateur_id=dossier.utilisateur_id)
        .exists()
    )


@transaction.atomic
def valider_piece(dossier: DossierKyc, *, par) -> DossierKyc:
    """Le second regard. Refusé au déclarant, au sujet, à l'équipe et à l'ouvreur."""
    _exiger_droit(par)
    dossier = DossierKyc.objects.select_for_update(of=("self",)).select_related("utilisateur", "boutique").get(pk=dossier.pk)
    if dossier.etat != DossierKyc.EN_ATTENTE:
        raise ValidationError(_('Cette pièce est déjà %(lower)se : rien à décider.') % {"lower": dossier.get_etat_display().lower()})
    refus = refus_quatre_yeux(
        par,
        declare_par_id=dossier.declare_par_id,
        boutique_ids=_boutiques_du_sujet(dossier),
        sujet_id=dossier.utilisateur_id,
        quoi="cette pièce",
    )
    if refus:
        raise PermissionDenied(refus)
    if dossier.expire_avant(timezone.localdate()):
        raise ValidationError(
            _('Cette pièce a expiré le %(expire_le)s depuis son attestation : rejetez-la, et demandez-en une en cours de validité.') % {"expire_le": format(dossier.expire_le, "%d/%m/%Y")}
        )
    if _usurpation(dossier):
        raise ValidationError(
            _("Ce numéro de pièce est déjà validé pour une autre personne : la validation est bloquée. "
            "Rejetez l'attestation, ou retirez d'abord la pièce validée par erreur.")
        )
    dossier.etat = DossierKyc.VALIDE
    dossier.verifie_par = par
    dossier.verifie_le = timezone.now()
    dossier.motif_rejet = ""
    dossier.save(update_fields=["etat", "verifie_par", "verifie_le", "motif_rejet"])
    _tracer(
        par,
        ecran="verification_piece",
        boutique_id=dossier.boutique_id,
        motif=(
            f"Validation {dossier.get_type_piece_display()} {dossier.numero_masque}"
            + (f" de {dossier.utilisateur.nom_complet}" if dossier.utilisateur_id else "")
        ),
    )
    return dossier


@transaction.atomic
def rejeter_piece(dossier: DossierKyc, *, par, motif: str) -> DossierKyc:
    """Rejeter, avec une raison que le commerçant lira. Ouvert au déclarant : un refus n'ouvre rien."""
    _exiger_droit(par)
    motif = _motif(motif, "Dites pourquoi : le commerçant lira ce motif pour corriger son dossier.")
    dossier = DossierKyc.objects.select_for_update().get(pk=dossier.pk)
    if dossier.etat != DossierKyc.EN_ATTENTE:
        raise ValidationError(_('Cette pièce est déjà %(lower)se : rien à décider.') % {"lower": dossier.get_etat_display().lower()})
    dossier.etat = DossierKyc.REJETE
    dossier.motif_rejet = motif
    dossier.verifie_le = timezone.now()
    # `verifie_par` reste vide si le déclarant rejette sa propre attestation : la contrainte des
    # quatre yeux porte sur la validation, et la trace dit qui a rejeté.
    dossier.verifie_par = par if par.pk != dossier.declare_par_id else None
    dossier.save(update_fields=["etat", "motif_rejet", "verifie_le", "verifie_par"])
    _tracer(
        par,
        ecran="verification_piece",
        boutique_id=dossier.boutique_id,
        motif=f"Rejet {dossier.get_type_piece_display()} {dossier.numero_masque} : {motif}",
    )
    return dossier


@transaction.atomic
def attester_appel(boutique, gerant, *, par, note: str = "") -> DossierKyc:
    """L'administrateur a appelé le gérant à son numéro, et c'est bien lui qui a répondu.

    Il n'existe pas de passerelle SMS : on ne fait pas semblant d'en avoir une. L'appel est
    lui-même le second regard — le numéro a été déclaré par le gérant, il est vérifié par un
    administrateur qui n'est ni l'ouvreur ni de l'équipe. D'où une attestation validée d'emblée.
    """
    _exiger_droit(par)
    boutique = Boutique.objects.get(pk=boutique.pk)
    if gerant not in gerants(boutique):
        raise ValidationError({"gerant": "Ce compte n'est pas gérant de la boutique."})
    refus = refus_quatre_yeux(
        par, boutique_ids={boutique.pk}, sujet_id=gerant.pk, quoi="ce téléphone"
    )
    if refus:
        raise PermissionDenied(refus)
    pays_du_numero = cemac.pays_du_numero(gerant.telephone)
    dossier = DossierKyc.objects.create(
        utilisateur=gerant,
        boutique=boutique,
        type_piece=DossierKyc.TELEPHONE,
        numero_empreinte=empreinte_numero(gerant.telephone),
        numero_fin=fin_de_numero(gerant.telephone),
        pays=pays_du_numero.code if pays_du_numero else boutique.pays,
        nom_lu=gerant.nom_complet,
        mode_verification=DossierKyc.APPEL,
        etat=DossierKyc.VALIDE,
        verifie_par=par,
        verifie_le=timezone.now(),
    )
    gerant.telephone_verifie = True
    gerant.save(update_fields=["telephone_verifie"])
    _tracer(
        par,
        ecran="verification_appel",
        boutique_id=boutique.pk,
        motif=f"Appel de vérification du téléphone {masquer(gerant.telephone, 3)} de {gerant.nom_complet}"
        + (f" — {note.strip()}" if (note or "").strip() else ""),
    )
    return dossier


# ----------------------------------------------------------------------------
# Le compte de versement
# ----------------------------------------------------------------------------
def normaliser_numero_compte(numero: str) -> str:
    return re.sub(r"[\s.\-]", "", (numero or "")).upper()


def _verifier_saisie_compte(boutique, operateur: str, numero: str, titulaire: str) -> dict:
    erreurs = {}
    p = pays_ou_none(boutique.pays)
    if operateur not in operateurs_admis(boutique.pays):
        admis = ", ".join(cemac.LIBELLES_OPERATEURS[o] for o in operateurs_admis(boutique.pays)) or "aucun"
        erreurs["operateur"] = (
            f"Cet opérateur n'est pas proposé {'au ' + p.nom if p else 'dans ce pays'}. Opérateurs admis : {admis}."
        )
    elif operateur == cemac.VIREMENT_BANCAIRE:
        if not _IBAN.fullmatch(numero):
            erreurs["numero"] = "Un RIB ou un IBAN s'écrit en 10 à 34 lettres et chiffres, sans espace."
    elif not cemac.numero_valide(numero, boutique.pays):
        erreurs["numero"] = (
            f"Numéro Mobile Money invalide : attendu {p.indicatif} suivi de {p.longueur_numero} chiffres."
        )
    if len(normaliser_nom(titulaire)) < 1 or len((titulaire or "").strip()) < 3:
        erreurs["titulaire"] = "Le nom du titulaire, tel que l'opérateur l'affiche, est obligatoire."
    return erreurs


@transaction.atomic
def declarer_compte(boutique, *, par, operateur: str, numero: str, titulaire: str, depuis_console: bool = False) -> CompteVersement:
    """Déclarer où verser : par le gérant depuis son back-office, ou par un administrateur.

    La déclaration n'ouvre rien : le compte attend la vérification d'un administrateur **autre**
    que le déclarant, puis un délai de carence. Une déclaration encore en attente est retirée par
    la suivante — jamais supprimée : il faut pouvoir dire, plus tard, qui a proposé quel numéro.
    """
    if depuis_console:
        _exiger_droit(par)
    else:
        from apps.accounts.permissions import BOUTIQUE_ADMINISTRER, droits_de

        if BOUTIQUE_ADMINISTRER not in droits_de(par, boutique):
            raise PermissionDenied("Seul un gérant déclare le compte de versement de la boutique.")
    boutique = Boutique.objects.select_for_update().get(pk=boutique.pk)
    numero = normaliser_numero_compte(numero)
    titulaire = re.sub(r"\s+", " ", (titulaire or "").strip())
    erreurs = _verifier_saisie_compte(boutique, operateur, numero, titulaire)
    if erreurs:
        raise ValidationError(erreurs)

    maintenant = timezone.now()
    for ancien in CompteVersement.objects.select_for_update().filter(boutique=boutique, etat=CompteVersement.EN_ATTENTE):
        ancien.etat = CompteVersement.RETIRE
        ancien.retire_le = maintenant
        ancien.motif = "Remplacé par une nouvelle déclaration avant vérification."
        ancien.save(update_fields=["etat", "retire_le", "motif", "modifie_le"])

    compte = CompteVersement.objects.create(
        boutique=boutique,
        pays=boutique.pays,
        operateur=operateur,
        numero=numero,
        titulaire=titulaire,
        declare_par=par,
        cree_par=par,
    )
    if depuis_console:
        _tracer(
            par,
            ecran="verification_compte_declarer",
            boutique_id=boutique.pk,
            motif=f"Déclaration du compte de versement {compte.get_operateur_display()} {masquer(numero)} au nom de « {titulaire} »",
        )
    return compte


@transaction.atomic
def verifier_compte(compte: CompteVersement, *, par) -> CompteVersement:
    """Vérifier un compte, retirer le précédent, et poser le délai de carence.

    À la vérification, le compte vérifié précédent passe `retire` — jamais supprimé — et le
    nouveau n'est **utilisable** qu'après `DELAI_DE_CARENCE`. Pendant ce délai, aucun compte n'est
    utilisable : les versements attendent. C'est voulu : si ce changement est une fraude, rien
    n'est parti avant que le gérant, prévenu, ait pu le dire.
    """
    _exiger_droit(par)
    compte = CompteVersement.objects.select_for_update().select_related("boutique").get(pk=compte.pk)
    boutique = compte.boutique
    if compte.etat != CompteVersement.EN_ATTENTE:
        raise ValidationError(_('Ce compte est déjà « %(lower)s » : rien à décider.') % {"lower": compte.get_etat_display().lower()})
    refus = refus_quatre_yeux(par, declare_par_id=compte.declare_par_id, boutique_ids={boutique.pk}, quoi="ce compte")
    if refus:
        raise PermissionDenied(refus)
    erreurs = _verifier_saisie_compte(boutique, compte.operateur, compte.numero, compte.titulaire)
    if compte.pays != boutique.pays:
        erreurs["operateur"] = "Ce compte a été déclaré pour un autre pays que celui de la boutique."
    if erreurs:
        raise ValidationError(list(erreurs.values()))
    if not titulaire_concorde(compte, boutique):
        pieces = [n for n in noms_de_reference(boutique) if n != boutique.raison_sociale]
        suite = (
            f"le nom lu sur la pièce du gérant (« {' », « '.join(pieces)} »)"
            if pieces
            else "la pièce du gérant — qui n'est pas encore validée : validez-la d'abord, c'est à elle qu'on compare"
        )
        raise ValidationError(
            _("Le titulaire « %(titulaire)s » ne correspond ni à %(suite)s, ni à la raison sociale (« %(raison_sociale)s »). Un compte au nom d'un tiers ne reçoit pas l'argent de la boutique.") % {"titulaire": compte.titulaire, "suite": suite, "raison_sociale": boutique.raison_sociale}
        )

    maintenant = timezone.now()
    for ancien in CompteVersement.objects.select_for_update().filter(boutique=boutique, etat=CompteVersement.VERIFIE):
        ancien.etat = CompteVersement.RETIRE
        ancien.retire_le = maintenant
        ancien.motif = f"Remplacé par le compte {compte.get_operateur_display()} {masquer(compte.numero)}."
        ancien.save(update_fields=["etat", "retire_le", "motif", "modifie_le"])

    compte.etat = CompteVersement.VERIFIE
    compte.verifie_par = par
    compte.verifie_le = maintenant
    compte.utilisable_le = maintenant + DELAI_DE_CARENCE
    compte.motif = ""
    compte.save(update_fields=["etat", "verifie_par", "verifie_le", "utilisable_le", "motif", "modifie_le"])
    _tracer(
        par,
        ecran="verification_compte",
        boutique_id=boutique.pk,
        motif=(
            f"Vérification du compte de versement {compte.get_operateur_display()} {masquer(compte.numero)} "
            f"de « {boutique.enseigne} » — utilisable le {timezone.localtime(compte.utilisable_le):%d/%m/%Y à %H:%M}"
        ),
    )
    return compte


@transaction.atomic
def rejeter_compte(compte: CompteVersement, *, par, motif: str) -> CompteVersement:
    _exiger_droit(par)
    motif = _motif(motif, "Dites pourquoi : le commerçant lira ce motif pour déclarer le bon compte.")
    compte = CompteVersement.objects.select_for_update().select_related("boutique").get(pk=compte.pk)
    if compte.etat != CompteVersement.EN_ATTENTE:
        raise ValidationError(_('Ce compte est déjà « %(lower)s » : rien à décider.') % {"lower": compte.get_etat_display().lower()})
    compte.etat = CompteVersement.REJETE
    compte.motif = motif[:300]
    compte.save(update_fields=["etat", "motif", "modifie_le"])
    _tracer(
        par,
        ecran="verification_compte",
        boutique_id=compte.boutique_id,
        motif=f"Rejet du compte de versement {compte.get_operateur_display()} {masquer(compte.numero)} : {motif}",
    )
    return compte


def alertes_compte(compte: CompteVersement) -> list[str]:
    """Le même numéro de versement ailleurs : une personne, plusieurs vitrines (docs/23, §2.5)."""
    autres = (
        CompteVersement.objects.filter(numero=compte.numero, etat__in=[CompteVersement.VERIFIE, CompteVersement.EN_ATTENTE])
        .exclude(boutique_id=compte.boutique_id)
        .select_related("boutique")
    )
    return [
        f"Ce numéro est aussi déclaré pour « {a.boutique.enseigne} » ({a.boutique.get_etat_display().lower()}). "
        "Un même propriétaire, c'est son droit ; une boutique suspendue qui renaît sous un autre nom, non."
        for a in autres[:3]
    ]


def compte_de_versement_utilisable(boutique, *, maintenant=None) -> CompteVersement | None:
    """Le compte où verser **aujourd'hui**, ou `None` : aucun vérifié, ou délai de carence en cours.

    Point d'entrée des versements. `None` veut dire « on ne verse pas », jamais « on verse
    ailleurs » : il n'y a pas de repli sur l'ancien compte, retiré précisément pour ne plus
    recevoir.
    """
    maintenant = maintenant or timezone.now()
    return (
        CompteVersement.objects.filter(
            boutique_id=getattr(boutique, "pk", boutique),
            etat=CompteVersement.VERIFIE,
            utilisable_le__isnull=False,
            utilisable_le__lte=maintenant,
        )
        .order_by("-verifie_le")
        .first()
    )


# ----------------------------------------------------------------------------
# La file de la console
# ----------------------------------------------------------------------------
def file_des_verifications(*, jour=None) -> dict:
    """Ce qui attend un geste, par nature. Rien n'y porte un numéro en clair."""
    jour = jour or timezone.localdate()
    candidatures, pretes, a_regulariser = [], [], []
    for b in Boutique.objects.filter(etat__in=[Boutique.CANDIDATURE, Boutique.ACTIVE]).order_by("enseigne"):
        manques = manques_pour_activer(b)
        if b.etat == Boutique.CANDIDATURE:
            (candidatures if manques else pretes).append({"boutique": b, "manques": manques})
        elif manques:
            a_regulariser.append({"boutique": b, "manques": manques})
    return {
        "pieces": list(
            DossierKyc.objects.filter(etat=DossierKyc.EN_ATTENTE)
            .select_related("utilisateur", "boutique", "declare_par")
            .order_by("cree_le")
        ),
        "comptes": list(
            CompteVersement.objects.filter(etat=CompteVersement.EN_ATTENTE)
            .select_related("boutique", "declare_par")
            .order_by("cree_le")
        ),
        "candidatures": candidatures,
        "pretes": pretes,
        "a_regulariser": a_regulariser,
        "expirent": list(
            DossierKyc.objects.filter(
                etat=DossierKyc.VALIDE,
                type_piece__in=DossierKyc.PIECES_IDENTITE,
                expire_le__gte=jour,
                expire_le__lte=jour + PREAVIS_EXPIRATION,
            )
            .select_related("utilisateur", "boutique")
            .order_by("expire_le")
        ),
    }


# ----------------------------------------------------------------------------
# L'avis au gérant : « un compte de versement a été déclaré pour votre boutique »
# ----------------------------------------------------------------------------
# Le délai de carence ne protège que si quelqu'un regarde pendant qu'il court. Le gérant est la seule
# personne qui sait avec certitude si un numéro est le sien. Chaque compte déclaré par **quelqu'un
# d'autre que lui** — un employé, un administrateur, un voleur de mot de passe — lui est donc montré
# dans son back-office, avec deux réponses : « c'est bien moi » ou « ce n'est pas moi ».
#
# Pas de SMS : aucune passerelle n'est branchée, et un avis inventé serait pire qu'aucun. L'avis vit
# dans le back-office, où le gérant passe chaque jour ; le délai de carence lui en laisse le temps.
FENETRE_AVIS = timedelta(days=14)


def comptes_a_confirmer(boutique, gerant) -> list:
    """Les comptes déclarés récemment par un autre que ce gérant, auxquels il n'a pas répondu."""
    if boutique is None or gerant is None:
        return []
    return list(
        CompteVersement.objects.filter(
            boutique_id=boutique.pk,
            etat__in=[CompteVersement.EN_ATTENTE, CompteVersement.VERIFIE],
            confirme_par_gerant_le__isnull=True,
            conteste_le__isnull=True,
            cree_le__gte=timezone.now() - FENETRE_AVIS,
        )
        .exclude(declare_par_id=gerant.pk)
        .order_by("-cree_le")
    )


def _exiger_gerant(compte, par) -> None:
    if par is None or par.pk not in {g.pk for g in gerants(compte.boutique)}:
        raise PermissionDenied("Seul un gérant de la boutique répond pour son compte de versement.")


@transaction.atomic
def confirmer_compte_par_gerant(compte, *, par) -> CompteVersement:
    """« C'est bien moi » : l'avis disparaît. Rien d'autre ne change — la vérification suit son cours."""
    compte = CompteVersement.objects.select_for_update().select_related("boutique").get(pk=compte.pk)
    _exiger_gerant(compte, par)
    if compte.conteste_le is None and compte.confirme_par_gerant_le is None:
        compte.confirme_par_gerant_le = timezone.now()
        compte.save(update_fields=["confirme_par_gerant_le", "modifie_le"])
    return compte


def contester_compte(compte, *, par) -> CompteVersement:
    """« Ce n'est pas moi » : le compte est retiré, les versements qui y partaient sont annulés, et
    la plateforme reçoit un signal critique. Un humain enquête ; rien ne part entre-temps.

    Le compte n'est pas supprimé : qui l'a déclaré, quand, et vers quel numéro, c'est précisément ce
    que l'enquête lira.
    """
    from apps.confiance.models import SignalRisque
    from apps.confiance.signaux import Constat, enregistrer
    from apps.payments.models import Versement
    from apps.payments.versements import VersementRefuse, annuler_versement

    maintenant = timezone.now()
    with transaction.atomic():
        compte = CompteVersement.objects.select_for_update(of=("self",)).select_related("boutique", "declare_par").get(pk=compte.pk)
        _exiger_gerant(compte, par)
        if compte.conteste_le is not None:
            return compte
        compte.conteste_le = maintenant
        compte.conteste_par = par
        if compte.etat in (CompteVersement.EN_ATTENTE, CompteVersement.VERIFIE):
            compte.etat = CompteVersement.RETIRE
            compte.retire_le = maintenant
        compte.motif = "Contesté par le gérant : il ne l'a pas déclaré."
        compte.save(update_fields=["conteste_le", "conteste_par", "etat", "retire_le", "motif", "modifie_le"])

    annules = 0
    for versement in Versement.objects.filter(compte=compte, etat=Versement.DEMANDE):
        try:
            annuler_versement(versement, motif="Compte de destination contesté par le gérant.", par=par)
            annules += 1
        except VersementRefuse:
            pass

    declarant = compte.declare_par.nom_complet if compte.declare_par_id else "inconnu"
    enregistrer(
        Constat(
            boutique_id=compte.boutique_id,
            type=SignalRisque.CHANGEMENT_COMPTE,
            gravite=SignalRisque.CRITIQUE,
            score=100,
            resume=(
                f"Le gérant conteste le compte {compte.get_operateur_display()} {masquer(compte.numero)} "
                f"déclaré par {declarant}."
            )[:240],
            preuves={
                "compte": str(compte.pk),
                "numero": masquer(compte.numero),
                "declare_par": declarant,
                "declare_le": compte.cree_le.isoformat(timespec="minutes"),
                "conteste_par": par.nom_complet,
                "versements_annules": annules,
            },
            faits=[f"conteste:{compte.pk}"],
        ),
        maintenant=maintenant,
    )
    return compte
