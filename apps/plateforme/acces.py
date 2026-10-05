"""La porte de la console de la plateforme, et le motif qui l'accompagne.

La console est l'écran de travail des deux personnages d'administration de l'ADR-012 :

* le **superadministrateur** (`is_superuser`), qui administre tout — il reçoit ici tous les
  droits de plateforme, plus les écrans qui lui sont réservés (nommer les administrateurs du
  marché, la santé technique) ;
* l'**administrateur du marché** (`is_staff` + `RolePlateforme`), qui reçoit exactement les
  droits `plateforme.*` que son rôle porte, et rien d'autre.

Ce que la console lit, et pourquoi c'est sans risque
----------------------------------------------------

Les boutiques, les baux, les factures de loyer, les emplacements premium, les rayons et les
offres **ne sont pas scopés** : ce sont les contrats du bailleur, pas les données du locataire.
Les lire ne franchit aucune barrière — la plupart des écrans de la console n'en franchissent
donc aucune.

Ce qui franchit une barrière — l'activité agrégée d'une boutique, lue dans des tables scopées —
passe par `acces_plateforme()`, et laisse une ligne dans le journal en ajout seul. Le motif est
demandé **une fois par session de suivi** (`ouvrir_suivi`), puis rappelé à chaque écran : chaque
lecture reste journalisée, mais l'administrateur n'a pas à retaper sa raison à chaque clic. Un
journal qu'on remplit de motifs inventés pour passer ne vaut pas mieux qu'un journal absent.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.permissions import TOUS_PLATEFORME, droits_plateforme_de
from apps.core.tenancy import acces_plateforme
from django.utils.translation import gettext_lazy

# Droits propres à la console qui ne sont **pas** des droits de plateforme : ils n'existent que
# pour le superadministrateur. Nommés comme les autres, pour que les gabarits les testent de la
# même manière (`{% if 'console.administrateurs' in droits %}`).
CONSOLE_ADMINISTRATEURS = "console.administrateurs"
CONSOLE_TECHNIQUE = "console.technique"
RESERVES_SUPERADMIN = frozenset({CONSOLE_ADMINISTRATEURS, CONSOLE_TECHNIQUE})

LIBELLES_CONSOLE = {
    "plateforme.boutiques": "Valider, suspendre et résilier les boutiques",
    "plateforme.commissions": "Fixer les taux de commission",
    "plateforme.emplacements": "Vendre les emplacements premium",
    "plateforme.litiges": "Instruire les litiges",
    "plateforme.apporteurs": "Gérer le réseau d'apporteurs",
    "plateforme.versements": "Exécuter les versements aux marchands",
    CONSOLE_ADMINISTRATEURS: "Nommer les administrateurs du marché",
    CONSOLE_TECHNIQUE: "Consulter la santé technique",
}

# Les motifs proposés. Une liste fermée plus « Autre », parce qu'un champ libre seul se remplit de
# « test » et de « . » au bout d'une semaine — et qu'un auditeur qui relit le journal doit pouvoir
# regrouper les lignes.
MOTIFS_DE_SUIVI = [
    ("suivi_mensuel", gettext_lazy("Suivi mensuel de l'activité des boutiques")),
    ("commission", gettext_lazy("Calcul ou contrôle de la commission")),
    ("loyer", gettext_lazy("Relance d'un loyer impayé")),
    ("litige", gettext_lazy("Instruction d'un litige")),
    ("accompagnement", gettext_lazy("Accompagnement d'un commerçant, à sa demande")),
    ("autre", gettext_lazy("Autre — à préciser")),
]

DUREE_DU_SUIVI = timedelta(minutes=30)
_CLE_SUIVI = "plateforme_suivi"


# ----------------------------------------------------------------------------
# Les droits
# ----------------------------------------------------------------------------
def est_superadministrateur(utilisateur) -> bool:
    return bool(
        utilisateur
        and utilisateur.is_authenticated
        and utilisateur.is_active
        and utilisateur.is_superuser
    )


def droits_console_de(utilisateur) -> frozenset[str]:
    """Les droits de la console : tout pour le superadministrateur, son rôle pour les autres.

    Le superadministrateur administre tout — c'est la définition retenue. Il reçoit donc tous les
    droits de plateforme **et** les écrans qui lui sont réservés. Cela ne rouvre pas le
    court-circuit que l'ADR-012 a fermé : ces droits sont ceux du bailleur, aucun d'eux n'ouvre la
    marge, le coût ou le cahier d'une boutique.
    """
    if utilisateur is None or not utilisateur.is_authenticated or not utilisateur.is_active:
        return frozenset()
    if utilisateur.is_superuser:
        return TOUS_PLATEFORME | RESERVES_SUPERADMIN
    if not utilisateur.is_staff:
        return frozenset()
    return droits_plateforme_de(utilisateur)


def niveau_de(utilisateur) -> str:
    """« Superadministrateur » ou « Administrateur du marché » — affiché dans le rail."""
    return "Superadministrateur" if est_superadministrateur(utilisateur) else "Administrateur du marché"


# ----------------------------------------------------------------------------
# Le motif de suivi
# ----------------------------------------------------------------------------
def suivi_actif(request) -> dict | None:
    """Le motif de la session de suivi en cours, ou `None` s'il n'y en a pas ou plus."""
    suivi = request.session.get(_CLE_SUIVI)
    if not suivi:
        return None
    try:
        expire = timezone.datetime.fromisoformat(suivi["expire"])
    except (KeyError, ValueError, TypeError):
        request.session.pop(_CLE_SUIVI, None)
        return None
    if expire <= timezone.now():
        request.session.pop(_CLE_SUIVI, None)
        return None
    return suivi


def ouvrir_suivi(request, code: str, precision: str = "") -> str:
    """Ouvre une session de suivi et renvoie le motif retenu. `ValueError` si le motif manque."""
    libelles = dict(MOTIFS_DE_SUIVI)
    if code not in libelles:
        raise ValueError("Choisissez un motif dans la liste.")
    precision = (precision or "").strip()
    if code == "autre" and len(precision) < 8:
        raise ValueError("Précisez le motif en une phrase : il sera relu par un auditeur.")
    motif = libelles[code] if code != "autre" else precision
    if code != "autre" and precision:
        motif = f"{libelles[code]} — {precision}"
    request.session[_CLE_SUIVI] = {
        "code": code,
        "motif": motif[:300],
        "expire": (timezone.now() + DUREE_DU_SUIVI).isoformat(),
    }
    return motif


def fermer_suivi(request) -> None:
    request.session.pop(_CLE_SUIVI, None)


@contextmanager
def lecture_journalisee(request, *, ecran: str, boutique_id=None):
    """Lecture transverse sous le motif de la session : une ligne de journal par écran affiché.

    À n'utiliser que dans une vue protégée par `exige_console(..., suivi=True)`, qui garantit
    qu'un motif est ouvert.
    """
    suivi = suivi_actif(request)
    if suivi is None:  # pragma: no cover — la porte l'a déjà refusé
        raise PermissionError("Aucune session de suivi ouverte.")
    with acces_plateforme(
        utilisateur=request.user, motif=suivi["motif"], ecran=ecran, boutique_id=boutique_id
    ):
        yield


# ----------------------------------------------------------------------------
# Le contexte commun des gabarits
# ----------------------------------------------------------------------------
def contexte_console(request, page: str, **extra) -> dict:
    """Socle de tous les gabarits de la console."""
    droits = getattr(request, "_droits_console", None)
    if droits is None:
        droits = droits_console_de(request.user)
    suivi = suivi_actif(request)
    return {
        "page": page,
        "droits": droits,
        "niveau": niveau_de(request.user),
        "superadmin": est_superadministrateur(request.user),
        "suivi": suivi,
        "motifs_de_suivi": MOTIFS_DE_SUIVI,
        # Le compteur du rail : ce qui attend un geste. Calculé une fois, ici.
        "a_traiter": _a_traiter(droits),
        **extra,
    }


def _a_traiter(droits) -> dict:
    from apps.marketplace.models import Boutique, FactureLoyer

    compteurs = {"candidatures": None, "impayes": None}
    if "plateforme.boutiques" in droits:
        compteurs["candidatures"] = (
            Boutique.objects.filter(etat=Boutique.CANDIDATURE).count() or None
        )
        compteurs["impayes"] = (
            FactureLoyer.objects.filter(
                etat__in=[FactureLoyer.EMISE, FactureLoyer.IMPAYEE],
                echeance__lt=timezone.localdate(),
            ).count()
            or None
        )
    return compteurs


# ----------------------------------------------------------------------------
# La porte
# ----------------------------------------------------------------------------
def exige_console(*droits_requis: str, suivi: bool = False):
    """Exige un compte d'administration et les droits nommés.

    * Un visiteur non connecté est renvoyé à la connexion.
    * Un compte sans aucun droit de console (un commerçant, un caissier) reçoit un 403 explicite :
      la console existe, ce n'est simplement pas la sienne.
    * `suivi=True` : l'écran lit à travers les boutiques. Sans motif ouvert, on affiche la page
      qui le demande, et on revient ensuite exactement ici.
    """

    def decorateur(vue):
        @wraps(vue)
        @login_required(login_url="connexion")
        def enveloppe(request, *args, **kwargs):
            droits = droits_console_de(request.user)
            request._droits_console = droits
            if not droits:
                return render(
                    request,
                    "plateforme/refus.html",
                    contexte_console(
                        request,
                        page="",
                        manquants=[LIBELLES_CONSOLE.get(d, d) for d in droits_requis]
                        or ["Accéder à la console de la plateforme"],
                    ),
                    status=403,
                )
            manquants = [d for d in droits_requis if d not in droits]
            if manquants:
                return render(
                    request,
                    "plateforme/refus.html",
                    contexte_console(
                        request, page="", manquants=[LIBELLES_CONSOLE.get(d, d) for d in manquants]
                    ),
                    status=403,
                )
            if suivi and suivi_actif(request) is None:
                return redirect(
                    f"{reverse('plateforme:suivi_ouvrir')}?suite={request.get_full_path()}"
                )
            return vue(request, *args, **kwargs)

        return enveloppe

    return decorateur
