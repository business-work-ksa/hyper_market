"""Ce que la confiance retient : les mesures d'une boutique, ses changements de palier, ses signaux.

Trois modèles, aucun scopé par boutique — et c'est voulu. Ils appartiennent à la plateforme, pas
au commerçant : ils sont **à propos** d'une boutique, comme son bail, et non **à** elle, comme ses
ventes. Les scoper les rendrait invisibles à celui qui en a besoin, l'administrateur qui décide.

* `MesureConfiance` — la dernière photographie de ce qu'une boutique a prouvé (livraisons
  confirmées, ancienneté, litiges), écrite par la tâche de nuit. Elle existe pour que la console
  et la vitrine n'aient **pas** à relire les commandes : la première parce qu'une lecture de table
  scopée y exige un motif et une trace (ADR-012), la seconde parce qu'une requête par carte
  d'article ruinerait une page de catalogue sur 3G. Ce ne sont que des **agrégats**, et les mêmes
  que ceux que la vitrine publie : aucun chiffre privé du commerçant ne sort par cette porte.
* `ChangementPalier` — le journal, en ajout seul, de chaque montée et de chaque rétrogradation,
  avec ses raisons. Un marchand qui demande « pourquoi mes fonds sont-ils retenus sept jours ? »
  doit recevoir une réponse datée, pas une supposition.
* `SignalRisque` — un indice, présenté à un humain qui décide. Jamais une sanction automatique.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.marketplace.confiance import CHOIX_PALIERS
from django.utils.translation import gettext_lazy as _l


class MesureConfiance(BaseModel):
    """Ce qu'une boutique a prouvé, à la dernière évaluation. Une ligne par boutique, réécrite."""

    boutique = models.OneToOneField(
        "marketplace.Boutique", on_delete=models.CASCADE, related_name="mesure_confiance"
    )
    livraisons_confirmees = models.PositiveIntegerField(default=0)
    acheteurs_distincts = models.PositiveIntegerField(
        default=0,
        help_text=(
            _l("Acheteurs distincts derrière ces livraisons. Cent livraisons à un seul acheteur ne "
            "prouvent pas la même chose que cent livraisons à cent acheteurs.")
        ),
    )
    litiges_clos = models.PositiveIntegerField(default=0)
    litiges_perdus = models.PositiveIntegerField(default=0)
    # Fraction (0,05 = 5 %) des sous-commandes abouties qui se sont soldées par un litige perdu.
    taux_litiges_perdus = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    premiere_activation = models.DateField(null=True, blank=True)
    mesuree_le = models.DateTimeField()

    class Meta:
        verbose_name = "mesure de confiance"
        verbose_name_plural = "mesures de confiance"

    def __str__(self):
        return f"{self.boutique} · {self.livraisons_confirmees} livraisons confirmées"


class ChangementPalier(BaseModel):
    """Une montée ou une rétrogradation de palier, et pourquoi. **Ajout seul.**

    Pas de clé vers l'utilisateur : c'est la tâche de nuit qui décide d'un palier, selon des règles
    écrites en code (`apps/confiance/paliers.py`), jamais un administrateur d'un clic. Un palier
    qu'on pourrait fixer à la main serait le premier levier qu'un complice interne actionnerait.
    """

    boutique = models.ForeignKey(
        "marketplace.Boutique", on_delete=models.PROTECT, related_name="changements_palier"
    )
    ancien = models.PositiveSmallIntegerField(choices=CHOIX_PALIERS)
    nouveau = models.PositiveSmallIntegerField(choices=CHOIX_PALIERS)
    raisons = models.JSONField(default=list, help_text=_l("Phrases lisibles, dans l'ordre."))
    mesures = models.JSONField(default=dict, help_text=_l("Les chiffres au moment de la décision."))
    # L'instant de l'évaluation qui a décidé, distinct de `cree_le` : c'est lui qui ouvre la
    # fenêtre avant la montée suivante, et une évaluation rejouée pour une date donnée doit
    # raisonner sur cette date-là, pas sur l'horloge du serveur.
    decide_le = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = "changement de palier"
        verbose_name_plural = "changements de palier"
        ordering = ["-decide_le", "-cree_le"]

    def __str__(self):
        return f"{self.boutique} · palier {self.ancien} → {self.nouveau}"

    @property
    def est_une_montee(self) -> bool:
        return self.nouveau > self.ancien

    def save(self, *args, **kwargs):
        # Même règle que le journal des accès : une ligne vraie ne se réécrit pas. On corrige un
        # palier par une nouvelle évaluation, qui laisse sa propre ligne.
        if not self._state.adding:
            raise ValueError("Un changement de palier ne se modifie pas : le journal est en ajout seul.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Un changement de palier ne se supprime pas : le journal est en ajout seul.")


class SignalRisque(BaseModel):
    """Un indice de fraude sur une boutique, en attente d'une décision humaine.

    **Un signal n'est pas une preuve.** Chaque détecteur (`apps/confiance/signaux.py`) dit pourquoi
    son constat mérite un regard, et pourquoi il peut être innocent. Le signal ne suspend rien : il
    met une preuve lisible sous les yeux d'un administrateur, qui écarte ou confirme, avec un motif,
    et dont le geste est inscrit au journal des accès.

    **Un seul signal ouvert par boutique et par type.** La tâche de nuit repasse chaque soir : si
    elle recréait le signal, la file se remplirait de doublons et on cesserait de la lire. Elle met
    donc à jour le signal ouvert (contrainte en base, pas seulement en Python).
    """

    IDENTITES_PARTAGEES = "identites_partagees"
    PRIX_APPAT = "prix_appat"
    PIC_PREPAIEMENT = "pic_prepaiement"
    LITIGES_ANNULATIONS = "litiges_annulations"
    CHANGEMENT_COMPTE = "changement_compte"
    NON_VERIFIEE = "non_verifiee"
    TYPES = [
        (IDENTITES_PARTAGEES, _l("Identité partagée avec une autre boutique")),
        (PRIX_APPAT, _l("Prix d'appât")),
        (PIC_PREPAIEMENT, _l("Pic de prépaiement")),
        (LITIGES_ANNULATIONS, _l("Litiges et annulations anormaux")),
        (CHANGEMENT_COMPTE, _l("Compte de versement changé avant un versement")),
        (NON_VERIFIEE, _l("Boutique active non vérifiée")),
    ]

    # Trois gravités, pas cinq : au-delà, personne ne sait plus dire la différence entre la
    # deuxième et la troisième, et le tri devient un avis.
    MODEREE = 1
    ELEVEE = 2
    CRITIQUE = 3
    GRAVITES = [(MODEREE, _l("Modérée")), (ELEVEE, _l("Élevée")), (CRITIQUE, _l("Critique"))]

    OUVERT = "ouvert"
    ECARTE = "ecarte"
    CONFIRME = "confirme"
    ETATS = [(OUVERT, _l("Ouvert")), (ECARTE, _l("Écarté")), (CONFIRME, _l("Confirmé"))]

    boutique = models.ForeignKey(
        "marketplace.Boutique", on_delete=models.PROTECT, related_name="signaux_risque"
    )
    type = models.CharField(max_length=32, choices=TYPES, db_index=True)
    gravite = models.PositiveSmallIntegerField(choices=GRAVITES, default=MODEREE, db_index=True)
    score = models.PositiveSmallIntegerField(default=0, help_text=_l("0 à 100, pour trier à gravité égale."))
    resume = models.CharField(max_length=240, help_text=_l("La preuve en une phrase, pour la file."))
    preuves = models.JSONField(default=dict)
    # Empreinte des faits qui fondent le signal. Un signal écarté ne revient pas tant que les faits
    # sont les mêmes : l'administrateur a déjà jugé ceux-là. S'ils changent — une troisième boutique
    # partage le téléphone — l'empreinte change, et un nouveau signal s'ouvre.
    empreinte = models.CharField(max_length=64, db_index=True)
    constate_le = models.DateTimeField(help_text=_l("Dernière fois que la tâche de nuit l'a constaté."))
    etat = models.CharField(max_length=16, choices=ETATS, default=OUVERT, db_index=True)
    traite_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    traite_le = models.DateTimeField(null=True, blank=True)
    decision = models.TextField(blank=True, help_text=_l("Le motif de la décision, obligatoire."))

    class Meta:
        verbose_name = "signal de risque"
        verbose_name_plural = "signaux de risque"
        ordering = ["-gravite", "-score", "-constate_le"]
        constraints = [
            models.UniqueConstraint(
                fields=["boutique", "type"],
                condition=models.Q(etat="ouvert"),
                name="un_signal_ouvert_par_type_et_boutique",
            )
        ]

    def __str__(self):
        return f"{self.get_type_display()} · {self.boutique} · {self.get_gravite_display()}"

    @property
    def est_ouvert(self) -> bool:
        return self.etat == self.OUVERT
