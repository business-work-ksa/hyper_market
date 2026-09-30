"""Référentiel des six pays de la CEMAC : ce qui change d'un pays à l'autre pour vérifier un marchand.

La plateforme démarre au Cameroun, mais ses marchands et leurs clients franchissent les frontières
(Kousséri–N'Djamena, Kyé-Ossi–Bitam–Ebebiyín, Douala–Brazzaville par le fleuve des marchandises).
Une vérification d'identité écrite pour le seul Cameroun refuserait un commerçant gabonais honnête,
ou pire, accepterait n'importe quoi dans un champ « NIU » qui ne veut rien dire à Libreville.

Ce qui est **commun** aux six : le franc CFA d'Afrique centrale (XAF), émis par la BEAC ; la
supervision bancaire et des services de paiement par la COBAC ; le droit des affaires OHADA, donc le
RCCM comme registre du commerce ; le règlement CEMAC de lutte contre le blanchiment.

Ce qui **change** : l'indicatif téléphonique, le nom de l'identifiant fiscal, les opérateurs de
Mobile Money actifs, et la loi nationale de protection des données.

Toute ligne de ce fichier est une donnée de terrain **à valider** par un juriste local avant
l'ouverture du pays concerné (voir docs/23, §6). Les règles, elles, ne sont pas ici : ce fichier dit
*ce qui existe*, les modules de vérification disent *ce qu'on en exige*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Opérateurs de Mobile Money. Le code est stable : il est enregistré sur un compte de versement.
MTN_MOMO = "MTN_MOMO"
ORANGE_MONEY = "ORANGE_MONEY"
AIRTEL_MONEY = "AIRTEL_MONEY"
MOOV_MONEY = "MOOV_MONEY"
VIREMENT_BANCAIRE = "VIREMENT_BANCAIRE"

LIBELLES_OPERATEURS = {
    MTN_MOMO: "MTN Mobile Money",
    ORANGE_MONEY: "Orange Money",
    AIRTEL_MONEY: "Airtel Money",
    MOOV_MONEY: "Moov Money",
    VIREMENT_BANCAIRE: "Virement bancaire",
}

# Pièces d'identité d'une personne physique, communes aux six pays à quelques noms près.
CNI = "CNI"
PASSEPORT = "PASSEPORT"
CARTE_CONSULAIRE = "CARTE_CONSULAIRE"
TITRE_SEJOUR = "TITRE_SEJOUR"


@dataclass(frozen=True)
class Pays:
    code: str  # ISO 3166-1 alpha-2, celui de `Boutique.pays`
    nom: str
    indicatif: str
    longueur_numero: int  # chiffres après l'indicatif
    identifiant_fiscal: str  # sigle affiché : NIU au Cameroun et au Congo, NIF ailleurs
    libelle_identifiant_fiscal: str
    operateurs: tuple[str, ...]
    pieces: tuple[str, ...] = (CNI, PASSEPORT, CARTE_CONSULAIRE, TITRE_SEJOUR)
    ouvert: bool = False  # le marché accepte-t-il des boutiques de ce pays aujourd'hui ?
    notes: tuple[str, ...] = field(default_factory=tuple)


PAYS = {
    p.code: p
    for p in (
        Pays(
            code="CM",
            nom="Cameroun",
            indicatif="+237",
            longueur_numero=9,
            identifiant_fiscal="NIU",
            libelle_identifiant_fiscal="Numéro d'identifiant unique",
            operateurs=(MTN_MOMO, ORANGE_MONEY, VIREMENT_BANCAIRE),
            ouvert=True,
            notes=(
                "Données personnelles : loi n° 2024/017 du 23 décembre 2024 (docs/08, §4).",
            ),
        ),
        Pays(
            code="GA",
            nom="Gabon",
            indicatif="+241",
            longueur_numero=8,
            identifiant_fiscal="NIF",
            libelle_identifiant_fiscal="Numéro d'identification fiscale",
            operateurs=(AIRTEL_MONEY, MOOV_MONEY, VIREMENT_BANCAIRE),
        ),
        Pays(
            code="CG",
            nom="Congo",
            indicatif="+242",
            longueur_numero=9,
            identifiant_fiscal="NIU",
            libelle_identifiant_fiscal="Numéro d'identification unique",
            operateurs=(MTN_MOMO, AIRTEL_MONEY, VIREMENT_BANCAIRE),
        ),
        Pays(
            code="TD",
            nom="Tchad",
            indicatif="+235",
            longueur_numero=8,
            identifiant_fiscal="NIF",
            libelle_identifiant_fiscal="Numéro d'identification fiscale",
            operateurs=(AIRTEL_MONEY, MOOV_MONEY, VIREMENT_BANCAIRE),
        ),
        Pays(
            code="CF",
            nom="République centrafricaine",
            indicatif="+236",
            longueur_numero=8,
            identifiant_fiscal="NIF",
            libelle_identifiant_fiscal="Numéro d'identification fiscale",
            operateurs=(ORANGE_MONEY, MOOV_MONEY, VIREMENT_BANCAIRE),
        ),
        Pays(
            code="GQ",
            nom="Guinée équatoriale",
            indicatif="+240",
            longueur_numero=9,
            identifiant_fiscal="NIF",
            libelle_identifiant_fiscal="Número de identificación fiscal",
            operateurs=(VIREMENT_BANCAIRE,),
            notes=(
                "Mobile Money peu développé : versement par virement bancaire. Langue de travail "
                "espagnole — à prévoir dans les écrans avant toute ouverture.",
            ),
        ),
    )
}

PAYS_OUVERTS = tuple(code for code, p in PAYS.items() if p.ouvert)


def pays(code: str) -> Pays:
    """Le pays, ou une `KeyError` explicite : un code inconnu est une erreur de donnée."""
    try:
        return PAYS[code]
    except KeyError:
        raise KeyError(f"« {code} » n'est pas un pays de la CEMAC.") from None


def pays_du_numero(numero: str) -> Pays | None:
    """Le pays d'un numéro au format international, s'il est de la CEMAC."""
    numero = (numero or "").replace(" ", "")
    for p in PAYS.values():
        if numero.startswith(p.indicatif):
            return p
    return None


def numero_valide(numero: str, code_pays: str) -> bool:
    """Le numéro a-t-il l'indicatif et la longueur du pays ? Ne dit rien de son titulaire."""
    p = pays(code_pays)
    numero = (numero or "").replace(" ", "")
    reste = numero[len(p.indicatif):]
    return numero.startswith(p.indicatif) and reste.isdigit() and len(reste) == p.longueur_numero
