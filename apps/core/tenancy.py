"""Multi-tenant : contexte de boutique courante et gestionnaires filtrants.

Barrière 1 (contexte de requête) et barrière 2 (gestionnaire par défaut filtrant) de la stratégie
décrite en docs/09-architecture-technique.md, §3.2. La barrière 3 (`RLS` PostgreSQL) est posée par
les migrations de `apps.core`.

Le contexte est porté par une `ContextVar` : sûr en asynchrone et par tâche Celery, contrairement
à une variable globale ou à un attribut de thread.
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


def definir_boutique_courante(boutique_id):
    """Positionne le contexte. Retourne le jeton de restauration."""
    return _boutique.set(boutique_id)


@contextmanager
def contexte_boutique(boutique):
    """Exécute un bloc dans le contexte d'une boutique donnée.

    Accepte une instance de `Boutique` ou un identifiant.
    """
    boutique_id = getattr(boutique, "pk", boutique)
    jeton = _boutique.set(boutique_id)
    try:
        yield boutique_id
    finally:
        _boutique.reset(jeton)


@contextmanager
def contexte_plateforme():
    """Lève le filtrage par boutique, pour les rôles plateforme et les tâches de fond.

    Tout usage est un accès transverse : il doit être justifié, restreint aux rôles plateforme
    et journalisé par l'appelant.
    """
    jeton = _boutique.set(_PLATEFORME)
    try:
        yield
    finally:
        _boutique.reset(jeton)


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
