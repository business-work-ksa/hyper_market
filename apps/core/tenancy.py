"""Multi-tenant : contexte de boutique courante et gestionnaires filtrants.

Barrière 1 (contexte de requête) et barrière 2 (gestionnaire par défaut filtrant) de la stratégie
décrite en docs/09-architecture-technique.md, §3.2. La barrière 3 (`RLS` PostgreSQL) est posée par
la migration `core.0002` et décrite dans `apps/core/rls.py`.

Le contexte est porté par une `ContextVar` : sûr en asynchrone et par tâche Celery, contrairement
à une variable globale ou à un attribut de thread. Chaque changement de contexte est **répercuté
sur la connexion PostgreSQL**, où il pilote les politiques de sécurité au niveau ligne : sans cela,
la barrière 3 verrait toujours un réglage vide et ne montrerait jamais rien.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

__all__ = [
    "BoutiqueNonDefinie",
    "boutique_courante",
    "definir_boutique_courante",
    "contexte_boutique",
    "contexte_plateforme",
    "appliquer_contexte_bd",
    "TenantQuerySet",
    "TenantManager",
]

# `None` = aucune boutique ; le sentinelle `_PLATEFORME` = accès transverse assumé.
_PLATEFORME = object()

_boutique: ContextVar[object | None] = ContextVar("boutique_courante", default=None)


class BoutiqueNonDefinie(RuntimeError):
    """Levée quand une requête scopée est exécutée hors de tout contexte de boutique."""


def boutique_courante():
    """Identifiant de la boutique courante, `_PLATEFORME`, ou `None`."""
    return _boutique.get()


def _valeur_de_session() -> str:
    """Traduction du contexte en réglage de session PostgreSQL."""
    from apps.core.rls import VALEUR_PLATEFORME

    courante = _boutique.get()
    if courante is _PLATEFORME:
        return VALEUR_PLATEFORME
    if courante is None:
        # Chaîne vide plutôt qu'absence : la politique ne trouve alors aucune
        # ligne, ce qui reproduit exactement le choix de la barrière 2.
        return ""
    return str(courante)


def appliquer_contexte_bd(*, alias: str = "default", silencieux: bool = False) -> None:
    """Répercute le contexte courant sur la connexion, pour les politiques `RLS`.

    Appelée à chaque entrée et à chaque sortie de contexte, sans mise en cache.
    Un `SET` PostgreSQL est **transactionnel** : mémoriser la dernière valeur
    appliquée la ferait diverger de la base au premier `ROLLBACK`, et les
    requêtes suivantes ne verraient plus rien — ou verraient la mauvaise
    boutique. Une requête minuscule à chaque frontière de contexte coûte moins
    cher que ce risque-là.

    `silencieux` sert aux chemins de sortie. Si le bloc s'est terminé sur une
    erreur SQL, la transaction est en échec et toute requête y échoue à son
    tour : restaurer le réglage masquerait l'erreur d'origine par une erreur de
    plomberie. On l'ignore alors, sans conséquence — le `ROLLBACK` qui suit
    remet de toute façon le réglage à sa valeur d'avant la transaction.

    Sans PostgreSQL, l'appel est un no-op : les barrières 1 et 2 s'appliquent
    seules, ce qui suffit aux tests unitaires et **jamais à la production**.
    """
    from django.db import DatabaseError, connections

    from apps.core.rls import NOM_REGLAGE

    connexion = connections[alias]
    if connexion.vendor != "postgresql":
        return

    try:
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT set_config(%s, %s, false)", [NOM_REGLAGE, _valeur_de_session()]
            )
    except DatabaseError:
        if not silencieux:
            raise


def definir_boutique_courante(boutique_id):
    """Positionne le contexte et le répercute en base. Retourne le jeton de restauration."""
    jeton = _boutique.set(boutique_id)
    appliquer_contexte_bd()
    return jeton


def restaurer_boutique_courante(jeton) -> None:
    """Restaure le contexte précédent et le répercute en base."""
    _boutique.reset(jeton)
    appliquer_contexte_bd(silencieux=True)


@contextmanager
def contexte_boutique(boutique):
    """Exécute un bloc dans le contexte d'une boutique donnée.

    Accepte une instance de `Boutique` ou un identifiant.
    """
    boutique_id = getattr(boutique, "pk", boutique)
    jeton = _boutique.set(boutique_id)
    appliquer_contexte_bd()
    try:
        yield boutique_id
    finally:
        _boutique.reset(jeton)
        appliquer_contexte_bd(silencieux=True)


@contextmanager
def contexte_plateforme():
    """Lève le filtrage par boutique, pour les rôles plateforme et les tâches de fond.

    Tout usage est un accès transverse : il doit être justifié, restreint aux rôles plateforme
    et journalisé par l'appelant. Il lève aussi la barrière 3 : le réglage de session passe à
    `plateforme`, et les politiques `RLS` s'ouvrent.
    """
    jeton = _boutique.set(_PLATEFORME)
    appliquer_contexte_bd()
    try:
        yield
    finally:
        _boutique.reset(jeton)
        appliquer_contexte_bd(silencieux=True)


class TenantQuerySet(models.QuerySet):
    """QuerySet filtré sur la boutique courante."""

    def _filtrer_sur_contexte(self):
        courante = _boutique.get()
        if courante is _PLATEFORME:
            return self
        if courante is None:
            # Choix délibéré : ne rien renvoyer plutôt que tout renvoyer. Un oubli de contexte
            # produit un résultat vide et visible, jamais une fuite silencieuse entre boutiques.
            return self.none()
        return self.filter(boutique_id=courante)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Gestionnaire par défaut des modèles scopés.

    Toute requête passant par ce gestionnaire est bornée à la boutique courante. L'accès transverse
    exige soit `contexte_plateforme()`, soit le gestionnaire explicite `objects_all_tenants`.
    """

    def get_queryset(self):
        return super().get_queryset()._filtrer_sur_contexte()
