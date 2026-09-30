"""Séquestre par sous-commande, portefeuille à deux compartiments, versements.

L'ancien `Sequestre` (un par commande) n'a jamais été écrit par aucun code : sa table est vide
partout. Il est donc remplacé plutôt que transformé — une migration de données sur une table vide
n'aurait rien prouvé, et un champ `boutique` non nul ne s'ajoute pas sans valeur à inventer.
"""

import apps.core.uuid7
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("marketplace", "0007_confiance_et_versement"),
        ("orders", "0004_confiance_et_versement"),
        ("payments", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(name="Sequestre"),
        migrations.CreateModel(
            name="Sequestre",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=apps.core.uuid7.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("cree_le", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                ("montant_encaisse", models.DecimalField(decimal_places=2, max_digits=14)),
                ("commission", models.DecimalField(decimal_places=2, max_digits=14)),
                (
                    "montant",
                    models.DecimalField(
                        decimal_places=2, help_text="Part nette du marchand.", max_digits=14
                    ),
                ),
                (
                    "montant_libere",
                    models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14),
                ),
                (
                    "montant_rembourse",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0"),
                        help_text="Ce qui, sur la part du marchand, revient à l'acheteur.",
                        max_digits=14,
                    ),
                ),
                (
                    "rembourse_acheteur",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0"),
                        help_text="Total à rendre à l'acheteur, commission annulée comprise.",
                        max_digits=14,
                    ),
                ),
                (
                    "etat",
                    models.CharField(
                        choices=[
                            ("bloque", "Bloqué"),
                            ("libere", "Libéré"),
                            ("rembourse", "Remboursé"),
                            ("partage", "Libéré en partie, remboursé en partie"),
                        ],
                        db_index=True,
                        default="bloque",
                        max_length=16,
                    ),
                ),
                ("libere_le", models.DateTimeField(blank=True, null=True)),
                ("rembourse_le", models.DateTimeField(blank=True, null=True)),
                ("motif", models.CharField(blank=True, max_length=255)),
                ("code_remise_hache", models.CharField(blank=True, max_length=128)),
                ("essais_code_echoues", models.PositiveSmallIntegerField(default=0)),
                ("code_verrouille_le", models.DateTimeField(blank=True, null=True)),
                (
                    "confirmation",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("code", "Code de remise saisi à la livraison"),
                            ("acheteur", "Confirmée par l'acheteur"),
                            (
                                "implicite",
                                "Réputée confirmée, sans réclamation 7 jours après l'expédition",
                            ),
                        ],
                        max_length=12,
                    ),
                ),
                (
                    "boutique",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sequestres",
                        to="marketplace.boutique",
                    ),
                ),
                (
                    "commande",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sequestres",
                        to="orders.commande",
                    ),
                ),
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
                (
                    "sous_commande",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sequestre",
                        to="orders.souscommande",
                    ),
                ),
            ],
            options={
                "verbose_name": "séquestre",
                "ordering": ["-cree_le"],
                "indexes": [
                    models.Index(
                        fields=["boutique", "etat"], name="sequestre_boutique_etat"
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="mouvementportefeuille",
            name="compartiment",
            field=models.CharField(
                choices=[("disponible", "Disponible"), ("bloque", "Bloqué")],
                db_index=True,
                default="disponible",
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name="mouvementportefeuille",
            name="solde_apres",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Solde du compartiment après le mouvement.",
                max_digits=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="mouvementportefeuille",
            constraint=models.UniqueConstraint(
                condition=models.Q(("origine_id__isnull", False)),
                fields=("type", "compartiment", "origine_id"),
                name="un_mouvement_par_origine",
            ),
        ),
        migrations.CreateModel(
            name="Versement",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=apps.core.uuid7.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("cree_le", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("modifie_le", models.DateTimeField(auto_now=True)),
                ("montant", models.DecimalField(decimal_places=2, max_digits=16)),
                (
                    "etat",
                    models.CharField(
                        choices=[
                            ("demande", "À exécuter"),
                            ("execute", "Exécuté"),
                            ("annule", "Annulé"),
                        ],
                        db_index=True,
                        default="demande",
                        max_length=12,
                    ),
                ),
                ("pays", models.CharField(max_length=2)),
                ("operateur", models.CharField(max_length=24)),
                ("numero", models.CharField(max_length=34)),
                ("titulaire", models.CharField(max_length=160)),
                ("execute_le", models.DateTimeField(blank=True, null=True)),
                ("reference_operateur", models.CharField(blank=True, max_length=120)),
                ("annule_le", models.DateTimeField(blank=True, null=True)),
                ("motif_annulation", models.CharField(blank=True, max_length=300)),
                (
                    "annule_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "boutique",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="versements",
                        to="marketplace.boutique",
                    ),
                ),
                (
                    "compte",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="versements",
                        to="marketplace.compteversement",
                    ),
                ),
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
                (
                    "demande_par",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "execute_par",
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
                "verbose_name": "versement",
                "ordering": ["-cree_le"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("reference_operateur", ""), _negated=True),
                        fields=("reference_operateur",),
                        name="une_reference_operateur_par_versement",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("montant__gt", 0)),
                        name="versement_montant_positif",
                    ),
                ],
            },
        ),
    ]
