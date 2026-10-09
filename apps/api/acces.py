"""La porte de l'API : boutique, droits, contexte de tenant.

C'est l'équivalent, côté API, de `apps/backoffice/acces.py`. Les deux lisent
**la même matrice de droits** (`apps.accounts.permissions`) : il n'existe pas
une version des droits pour l'écran et une autre pour l'API. Un caissier ne voit
pas la marge parce qu'elle est cachée dans un gabarit ; il ne la voit pas parce
qu'elle n'est jamais calculée pour lui, quel que soit le chemin d'accès.

Trois choses se règlent ici, dans cet ordre :

1. **La boutique** est lue sur le jeton (ADR-010). Le client ne la déclare pas.
2. **Les droits** sont recalculés à chaque requête, à partir des appartenances
   actives — jamais figés dans le jeton.
3. **Le contexte de tenant** est établi pour la durée de la requête, puis
   restauré, y compris si la vue lève une exception.
"""

from rest_framework import exceptions, permissions
from rest_framework.views import APIView

from apps.accounts.permissions import LIBELLES, droits_de
from apps.api.authentification import AuthentificationJeton
from apps.core.tenancy import definir_boutique_courante, restaurer_boutique_courante

__all__ = ["DroitRefuse", "ADroitsSurLaBoutique", "VueApi", "boutique_de", "droits_de_la_requete"]


class DroitRefuse(exceptions.PermissionDenied):
    """403 nommant les droits qui manquent.

    Un refus muet fait croire à une panne, et un commerçant qui croit à une panne
    appelle. La réponse dit donc quel droit manque, en clair — c'est la même
    règle que la page de refus du back-office.
    """

    def __init__(self, manquants):
        super().__init__(
            {
                "detail": "Votre rôle ne permet pas cette opération.",
                "droits_manquants": [
                    {"code": code, "libelle": LIBELLES.get(code, code)} for code in manquants
                ],
            }
        )


def boutique_de(request):
    """Boutique portée par le jeton présenté."""
    jeton = getattr(request, "auth", None)
    return getattr(jeton, "boutique", None)


def droits_de_la_requete(request) -> frozenset[str]:
    """Droits acquis sur la boutique du jeton, mémorisés pour la requête."""
    acquis = getattr(request, "_droits", None)
    if acquis is None:
        acquis = droits_de(request.user, boutique_de(request))
        request._droits = acquis
    return acquis


class ADroitsSurLaBoutique(permissions.BasePermission):
    """Exige une boutique résolue et les droits déclarés par la vue."""

    def has_permission(self, request, view):
        if boutique_de(request) is None:
            raise exceptions.NotAuthenticated("Aucune boutique n'est attachée à ce jeton.")

        acquis = droits_de_la_requete(request)
        manquants = [d for d in view.droits_pour(request.method) if d not in acquis]
        if manquants:
            raise DroitRefuse(manquants)
        return True


class VueApi(APIView):
    """Base de toutes les vues d'API.

    `droits_requis` s'applique à toutes les méthodes ; `droits_par_methode`
    affine — lire des articles et en mouvementer le stock ne demandent pas la
    même chose sur la même adresse.
    """

    # Le jeton, et rien d'autre. L'authentification par session n'est pas
    # acceptée ici : elle rouvrirait la question « quelle boutique ? » que
    # l'ADR-010 ferme en la portant sur la crédential. Un navigateur connecté
    # utilise le back-office, qui a sa propre porte.
    authentication_classes = [AuthentificationJeton]
    permission_classes = [permissions.IsAuthenticated, ADroitsSurLaBoutique]

    droits_requis: tuple[str, ...] = ()
    droits_par_methode: dict[str, tuple[str, ...]] = {}

    def droits_pour(self, methode: str) -> tuple[str, ...]:
        return self.droits_par_methode.get((methode or "").upper(), self.droits_requis)

    # -- Contexte de tenant --------------------------------------------------
    def dispatch(self, request, *args, **kwargs):
        """Ouvre le contexte de boutique et le referme quoi qu'il arrive.

        Le `finally` n'est pas un excès de prudence. Les connexions sont
        persistantes et le contexte est répercuté sur la connexion PostgreSQL
        (barrière 3) : une requête qui échouerait sans restaurer laisserait la
        **suivante** hériter de sa boutique. Se reposer sur
        `finalize_response` ne suffirait pas — une exception non convertie par
        DRF ne passe pas par là.
        """
        self._jeton_contexte = None
        try:
            return super().dispatch(request, *args, **kwargs)
        finally:
            if self._jeton_contexte is not None:
                restaurer_boutique_courante(self._jeton_contexte)
                self._jeton_contexte = None

    def initial(self, request, *args, **kwargs):
        # `super()` authentifie et vérifie les droits. La matrice se lit sur les
        # appartenances, qui ne sont pas scopées : aucun contexte n'est requis
        # pour décider de l'accès — et c'est heureux, puisque c'est l'accès qui
        # va déterminer le contexte.
        super().initial(request, *args, **kwargs)
        boutique = boutique_de(request)
        if boutique is not None:
            self._jeton_contexte = definir_boutique_courante(boutique.pk)

    # -- Confort -------------------------------------------------------------
    @property
    def boutique(self):
        return boutique_de(self.request)

    @property
    def droits(self) -> frozenset[str]:
        return droits_de_la_requete(self.request)
