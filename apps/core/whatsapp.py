"""WhatsApp : le lien qui ouvre la conversation, et l'envoi par l'API WhatsApp Business.

Deux façons de faire partir un message, et elles ne se remplacent pas :

* **le lien `wa.me`** ouvre WhatsApp sur le téléphone de la personne, message déjà écrit. Aucune
  clé, aucun coût, aucun compte chez Meta — mais c'est la personne qui appuie sur « Envoyer » ;
* **l'API WhatsApp Business (Cloud API)** envoie sans personne derrière l'écran. Elle exige un
  compte Meta Business vérifié, un numéro dédié, et — pour écrire le premier à quelqu'un — un
  **gabarit validé par Meta**. Elle est facturée à la conversation.

Ce module ne sait rien des commandes ni des rapports : il transporte un texte. Il n'est configuré
que si les trois réglages `WHATSAPP_JETON`, `WHATSAPP_NUMERO_ID` et un nom de gabarit sont posés
dans l'hébergeur ; sans eux, `api_configuree()` répond non et **aucun appel n'est tenté**.

Les paramètres d'un gabarit ne peuvent contenir ni saut de ligne, ni tabulation, ni plus de quatre
espaces à la suite : Meta refuse le message entier. `parametre()` les nettoie.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote

from django.conf import settings
from django.utils.translation import gettext as _

INDICATIF = "237"
DELAI_RESEAU = 8  # secondes : un avis ne retient jamais une commande plus longtemps
URL_GRAPH = "https://graph.facebook.com"
LONGUEUR_PARAMETRE = 900


class WhatsAppIndisponible(Exception):
    """L'API n'a pas répondu : réseau, délai, panne chez Meta."""


class WhatsAppRefuse(Exception):
    """L'API a répondu non : jeton expiré, gabarit inconnu, numéro sans WhatsApp…"""


@dataclass
class ReponseHttp:
    statut: int
    corps: bytes


def numero_international(numero: str) -> str:
    """Les chiffres du numéro, avec l'indicatif camerounais s'il manque (neuf chiffres)."""
    chiffres = "".join(c for c in (numero or "") if c.isdigit())
    if len(chiffres) == 9:
        chiffres = INDICATIF + chiffres
    return chiffres


def lien(message: str, numero: str = "") -> str:
    """Le lien qui ouvre WhatsApp avec le message déjà écrit.

    Sans numéro, WhatsApp demande à qui l'envoyer.
    """
    return f"https://wa.me/{numero_international(numero)}?text={quote(message)}"


def parametre(texte: str) -> str:
    """Un paramètre de gabarit acceptable par Meta : une ligne, sans blancs à rallonge."""
    texte = re.sub(r"[\r\n\t]+", " · ", str(texte))
    texte = re.sub(r" {4,}", "   ", texte).strip()
    return texte[:LONGUEUR_PARAMETRE]


def _configuration() -> dict:
    return dict(getattr(settings, "WHATSAPP", {}) or {})


def api_configuree(gabarit: str = "gabarit_commande") -> bool:
    configuration = _configuration()
    return bool(configuration.get("jeton") and configuration.get("numero_id") and configuration.get(gabarit))


def requete_http(url: str, *, entetes: dict, corps: bytes) -> ReponseHttp:
    """Un appel HTTP, et rien d'autre : c'est le seul point que les tests remplacent."""
    demande = urllib.request.Request(url, data=corps, headers=entetes, method="POST")
    try:
        with urllib.request.urlopen(demande, timeout=DELAI_RESEAU) as reponse:
            return ReponseHttp(reponse.status, reponse.read())
    except urllib.error.HTTPError as exc:
        return ReponseHttp(exc.code, exc.read() or b"")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
        raise WhatsAppIndisponible(_('WhatsApp injoignable (%(name)s).') % {"name": type(exc).__name__}) from exc


def envoyer_gabarit(numero: str, *, gabarit: str = "gabarit_commande", parametres: list[str]) -> str:
    """Envoie un message à gabarit ; renvoie l'identifiant du message chez Meta.

    `gabarit` est la **clé de réglage** qui porte le nom du gabarit (`gabarit_commande`), pas le
    nom lui-même : le nom validé chez Meta se change dans l'hébergeur, sans toucher au code.
    """
    configuration = _configuration()
    if not api_configuree(gabarit):
        raise WhatsAppRefuse(_("API WhatsApp non configurée : aucun appel n'a été tenté."))
    destinataire = numero_international(numero)
    if len(destinataire) < 8:
        raise WhatsAppRefuse(_("Numéro de destinataire invalide."))

    version = configuration.get("version") or "v21.0"
    url = f"{URL_GRAPH}/{version}/{configuration['numero_id']}/messages"
    charge = {
        "messaging_product": "whatsapp",
        "to": destinataire,
        "type": "template",
        "template": {
            "name": configuration[gabarit],
            "language": {"code": configuration.get("langue") or "fr"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": parametre(p)} for p in parametres],
                }
            ],
        },
    }
    reponse = requete_http(
        url,
        entetes={
            "Authorization": f"Bearer {configuration['jeton']}",
            "Content-Type": "application/json",
        },
        corps=json.dumps(charge).encode(),
    )
    try:
        donnees = json.loads(reponse.corps or b"{}")
    except ValueError:
        donnees = {}
    if reponse.statut >= 500:
        raise WhatsAppIndisponible(_('WhatsApp indisponible (HTTP %(statut)s).') % {"statut": reponse.statut})
    if reponse.statut >= 400 or not donnees.get("messages"):
        erreur = (donnees.get("error") or {}).get("message") or f"HTTP {reponse.statut}"
        # Le message d'erreur de Meta ne contient pas le jeton ; on le tronque quand même.
        raise WhatsAppRefuse(_('WhatsApp a refusé le message : %(element)s') % {"element": erreur[:200]})
    return str(donnees["messages"][0].get("id", ""))
