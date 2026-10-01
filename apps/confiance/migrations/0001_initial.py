"""Mesures de confiance, journal des changements de palier, signaux de risque.

Écrite à la main plutôt que générée : les modèles d'autres applications évoluaient en parallèle, et
une migration générée aurait embarqué leurs champs. Elle ne touche qu'à `confiance`.
"""

import apps.core.uuid7
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

CHOIX_PALIERS = [
    (0, "Nouvelle boutique"),
    (1, "Boutique confirmée"),
    (2, "Boutique reconnue"),
    (3, "Boutique établie"),
]


def _socle():
    return [
        ("id", models.UUIDField(default=apps.core.uuid7.uuid7, editable=False, primary_key=True, serialize=False)),
        ("cree_le", models.DateTimeField(auto_now_add=True, db_index=True)),
        ("modifie_le", models.DateTimeField(auto_now=True)),
        (
            "cree_par",
            models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("marketplace", "0007_confiance_et_versement"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MesureConfiance",
            fields=_socle()
            + [
                ("livraisons_confirmees", models.PositiveIntegerField(default=0)),
                (
                    "acheteurs_distincts",
                    models.PositiveIntegerField(
                        default=0,
                        help_text=(
                            "Acheteurs distincts derrière ces livraisons. Cent livraisons à un seul acheteur ne "
                            "prouvent pas la même chose que cent livraisons à cent acheteurs."
                        ),
                    ),
                ),
                ("litiges_clos", models.PositiveIntegerField(default=0)),
                ("litiges_perdus", models.PositiveIntegerField(default=0)),
                ("taux_litiges_perdus", models.DecimalField(decimal_places=4, default=0, max_digits=5)),
                ("premiere_activation", models.DateField(blank=True, null=True)),
                ("mesuree_le", models.DateTimeField()),
                (
                    "boutique",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mesure_confiance",
                        to="marketplace.boutique",
                    ),
                ),
            ],
            options={"verbose_name": "mesure de confiance", "verbose_name_plural": "mesures de confiance"},
        ),
        migrations.CreateModel(
            name="ChangementPalier",
            fields=_socle()
            + [
                ("ancien", models.PositiveSmallIntegerField(choices=CHOIX_PALIERS)),
                ("nouveau", models.PositiveSmallIntegerField(choices=CHOIX_PALIERS)),
                ("raisons", models.JSONField(default=list, help_text="Phrases lisibles, dans l'ordre.")),
                ("mesures", models.JSONField(default=dict, help_text="Les chiffres au moment de la décision.")),
                ("decide_le", models.DateTimeField(db_index=True)),
                (
                    "boutique",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="changements_palier",
                        to="marketplace.boutique",
                    ),
                ),
            ],
            options={
                "verbose_name": "changement de palier",
                "verbose_name_plural": "changements de palier",
                "ordering": ["-decide_le", "-cree_le"],
            },
        ),
        migrations.CreateModel(
            name="SignalRisque",
            fields=_socle()
            + [
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("identites_partagees", "Identité partagée avec une autre boutique"),
                            ("prix_appat", "Prix d'appât"),
                            ("pic_prepaiement", "Pic de prépaiement"),
                            ("litiges_annulations", "Litiges et annulations anormaux"),
                            ("changement_compte", "Compte de versement changé avant un versement"),
                            ("non_verifiee", "Boutique active non vérifiée"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                (
                    "gravite",
                    models.PositiveSmallIntegerField(
                        choices=[(1, "Modérée"), (2, "Élevée"), (3, "Critique")], db_index=True, default=1
                    ),
                ),
                ("score", models.PositiveSmallIntegerField(default=0, help_text="0 à 100, pour trier à gravité égale.")),
                ("resume", models.CharField(help_text="La preuve en une phrase, pour la file.", max_length=240)),
                ("preuves", models.JSONField(default=dict)),
                ("empreinte", models.CharField(db_index=True, max_length=64)),
                ("constate_le", models.DateTimeField(help_text="Dernière fois que la tâche de nuit l'a constaté.")),
                (
                    "etat",
                    models.CharField(
                        choices=[("ouvert", "Ouvert"), ("ecarte", "Écarté"), ("confirme", "Confirmé")],
                        db_index=True,
                        default="ouvert",
                        max_length=16,
                    ),
                ),
                ("traite_le", models.DateTimeField(blank=True, null=True)),
                ("decision", models.TextField(blank=True, help_text="Le motif de la décision, obligatoire.")),
                (
                    "boutique",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="signaux_risque",
                        to="marketplace.boutique",
                    ),
                ),
                (
                    "traite_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "signal de risque",
                "verbose_name_plural": "signaux de risque",
                "ordering": ["-gravite", "-score", "-constate_le"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("etat", "ouvert")),
                        fields=("boutique", "type"),
                        name="un_signal_ouvert_par_type_et_boutique",
                    )
                ],
            },
        ),
    ]
