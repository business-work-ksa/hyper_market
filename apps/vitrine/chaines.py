"""Chaînes affichées par le marché mais définies hors de ses gabarits.

Les libellés des paliers de confiance vivent dans `apps/marketplace/confiance.py`, qui ne dépend pas
de la traduction ; le gabarit les traduit au vol (`{% translate confiance.palier.libelle %}`).
Les marquer ici les fait entrer dans le catalogue de `apps/vitrine/locale/` sans toucher au modèle.
"""

from django.utils.translation import gettext_noop

LIBELLES_DYNAMIQUES = [
    gettext_noop("Nouvelle boutique"),
    gettext_noop("Boutique confirmée"),
    gettext_noop("Boutique reconnue"),
    gettext_noop("Boutique établie"),
    gettext_noop("En attente"),
    gettext_noop("Acceptée"),
    gettext_noop("Préparée"),
    gettext_noop("Expédiée"),
    gettext_noop("Livrée"),
    gettext_noop("Annulée"),
    gettext_noop("Commande non reçue"),
    gettext_noop("Article non conforme à l'annonce"),
    gettext_noop("Commande incomplète"),
    gettext_noop("Autre"),
]
