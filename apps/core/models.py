"""Modèles de base : identité technique, scope multi-tenant, audit, synchronisation, consentement."""

from django.conf import settings
from django.db import models

from apps.core.tenancy import TenantManager
from apps.core.uuid7 import uuid7


class BaseModel(models.Model):
    """Socle de tout modèle métier : identifiant UUIDv7 et traçabilité de création."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    cree_le = models.DateTimeField(auto_now_add=True, db_index=True)
    modifie_le = models.DateTimeField(auto_now=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True


class TenantScopedModel(BaseModel):
    """Modèle appartenant à une boutique.

    `objects` est filtré sur la boutique courante ; `objects_all_tenants` ne l'est pas et son
    usage est réservé aux rôles plateforme (docs/09-architecture-technique.md, §3.2).
    """

    boutique = models.ForeignKey(
        "marketplace.Boutique",
        on_delete=models.PROTECT,
        related_name="%(class)s_set",
    )

    objects = TenantManager()
    objects_all_tenants = models.Manager()

    class Meta:
        abstract = True
        base_manager_name = "objects_all_tenants"


class EntreeAudit(models.Model):
    """Journal d'audit inaltérable.

    Volontairement hors de `BaseModel` : cette table n'est jamais modifiée, jamais scopée, et
    doit rester écrivable même quand aucun contexte de boutique n'est défini.
    """

    CREATION = "creation"
    MODIFICATION = "modification"
    SUPPRESSION = "suppression"
    LECTURE_SENSIBLE = "lecture_sensible"
    ACCES_TRANSVERSE = "acces_transverse"

    ACTIONS = [
        (CREATION, "Création"),
        (MODIFICATION, "Modification"),
        (SUPPRESSION, "Suppression"),
        (LECTURE_SENSIBLE, "Lecture de données sensibles"),
        (ACCES_TRANSVERSE, "Accès transverse plateforme"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    horodatage = models.DateTimeField(auto_now_add=True, db_index=True)
    acteur = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    boutique_id = models.UUIDField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=32, choices=ACTIONS)
    objet_type = models.CharField(max_length=128)
    objet_id = models.CharField(max_length=64, blank=True)
    avant = models.JSONField(null=True, blank=True)
    apres = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "entrée d'audit"
        verbose_name_plural = "journal d'audit"
        ordering = ["-horodatage"]
        indexes = [models.Index(fields=["objet_type", "objet_id"])]

    def __str__(self):
        return f"{self.horodatage:%Y-%m-%d %H:%M} {self.action} {self.objet_type}"

    def save(self, *args, **kwargs):
        if self.pk and EntreeAudit.objects.filter(pk=self.pk).exists():
            raise ValueError("Une entrée d'audit est inaltérable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Une entrée d'audit ne peut pas être supprimée.")


class OperationSync(models.Model):
    """Journal d'opérations du mode hors ligne.

    Le client n'envoie pas un état mais une suite d'opérations, chacune portant sa clé
    d'idempotence. Le serveur rejoue chaque opération **au plus une fois** : une opération déjà
    appliquée renvoie le résultat précédemment produit (ADR-004).
    """

    RECUE = "recue"
    APPLIQUEE = "appliquee"
    REJETEE = "rejetee"

    ETATS = [(RECUE, "Reçue"), (APPLIQUEE, "Appliquée"), (REJETEE, "Rejetée")]

    operation_id = models.UUIDField(primary_key=True, editable=False)
    type = models.CharField(max_length=64, db_index=True)
    boutique_id = models.UUIDField(db_index=True)
    charge_utile = models.JSONField()
    horodatage_client = models.DateTimeField()
    recue_le = models.DateTimeField(auto_now_add=True)
    etat = models.CharField(max_length=16, choices=ETATS, default=RECUE)
    resultat = models.JSONField(null=True, blank=True)
    erreur = models.TextField(blank=True)

    class Meta:
        verbose_name = "opération de synchronisation"
        verbose_name_plural = "opérations de synchronisation"
        ordering = ["-horodatage_client"]

    def __str__(self):
        return f"{self.type} · {self.etat}"


class Consentement(models.Model):
    """Registre des consentements — loi camerounaise n° 2024/017.

    Le consentement doit être éclairé, spécifique et non équivoque, et révocable. Il est donc un
    objet de première classe, horodaté et opposable, et non une case à cocher sur un formulaire
    (docs/08-conformite-juridique-et-fiscale.md, §4).
    """

    MARKETING_SMS = "marketing_sms"
    MARKETING_WHATSAPP = "marketing_whatsapp"
    MARKETING_EMAIL = "marketing_email"
    PARTAGE_CABINET = "partage_cabinet"
    SCORING_CREDIT = "scoring_credit"

    FINALITES = [
        (MARKETING_SMS, "Sollicitations commerciales par SMS"),
        (MARKETING_WHATSAPP, "Sollicitations commerciales par WhatsApp"),
        (MARKETING_EMAIL, "Sollicitations commerciales par courriel"),
        (PARTAGE_CABINET, "Partage des données comptables avec le cabinet partenaire"),
        (SCORING_CREDIT, "Analyse des données de vente à des fins d'octroi de financement"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="consentements"
    )
    finalite = models.CharField(max_length=64, choices=FINALITES)
    accorde = models.BooleanField()
    horodatage = models.DateTimeField(auto_now_add=True)
    revoque_le = models.DateTimeField(null=True, blank=True)
    preuve = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "consentement"
        verbose_name_plural = "registre des consentements"
        ordering = ["-horodatage"]
        indexes = [models.Index(fields=["utilisateur", "finalite"])]

    def __str__(self):
        etat = "accordé" if self.est_actif else "refusé/révoqué"
        return f"{self.utilisateur} · {self.get_finalite_display()} · {etat}"

    @property
    def est_actif(self) -> bool:
        return self.accorde and self.revoque_le is None
