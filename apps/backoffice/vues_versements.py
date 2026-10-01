"""Versements : où est l'argent de la boutique, et comment il lui parvient.

Le portefeuille affiché ici est un **compte de suivi**, pas un dépôt (docs/08, §5.2) : il retrace
ce que la plateforme doit à la boutique. Deux soldes, parce qu'il y a deux situations :

* **bloqué** — les parts prépayées dont la livraison n'est pas encore confirmée, ou dont le délai
  du palier court encore ;
* **disponible** — ce que le marchand peut demander à recevoir, maintenant.

Lire ces soldes demande `comptabilite.voir` : c'est la trésorerie à venir de la boutique. Les
**demander** exige davantage, `boutique.administrer` — le gérant. Un comptable, et à plus forte
raison un cabinet extérieur, suit l'argent ; il ne le fait pas partir.

La destination n'est jamais saisie ici : c'est le compte de versement vérifié de la boutique,
sorti de son délai de carence, et il est recopié sur le versement au moment de la demande.
"""

from decimal import Decimal

from django.contrib import messages
from django.shortcuts import redirect, render

from apps.accounts import permissions as droit
from apps.backoffice.acces import contexte_commun, exige
from apps.marketplace.confiance import palier_de
from apps.payments import sequestre as sequestre_service
from apps.payments import versements as versements_service
from apps.payments.models import MouvementPortefeuille, Versement
from django.utils.translation import gettext as _


@exige(droit.COMPTABILITE_VOIR)
def versements(request):
    contexte = contexte_commun(request, "versements")
    boutique = contexte["boutique"]
    peut_demander = droit.BOUTIQUE_ADMINISTRER in contexte["droits"]

    if request.method == "POST":
        if not peut_demander:
            messages.error(request, _("Seul le gérant de la boutique demande un versement."))
            return redirect("versements_marchand")
        try:
            versement = versements_service.demander_versement(boutique, par=request.user)
        except versements_service.VersementRefuse as refus:
            messages.error(request, str(refus))
        else:
            messages.success(
                request,
                _("Versement de %(montant_lisible)s FCFA demandé, vers %(libelle_operateur)s %(numero)s. La plateforme l'exécute et vous en communique la référence.") % {"montant_lisible": sequestre_service.montant_lisible(versement.montant), "libelle_operateur": versement.libelle_operateur, "numero": versement.numero},
            )
        return redirect("versements_marchand")

    compte, refus_compte = versements_service.compte_de_destination(boutique)
    bilan = sequestre_service.bilan(boutique)
    contexte.update(
        {
            "bilan": bilan,
            "compte": compte,
            "refus_compte": refus_compte,
            "peut_demander": peut_demander,
            "en_attente": Versement.objects.filter(
                boutique=boutique, etat=Versement.DEMANDE
            ).exists(),
            # Borné par le contexte de la boutique (barrière 3) : ses mouvements, et eux seuls.
            "mouvements": list(MouvementPortefeuille.objects.order_by("-cree_le")[:50]),
            "historique": list(
                Versement.objects.filter(boutique=boutique).order_by("-cree_le")[:30]
            ),
            "palier": palier_de(boutique),
            "zero": Decimal("0"),
        }
    )
    return render(request, "versements.html", contexte)
