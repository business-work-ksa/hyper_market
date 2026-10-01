"""Le rapport de la semaine, pour le patron, sur WhatsApp (docs/22, §2.2).

Le propriétaire d'une boutique à Douala n'ouvre pas un tableau de bord. Il ouvre WhatsApp quarante
fois par jour. Le rapport va donc à lui : six lignes, le lundi.

Ce qu'il dit, et rien d'autre : chiffre d'affaires de la semaine écoulée et sa comparaison avec la
précédente, les articles qui partent, les ruptures, et ce que doivent les clients du cahier. Pas de
marge : un message WhatsApp se transfère, se lit par-dessus l'épaule, et la marge est précisément ce
que le reste du logiciel protège avec le plus de soin (ADR-012). Le cahier n'y figure que pour qui a
le droit de le voir.

Deux façons de l'envoyer :

* **À la main**, depuis le back-office : un lien « Envoyer sur WhatsApp » ouvre WhatsApp avec le
  message déjà écrit. Aucune clé, aucun coût — c'est ce qui marche dès aujourd'hui ;
* **Tout seul, le lundi** — plus tard, par l'API WhatsApp Business, quand un gabarit aura été
  validé par Meta. Facturé à la conversation : un message par boutique et par semaine, et rien de
  plus (docs/22, §2.2 — jamais « illimité »). Le texte produit ici est celui que ce gabarit portera.

Tout est lu dans le contexte de la boutique : le rapport d'une boutique ne voit que ses tickets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote

from django.db.models import DecimalField, F, Sum
from django.utils import timezone

from apps.accounts import permissions as droit
from apps.core.tenancy import contexte_boutique

ARTICLES = 5
RUPTURES_NOMMEES = 3
INDICATIF = "237"


@dataclass
class Rapport:
    boutique: str
    debut: date
    fin: date
    chiffre_affaires: Decimal
    precedent: Decimal
    tickets: int
    articles: list = field(default_factory=list)  # [(libellé, quantité)]
    ruptures: list = field(default_factory=list)  # libellés
    ruptures_total: int = 0
    stock_visible: bool = False
    cahier: Decimal | None = None  # None : la personne n'a pas le droit de le voir

    @property
    def evolution(self) -> int | None:
        """L'écart à la semaine précédente, en pour-cent entier ; `None` si elle était vide."""
        if not self.precedent:
            return None
        return int(round((self.chiffre_affaires - self.precedent) / self.precedent * 100))


def semaine_ecoulee(aujourdhui: date | None = None) -> tuple[date, date]:
    """Du lundi au dimanche de la dernière semaine complète. Un rapport du lundi parle de celle-là."""
    aujourdhui = aujourdhui or timezone.localdate()
    fin = aujourdhui - timedelta(days=aujourdhui.weekday() + 1)
    return fin - timedelta(days=6), fin


def rapport_de_la_semaine(boutique, *, droits, aujourdhui: date | None = None) -> Rapport:
    from apps.backoffice.acces import niveaux_en_alerte
    from apps.pos.models import LigneTicket, Ticket

    debut, fin = semaine_ecoulee(aujourdhui)
    with contexte_boutique(boutique):
        tickets = Ticket.objects.filter(
            etat=Ticket.CLOTURE, cloture_le__date__gte=debut, cloture_le__date__lte=fin
        )
        agregat = tickets.aggregate(total=Sum("total_ttc"))
        precedent = Ticket.objects.filter(
            etat=Ticket.CLOTURE,
            cloture_le__date__gte=debut - timedelta(days=7),
            cloture_le__date__lte=fin - timedelta(days=7),
        ).aggregate(total=Sum("total_ttc"))["total"]

        articles = list(
            LigneTicket.objects.filter(ticket__in=tickets)
            .values("libelle")
            .annotate(
                qte=Sum("quantite"),
                montant=Sum(
                    F("quantite") * F("pu_ttc") - F("remise"),
                    output_field=DecimalField(max_digits=18, decimal_places=4),
                ),
            )
            .order_by("-montant")[:ARTICLES]
        )

        ruptures = []
        total_ruptures = 0
        if droit.STOCK_VOIR in droits:
            alertes = niveaux_en_alerte().filter(quantite__lte=0)
            total_ruptures = alertes.count()
            ruptures = [n.variante.produit.libelle for n in alertes[:RUPTURES_NOMMEES]]

        cahier = None
        if droit.CAHIER_VOIR in droits:
            from apps.pos.cahier import avec_soldes

            cahier = avec_soldes().filter(encours__gt=0).aggregate(t=Sum("encours"))["t"] or Decimal(
                "0"
            )

    return Rapport(
        boutique=boutique.enseigne,
        debut=debut,
        fin=fin,
        chiffre_affaires=agregat["total"] or Decimal("0"),
        precedent=precedent or Decimal("0"),
        tickets=_compter(boutique, tickets),
        stock_visible=droit.STOCK_VOIR in droits,
        articles=[(a["libelle"], a["qte"]) for a in articles],
        ruptures=ruptures,
        ruptures_total=total_ruptures,
        cahier=cahier,
    )


def _compter(boutique, tickets) -> int:
    with contexte_boutique(boutique):
        return tickets.count()


def _fcfa(montant) -> str:
    entier = int(Decimal(montant).quantize(Decimal("1")))
    return f"{entier:,}".replace(",", " ") + " FCFA"


def _quantite(q) -> str:
    q = Decimal(q).normalize()
    return f"{q:f}".rstrip("0").rstrip(".") if "." in f"{q:f}" else f"{q:f}"


def texte(rapport: Rapport) -> str:
    """Six lignes, lisibles sur un téléphone d'entrée de gamme, sans mise en forme exotique."""
    lignes = [f"*{rapport.boutique}* — semaine du {rapport.debut:%d/%m} au {rapport.fin:%d/%m}"]
    ventes = f"Ventes : {_fcfa(rapport.chiffre_affaires)} ({rapport.tickets} ticket{'s' if rapport.tickets > 1 else ''})"
    if rapport.evolution is not None:
        signe = "+" if rapport.evolution >= 0 else ""
        ventes += f", {signe}{rapport.evolution} % sur la semaine d'avant"
    lignes.append(ventes)
    if rapport.articles:
        lignes.append(
            "Ce qui part : "
            + ", ".join(f"{libelle} ({_quantite(q)})" for libelle, q in rapport.articles)
        )
    else:
        lignes.append("Aucune vente enregistrée cette semaine.")
    if rapport.ruptures_total:
        noms = ", ".join(rapport.ruptures)
        reste = rapport.ruptures_total - len(rapport.ruptures)
        lignes.append(f"En rupture : {noms}" + (f" et {reste} autre{'s' if reste > 1 else ''}" if reste > 0 else ""))
    elif rapport.stock_visible:
        lignes.append("Aucune rupture.")
    if rapport.cahier is not None:
        lignes.append(f"Cahier de crédit : {_fcfa(rapport.cahier)} à recevoir de vos clients")
    lignes.append("— HyperMarché")
    return "\n".join(lignes)


def lien_whatsapp(message: str, numero: str = "") -> str:
    """Le lien qui ouvre WhatsApp avec le message déjà écrit.

    Sans numéro, WhatsApp demande à qui l'envoyer : le patron choisit lui-même, ou se l'envoie.
    Un numéro camerounais saisi sans indicatif (neuf chiffres) reçoit le 237 que wa.me exige.
    """
    chiffres = "".join(c for c in (numero or "") if c.isdigit())
    if len(chiffres) == 9:
        chiffres = INDICATIF + chiffres
    return f"https://wa.me/{chiffres}?text={quote(message)}"
