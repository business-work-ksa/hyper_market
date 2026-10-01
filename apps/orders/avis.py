"""Prévenir l'équipe d'une boutique, sur WhatsApp, qu'une commande l'attend.

Le vendeur d'une boutique de Mboppi n'a pas le back-office ouvert : il sert au comptoir. Une
commande qui attend trois heures son acceptation est une commande que l'acheteur annule. L'avis va
donc à lui, sur le téléphone qu'il regarde déjà.

**Qui est prévenu.** Les personnes rattachées à la boutique dont le rôle ouvre
`commandes.traiter` — celles qui acceptent, préparent et expédient — et que le gérant n'a pas
retirées de la liste (`Appartenance.avis_commandes`). Personne d'autre : un caissier qui ne traite
pas les commandes n'a pas à recevoir le détail des ventes en ligne.

**Quand.** Au moment où la part devient une chose à faire pour la boutique :

* une part **payée à la livraison** est à préparer dès que la commande est passée ;
* une part **prépayée** ne l'est qu'une fois l'argent constaté. Prévenir avant, c'est faire
  préparer un colis que l'acheteur ne paiera peut-être jamais.

**Ce que dit l'avis.** Le numéro de la commande, les articles, le total, le mode de paiement et le
lien vers la commande dans le back-office. **Ni le nom, ni le téléphone, ni l'adresse de
l'acheteur** : un message WhatsApp se transfère, et ces données restent derrière la connexion du
back-office, où le droit de les voir est vérifié (loi camerounaise n° 2024/017 sur la protection
des données personnelles — minimisation).

**Comment.** Par l'API WhatsApp Business quand elle est configurée (`apps/core/whatsapp.py`).
Sinon, rien ne part tout seul — et l'écran de la commande propose à chacun un lien `wa.me`, message
déjà écrit. Un avis qui échoue ne fait **jamais** échouer la commande : il est noté, et l'écran le
dit.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts import permissions as droit
from apps.core import whatsapp
from apps.core.tenancy import contexte_boutique

journal = logging.getLogger(__name__)

ARTICLES_NOMMES = 4


def roles_qui_traitent() -> list[str]:
    return [code for code, droits in droit.DROITS_PAR_ROLE.items() if droit.COMMANDES_TRAITER in droits]


def responsables(boutique_id) -> list:
    """Les personnes à prévenir pour cette boutique, une seule fois chacune."""
    from apps.accounts.models import Appartenance

    appartenances = (
        Appartenance.objects.filter(
            boutique_id=boutique_id,
            actif=True,
            avis_commandes=True,
            role__code__in=roles_qui_traitent(),
            utilisateur__is_active=True,
        )
        .exclude(utilisateur__telephone="")
        .select_related("utilisateur")
        .order_by("utilisateur__nom_complet")
    )
    vus, personnes = set(), []
    for appartenance in appartenances:
        if appartenance.utilisateur_id not in vus:
            vus.add(appartenance.utilisateur_id)
            personnes.append(appartenance.utilisateur)
    return personnes


def _montant(montant) -> str:
    return f"{int(Decimal(montant).quantize(Decimal('1'))):,}".replace(",", " ")


def _quantite(q) -> str:
    texte = f"{Decimal(q).normalize():f}"
    return texte.rstrip("0").rstrip(".") if "." in texte else texte


def _adresse(sous_commande, base: str = "") -> str:
    """Adresse absolue de la commande : un lien relatif ne mène nulle part depuis WhatsApp."""
    chemin = reverse("commande", args=[sous_commande.pk])
    base = (getattr(settings, "URL_PUBLIQUE", "") or base or "").rstrip("/")
    return f"{base}{chemin}"


def elements(sous_commande, base: str = "") -> dict:
    """Ce que dit l'avis, élément par élément : le gabarit Meta et le lien wa.me lisent les mêmes."""
    from apps.orders.models import LigneCommande, SousCommande

    with contexte_boutique(sous_commande.boutique_id):
        lignes = list(LigneCommande.objects.filter(sous_commande=sous_commande).order_by("cree_le"))
    noms = [f"{_quantite(l.quantite)} × {l.libelle}" for l in lignes[:ARTICLES_NOMMES]]
    reste = len(lignes) - len(noms)
    if reste > 0:
        noms.append(f"et {reste} autre{'s' if reste > 1 else ''}")
    paiement = (
        "déjà payée en ligne"
        if sous_commande.mode_paiement == SousCommande.PREPAYE
        else "à encaisser à la livraison"
    )
    return {
        "numero": sous_commande.commande.numero,
        "boutique": sous_commande.boutique.enseigne,
        "articles": ", ".join(noms) or "—",
        "total": _montant(sous_commande.total_ttc),
        "paiement": paiement,
        "adresse": _adresse(sous_commande, base),
    }


def message(sous_commande, base: str = "") -> str:
    """Le texte de l'avis, pour le lien wa.me. Quatre lignes, sans donnée sur l'acheteur."""
    e = elements(sous_commande, base)
    return "\n".join(
        [
            f"*Nouvelle commande {e['numero']}* — {e['boutique']}",
            e["articles"],
            f"Total : {e['total']} FCFA, {e['paiement']}",
            f"À traiter : {e['adresse']}",
        ]
    )


def liens(sous_commande, base: str = "") -> list[dict]:
    """Pour l'écran de la commande : chaque responsable, et le lien qui le prévient à la main.

    `base` est l'adresse du site telle que la requête la voit, à défaut d'`URL_PUBLIQUE`.
    """
    texte = message(sous_commande, base)
    return [
        {"personne": p, "lien": whatsapp.lien(texte, p.telephone)}
        for p in responsables(sous_commande.boutique_id)
    ]


def aviser(sous_commande) -> list:
    """Envoie l'avis à chaque responsable, par l'API. Sans API configurée, ne fait rien.

    Idempotent : un responsable déjà avisé pour cette part — qu'il l'ait été ou que l'envoi ait
    échoué — n'est pas relancé. Ne lève jamais : un avis n'est pas la commande.
    """
    if not whatsapp.api_configuree("gabarit_commande"):
        return []
    try:
        e = elements(sous_commande)
        parametres = [e["numero"], e["boutique"], e["articles"], e["total"], e["paiement"], e["adresse"]]
        avis = []
        for personne in responsables(sous_commande.boutique_id):
            avis.append(_aviser_une_personne(sous_commande, personne, parametres))
        return [a for a in avis if a is not None]
    except Exception:  # noqa: BLE001 — une panne d'avis ne remonte jamais jusqu'à l'acheteur
        journal.exception("Avis WhatsApp de la commande %s non envoyé", sous_commande.pk)
        return []


def _aviser_une_personne(sous_commande, personne, parametres):
    from apps.orders.models import AvisCommande

    with contexte_boutique(sous_commande.boutique_id):
        if AvisCommande.objects.filter(sous_commande=sous_commande, destinataire=personne).exists():
            return None
        numero = whatsapp.numero_international(personne.telephone)
        try:
            reference = whatsapp.envoyer_gabarit(
                personne.telephone, gabarit="gabarit_commande", parametres=parametres
            )
        except (whatsapp.WhatsAppRefuse, whatsapp.WhatsAppIndisponible) as exc:
            etat, reference, erreur = AvisCommande.ECHEC, "", str(exc)[:255]
        else:
            etat, erreur = AvisCommande.ENVOYE, ""
        try:
            with transaction.atomic():
                return AvisCommande.objects.create(
                    boutique_id=sous_commande.boutique_id,
                    sous_commande=sous_commande,
                    destinataire=personne,
                    numero=numero,
                    etat=etat,
                    reference=reference,
                    erreur=erreur,
                )
        except IntegrityError:
            # Course perdue contre un autre appel : son avis fait foi.
            return None


def aviser_apres_validation(parts) -> None:
    """Programme l'avis des parts pour **après** l'enregistrement de la transaction.

    Jamais pendant : un message parti pour une commande que la transaction annule ensuite
    ferait préparer un colis qui n'existe pas.
    """
    identifiants = [p.pk for p in parts]
    if identifiants and whatsapp.api_configuree("gabarit_commande"):
        transaction.on_commit(lambda: _aviser_les_parts(identifiants))


def _aviser_les_parts(identifiants) -> None:
    from apps.core.tenancy import contexte_plateforme
    from apps.orders.models import SousCommande

    with contexte_plateforme():
        parts = list(
            SousCommande.objects.filter(pk__in=identifiants).select_related("commande", "boutique")
        )
    for part in parts:
        if part.etat != SousCommande.ANNULEE:
            aviser(part)
