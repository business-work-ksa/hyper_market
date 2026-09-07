"""Barrière 1 du multi-tenant : résolution de la boutique courante pour chaque requête."""

from apps.core.tenancy import definir_boutique_courante

ENTETE_BOUTIQUE = "HTTP_X_BOUTIQUE"


class BoutiqueCouranteMiddleware:
    """Positionne le contexte de boutique à partir de la requête.

    Ordre de résolution :
      1. en-tête `X-Boutique` (clients API et caisse) ;
      2. boutique sélectionnée en session (interface marchand) ;
      3. appartenance unique de l'utilisateur, s'il n'en a qu'une.

    Aucune boutique résolue laisse le contexte à `None` : les gestionnaires scopés renvoient alors
    un ensemble vide. C'est délibéré — un oubli de contexte doit produire une absence de données,
    jamais une fuite.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        boutique_id = self._resoudre(request)
        jeton = definir_boutique_courante(boutique_id)
        request.boutique_id = boutique_id
        try:
            return self.get_response(request)
        finally:
            from apps.core.tenancy import _boutique

            _boutique.reset(jeton)

    @staticmethod
    def _resoudre(request):
        entete = request.META.get(ENTETE_BOUTIQUE)
        if entete:
            return entete

        if hasattr(request, "session"):
            en_session = request.session.get("boutique_id")
            if en_session:
                return en_session

        utilisateur = getattr(request, "user", None)
        if utilisateur is not None and utilisateur.is_authenticated:
            appartenances = list(
                utilisateur.appartenances.filter(actif=True).values_list("boutique_id", flat=True)[:2]
            )
            if len(appartenances) == 1:
                return appartenances[0]

        return None
