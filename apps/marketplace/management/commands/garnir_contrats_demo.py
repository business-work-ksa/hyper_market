"""Garnir les contrats de démonstration : loyers, une candidature, des emplacements premium.

`charger_demo` peuple ce que vivent les **commerçants** : ventes, stock, écritures. La console de la
plateforme, elle, lit ce que vit le **bailleur** — les factures de loyer, les candidatures, les
emplacements vendus — et rien de tout cela n'existait dans le jeu de démonstration. Un tableau de
bord de place de marché qui affiche zéro partout ne démontre rien, sinon qu'il est vide.

Commande distincte, et idempotente, pour une raison précise : une instance déjà garnie
(`preparer_demo` refuse de recharger une base qui contient des boutiques) doit pouvoir recevoir
ces contrats sans rejouer vingt jours de ventes. Elle ne fait rien s'il existe déjà une facture de
loyer : sur une instance réelle, le premier loyer émis la rend inerte pour toujours.

Tout est sur des tables non scopées (contrats du bailleur) : aucune barrière n'est franchie.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.marketplace.models import (
    Bail,
    Boutique,
    EmplacementPremium,
    FactureLoyer,
    Rayon,
    TypeEmplacement,
)

MOIS_D_HISTORIQUE = 6

# Une boutique qui paie en retard et une qui a un mois impayé : sans elles, la file « À traiter »
# et le taux de recouvrement n'ont rien à montrer, et ce sont précisément les deux écrans dont un
# exploitant se sert chaque semaine.
SLUG_RETARD = "quincaillerie-ateba"
SLUG_IMPAYE = "nkolo-electronique"


def _premier_du_mois(jour, recul: int):
    annee, mois = jour.year, jour.month - recul
    while mois <= 0:
        mois += 12
        annee -= 1
    return jour.replace(year=annee, month=mois, day=1)


class Command(BaseCommand):
    help = "Ajoute loyers, candidature et emplacements premium à une démonstration (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        if FactureLoyer.objects.exists():
            self.stdout.write("Des factures de loyer existent déjà : rien à garnir.")
            return
        baux = list(
            Bail.objects.filter(etat=Bail.ACTIF).select_related("boutique", "boutique__rayon_principal")
        )
        if not baux:
            self.stdout.write("Aucun bail actif : chargez d'abord la démonstration.")
            return

        aujourdhui = timezone.localdate()
        factures = 0
        for bail in baux:
            for recul in range(MOIS_D_HISTORIQUE - 1, -1, -1):
                periode = _premier_du_mois(aujourdhui, recul)
                echeance = periode + timedelta(days=9)
                facture = FactureLoyer(
                    bail=bail, periode=periode, montant_ht=bail.loyer_mensuel, echeance=echeance
                )
                en_retard = bail.boutique.slug in (SLUG_RETARD, SLUG_IMPAYE)
                if recul == 0 and (en_retard or echeance >= aujourdhui):
                    pass  # le mois en cours : émise, due plus tard ou attendue des retardataires
                elif recul == 1 and bail.boutique.slug == SLUG_IMPAYE:
                    facture.etat = FactureLoyer.IMPAYEE
                else:
                    retard = 17 if bail.boutique.slug == SLUG_RETARD else -3
                    facture.etat = FactureLoyer.PAYEE
                    facture.paye_le = timezone.make_aware(
                        timezone.datetime.combine(echeance + timedelta(days=retard), timezone.datetime.min.time())
                    ).replace(hour=10)
                facture.save()
                factures += 1

        emplacements = self._emplacements(baux, aujourdhui)
        candidature = self._candidature()
        self.stdout.write(
            self.style.SUCCESS(
                f"Contrats de démonstration : {factures} factures de loyer, "
                f"{emplacements} emplacements premium"
                + (", une candidature à valider." if candidature else ".")
            )
        )

    def _emplacements(self, baux, aujourdhui) -> int:
        par_slug = {b.boutique.slug: b.boutique for b in baux}
        plan = [
            # (slug, type, début relatif, durée en jours, tarif)
            ("bella-cosmetiques", EmplacementPremium.ACCUEIL, -10, 28, "60000"),
            ("boulangerie-bonapriso", EmplacementPremium.TETE_DE_GONDOLE, -4, 14, "25000"),
            ("pharmacie-du-wouri", EmplacementPremium.BANDEAU_RAYON, 6, 21, "35000"),
            ("auto-pieces-ndokoti", EmplacementPremium.TETE_DE_GONDOLE, -60, 14, "25000"),
        ]
        n = 0
        for slug, type_, decalage, duree, tarif in plan:
            boutique = par_slug.get(slug)
            if boutique is None:
                continue
            debut = aujourdhui + timedelta(days=decalage)
            EmplacementPremium.objects.create(
                rayon=boutique.rayon_principal,
                type=type_,
                debut=debut,
                fin=debut + timedelta(days=duree),
                tarif=Decimal(tarif),
                boutique_occupante=boutique,
            )
            n += 1
        return n

    def _candidature(self) -> bool:
        """Une boutique en attente de validation : c'est le geste quotidien de l'exploitant."""
        if Boutique.objects.filter(etat=Boutique.CANDIDATURE).exists():
            return False
        rayon = Rayon.objects.filter(code="mode-accessoires").first() or Rayon.objects.order_by("ordre").first()
        offre = TypeEmplacement.objects.filter(code=TypeEmplacement.ETAL).first() or (
            TypeEmplacement.objects.order_by("ordre").first()
        )
        if rayon is None or offre is None:
            return False
        boutique, cree = Boutique.objects.get_or_create(
            slug="couture-akwa",
            defaults={
                "raison_sociale": "Atelier Couture Akwa",
                "enseigne": "Couture Akwa",
                "metier": "MODE",
                "ville": "Douala",
                "telephone": "+237699110099",
                "rayon_principal": rayon,
                "etat": Boutique.CANDIDATURE,
            },
        )
        if cree:
            Bail.objects.create(
                boutique=boutique,
                type_emplacement=offre,
                loyer_mensuel=offre.loyer_mensuel,
                taux_commission=offre.taux_commission_defaut,
                etat=Bail.BROUILLON,
            )
        return cree
