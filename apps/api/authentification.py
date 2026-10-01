"""Authentification par jeton porteur.

    Authorization: Bearer hm_<prefixe>_<secret>

Le jeton désigne l'utilisateur **et** la boutique (ADR-010). L'appartenance est
revérifiée à chaque requête, et non figée à l'émission : un salarié dont l'accès
a été retiré ce matin ne doit pas continuer à lire les ventes cet après-midi
parce qu'il détient un jeton émis la semaine dernière.

Pourquoi pas `rest_framework.authtoken`
---------------------------------------

Deux raisons, et la première suffirait :

1. **Il stocke la clé en clair.** Une lecture de la table donne des jetons
   utilisables. Ici, seule une empreinte est conservée (`apps/api/models.py`).
2. **Il est lié à un utilisateur, pas à un tenant.** Notre modèle a besoin de la
   boutique sur la crédential elle-même — c'est ce qui retire au client toute
   possibilité de déclarer le tenant qu'il veut lire.
"""

from django.utils import timezone
from rest_framework import authentication, exceptions

from apps.api.models import PREFIXE_PRODUIT, JetonApi

__all__ = ["AuthentificationJeton", "MOT_CLE"]

MOT_CLE = "Bearer"


class AuthentificationJeton(authentication.BaseAuthentication):
    def authenticate(self, request):
        entete = authentication.get_authorization_header(request).split()
        if not entete or entete[0].lower() != MOT_CLE.lower().encode():
            return None  # pas notre affaire : une autre classe peut répondre
        if len(entete) != 2:
            raise exceptions.AuthenticationFailed("En-tête d'autorisation mal formé.")

        jeton = self._resoudre(entete[1].decode("utf-8", errors="ignore"))

        # L'accès du porteur est revérifié à chaque requête, jamais présumé.
        if not jeton.utilisateur.is_active:
            raise exceptions.AuthenticationFailed("Ce compte est désactivé.")
        if not jeton.utilisateur.appartenances.filter(
            actif=True, boutique_id=jeton.boutique_id
        ).exists():
            raise exceptions.AuthenticationFailed(
                "Ce compte n'a plus accès à cette boutique."
            )

        # Un jeton dont on ne sait pas s'il sert encore ne peut pas être retiré
        # sans risque. Écrit à la minute pour ne pas produire une écriture par
        # requête sur une caisse qui interroge en boucle.
        maintenant = timezone.now()
        if jeton.dernier_usage_le is None or (
            maintenant - jeton.dernier_usage_le
        ).total_seconds() > 60:
            JetonApi.objects.filter(pk=jeton.pk).update(dernier_usage_le=maintenant)

        return (jeton.utilisateur, jeton)

    def authenticate_header(self, request):
        return MOT_CLE

    @staticmethod
    def _resoudre(presente: str) -> JetonApi:
        """Retrouve le jeton, ou refuse — toujours avec le même message.

        Le message d'échec est volontairement identique pour un préfixe inconnu,
        un secret faux et un jeton révoqué : distinguer les cas dirait à un
        attaquant lesquels de ses essais ont touché un préfixe réel.
        """
        refus = exceptions.AuthenticationFailed("Jeton invalide ou révoqué.")

        morceaux = presente.split("_")
        if len(morceaux) != 3 or morceaux[0] != PREFIXE_PRODUIT:
            raise refus

        _, prefixe, secret = morceaux
        jeton = (
            JetonApi.objects.select_related("utilisateur", "boutique")
            .filter(prefixe=prefixe, revoque_le__isnull=True)
            .first()
        )
        if jeton is None or not jeton.correspond(secret):
            raise refus
        return jeton
