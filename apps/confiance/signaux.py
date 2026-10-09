"""Les détecteurs de risque : des indices, présentés à un humain qui décide.

Une place de marché africaine perd rarement de l'argent par un piratage. Elle en perd par une
vitrine qui encaisse et disparaît, par un numéro de versement changé la veille d'un virement, par
un réseau de boutiques qu'on ferme et qu'on rouvre sous un autre nom. Aucun de ces schémas ne se
lit dans une seule ligne de base ; chacun laisse une **trace statistique** qu'on peut chercher la
nuit, quand personne n'attend de réponse.

Trois règles gouvernent ce module.

**Un signal n'est pas une preuve.** Chaque détecteur dit dans sa docstring pourquoi son constat
mérite un regard, et pourquoi il peut être parfaitement innocent. Aucun ne suspend quoi que ce
soit : `SignalRisque` met la preuve sous les yeux d'un administrateur, qui écarte ou confirme,
avec un motif inscrit au journal des accès (ADR-012). Une sanction automatique fondée sur un
indice punirait les honnêtes — et apprendrait aux fraudeurs le seuil exact à ne pas franchir.

**La preuve est lisible.** « même téléphone que Boutique X, ouverte le 3 mars 2026, suspendue »
et non « score 83 ». Un administrateur qui ne comprend pas un signal l'écarte ; un signal écarté
par incompréhension est un signal perdu.

**La file ne se remplit pas de doublons.** Un signal ouvert du même type pour la même boutique
est mis à jour, pas recréé (contrainte en base). Un signal écarté ne revient pas tant que les
faits sont les mêmes (`empreinte`) : l'administrateur a déjà jugé ceux-là, et les lui remontrer
chaque nuit lui apprendrait à ne plus lire la file.

Ce module lit des tables scopées (commandes, articles, litiges) : c'est une tâche technique sans
demandeur humain, d'où `contexte_plateforme()` — légitime ici, jamais dans la console. La console
ne relit rien de tout cela : elle affiche les preuves que la tâche a écrites dans le signal.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.core.tenancy import contexte_plateforme
from django.utils.translation import gettext as _

journal = logging.getLogger(__name__)

# Les seuils sont des paramètres à calibrer sur les six premiers mois, comme ceux des paliers. Ils
# sont en code pour la même raison : ce sont des règles, relues en revue, pas des curseurs.
RECENTE_JOURS = 30  # « boutique récente » pour les prix d'appât
JEUNE_JOURS = 90  # « boutique jeune » pour le pic de prépaiement : un trimestre d'historique
APPAT_RATIO = Decimal("0.5")  # moins de la moitié du prix médian du marché
APPAT_PART_MIN = Decimal("0.30")  # part des articles comparables vendus à prix d'appât
APPAT_COMPARABLES_MIN = 3
APPAT_REFERENCES_MIN = 3  # prix de référence ailleurs, pour qu'une médiane veuille dire quelque chose
PIC_FENETRE_JOURS = 7
PIC_HISTORIQUE_JOURS = 56
PIC_HISTORIQUE_JOURS_ETABLIE = 84  # douze semaines pour la médiane d'une boutique établie
PIC_MINIMUM = 10  # en dessous, dix commandes ne sont pas un pic, c'est un bon début
PIC_FACTEUR = 3
LITIGES_FENETRE_JOURS = 30
LITIGES_VOLUME_MIN = 10
LITIGES_TAUX_MIN = Decimal("0.10")
ANNULATIONS_TAUX_MIN = Decimal("0.30")
FACTEUR_MARCHE = 3  # « anormal » = nettement au-dessus du reste du marché, pas seulement haut
COMPTE_DELAI_JOURS = 7


# ----------------------------------------------------------------------------
# Le constat, et son enregistrement
# ----------------------------------------------------------------------------
@dataclass
class Constat:
    boutique_id: object
    type: str
    gravite: int
    score: int
    resume: str
    preuves: dict
    faits: list = field(default_factory=list)  # ce qui fonde le signal, pour l'empreinte

    @property
    def empreinte(self) -> str:
        brut = json.dumps(sorted(str(f) for f in self.faits), ensure_ascii=False)
        return hashlib.sha256(f"{self.type}|{brut}".encode()).hexdigest()[:32]


def enregistrer(constat: Constat, *, maintenant: datetime):
    """Crée ou met à jour le signal ouvert. Renvoie `(signal, "cree" | "maj" | None)`.

    `None` : ces mêmes faits ont déjà été jugés par un humain — on ne les lui remontre pas.
    """
    from apps.confiance.models import SignalRisque

    valeurs = {
        "gravite": constat.gravite,
        "score": max(0, min(int(constat.score), 100)),
        "resume": constat.resume[:240],
        "preuves": constat.preuves,
        "empreinte": constat.empreinte,
        "constate_le": maintenant,
    }
    ouvert = SignalRisque.objects.filter(
        boutique_id=constat.boutique_id, type=constat.type, etat=SignalRisque.OUVERT
    ).first()
    if ouvert is not None:
        for nom, valeur in valeurs.items():
            setattr(ouvert, nom, valeur)
        ouvert.save()
        return ouvert, "maj"
    deja_juge = SignalRisque.objects.filter(
        boutique_id=constat.boutique_id, type=constat.type, empreinte=constat.empreinte
    ).exclude(etat=SignalRisque.OUVERT)
    if deja_juge.exists():
        return None, None
    try:
        with transaction.atomic():
            return (
                SignalRisque.objects.create(
                    boutique_id=constat.boutique_id, type=constat.type, **valeurs
                ),
                "cree",
            )
    except IntegrityError:
        # Deux évaluations simultanées : la contrainte a arbitré, on met à jour celle qui a gagné.
        ouvert = SignalRisque.objects.get(
            boutique_id=constat.boutique_id, type=constat.type, etat=SignalRisque.OUVERT
        )
        for nom, valeur in valeurs.items():
            setattr(ouvert, nom, valeur)
        ouvert.save()
        return ouvert, "maj"


# ----------------------------------------------------------------------------
# Petits outils
# ----------------------------------------------------------------------------
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]


def date_lisible(jour) -> str:
    if jour is None:
        return "date inconnue"
    if isinstance(jour, datetime):
        jour = timezone.localdate(jour)
    return f"{jour.day}{'er' if jour.day == 1 else ''} {MOIS[jour.month - 1]} {jour.year}"


def masquer(numero: str) -> str:
    """Un numéro de compte n'est jamais recopié en entier dans une preuve : quatre chiffres
    suffisent à reconnaître le compte, pas à s'en servir."""
    chiffres = re.sub(r"\s", "", numero or "")
    return "•••• " + chiffres[-4:] if len(chiffres) > 4 else "••••"


def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte or "") if unicodedata.category(c) != "Mn"
    )


def normaliser_libelle(texte: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _sans_accents(texte).lower()).strip()


def normaliser_identifiant(texte: str) -> str:
    """RCCM, NIU, pièce : majuscules, sans espaces ni ponctuation.

    Une valeur trop courte ou faite d'un seul caractère répété (« N/A », « 0000 », « néant ») n'est
    pas un identifiant : deux boutiques qui l'ont saisie ne partagent rien d'autre qu'une paresse.
    """
    valeur = re.sub(r"[^A-Z0-9]", "", _sans_accents(texte).upper())
    if len(valeur) < 5 or len(set(valeur)) < 3 or valeur in {"NEANT", "AUCUN", "INCONNU"}:
        return ""
    return valeur


def normaliser_telephone(numero: str, code_pays: str = "CM") -> str:
    """Au format international, pour que « 699 12 34 56 » et « +237699123456 » se reconnaissent."""
    from apps.marketplace.cemac import PAYS

    chiffres = re.sub(r"\D", "", numero or "")
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    for p in PAYS.values():
        indicatif = p.indicatif.lstrip("+")
        if chiffres.startswith(indicatif) and len(chiffres) - len(indicatif) == p.longueur_numero:
            return "+" + chiffres
    p = PAYS.get(code_pays)
    if p and len(chiffres) == p.longueur_numero:
        return p.indicatif + chiffres
    return "+" + chiffres if len(chiffres) >= 8 and len(set(chiffres)) >= 3 else ""


def _taux(n, d) -> Decimal:
    return (Decimal(n) / Decimal(d)).quantize(Decimal("0.0001")) if d else Decimal("0")


def _pc(fraction) -> str:
    return f"{Decimal(fraction) * 100:.0f} %"


def _fcfa(montant) -> str:
    return f"{Decimal(montant or 0):,.0f}".replace(",", " ") + " FCFA"


@dataclass
class Contexte:
    """Ce que tous les détecteurs partagent, lu une fois."""

    maintenant: datetime
    boutiques: dict  # id → Boutique
    activations: dict  # id → date de première activation

    def age_jours(self, boutique_id) -> int | None:
        debut = self.activations.get(boutique_id)
        return None if debut is None else (timezone.localdate(self.maintenant) - debut).days

    def presenter(self, boutique_id) -> dict:
        b = self.boutiques[boutique_id]
        return {
            "id": str(b.pk),
            "enseigne": b.enseigne,
            "etat": b.etat,
            "etat_libelle": b.get_etat_display(),
            "ouverte_le": date_lisible(self.activations.get(b.pk) or b.cree_le),
        }


# ----------------------------------------------------------------------------
# 1. Identités partagées
# ----------------------------------------------------------------------------
LIBELLES_CHAMPS = {
    "telephone": "téléphone",
    "rccm": "RCCM",
    "niu": "identifiant fiscal",
    "compte": "compte de versement",
    "piece": "pièce d'identité",
}


def detecter_identites_partagees(ctx: Contexte) -> list[Constat]:
    """Même téléphone, RCCM, identifiant fiscal, pièce d'identité ou compte de versement entre
    deux boutiques distinctes.

    **Pourquoi c'est un indice.** C'est le schéma le plus rentable d'une fraude de place de marché :
    une personne, plusieurs vitrines. On encaisse sur l'une, on la laisse suspendre, on rouvre sous
    un autre nom avec les mêmes coordonnées — parce qu'un numéro Mobile Money et une pièce
    d'identité, eux, ne se changent pas facilement. Le lien avec une boutique **suspendue ou
    résiliée** est le cas grave.

    **Pourquoi ce n'est pas une preuve.** Un commerçant honnête peut tenir deux boutiques ; une
    galerie marchande peut donner le même standard à ses locataires ; un comptable peut déposer
    plusieurs dossiers avec son propre téléphone. Deux boutiques établies qui se partagent un
    numéro sont le plus souvent un seul propriétaire, et c'est son droit.
    """
    from apps.accounts.models import DossierKyc
    from apps.marketplace.cemac import PAYS
    from apps.marketplace.models import Boutique, CompteVersement

    liens = defaultdict(set)  # (champ, valeur) → {boutique_id}
    affichage = {}
    for b in ctx.boutiques.values():
        for champ, valeur, montre in (
            ("telephone", normaliser_telephone(b.telephone, b.pays), b.telephone),
            ("rccm", normaliser_identifiant(b.rccm), b.rccm),
            ("niu", normaliser_identifiant(b.niu), b.niu),
        ):
            if valeur:
                liens[(champ, valeur)].add(b.pk)
                affichage[(champ, valeur)] = montre
    for boutique_id, numero in CompteVersement.objects.values_list("boutique_id", "numero"):
        valeur = normaliser_identifiant(numero)
        if valeur and boutique_id in ctx.boutiques:
            liens[("compte", valeur)].add(boutique_id)
            affichage[("compte", valeur)] = masquer(numero)
    # La pièce d'identité : comparée par son empreinte quand le dossier ne garde que celle-ci
    # (minimisation, `apps/accounts/models.py`), par son numéro sinon.
    types_pieces = {code for p in PAYS.values() for code in p.pieces}
    champs_kyc = {f.name for f in DossierKyc._meta.get_fields()}
    par_empreinte = "numero_empreinte" in champs_kyc
    colonnes = ("numero_empreinte", "numero_fin") if par_empreinte else ("numero", "numero")
    for boutique_id, cle, fin in DossierKyc.objects.filter(
        boutique__isnull=False, type_piece__in=types_pieces
    ).values_list("boutique_id", *colonnes):
        valeur = (cle or "").strip() if par_empreinte else normaliser_identifiant(cle)
        if valeur and boutique_id in ctx.boutiques:
            liens[("piece", valeur)].add(boutique_id)
            affichage[("piece", valeur)] = ("•••• " + (fin or "")) if par_empreinte else masquer(fin)

    par_boutique = defaultdict(lambda: defaultdict(list))  # sujet → autre → [champs]
    for (champ, valeur), ids in liens.items():
        if len(ids) < 2:
            continue
        for sujet in ids:
            for autre in ids - {sujet}:
                par_boutique[sujet][autre].append((champ, affichage[(champ, valeur)]))

    constats = []
    fermees = {Boutique.SUSPENDUE, Boutique.RESILIEE}
    for sujet, autres in par_boutique.items():
        b = ctx.boutiques[sujet]
        # On ne signale que là où une décision reste à prendre : une candidature à valider ou une
        # boutique qui vend. Une boutique déjà fermée est la *preuve* d'un autre signal.
        if b.etat not in (Boutique.CANDIDATURE, Boutique.ACTIVE):
            continue
        liste, faits, phrases = [], [], []
        grave = False
        for autre_id, champs in sorted(autres.items(), key=lambda x: ctx.boutiques[x[0]].enseigne):
            autre = ctx.presenter(autre_id)
            noms = sorted({LIBELLES_CHAMPS[c] for c, _ in champs})
            autre["champs"] = [{"champ": LIBELLES_CHAMPS[c], "valeur": v} for c, v in sorted(champs)]
            liste.append(autre)
            faits.extend(f"{autre_id}:{c}" for c, _ in champs)
            grave = grave or autre["etat"] in fermees
            etat = f", {autre['etat_libelle'].lower()}" if autre["etat"] != Boutique.ACTIVE else ""
            phrases.append(
                f"même {' et '.join(noms)} que « {autre['enseigne']} », ouverte le {autre['ouverte_le']}{etat}"
            )
        age = ctx.age_jours(sujet)
        nouvelle = b.etat == Boutique.CANDIDATURE or (age is not None and age < RECENTE_JOURS)
        if grave:
            gravite = 3
        elif nouvelle:
            gravite = 2
        else:
            gravite = 1
        constats.append(
            Constat(
                boutique_id=sujet,
                type="identites_partagees",
                gravite=gravite,
                score=40 + 15 * len(set(faits)) + (30 if grave else 0),
                resume=phrases[0][0].upper() + phrases[0][1:] + (f" (et {len(phrases) - 1} autre(s))" if len(phrases) > 1 else ""),
                preuves={
                    "phrases": phrases,
                    "boutiques": liste,
                    "lien_ferme": grave,
                    "nouvelle": nouvelle,
                },
                faits=faits,
            )
        )
    return constats


# ----------------------------------------------------------------------------
# 2. Prix d'appât
# ----------------------------------------------------------------------------
def _cles_article(libelle, attributs, reference, code_barres, designations) -> set[str]:
    cles = set()
    base = normaliser_libelle(libelle)
    if base:
        details = " ".join(normaliser_libelle(str(v)) for _, v in sorted((attributs or {}).items()))
        cles.add(f"l:{base} {details}".strip())
    if reference and normaliser_identifiant(reference):
        cles.add(f"r:{normaliser_identifiant(reference)}")
    if code_barres and len(code_barres.strip()) >= 8:
        cles.add(f"c:{code_barres.strip()}")
    for d in designations:
        if normaliser_libelle(d):
            cles.add(f"d:{normaliser_libelle(d)}")
    return cles


def detecter_prix_appat(ctx: Contexte) -> list[Constat]:
    """Une boutique récente dont une part importante des articles est bien en dessous du prix
    médian des mêmes articles ailleurs sur le marché.

    **Pourquoi c'est un indice.** C'est l'hameçon d'une boutique éphémère : un téléphone à moitié
    prix attire des centaines de prépaiements en quelques jours, et la boutique n'a jamais eu
    l'intention de livrer. Le prix n'est pas une erreur, c'est la stratégie.

    **Pourquoi ce n'est pas une preuve.** Un grossiste qui entre sur le marché casse les prix pour
    se faire connaître ; un déstockage est légitime ; et deux articles de « même désignation »
    peuvent être un original et une copie. D'où trois garde-fous : seulement les boutiques
    récentes (une boutique établie a déjà prouvé qu'elle livre), une médiane sur au moins trois
    prix de deux autres boutiques, et une *part* des articles, pas un seul.

    « Même désignation » : même libellé et mêmes attributs une fois normalisés, ou même
    désignation déclarée (DCI, référence d'un autre fabricant — ADR-011), même référence
    constructeur, même code-barres.
    """
    from apps.catalog.models import Designation, Variante
    from apps.marketplace.models import Boutique

    actives = [b for b in ctx.boutiques.values() if b.etat == Boutique.ACTIVE]
    sujets = {
        b.pk for b in actives if (ctx.age_jours(b.pk) is not None and ctx.age_jours(b.pk) < RECENTE_JOURS)
    }
    if not sujets:
        return []
    ids_actives = [b.pk for b in actives]
    lignes = list(
        Variante.objects.filter(
            boutique_id__in=ids_actives, actif=True, produit__actif=True, prix_vente__gt=0
        ).values_list(
            "id", "boutique_id", "produit__libelle", "attributs", "reference_constructeur",
            "code_barres", "prix_vente",
        )
    )
    designations = defaultdict(list)
    for variante_id, valeur in Designation.objects.filter(
        variante__boutique_id__in=ids_actives
    ).values_list("variante_id", "valeur"):
        designations[variante_id].append(valeur)

    par_cle = defaultdict(list)  # clé → [(variante_id, boutique_id, prix)]
    articles = []
    for vid, bid, libelle, attributs, reference, code, prix in lignes:
        cles = _cles_article(libelle, attributs, reference, code, designations.get(vid, []))
        articles.append((vid, bid, libelle, prix, cles))
        for cle in cles:
            par_cle[cle].append((vid, bid, prix))

    comparables, appats = defaultdict(int), defaultdict(list)
    for vid, bid, libelle, prix, cles in articles:
        if bid not in sujets:
            continue
        references = {}
        for cle in cles:
            for autre_vid, autre_bid, autre_prix in par_cle[cle]:
                if autre_bid != bid:
                    references[autre_vid] = (autre_bid, autre_prix)
        if len(references) < APPAT_REFERENCES_MIN or len({b for b, _ in references.values()}) < 2:
            continue
        comparables[bid] += 1
        mediane = statistics.median(p for _, p in references.values())
        if prix < mediane * APPAT_RATIO:
            appats[bid].append(
                {
                    "article": libelle,
                    "prix": str(prix),
                    "mediane": str(mediane),
                    "ecart": _pc(1 - prix / mediane),
                    "references": len(references),
                    "variante": str(vid),
                }
            )

    constats = []
    for bid in sujets:
        n, liste = comparables[bid], appats[bid]
        if n < APPAT_COMPARABLES_MIN or len(liste) < 2:
            continue
        part = _taux(len(liste), n)
        if part < APPAT_PART_MIN:
            continue
        liste.sort(key=lambda a: Decimal(a["prix"]) / Decimal(a["mediane"]))
        premier = liste[0]
        constats.append(
            Constat(
                boutique_id=bid,
                type="prix_appat",
                gravite=2 if part >= Decimal("0.5") else 1,
                score=int(part * 100),
                resume=(
                    _('%(len)s article(s) sur %(n)s comparables à moins de la moitié du prix du marché, boutique ouverte depuis %(age_jours)s jour(s) — ex. « %(element)s » à %(fcfa)s contre %(fcfa2)s') % {"len": len(liste), "n": n, "age_jours": ctx.age_jours(bid), "element": premier['article'], "fcfa": _fcfa(premier['prix']), "fcfa2": _fcfa(premier['mediane'])}
                ),
                preuves={
                    "anciennete_jours": ctx.age_jours(bid),
                    "comparables": n,
                    "appats": liste[:12],
                    "part": _pc(part),
                },
                faits=[a["variante"] for a in liste],
            )
        )
    return constats


# ----------------------------------------------------------------------------
# 3. Pic de prépaiement
# ----------------------------------------------------------------------------
def condition_prepayee():
    """Une sous-commande dont l'acheteur a **déjà payé**. Le paiement à la livraison n'expose rien —
    il ne compte pas.

    Deux lectures, selon ce que le schéma des paiements porte : le mode de paiement de la part
    (`SousCommande.mode_paiement`) quand il existe ; sinon un séquestre ouvert sur la commande, ou
    un encaissement Mobile Money / carte réussi.
    """
    from apps.orders.models import SousCommande
    from apps.payments.models import Prestataire, Sequestre, Transaction

    if any(f.name == "mode_paiement" for f in SousCommande._meta.get_fields()):
        return Q(mode_paiement=getattr(SousCommande, "PREPAYE", "prepaye"))
    return Q(Exists(Sequestre.objects.filter(commande_id=OuterRef("commande_id")))) | Q(
        Exists(
            Transaction.objects.filter(
                commande_id=OuterRef("commande_id"),
                sens=Transaction.ENCAISSEMENT,
                etat=Transaction.REUSSIE,
            ).exclude(prestataire_id=Prestataire.PAIEMENT_LIVRAISON)
        )
    )


def detecter_pic_prepaiement(ctx: Contexte) -> list[Constat]:
    """Des commandes prépayées sans commune mesure avec l'historique de la boutique, sur 7 jours.

    Deux lectures, parce qu'il y a deux escroqueries :

    * **la boutique jeune** (moins de 90 jours) : le *nombre* de commandes prépayées de la semaine
      comparé à sa moyenne hebdomadaire depuis son activation. C'est la fausse boutique qui
      encaisse le plus vite possible avant de disparaître ;
    * **la boutique établie** : le *montant* prépayé de la semaine comparé à la **médiane** de ses
      semaines précédentes (douze au plus). C'est l'escroquerie longue : on gagne patiemment le
      palier sans plafond, puis on encaisse beaucoup, d'un coup, et on part (docs/23, §2.2). La
      médiane et non la moyenne, pour qu'une seule bonne semaine passée ne masque pas la suivante.

    **Pourquoi c'est un indice.** C'est le moment de la sortie : une fraude ne gagne rien à vendre
    lentement. Le plafond de séquestre limite la perte des jeunes boutiques ; ce signal fait
    regarder *avant* qu'il soit atteint — et c'est la seule protection d'une boutique sans plafond.

    **Pourquoi ce n'est pas une preuve.** Un lancement réussi, une campagne d'un apporteur, la
    rentrée scolaire pour une librairie, les fêtes pour un traiteur produisent la même courbe. D'où
    un seuil absolu (dix commandes ne sont pas un pic), et une gravité qui monte surtout quand la
    boutique n'a encore **jamais** fait confirmer une livraison, ou quand rien ne plafonne son
    encours.
    """
    from apps.marketplace.confiance import palier
    from apps.marketplace.models import Boutique
    from apps.orders.models import SousCommande

    sujets = {b.pk: b for b in ctx.boutiques.values() if b.etat == Boutique.ACTIVE}
    if not sujets:
        return []
    try:
        condition = condition_prepayee()
    except (ImportError, AttributeError):  # pragma: no cover — le schéma des paiements a bougé
        journal.warning("Pic de prépaiement : condition de prépaiement indisponible, détecteur ignoré.")
        return []

    fin_historique = ctx.maintenant - timedelta(days=PIC_FENETRE_JOURS)
    debut_historique = fin_historique - timedelta(days=PIC_HISTORIQUE_JOURS_ETABLIE)
    lignes = SousCommande.objects.filter(
        boutique_id__in=list(sujets), cree_le__gte=debut_historique, cree_le__lte=ctx.maintenant
    ).filter(condition).values_list("boutique_id", "cree_le", "total_ttc")
    recent = defaultdict(list)
    semaines = defaultdict(lambda: defaultdict(lambda: [0, Decimal("0")]))  # b → rang → [n, montant]
    for bid, cree_le, ttc in lignes:
        if cree_le >= fin_historique:
            recent[bid].append(ttc or Decimal("0"))
        else:
            rang = int((fin_historique - cree_le).total_seconds() // (7 * 86400))
            semaines[bid][rang][0] += 1
            semaines[bid][rang][1] += ttc or Decimal("0")
    confirmees = set(
        SousCommande.objects.filter(boutique_id__in=list(recent), livraison_confirmee_le__isnull=False)
        .values_list("boutique_id", flat=True)
        .distinct()
    )

    constats = []
    for bid, montants in recent.items():
        n = len(montants)
        if n < PIC_MINIMUM:
            continue
        total = sum(montants, Decimal("0"))
        age = ctx.age_jours(bid)
        plafond = palier(sujets[bid].palier_confiance).plafond_sequestre
        jamais_livre = bid not in confirmees
        au_plafond = plafond is not None and total >= plafond
        jeune = age is not None and age < JEUNE_JOURS

        if jeune:
            # L'historique commence à l'activation : une boutique de dix jours n'a pas huit
            # semaines de passé, et diviser par huit ferait paraître normal n'importe quel pic.
            debut = ctx.activations.get(bid)
            jours_hist = PIC_HISTORIQUE_JOURS
            if debut is not None:
                debut_local = timezone.make_aware(datetime.combine(debut, datetime.min.time()))
                jours_hist = max(min((fin_historique - debut_local).days, PIC_HISTORIQUE_JOURS), 0)
            nb_semaines = max(Decimal(jours_hist) / 7, Decimal(1))
            passees = sum(v[0] for r, v in semaines[bid].items() if r < PIC_HISTORIQUE_JOURS // 7)
            reference = Decimal(passees) / nb_semaines
            if Decimal(n) < PIC_FACTEUR * max(reference, Decimal(1)):
                continue
            ratio = Decimal(n) / max(reference, Decimal(1))
            comparaison = f"{n} commandes prépayées en 7 jours ({_fcfa(total)}) contre {reference:.1f} par semaine auparavant"
        else:
            # Semaines vides comprises : une boutique qui ne vendait rien trois semaines sur quatre
            # a une médiane basse, et c'est bien ce qu'on veut mesurer.
            nb = min(PIC_HISTORIQUE_JOURS_ETABLIE // 7, max((age or 0) // 7 - 1, 1))
            hebdo = [semaines[bid].get(r, [0, Decimal("0")])[1] for r in range(nb)]
            reference = statistics.median(hebdo) if hebdo else Decimal("0")
            if total < PIC_FACTEUR * max(reference, Decimal("1")):
                continue
            ratio = total / max(reference, Decimal("1"))
            comparaison = (
                f"{_fcfa(total)} prépayés en 7 jours ({n} commandes) contre une semaine médiane de "
                f"{_fcfa(reference)} sur les {nb} précédentes"
            )

        sans_plafond = plafond is None
        if (jamais_livre and au_plafond) or (sans_plafond and ratio >= 2 * PIC_FACTEUR):
            gravite = 3
        elif jamais_livre or au_plafond or sans_plafond:
            gravite = 2
        else:
            gravite = 1
        constats.append(
            Constat(
                boutique_id=bid,
                type="pic_prepaiement",
                gravite=gravite,
                score=min(100, 40 + int(ratio * 5)),
                resume=comparaison
                + (" — aucune livraison encore confirmée" if jamais_livre else "")
                + (" — palier sans plafond de séquestre" if sans_plafond else ""),
                preuves={
                    "lecture": "jeune" if jeune else "etablie",
                    "recentes": n,
                    "montant": str(total),
                    "reference": f"{reference:.1f}" if jeune else str(reference),
                    "ratio": f"{ratio:.1f}",
                    "anciennete_jours": age,
                    "jamais_livre": jamais_livre,
                    "plafond_sequestre": str(plafond) if plafond is not None else None,
                    "au_plafond": au_plafond,
                    "sans_plafond": sans_plafond,
                    "phrase": comparaison,
                },
                # La semaine ISO du pic : un nouveau pic, une autre semaine, est un fait nouveau.
                faits=[f"semaine:{timezone.localdate(ctx.maintenant).isocalendar()[:2]}"],
            )
        )
    return constats


# ----------------------------------------------------------------------------
# 4. Litiges et annulations anormaux
# ----------------------------------------------------------------------------
def detecter_litiges_annulations(ctx: Contexte) -> list[Constat]:
    """Sur trente jours, une part de litiges ou d'annulations nettement au-dessus du marché.

    **Pourquoi c'est un indice.** Une boutique qui ne livre pas se trahit par ses acheteurs avant
    de se trahir par ses chiffres : « commande non reçue », annulations en série, remboursements.
    Le palier ne compte que les litiges **tranchés** ; ce signal-ci regarde ceux qui s'ouvrent,
    pour voir venir.

    **Pourquoi ce n'est pas une preuve.** Un acheteur de mauvaise foi ouvre un litige pour ne pas
    payer ; une panne de livreur ou une route coupée en saison des pluies fait monter les
    annulations de tout un quartier. D'où un volume minimal et une comparaison au **reste du
    marché** : si tout le monde souffre en même temps, ce n'est pas cette boutique-là.
    """
    from django.db.models import Count

    from apps.marketplace.models import Boutique
    from apps.orders.models import Litige, SousCommande

    depuis = ctx.maintenant - timedelta(days=LITIGES_FENETRE_JOURS)
    actives = [b.pk for b in ctx.boutiques.values() if b.etat == Boutique.ACTIVE]
    if not actives:
        return []
    volumes = {
        l["boutique_id"]: l
        for l in SousCommande.objects.filter(boutique_id__in=actives, cree_le__gte=depuis)
        .order_by()
        .values("boutique_id")
        .annotate(n=Count("id"), annulees=Count("id", filter=Q(etat=SousCommande.ANNULEE)))
    }
    litiges = {
        l["boutique_id"]: l
        for l in Litige.objects.filter(boutique_id__in=actives, cree_le__gte=depuis)
        .order_by()
        .values("boutique_id")
        .annotate(n=Count("id"), non_recues=Count("id", filter=Q(motif=Litige.NON_RECUE)))
    }
    total_n = sum(v["n"] for v in volumes.values())
    total_a = sum(v["annulees"] for v in volumes.values())
    total_l = sum(v["n"] for v in litiges.values())

    constats = []
    for bid, v in volumes.items():
        n = v["n"]
        if n < LITIGES_VOLUME_MIN:
            continue
        a, l = v["annulees"], litiges.get(bid, {}).get("n", 0)
        non_recues = litiges.get(bid, {}).get("non_recues", 0)
        # Le marché *sans* la boutique observée : sinon, une grosse boutique tire la moyenne vers
        # elle et ne paraît jamais anormale.
        reste_n = total_n - n
        marche_l = _taux(total_l - l, reste_n)
        marche_a = _taux(total_a - a, reste_n)
        taux_l, taux_a = _taux(l, n), _taux(a, n)
        anormal_l = taux_l >= LITIGES_TAUX_MIN and taux_l >= FACTEUR_MARCHE * marche_l
        anormal_a = taux_a >= ANNULATIONS_TAUX_MIN and taux_a >= FACTEUR_MARCHE * marche_a
        if not (anormal_l or anormal_a):
            continue
        faits, phrases = [], []
        if anormal_l:
            phrases.append(f"{l} litige(s) sur {n} commandes ({_pc(taux_l)}, marché {_pc(marche_l)})")
            faits.append("litiges")
        if anormal_a:
            phrases.append(f"{a} annulation(s) sur {n} commandes ({_pc(taux_a)}, marché {_pc(marche_a)})")
            faits.append("annulations")
        grave = (anormal_l and anormal_a) or taux_l >= Decimal("0.25") or (l and non_recues * 2 >= l and l >= 3)
        constats.append(
            Constat(
                boutique_id=bid,
                type="litiges_annulations",
                gravite=2 if grave else 1,
                score=min(100, int((taux_l + taux_a) * 100) + 20),
                resume="Sur 30 jours : " + " ; ".join(phrases),
                preuves={
                    "fenetre_jours": LITIGES_FENETRE_JOURS,
                    "commandes": n,
                    "litiges": l,
                    "litiges_non_recues": non_recues,
                    "annulations": a,
                    "taux_litiges": _pc(taux_l),
                    "taux_annulations": _pc(taux_a),
                    "marche_litiges": _pc(marche_l),
                    "marche_annulations": _pc(marche_a),
                    "phrases": phrases,
                },
                faits=faits,
            )
        )
    return constats


# ----------------------------------------------------------------------------
# 5. Changement de compte de versement, puis demande de versement
# ----------------------------------------------------------------------------
def _demandes_de_versement(boutique_ids, depuis):
    """Les demandes de versement depuis `depuis` : `[{boutique_id, le, montant}]`, ou `None` si le
    modèle `Versement` n'existe pas (encore) ou n'a pas la forme attendue.

    Importé paresseusement : le modèle est écrit par le chantier des paiements, et ce détecteur
    doit se taire proprement tant qu'il n'existe pas — pas faire tomber la tâche de nuit.
    """
    try:
        from apps.payments.models import Versement
    except ImportError:
        return None
    champs = {f.name for f in Versement._meta.get_fields()}
    if "boutique" not in champs:
        return None
    date = next((c for c in ("demande_le", "cree_le") if c in champs), None)
    if date is None:
        return None
    valeurs = {"boutique_id": "boutique_id", "le": date}
    if "montant" in champs:
        valeurs["montant"] = "montant"
    if "demande_par" in champs:
        valeurs["demande_par"] = "demande_par__nom_complet"
    lignes = (
        Versement._default_manager.filter(
            boutique_id__in=list(boutique_ids), **{f"{date}__gte": depuis}
        )
        .order_by(date)
        .values_list(*valeurs.values())
    )
    return [dict(zip(valeurs.keys(), ligne)) for ligne in lignes]


def detecter_changement_compte(ctx: Contexte) -> list[Constat]:
    """Un compte de versement changé, puis une demande de versement dans les sept jours.

    **Pourquoi c'est un indice — le plus fiable de tous.** Détourner l'argent d'un marchand ne
    demande ni de pirater la plateforme ni de voler une boutique : il suffit de remplacer son
    numéro de versement la veille d'un gros virement. C'est aussi la fraude **interne** type : un
    employé du marchand, ou un administrateur, qui déclare son propre numéro. D'où la gravité
    critique d'emblée, et la preuve qui nomme qui a déclaré et qui a vérifié le compte.

    **Pourquoi ce n'est pas une preuve.** Un marchand change d'opérateur, perd sa puce, passe du
    Mobile Money à la banque — et demande son argent, ce qui est bien normal. Le délai de carence
    de `CompteVersement` protège déjà ; ce signal fait regarder le cas avant qu'il se referme.

    Se tait sans erreur si le modèle `Versement` n'existe pas.
    """
    from apps.marketplace.models import CompteVersement

    horizon = ctx.maintenant - timedelta(days=30 + COMPTE_DELAI_JOURS)
    comptes = list(
        CompteVersement.objects.filter(boutique_id__in=list(ctx.boutiques))
        .select_related("declare_par", "verifie_par")
        .order_by("boutique_id", "cree_le")
    )
    changements = []
    precedent = {}
    for c in comptes:
        avant = precedent.get(c.boutique_id)
        precedent[c.boutique_id] = c
        if avant is not None and c.cree_le >= horizon and c.numero != avant.numero:
            changements.append((avant, c))
    if not changements:
        return []
    demandes = _demandes_de_versement({c.boutique_id for _, c in changements}, horizon)
    if demandes is None:
        return []

    constats = []
    for avant, nouveau in changements:
        fin = nouveau.cree_le + timedelta(days=COMPTE_DELAI_JOURS)
        suivies = [
            d for d in demandes
            if d["boutique_id"] == nouveau.boutique_id and nouveau.cree_le <= d["le"] <= fin
        ]
        if not suivies:
            continue
        declare = nouveau.declare_par
        interne = bool(declare and (declare.is_staff or declare.is_superuser))
        delai = suivies[0]["le"] - nouveau.cree_le
        heures = int(delai.total_seconds() // 3600)
        titulaire_change = (avant.titulaire or "").strip().lower() != (nouveau.titulaire or "").strip().lower()
        constats.append(
            Constat(
                boutique_id=nouveau.boutique_id,
                type="changement_compte",
                gravite=3,
                score=95 if interne or titulaire_change else 85,
                resume=(
                    f"Compte de versement changé le {date_lisible(nouveau.cree_le)} "
                    f"({masquer(avant.numero)} → {masquer(nouveau.numero)}), versement demandé "
                    + (f"{heures} h après" if heures < 48 else f"{delai.days} jours après")
                    + (" — titulaire différent" if titulaire_change else "")
                ),
                preuves={
                    "ancien": {
                        "numero": masquer(avant.numero),
                        "operateur": avant.get_operateur_display(),
                        "titulaire": avant.titulaire,
                        "depuis": date_lisible(avant.cree_le),
                    },
                    "nouveau": {
                        "numero": masquer(nouveau.numero),
                        "operateur": nouveau.get_operateur_display(),
                        "titulaire": nouveau.titulaire,
                        "declare_le": date_lisible(nouveau.cree_le),
                        "declare_par": getattr(declare, "nom_complet", "") or "inconnu",
                        "declare_par_administration": interne,
                        "verifie_par": getattr(nouveau.verifie_par, "nom_complet", "") or "",
                        "etat": nouveau.get_etat_display(),
                    },
                    "titulaire_change": titulaire_change,
                    "versements": [
                        {
                            "le": date_lisible(d["le"]),
                            "montant": str(d["montant"]) if d.get("montant") is not None else None,
                            "demande_par": d.get("demande_par") or "",
                        }
                        for d in suivies
                    ],
                },
                faits=[str(nouveau.pk)],
            )
        )
    return constats


# ----------------------------------------------------------------------------
# 6. Boutique active non vérifiée
# ----------------------------------------------------------------------------
def _fonction_manques():
    """`apps.confiance.verification.manques_pour_activer`, si elle existe. Importée paresseusement :
    le module est écrit par le chantier de la vérification d'identité."""
    try:
        from apps.confiance import verification
    except ImportError:
        return None
    return getattr(verification, "manques_pour_activer", None)


def _en_liste(manques) -> list[str]:
    if not manques:
        return []
    if isinstance(manques, dict):
        return [f"{k} : {v}" if v not in (True, None, "") else str(k) for k, v in manques.items()]
    if isinstance(manques, (list, tuple, set, frozenset)):
        return [str(m) for m in manques]
    return [str(manques)]


def detecter_non_verifiees(ctx: Contexte) -> list[Constat]:
    """Une boutique active à qui il manque ce qu'on exige pour l'activer.

    **Pourquoi c'est un indice.** Une boutique n'a pu devenir active sans vérification que par une
    exception : un geste d'administrateur pressé, une règle ajoutée après son activation, ou un
    contournement. Les deux premiers sont bénins, le troisième ne l'est pas — et les trois
    méritent qu'on complète le dossier.

    **Pourquoi ce n'est pas une preuve.** Une pièce expirée, un compte de versement en carence,
    une règle nouvelle : la plupart de ces boutiques sont honnêtes et simplement en retard.

    Se tait sans erreur si le module de vérification n'existe pas.
    """
    from apps.marketplace.models import Boutique

    fonction = _fonction_manques()
    if fonction is None:
        return []
    constats = []
    for b in ctx.boutiques.values():
        if b.etat != Boutique.ACTIVE:
            continue
        try:
            manques = _en_liste(fonction(b))
        except Exception:  # noqa: BLE001 — le code d'un autre chantier ne doit pas faire tomber la nuit
            journal.exception("Vérification indisponible pour %s", b.pk)
            continue
        if not manques:
            continue
        constats.append(
            Constat(
                boutique_id=b.pk,
                type="non_verifiee",
                gravite=2,
                score=50 + 10 * min(len(manques), 5),
                resume="Active sans vérification complète. " + " ".join(manques[:2]),
                preuves={"manques": manques},
                faits=manques,
            )
        )
    return constats


DETECTEURS = (
    detecter_identites_partagees,
    detecter_prix_appat,
    detecter_pic_prepaiement,
    detecter_litiges_annulations,
    detecter_changement_compte,
    detecter_non_verifiees,
)


# ----------------------------------------------------------------------------
# L'évaluation
# ----------------------------------------------------------------------------
def evaluer_signaux(*, maintenant: datetime | None = None, detecteurs=DETECTEURS) -> dict:
    """Passe tous les détecteurs et enregistre leurs constats. Idempotente.

    Ne suspend **rien** : c'est la décision d'un humain, dans la console.
    """
    from apps.confiance.paliers import premieres_activations
    from apps.marketplace.models import Boutique

    maintenant = maintenant or timezone.now()
    bilan = {"crees": 0, "mis_a_jour": 0, "deja_juges": 0, "par_type": defaultdict(int)}
    with contexte_plateforme():
        boutiques = {b.pk: b for b in Boutique.objects.all()}
        ctx = Contexte(
            maintenant=maintenant,
            boutiques=boutiques,
            activations=premieres_activations(boutiques.values()),
        )
        for detecteur in detecteurs:
            for constat in detecteur(ctx):
                _constat, issue = enregistrer(constat, maintenant=maintenant)
                if issue == "cree":
                    bilan["crees"] += 1
                elif issue == "maj":
                    bilan["mis_a_jour"] += 1
                else:
                    bilan["deja_juges"] += 1
                bilan["par_type"][constat.type] += 1
    bilan["par_type"] = dict(bilan["par_type"])
    return bilan


# ----------------------------------------------------------------------------
# La décision humaine
# ----------------------------------------------------------------------------
ECARTER, CONFIRMER = "ecarter", "confirmer"


def trancher(signal, *, decision: str, motif: str, par):
    """Écarte ou confirme un signal, avec un motif, et l'inscrit au journal des accès.

    Confirmer ne suspend pas la boutique : c'est un second geste, délibéré, dans l'assistant de
    changement d'état — qui demande lui aussi son motif. Lier les deux ferait d'un clic sur un
    signal une sanction.
    """
    from apps.confiance.models import SignalRisque
    from apps.core.models import AccesPlateforme

    if par is None or not getattr(par, "is_authenticated", False):
        raise ValidationError(_("Une décision exige un utilisateur identifié."))
    if decision not in (ECARTER, CONFIRMER):
        raise ValidationError({"decision": _("Choisissez : écarter ou confirmer.")})
    motif = (motif or "").strip()
    if len(motif) < 10:
        raise ValidationError(
            {"motif": _("Dites pourquoi, en une phrase : ce motif sera relu, peut-être par le commerçant.")}
        )
    with transaction.atomic():
        signal = SignalRisque.objects.select_for_update().select_related("boutique").get(pk=signal.pk)
        if signal.etat != SignalRisque.OUVERT:
            raise ValidationError(
                _('Ce signal a déjà été %(lower)s le %(date_lisible)s : une décision ne se rejoue pas.') % {"lower": signal.get_etat_display().lower(), "date_lisible": date_lisible(signal.traite_le)}
            )
        signal.etat = SignalRisque.ECARTE if decision == ECARTER else SignalRisque.CONFIRME
        signal.traite_par = par
        signal.traite_le = timezone.now()
        signal.decision = motif
        signal.save()
        verbe = "écarté" if decision == ECARTER else "confirmé"
        AccesPlateforme.objects.create(
            utilisateur=par,
            boutique_id=signal.boutique_id,
            ecran="plateforme:signal",
            motif=f"Signal « {signal.get_type_display()} » {verbe} : {motif}"[:300],
        )
    return signal
