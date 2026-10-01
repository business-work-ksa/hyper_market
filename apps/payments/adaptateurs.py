"""Abstraction multi-prestataire de paiement (docs/09, §6).

MTN et Orange se partagent le marché camerounais ; le pouvoir de négociation qui
en découle est le risque externe le plus élevé du projet (docs/02, §3.3). Aucune
dépendance à un opérateur unique n'est acceptable, et aucun code métier ne doit
connaître le nom d'un prestataire.

Ce que ce module contient, et ce qu'il ne contient pas
------------------------------------------------------

Il contient le contrat d'adaptateur, un prestataire simulé aux réponses
déterministes, le disjoncteur qui protège des appels sortants — et, depuis que le
paiement en ligne est ouvert, les **clients HTTP de MTN MoMo et d'Orange Money**
(`apps/payments/operateurs.py`).

Ces deux clients sont écrits contre les spécifications publiées par les
opérateurs et testés contre des réponses HTTP simulées. **Ils n'ont pas encore été
exécutés contre un vrai bac à sable** : il faut pour cela des identifiants que
seul le titulaire du compte marchand peut obtenir. La commande
`essayer_prestataire` fait ce premier aller-retour ; tant qu'elle n'a pas réussi,
un prestataire réel ne doit pas être activé en production. Sans identifiants, ils
refusent net, avec un message qui nomme ce qui manque — jamais une erreur réseau
déguisée. Camtel reste une coquille : aucune spécification publique.
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, runtime_checkable

__all__ = [
    "PaiementIndisponible",
    "PrestataireNonConfigure",
    "ReponseInitiation",
    "StatutTransaction",
    "PrestatairePaiement",
    "Disjoncteur",
    "FauxPrestataire",
    "AdaptateurCamtel",
    "adaptateur_pour",
    "enregistrer_adaptateur",
]


class PaiementIndisponible(RuntimeError):
    """Le prestataire ne répond pas, ou son disjoncteur est ouvert."""


class PrestataireNonConfigure(PaiementIndisponible):
    """L'adaptateur existe mais n'a pas d'identifiants : rien n'a été tenté."""


@dataclass(frozen=True)
class ReponseInitiation:
    """Ce que rend un prestataire quand on lui demande de débiter un client.

    `etat` reprend les états de `Transaction` : la plupart des paiements Mobile
    Money restent `initiee` le temps que le client tape son code sur son
    téléphone. C'est la notification, ou l'interrogation de statut, qui tranche.
    """

    reference_externe: str
    etat: str
    message: str = ""
    charge_utile: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StatutTransaction:
    etat: str
    message: str = ""
    charge_utile: dict = field(default_factory=dict)


@runtime_checkable
class PrestatairePaiement(Protocol):
    """Contrat que doit remplir tout prestataire, réel ou simulé."""

    code: str

    # `url_retour` : la page où l'opérateur renvoie l'acheteur quand le paiement se fait chez lui
    # (Orange WebPay) ; ignoré par un opérateur qui pousse la demande sur le téléphone (MTN).
    def initier(
        self, *, reference: str, montant: Decimal, numero: str, url_retour: str = ""
    ) -> ReponseInitiation: ...

    # `charge_utile` : ce que l'opérateur a rendu à l'initiation. Orange exige de rappeler son
    # jeton de paiement et le montant pour dire où en est la transaction.
    def statut(self, reference_externe: str, *, charge_utile: dict | None = None) -> StatutTransaction: ...

    def rembourser(self, reference_externe: str, montant: Decimal) -> StatutTransaction: ...

    def verser(self, *, reference: str, beneficiaire: str, montant: Decimal) -> ReponseInitiation: ...


# ---------------------------------------------------------------------------
# Disjoncteur
# ---------------------------------------------------------------------------
class Disjoncteur:
    """Coupe les appels vers un prestataire qui échoue en série.

    Sans lui, une panne d'opérateur se traduit par des caisses figées : chaque
    encaissement attend l'expiration du délai réseau avant d'échouer. Le
    disjoncteur transforme une attente de trente secondes en refus immédiat, ce
    qui laisse au routage la possibilité de basculer.

    **Limite assumée : l'état est en mémoire de processus.** Avec plusieurs
    serveurs, chacun apprend la panne de son côté. Le partager demande Redis, et
    ce n'est utile qu'à partir du moment où il y a plusieurs serveurs.
    """

    def __init__(self, *, seuil: int = 3, duree_ouverture: float = 30.0):
        self.seuil = seuil
        self.duree_ouverture = duree_ouverture
        self._echecs: dict[str, int] = {}
        self._ouvert_depuis: dict[str, float] = {}

    def disponible(self, code: str) -> bool:
        ouvert_depuis = self._ouvert_depuis.get(code)
        if ouvert_depuis is None:
            return True
        if time.monotonic() - ouvert_depuis >= self.duree_ouverture:
            # Demi-ouverture : on laisse passer un appel pour voir si c'est revenu.
            self._ouvert_depuis.pop(code, None)
            self._echecs[code] = self.seuil - 1
            return True
        return False

    def succes(self, code: str) -> None:
        self._echecs.pop(code, None)
        self._ouvert_depuis.pop(code, None)

    def echec(self, code: str) -> None:
        compte = self._echecs.get(code, 0) + 1
        self._echecs[code] = compte
        if compte >= self.seuil:
            self._ouvert_depuis[code] = time.monotonic()

    def reinitialiser(self) -> None:
        self._echecs.clear()
        self._ouvert_depuis.clear()


disjoncteur = Disjoncteur()


# ---------------------------------------------------------------------------
# Prestataire simulé
# ---------------------------------------------------------------------------
class FauxPrestataire:
    """Prestataire déterministe, pour les tests et les démonstrations.

    Le comportement est **dicté par le dernier chiffre du numéro du payeur**.
    C'est délibéré : une démonstration crédible doit pouvoir montrer un échec et
    une attente, pas seulement des paiements qui réussissent. Un commerçant à qui
    l'on ne montre que le cas heureux ne croit pas ce qu'il voit.

    | Dernier chiffre | Résultat |
    |---|---|
    | `0` | échec immédiat — solde insuffisant |
    | `9` | reste initiée — le client n'a pas encore validé sur son téléphone |
    | autre | réussite |
    """

    code = "FAUX"

    def __init__(self, code: str = "FAUX"):
        self.code = code

    @staticmethod
    def _cas(numero: str) -> str:
        chiffres = "".join(c for c in numero if c.isdigit())
        return chiffres[-1] if chiffres else "5"

    def initier(
        self, *, reference: str, montant: Decimal, numero: str, url_retour: str = ""
    ) -> ReponseInitiation:
        from apps.payments.models import Transaction

        cas = self._cas(numero)
        if cas == "0":
            return ReponseInitiation(
                reference_externe=f"SIM-{reference}",
                etat=Transaction.ECHOUEE,
                message="Solde insuffisant.",
            )
        if cas == "9":
            return ReponseInitiation(
                reference_externe=f"SIM-{reference}",
                etat=Transaction.INITIEE,
                message="En attente de validation sur le téléphone du client.",
            )
        return ReponseInitiation(
            reference_externe=f"SIM-{reference}",
            etat=Transaction.REUSSIE,
            message="Paiement accepté.",
        )

    def statut(self, reference_externe: str, *, charge_utile: dict | None = None) -> StatutTransaction:
        from apps.payments.models import Transaction

        return StatutTransaction(etat=Transaction.REUSSIE, message="Paiement accepté.")

    def rembourser(self, reference_externe: str, montant: Decimal) -> StatutTransaction:
        from apps.payments.models import Transaction

        return StatutTransaction(etat=Transaction.REUSSIE, message="Remboursement accepté.")

    def verser(self, *, reference: str, beneficiaire: str, montant: Decimal) -> ReponseInitiation:
        from apps.payments.models import Transaction

        return ReponseInitiation(
            reference_externe=f"SIM-V-{reference}",
            etat=Transaction.REUSSIE,
            message="Versement accepté.",
        )


# ---------------------------------------------------------------------------
# Adaptateurs des opérateurs réels — coquilles explicites
# ---------------------------------------------------------------------------
class AdaptateurHttp:
    """Base des adaptateurs d'opérateur.

    Elle porte la configuration attendue et refuse net tant qu'elle est absente.
    L'échec est ainsi lisible dans un journal d'exploitation — « clé MTN absente »
    — plutôt que déguisé en erreur réseau à trois heures du matin.

    Ne sert plus qu'à Camtel, dont aucune spécification d'API n'est publique : MTN et
    Orange ont leurs clients réels dans `apps/payments/operateurs.py`.
    """

    code = ""
    variables_requises: tuple[str, ...] = ()

    def __init__(self, **configuration):
        self.configuration = configuration

    def _exiger_configuration(self) -> None:
        manquantes = [
            nom for nom in self.variables_requises if not self.configuration.get(nom)
        ]
        if manquantes:
            raise PrestataireNonConfigure(
                f"{self.code} : configuration absente ({', '.join(manquantes)}). "
                "Aucun appel n'a été tenté."
            )
        raise PrestataireNonConfigure(
            f"{self.code} : l'appel réseau n'est pas implémenté. "
            "Il sera écrit contre le bac à sable de l'opérateur, jamais à l'aveugle."
        )

    def initier(
        self, *, reference: str, montant: Decimal, numero: str, url_retour: str = ""
    ) -> ReponseInitiation:
        self._exiger_configuration()

    def statut(self, reference_externe: str, *, charge_utile: dict | None = None) -> StatutTransaction:
        self._exiger_configuration()

    def rembourser(self, reference_externe: str, montant: Decimal) -> StatutTransaction:
        self._exiger_configuration()

    def verser(self, *, reference: str, beneficiaire: str, montant: Decimal) -> ReponseInitiation:
        self._exiger_configuration()


class AdaptateurCamtel(AdaptateurHttp):
    code = "CAMTEL"
    variables_requises = ("identifiant_marchand", "cle_api")


# ---------------------------------------------------------------------------
# Registre
# ---------------------------------------------------------------------------
_registre: dict[str, PrestatairePaiement] = {}


def enregistrer_adaptateur(adaptateur: PrestatairePaiement) -> None:
    _registre[adaptateur.code] = adaptateur


def adaptateur_pour(code: str) -> PrestatairePaiement:
    """Adaptateur d'un prestataire, par son code.

    Le registre est peuplé au chargement avec les coquilles d'opérateur et le
    prestataire simulé ; un déploiement réel remplace une entrée en appelant
    `enregistrer_adaptateur`, sans toucher au code métier.
    """
    # Les clients réels vivent dans `operateurs.py`, qui importe ce module-ci : ils s'enregistrent
    # eux-mêmes à leur chargement. Les charger ici, au premier besoin, plutôt qu'en tête de module,
    # évite l'import circulaire — dont le symptôme dépendait de l'ordre de chargement, donc
    # n'apparaissait qu'en production.
    import apps.payments.operateurs  # noqa: F401

    if code not in _registre:
        raise PaiementIndisponible(f"Aucun adaptateur enregistré pour « {code} ».")
    return _registre[code]


for _adaptateur in (FauxPrestataire(), AdaptateurCamtel()):
    enregistrer_adaptateur(_adaptateur)
