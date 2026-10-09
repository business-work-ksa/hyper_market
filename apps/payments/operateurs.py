"""Clients HTTP des deux opérateurs Mobile Money du Cameroun : MTN MoMo et Orange Money.

Écrits contre les spécifications que les opérateurs publient sur leurs portails de développeurs,
et testés contre des réponses HTTP simulées (`tests/test_operateurs.py`). **Pas encore exécutés
contre un vrai bac à sable** : il faut des identifiants que seul le titulaire du compte marchand
obtient. La commande `essayer_prestataire` fait ce premier aller-retour, et un opérateur ne doit
pas être activé en production avant qu'elle ait réussi.

Quatre règles, communes aux deux, et chacune a coûté cher à quelqu'un avant nous :

1. **Une notification d'opérateur ne prouve rien.** MTN n'en signe aucune ; celle d'Orange porte
   un jeton, mais un jeton se rejoue. Une notification ne sert donc qu'à *réveiller* : le statut
   est toujours relu auprès de l'opérateur avant d'être appliqué (`apps/payments/notifications.py`).
2. **Un jeton d'accès se garde en cache, jamais en mémoire de processus.** Sur une plateforme sans
   serveur, chaque appel peut tomber sur une instance neuve : sans cache partagé, on redemanderait
   un jeton à chaque paiement, et les opérateurs limitent ces demandes.
3. **Une erreur réseau n'est pas un refus.** Délai dépassé, 5xx, réponse illisible →
   `PaiementIndisponible`, que le disjoncteur compte. Un 4xx sur la demande elle-même → transaction
   `echouee` avec le motif de l'opérateur : le client doit pouvoir réessayer ou payer autrement.
4. **Aucun secret dans un message, un journal ou une charge utile enregistrée.** Les clés viennent
   de l'environnement (`config/settings.py`, `PAIEMENTS_OPERATEURS`) et n'en sortent pas.

Sans configuration, chaque client refuse net avec `PrestataireNonConfigure`, en nommant la variable
manquante : l'erreur se lit dans un journal d'exploitation, elle ne se déguise pas en panne réseau.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from apps.payments.adaptateurs import (
    PaiementIndisponible,
    PrestataireNonConfigure,
    ReponseInitiation,
    StatutTransaction,
)
from django.utils.translation import gettext as _

journal = logging.getLogger(__name__)

# Une fonction sans serveur a trente secondes en tout ; un opérateur qui ne répond pas en quinze ne
# répondra pas en vingt, et il faut laisser à la page le temps de dire quelque chose d'utile.
DELAI_RESEAU = 15
# Un jeton expire : on le jette une minute avant, pour ne jamais l'envoyer périmé en plein paiement.
MARGE_JETON = 60


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
class ReponseHttp:
    def __init__(self, statut: int, corps: bytes, entetes: dict):
        self.statut = statut
        self.corps = corps
        self.entetes = entetes

    def json(self) -> dict:
        if not self.corps:
            return {}
        try:
            donnees = json.loads(self.corps.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaiementIndisponible(_("Réponse illisible de l'opérateur.")) from exc
        return donnees if isinstance(donnees, dict) else {"valeur": donnees}


def requete_http(methode: str, url: str, *, entetes: dict, corps: bytes | None = None) -> ReponseHttp:
    """Un appel HTTP, et rien d'autre : c'est le seul point que les tests remplacent.

    Bibliothèque standard plutôt qu'une dépendance : deux appels par paiement ne justifient pas un
    paquet de plus dans une fonction dont la taille compte au démarrage.
    """
    demande = urllib.request.Request(url, data=corps, headers=entetes, method=methode)
    try:
        with urllib.request.urlopen(demande, timeout=DELAI_RESEAU) as reponse:
            return ReponseHttp(reponse.status, reponse.read(), dict(reponse.headers))
    except urllib.error.HTTPError as exc:
        # Un code d'erreur HTTP est une réponse : l'appelant décide s'il est un refus ou une panne.
        return ReponseHttp(exc.code, exc.read() or b"", dict(exc.headers or {}))
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
        raise PaiementIndisponible(_('Opérateur injoignable (%(name)s).') % {"name": type(exc).__name__}) from exc


def _configuration(code: str) -> dict:
    return dict(getattr(settings, "PAIEMENTS_OPERATEURS", {}).get(code, {}))


def _exiger(configuration: dict, code: str, noms: tuple[str, ...]) -> None:
    manquantes = [n for n in noms if not configuration.get(n)]
    if manquantes:
        raise PrestataireNonConfigure(
            f"{code} : configuration absente ({', '.join(manquantes)}). Aucun appel n'a été tenté."
        )


def _url_publique(chemin: str) -> str:
    """Adresse absolue d'une page de ce site, pour qu'un opérateur puisse y revenir."""
    base = (getattr(settings, "URL_PUBLIQUE", "") or "").rstrip("/")
    return f"{base}{chemin}" if base else ""


def _montant_entier(montant: Decimal) -> int:
    """Le franc CFA n'a pas de subdivision en usage : les deux opérateurs attendent un entier."""
    return int(Decimal(montant).quantize(Decimal("1")))


def _msisdn(numero: str) -> str:
    """Numéro au format international sans « + » : 2376XXXXXXXX, ce qu'attend MTN."""
    chiffres = "".join(c for c in (numero or "") if c.isdigit())
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if len(chiffres) == 9:
        chiffres = "237" + chiffres
    return chiffres


def _jeton_en_cache(cle: str, obtenir) -> str:
    jeton = cache.get(cle)
    if jeton:
        return jeton
    jeton, duree = obtenir()
    cache.set(cle, jeton, max(int(duree) - MARGE_JETON, 30))
    return jeton


# ---------------------------------------------------------------------------
# MTN MoMo — API « Collection » et « Disbursement »
# ---------------------------------------------------------------------------
class AdaptateurMtnMomo:
    """MTN Mobile Money Open API.

    Collecte : `POST /collection/v1_0/requesttopay` pousse une demande sur le téléphone du client,
    qui la valide avec son code secret ; la réponse est un 202 sans corps, et c'est la lecture de
    `GET /collection/v1_0/requesttopay/{référence}` (ou la notification) qui dit l'issue.

    Versement : même mécanique sur `/disbursement/v1_0/transfer`, avec **un autre produit, d'autres
    clés** — MTN sépare les deux, et c'est une bonne chose : une clé de collecte volée ne permet pas
    de verser.

    La référence d'une demande (`X-Reference-Id`) est un UUID version 4 que nous tirons nous-mêmes :
    c'est elle qui sert ensuite à relire le statut.
    """

    code = "MTN_MOMO"
    CHAMPS_COLLECTE = ("cle_abonnement_collecte", "utilisateur_api_collecte", "cle_api_collecte")
    CHAMPS_VERSEMENT = ("cle_abonnement_versement", "utilisateur_api_versement", "cle_api_versement")

    ETATS = {"SUCCESSFUL": "reussie", "FAILED": "echouee", "REJECTED": "echouee", "TIMEOUT": "expiree"}

    def _conf(self) -> dict:
        conf = _configuration(self.code)
        conf.setdefault("url_base", "https://sandbox.momodeveloper.mtn.com")
        conf.setdefault("environnement", "sandbox")
        # Le bac à sable de MTN n'accepte que l'euro ; la production camerounaise, le franc CFA.
        conf.setdefault("devise", "EUR" if conf["environnement"] == "sandbox" else "XAF")
        return conf

    def _jeton(self, conf: dict, produit: str) -> str:
        utilisateur = conf[f"utilisateur_api_{produit}"]
        chemin = "collection" if produit == "collecte" else "disbursement"

        def obtenir():
            identifiants = base64.b64encode(f"{utilisateur}:{conf[f'cle_api_{produit}']}".encode()).decode()
            reponse = requete_http(
                "POST",
                f"{conf['url_base']}/{chemin}/token/",
                entetes={
                    "Authorization": f"Basic {identifiants}",
                    "Ocp-Apim-Subscription-Key": conf[f"cle_abonnement_{produit}"],
                },
                corps=b"",
            )
            if reponse.statut != 200:
                raise PaiementIndisponible(
                    _("MTN a refusé le jeton d'accès (%(produit)s, HTTP %(statut)s).") % {"produit": produit, "statut": reponse.statut}
                )
            donnees = reponse.json()
            if not donnees.get("access_token"):
                raise PaiementIndisponible(_("MTN n'a pas rendu de jeton d'accès."))
            return donnees["access_token"], donnees.get("expires_in", 3600)

        return _jeton_en_cache(f"paiements:jeton:mtn:{produit}:{utilisateur}", obtenir)

    def _entetes(self, conf: dict, produit: str, **supplementaires) -> dict:
        return {
            "Authorization": f"Bearer {self._jeton(conf, produit)}",
            "X-Target-Environment": conf["environnement"],
            "Ocp-Apim-Subscription-Key": conf[f"cle_abonnement_{produit}"],
            "Content-Type": "application/json",
            **supplementaires,
        }

    # -- Collecte ----------------------------------------------------------------------------
    def initier(self, *, reference: str, montant: Decimal, numero: str, url_retour: str = "") -> ReponseInitiation:
        conf = self._conf()
        _exiger(conf, self.code, self.CHAMPS_COLLECTE)
        reference_mtn = str(uuid.uuid4())
        entetes = self._entetes(conf, "collecte", **{"X-Reference-Id": reference_mtn})
        rappel = _url_publique("/paiements/notifications/mtn/")
        if rappel:
            # MTN n'appelle que l'hôte déclaré pour l'utilisateur d'API (`providerCallbackHost`).
            entetes["X-Callback-Url"] = rappel
        corps = {
            "amount": str(_montant_entier(montant)),
            "currency": conf["devise"],
            "externalId": str(reference),
            "payer": {"partyIdType": "MSISDN", "partyId": _msisdn(numero)},
            "payerMessage": "Paiement HyperMarché",
            "payeeNote": f"Transaction {reference}",
        }
        reponse = requete_http(
            "POST",
            f"{conf['url_base']}/collection/v1_0/requesttopay",
            entetes=entetes,
            corps=json.dumps(corps).encode(),
        )
        if reponse.statut >= 500:
            raise PaiementIndisponible(_('MTN indisponible (HTTP %(statut)s).') % {"statut": reponse.statut})
        if reponse.statut != 202:
            motif = reponse.json().get("message") or reponse.json().get("code") or f"HTTP {reponse.statut}"
            return ReponseInitiation(
                reference_externe=reference_mtn,
                etat="echouee",
                message=f"MTN a refusé la demande : {motif}.",
                charge_utile={"operateur": "MTN", "refus": str(motif)[:200]},
            )
        return ReponseInitiation(
            reference_externe=reference_mtn,
            etat="initiee",
            message="Validez le paiement sur votre téléphone : composez votre code MTN MoMo.",
            charge_utile={"operateur": "MTN", "devise": conf["devise"]},
        )

    def statut(self, reference_externe: str, *, charge_utile: dict | None = None) -> StatutTransaction:
        return self._lire(reference_externe, "collecte", "collection/v1_0/requesttopay")

    def _lire(self, reference_externe: str, produit: str, chemin: str) -> StatutTransaction:
        conf = self._conf()
        _exiger(conf, self.code, self.CHAMPS_COLLECTE if produit == "collecte" else self.CHAMPS_VERSEMENT)
        reponse = requete_http(
            "GET",
            f"{conf['url_base']}/{chemin}/{reference_externe}",
            entetes=self._entetes(conf, produit),
        )
        if reponse.statut == 404:
            return StatutTransaction(etat="initiee", message="MTN ne connaît pas encore cette demande.")
        if reponse.statut != 200:
            raise PaiementIndisponible(_('MTN : lecture du statut impossible (HTTP %(statut)s).') % {"statut": reponse.statut})
        donnees = reponse.json()
        brut = str(donnees.get("status", "")).upper()
        etat = self.ETATS.get(brut, "initiee")
        raison = donnees.get("reason")
        if isinstance(raison, dict):
            raison = raison.get("message") or raison.get("code")
        return StatutTransaction(
            etat=etat,
            message=(f"MTN : {raison}" if raison else f"MTN : {brut or 'en attente'}"),
            charge_utile={
                "statut_operateur": brut,
                "reference_financiere": donnees.get("financialTransactionId", ""),
            },
        )

    def rembourser(self, reference_externe: str, montant: Decimal) -> StatutTransaction:
        # Un remboursement se fait ici par un **versement** vers le numéro du payeur, décidé et
        # tracé dans la console : l'API de remboursement de MTN exige un contrat que ce compte n'a
        # pas encore. Le dire vaut mieux qu'un appel vraisemblable.
        raise PrestataireNonConfigure(
            "MTN_MOMO : le remboursement par API n'est pas branché ; il se fait par versement "
            "vers le numéro du payeur, depuis la console."
        )

    # -- Versement ---------------------------------------------------------------------------
    def verser(self, *, reference: str, beneficiaire: str, montant: Decimal) -> ReponseInitiation:
        conf = self._conf()
        _exiger(conf, self.code, self.CHAMPS_VERSEMENT)
        reference_mtn = str(uuid.uuid4())
        corps = {
            "amount": str(_montant_entier(montant)),
            "currency": conf["devise"],
            "externalId": str(reference),
            "payee": {"partyIdType": "MSISDN", "partyId": _msisdn(beneficiaire)},
            "payerMessage": "Versement HyperMarché",
            "payeeNote": f"Versement {reference}",
        }
        reponse = requete_http(
            "POST",
            f"{conf['url_base']}/disbursement/v1_0/transfer",
            entetes=self._entetes(conf, "versement", **{"X-Reference-Id": reference_mtn}),
            corps=json.dumps(corps).encode(),
        )
        if reponse.statut >= 500:
            raise PaiementIndisponible(_('MTN indisponible (HTTP %(statut)s).') % {"statut": reponse.statut})
        if reponse.statut != 202:
            motif = reponse.json().get("message") or f"HTTP {reponse.statut}"
            return ReponseInitiation(
                reference_externe=reference_mtn,
                etat="echouee",
                message=f"MTN a refusé le versement : {motif}.",
                charge_utile={"operateur": "MTN", "refus": str(motif)[:200]},
            )
        return ReponseInitiation(
            reference_externe=reference_mtn,
            etat="initiee",
            message="Versement transmis à MTN.",
            charge_utile={"operateur": "MTN", "devise": conf["devise"]},
        )

    def statut_versement(self, reference_externe: str) -> StatutTransaction:
        return self._lire(reference_externe, "versement", "disbursement/v1_0/transfer")


# ---------------------------------------------------------------------------
# Orange Money — Web Payment (Cameroun)
# ---------------------------------------------------------------------------
class AdaptateurOrangeMoney:
    """Orange Money Web Payment.

    Le paiement se fait **chez Orange** : on obtient une adresse de paiement (`payment_url`), on y
    envoie l'acheteur, il y saisit son numéro et son code, puis Orange le renvoie sur notre page
    (`return_url`) et nous notifie (`notif_url`). Pour relire le statut, Orange exige de rappeler
    l'identifiant de commande, le montant et son jeton de paiement : ils sont gardés dans la charge
    utile de la transaction.

    La notification porte un `notif_token` rendu à l'initiation. On n'en garde que l'empreinte : la
    base n'a pas à contenir de quoi forger une notification.

    Pas de versement ici : l'offre Web Payment ne couvre que la collecte. Un versement vers Orange
    Money s'exécute à la main depuis la console, avec la référence de l'opération.
    """

    code = "ORANGE_MONEY"
    CHAMPS = ("id_client", "secret_client", "cle_marchand")
    ETATS = {"SUCCESS": "reussie", "FAILED": "echouee", "EXPIRED": "expiree"}

    def _conf(self) -> dict:
        conf = _configuration(self.code)
        conf.setdefault("url_base", "https://api.orange.com")
        # `dev/v1` et la devise « OUV » en bac à sable ; `cm/v1` et XAF en production.
        conf.setdefault("chemin", "orange-money-webpay/dev/v1")
        conf.setdefault("devise", "OUV" if "/dev/" in conf["chemin"] else "XAF")
        return conf

    def _jeton(self, conf: dict) -> str:
        def obtenir():
            identifiants = base64.b64encode(f"{conf['id_client']}:{conf['secret_client']}".encode()).decode()
            reponse = requete_http(
                "POST",
                f"{conf['url_base']}/oauth/v3/token",
                entetes={
                    "Authorization": f"Basic {identifiants}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                corps=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            )
            if reponse.statut != 200:
                raise PaiementIndisponible(_("Orange a refusé le jeton d'accès (HTTP %(statut)s).") % {"statut": reponse.statut})
            donnees = reponse.json()
            if not donnees.get("access_token"):
                raise PaiementIndisponible(_("Orange n'a pas rendu de jeton d'accès."))
            return donnees["access_token"], donnees.get("expires_in", 3600)

        return _jeton_en_cache(f"paiements:jeton:orange:{conf['id_client']}", obtenir)

    def _entetes(self, conf: dict) -> dict:
        return {
            "Authorization": f"Bearer {self._jeton(conf)}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def identifiant_commande(reference: str) -> str:
        """L'identifiant de commande envoyé à Orange : notre référence, sans tirets, bornée."""
        return str(reference).replace("-", "")[:30]

    @staticmethod
    def empreinte_jeton(jeton: str) -> str:
        return hashlib.sha256((jeton or "").encode()).hexdigest()

    def initier(self, *, reference: str, montant: Decimal, numero: str, url_retour: str = "") -> ReponseInitiation:
        conf = self._conf()
        _exiger(conf, self.code, self.CHAMPS)
        notification = _url_publique(f"/paiements/notifications/orange/{reference}/")
        if not notification or not url_retour:
            raise PrestataireNonConfigure(
                "ORANGE_MONEY : URL_PUBLIQUE absente — Orange doit pouvoir revenir sur ce site et "
                "le notifier. Aucun appel n'a été tenté."
            )
        order_id = self.identifiant_commande(reference)
        entier = _montant_entier(montant)
        corps = {
            "merchant_key": conf["cle_marchand"],
            "currency": conf["devise"],
            "order_id": order_id,
            "amount": entier,
            "return_url": url_retour,
            "cancel_url": url_retour,
            "notif_url": notification,
            "lang": "fr",
            "reference": "HyperMarché",
        }
        reponse = requete_http(
            "POST",
            f"{conf['url_base']}/{conf['chemin']}/webpayment",
            entetes=self._entetes(conf),
            corps=json.dumps(corps).encode(),
        )
        if reponse.statut >= 500:
            raise PaiementIndisponible(_('Orange indisponible (HTTP %(statut)s).') % {"statut": reponse.statut})
        donnees = reponse.json()
        if reponse.statut not in (200, 201) or not donnees.get("payment_url"):
            motif = donnees.get("message") or donnees.get("description") or f"HTTP {reponse.statut}"
            return ReponseInitiation(
                reference_externe=order_id,
                etat="echouee",
                message=f"Orange a refusé la demande : {motif}.",
                charge_utile={"operateur": "ORANGE", "refus": str(motif)[:200]},
            )
        return ReponseInitiation(
            reference_externe=order_id,
            etat="initiee",
            message="Poursuivez le paiement sur la page Orange Money.",
            charge_utile={
                "operateur": "ORANGE",
                "order_id": order_id,
                "montant": entier,
                "pay_token": donnees.get("pay_token", ""),
                "payment_url": donnees["payment_url"],
                "notif_token_empreinte": self.empreinte_jeton(donnees.get("notif_token", "")),
            },
        )

    def statut(self, reference_externe: str, *, charge_utile: dict | None = None) -> StatutTransaction:
        conf = self._conf()
        _exiger(conf, self.code, self.CHAMPS)
        charge = charge_utile or {}
        if not charge.get("pay_token"):
            return StatutTransaction(etat="initiee", message="Jeton de paiement Orange absent.")
        reponse = requete_http(
            "POST",
            f"{conf['url_base']}/{conf['chemin']}/transactionstatus",
            entetes=self._entetes(conf),
            corps=json.dumps(
                {
                    "order_id": charge.get("order_id") or reference_externe,
                    "amount": charge.get("montant"),
                    "pay_token": charge["pay_token"],
                }
            ).encode(),
        )
        if reponse.statut >= 500 or reponse.statut in (401, 403):
            raise PaiementIndisponible(_('Orange : lecture du statut impossible (HTTP %(statut)s).') % {"statut": reponse.statut})
        donnees = reponse.json()
        brut = str(donnees.get("status", "")).upper()
        return StatutTransaction(
            etat=self.ETATS.get(brut, "initiee"),
            message=f"Orange : {brut or 'en attente'}",
            charge_utile={"statut_operateur": brut, "reference_financiere": donnees.get("txnid", "")},
        )

    def rembourser(self, reference_externe: str, montant: Decimal) -> StatutTransaction:
        raise PrestataireNonConfigure(
            "ORANGE_MONEY : l'offre Web Payment ne rembourse pas par API ; le remboursement se "
            "fait par versement depuis la console."
        )

    def verser(self, *, reference: str, beneficiaire: str, montant: Decimal) -> ReponseInitiation:
        raise PrestataireNonConfigure(
            "ORANGE_MONEY : l'offre Web Payment ne verse pas ; exécutez le versement à la main et "
            "saisissez la référence Orange dans la console."
        )


# Les clients réels prennent leur place dans le registre à leur chargement. `adaptateur_pour` charge
# ce module au premier besoin : ce sens-là de l'import n'est jamais circulaire.
from apps.payments.adaptateurs import enregistrer_adaptateur  # noqa: E402

for _adaptateur in (AdaptateurMtnMomo(), AdaptateurOrangeMoney()):
    enregistrer_adaptateur(_adaptateur)
