"""Jeton d'accès à l'API (ADR-010).

Un jeton appartient à **un utilisateur et une boutique**. C'est la décision
structurante de ce module, et elle règle un problème qui, sans elle, revient à
chaque point d'entrée : **le client ne déclare jamais la boutique qu'il veut
lire.** Elle est lue sur le jeton présenté. Un en-tête `X-Boutique` falsifié ne
peut donc rien ouvrir, parce qu'il n'est pas consulté.

Trois choix qui méritent leur justification.

**Seule une empreinte est conservée.** La base ne contient jamais le secret,
seulement son SHA-256. Une fuite de la table des jetons ne donne aucun accès :
elle donne des empreintes, dont on ne remonte pas. C'est la même logique que
pour un mot de passe, avec une différence qui compte — un secret de 32
caractères tirés au hasard n'a pas besoin d'une fonction de dérivation lente,
parce qu'il n'est pas devinable par force brute. Un `bcrypt` ici n'ajouterait
que du temps de calcul à chaque requête d'API.

**Le préfixe est stocké en clair, et il est indispensable.** Sans lui,
authentifier une requête demanderait de hacher le secret présenté puis de
parcourir la table entière. Avec lui, la recherche est un accès par index, et
la comparaison d'empreinte se fait sur une seule ligne, en temps constant. Il
sert aussi à l'humain : c'est ce qui identifie un jeton dans une liste, quand
personne ne peut plus voir le secret.

**Le modèle n'est pas scopé par boutique.** Il porte pourtant une boutique. La
raison est un ordre d'exécution : ce jeton est lu **avant** que le contexte de
boutique n'existe — c'est justement lui qui va l'établir. Une table protégée par
les politiques d'isolation ne serait pas lisible à ce moment-là. `Appartenance`
est hors du scope pour exactement la même raison : les tables qui servent à
décider de l'accès ne peuvent pas dépendre de l'accès.
"""

import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.uuid7 import uuid7

__all__ = ["JetonApi", "PREFIXE_PRODUIT", "empreinte_de", "generer_jeton"]

PREFIXE_PRODUIT = "hm"

# Sans caractères ambigus : un jeton finit toujours par être recopié à la main
# une fois, dans un fichier de configuration, par quelqu'un qui le lit à l'écran.
ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

LONGUEUR_PREFIXE = 8
LONGUEUR_SECRET = 32


def empreinte_de(secret: str) -> str:
    """SHA-256 hexadécimal du secret. Voir l'en-tête du module pour le choix."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generer_jeton() -> tuple[str, str, str]:
    """Fabrique un jeton neuf.

    Retourne `(jeton_en_clair, prefixe, empreinte)`. Le jeton en clair n'est
    jamais réécrit nulle part : l'appelant le montre une fois, puis il disparaît.
    """
    prefixe = "".join(secrets.choice(ALPHABET) for _ in range(LONGUEUR_PREFIXE))
    secret = "".join(secrets.choice(ALPHABET) for _ in range(LONGUEUR_SECRET))
    return f"{PREFIXE_PRODUIT}_{prefixe}_{secret}", prefixe, empreinte_de(secret)


class JetonApi(models.Model):
    """Identifiant d'un client d'API : une tablette, une caisse, une intégration."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jetons_api"
    )
    boutique = models.ForeignKey(
        "marketplace.Boutique", on_delete=models.CASCADE, related_name="jetons_api"
    )
    libelle = models.CharField(
        max_length=120,
        help_text="À quoi sert ce jeton. Ex. « Tablette du comptoir 2 ».",
    )
    prefixe = models.CharField(max_length=16, unique=True, editable=False)
    empreinte = models.CharField(max_length=64, editable=False)
    cree_le = models.DateTimeField(auto_now_add=True)
    dernier_usage_le = models.DateTimeField(null=True, blank=True)
    revoque_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "jeton d'API"
        verbose_name_plural = "jetons d'API"
        ordering = ["-cree_le"]
        indexes = [models.Index(fields=["utilisateur", "boutique"])]

    def __str__(self):
        etat = "révoqué" if self.revoque_le else "actif"
        return f"{self.libelle} · {PREFIXE_PRODUIT}_{self.prefixe}_… ({etat})"

    @property
    def actif(self) -> bool:
        return self.revoque_le is None

    def correspond(self, secret: str) -> bool:
        """Comparaison en temps constant : une comparaison naïve fuit par sa durée."""
        return hmac.compare_digest(self.empreinte, empreinte_de(secret))

    def revoquer(self) -> None:
        if self.revoque_le is None:
            self.revoque_le = timezone.now()
            self.save(update_fields=["revoque_le"])

    @classmethod
    def emettre(cls, *, utilisateur, boutique, libelle: str) -> tuple["JetonApi", str]:
        """Crée un jeton et retourne `(jeton, secret en clair)`.

        Le secret en clair n'existe qu'ici et dans la réponse faite à l'appelant.
        Il n'est ni journalisé, ni stocké : un jeton perdu se remplace, il ne se
        retrouve pas.
        """
        en_clair, prefixe, empreinte = generer_jeton()
        jeton = cls.objects.create(
            utilisateur=utilisateur,
            boutique=boutique,
            libelle=libelle,
            prefixe=prefixe,
            empreinte=empreinte,
        )
        return jeton, en_clair
