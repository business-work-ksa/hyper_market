"""Garde-fous du conflit d'intérêts de l'exploitant-commerçant (ADR-012, garde-fou 3).

L'exploitant de cette place de marché y vend aussi. C'est assumé, et c'est même utile au
démarrage : ses propres boutiques amorcent le catalogue quand personne n'est encore inscrit.

Mais c'est un conflit d'intérêts structurel, et il ne se résout pas en interdisant l'activité —
il se borne en la rendant visible et en fermant les portes où l'avantage serait invisible.

Celle qui est fermée ici est la plus discrète et la plus décisive : **le taux de commission d'un
rayon.** Quelqu'un qui vend des pièces auto et qui peut abaisser la commission du rayon « Pièces
auto » ne s'accorde pas une faveur visible comme une tête de gondole gratuite — il déplace la
rentabilité de tous ses concurrents d'un même geste, dans un champ que personne ne relit.

Ce n'est pas une politique affichée, c'est une règle qui refuse.

Les deux autres garde-fous vivent là où ils sont vérifiables sans code :

* le tarif non nul d'un emplacement premium est une contrainte de base
  (`EmplacementPremium.Meta.constraints`) ;
* le motif obligatoire d'une dérogation de commission est dans `Bail.clean()`.

Le quatrième ne se code pas et reste une politique, ce que l'ADR dit explicitement : **publier la
règle**. Un exploitant-commerçant qui annonce d'emblée ce qu'il s'interdit est plus crédible que
celui qui se fait découvrir.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError

__all__ = ["boutiques_de", "en_conflit_sur_le_rayon", "fixer_taux_rayon"]


def boutiques_de(utilisateur):
    """Identifiants des boutiques où cette personne a une appartenance active.

    Sert au contrôle de conflit, donc on regarde **toutes** les appartenances actives, quel que
    soit le rôle : un simple caissier chez un concurrent a déjà accès à ses prix.
    """
    if utilisateur is None or not getattr(utilisateur, "is_authenticated", False):
        return set()
    return set(
        utilisateur.appartenances.filter(actif=True).values_list("boutique_id", flat=True)
    )


def en_conflit_sur_le_rayon(utilisateur, rayon) -> bool:
    """Cette personne vend-elle dans ce rayon ?

    On compare sur `rayon_principal`, qui est le rattachement déclaré d'une boutique. Une boutique
    qui vend accessoirement dans un autre rayon n'est pas détectée : c'est une limite assumée, et
    la nommer vaut mieux que la taire. Le jour où une boutique porte plusieurs rayons, ce calcul
    est le seul endroit à reprendre.
    """
    from apps.marketplace.models import Boutique

    mes_boutiques = boutiques_de(utilisateur)
    if not mes_boutiques:
        return False

    rayon_id = getattr(rayon, "pk", rayon)
    return Boutique.objects.filter(
        pk__in=mes_boutiques, rayon_principal_id=rayon_id
    ).exists()


def fixer_taux_rayon(rayon, taux: Decimal, *, par, motif: str):
    """Change le taux de commission d'un rayon, en refusant le juge et partie.

    Trois refus, dans cet ordre — du plus grave au plus formel :

    1. **Le conflit d'intérêts.** Quelqu'un qui vend dans ce rayon ne fixe pas son taux. Levé en
       `PermissionDenied` et non en `ValidationError` : ce n'est pas une saisie à corriger, c'est
       un geste qui n'est pas le sien.
    2. **Le motif.** Un taux de rayon gouverne la rentabilité de toutes les boutiques du rayon ;
       le changer sans écrire pourquoi rend la décision inauditable six mois plus tard.
    3. **La plage.** Un taux hors de [0, 1] est une erreur de saisie — presque toujours un
       pourcentage entré comme « 8 » au lieu de « 0,08 », ce qui prendrait 800 % de commission.
    """
    from apps.accounts.permissions import PLATEFORME_COMMISSIONS, droits_plateforme_de

    if PLATEFORME_COMMISSIONS not in droits_plateforme_de(par):
        raise PermissionDenied(
            "Fixer le taux d'un rayon est un droit d'exploitation de la place de marché."
        )

    if en_conflit_sur_le_rayon(par, rayon):
        raise PermissionDenied(
            f"Vous vendez dans le rayon « {rayon} » : vous n'en fixez pas la commission. "
            "Faites-le faire par quelqu'un qui n'y a pas d'intérêt (ADR-012)."
        )

    motif = (motif or "").strip()
    if not motif:
        raise ValidationError(
            {
                "motif": (
                    "Le taux d'un rayon gouverne la rentabilité de toutes ses boutiques. "
                    "Dites pourquoi vous le changez."
                )
            }
        )

    taux = Decimal(taux)
    if not (Decimal("0") <= taux <= Decimal("1")):
        raise ValidationError(
            {
                "taux_commission": (
                    f"Un taux se saisit en fraction, pas en pourcentage : {taux} vaudrait "
                    f"{taux:.0%} de commission."
                )
            }
        )

    ancien = rayon.taux_commission
    rayon.taux_commission = taux
    rayon.save(update_fields=["taux_commission"])

    # Le changement est journalisé là où l'on cherchera : le journal des accès plateforme, qui est
    # en ajout seul. Un champ « dernière modification » sur le rayon serait écrasé au changement
    # suivant, et c'est l'historique qui a de la valeur, pas l'état courant.
    from apps.core.models import AccesPlateforme

    AccesPlateforme.objects.create(
        utilisateur=par,
        boutique_id=None,
        ecran="marketplace/rayon/taux",
        motif=f"Taux « {rayon} » : {ancien:.2%} → {taux:.2%}. {motif}"[:300],
    )
    return rayon
