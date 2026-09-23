"""Aide en ligne : une fiche par écran, filtrée comme l'écran lui-même.

Le manuel (docs/21) raconte une **journée** : il se lit une fois, posément, et
se range. Ceci répond à une autre question, posée debout, au milieu d'un geste :
« qu'est-ce que je fais sur cet écran-là ? ». Les deux ne peuvent pas être le
même texte — cinq paragraphes de prose n'aident personne avec un client qui
attend, et trois puces ne remplacent pas un manuel.

Le contenu vit **en code**, pour la même raison que le référentiel des métiers :
il est filtré par les droits et par le métier, et une aide dont la base décide
serait une aide qu'un caissier pourrait se voir ouvrir par accident.

Trois règles, et la troisième est la seule qui compte vraiment
--------------------------------------------------------------

**Une fiche par clé d'écran.** La clé est celle passée à `contexte_commun` —
`stock`, `caisse`, `comptabilite`. C'est ce qui permet au bouton « ? » de
l'en-tête d'ouvrir l'aide **de l'écran qu'on regarde**, sans que chaque gabarit
ait à déclarer quoi que ce soit.

**Ce qui n'est pas ouvert n'est pas composé.** Une fiche déclare le droit
qu'elle suppose, et parfois la fonction de métier. Un caissier ne lit pas
l'aide de la comptabilité ; une quincaillerie ne lit pas celle de
l'ordonnancier. C'est la règle de tout le back-office, appliquée au texte comme
au reste — expliquer un écran qu'on ne peut pas ouvrir est une promesse qui ne
sera pas tenue.

**Les pièges valent mieux que les modes d'emploi.** Un utilisateur devine où
cliquer ; il ne devine pas qu'une quantité ne se retape pas, ni que compter la
caisse après avoir lu le théorique ne sert à rien. Chaque fiche porte donc ses
`gestes` — brefs — et ses `pieges`, qui sont la vraie valeur.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.accounts import permissions as droit
from apps.marketplace import metiers

__all__ = ["FICHES", "FicheVue", "fiches_pour", "fiche_de"]


@dataclass(frozen=True)
class Fiche:
    """L'aide d'un écran.

    `cle` doit être celle que la vue passe à `contexte_commun` : c'est le lien
    entre le bouton « ? » et la bonne ancre. Un test le vérifie pour toutes les
    entrées de navigation, parce qu'une ancre fausse mène à une page d'aide qui
    s'ouvre en haut sans rien montrer, et que personne ne le signale.
    """

    cle: str
    titre: str
    resume: str
    #: `(quand, quoi)`, ou `(quand, quoi, droit)` quand le geste demande plus que
    #: l'ouverture de l'écran.
    gestes: tuple[tuple[str, ...], ...] = ()
    pieges: tuple[str, ...] = ()
    droit_requis: str = ""
    fonction_requise: str = ""

    def visible_pour(self, droits, metier) -> bool:
        if self.droit_requis and self.droit_requis not in droits:
            return False
        if self.fonction_requise:
            return metier is not None and metier.a(self.fonction_requise)
        return True

    def gestes_pour(self, droits) -> list[tuple[str, str]]:
        """Les gestes que cette personne peut réellement faire sur cet écran.

        Ouvrir un écran et pouvoir tout y faire sont deux choses. Une caissière
        consulte le stock — elle ne reçoit pas la marchandise et ne lance pas
        d'inventaire. Lui expliquer « Stock › Inventaire » l'enverrait chercher
        un bouton qui n'est pas composé pour elle, et le premier jet de ce
        module faisait exactement cela.

        Le filtre est donc à deux étages : la fiche pour l'écran, le geste pour
        l'action. Les `pieges`, eux, ne sont pas filtrés : savoir qu'une
        quantité ne se retape pas est utile même à qui ne la retapera jamais —
        c'est ce qui permet de comprendre ce qu'on lit à l'écran.
        """
        visibles = []
        for geste in self.gestes:
            quand, quoi = geste[0], geste[1]
            requis = geste[2] if len(geste) > 2 else ""
            if requis and requis not in droits:
                continue
            visibles.append((quand, quoi))
        return visibles


FICHES: tuple[Fiche, ...] = (
    Fiche(
        cle="tableau_de_bord",
        titre="Tableau de bord",
        resume="Ce que la boutique a fait aujourd'hui, et ce qu'il faut commander.",
        gestes=(
            ("Les tuiles", "Ventes et marge du jour, valeur du stock au coût moyen, articles à réapprovisionner."),
            ("Le graphique", "Quatorze jours de chiffre d'affaires, ventes clôturées seulement."),
            ("Santé du stock", "Ce qui est en rupture d'abord, ce qui passe sous le seuil ensuite."),
        ),
        pieges=(
            "Un article dont le seuil d'alerte est à zéro n'apparaîtra jamais ici : "
            "vous ne serez prévenu de rien.",
        ),
        droit_requis=droit.TABLEAU_DE_BORD,
    ),
    Fiche(
        cle="caisse",
        titre="Caisse",
        resume="Encaisser, y compris sans réseau.",
        gestes=(
            ("Ouvrir la session", "Saisissez les espèces présentes dans le tiroir avant la première vente."),
            ("Vendre", "Cherchez par nom, référence ou code-barres, puis choisissez le règlement : espèces, Mobile Money, carte, ou à crédit."),
            ("Fermer la session", "Comptez le tiroir, puis saisissez votre comptage."),
        ),
        pieges=(
            "Sans réseau, continuez à encaisser : les ventes attendent sur l'appareil "
            "et repartent seules, dans l'ordre. Ne fermez pas l'application tant que "
            "le bandeau annonce des ventes en attente.",
            "Le montant théorique est affiché à côté du champ de comptage. Comptez "
            "avant de le regarder — un chiffre qu'on a sous les yeux est un chiffre "
            "qu'on recopie, et un écart recopié n'existe pas.",
            "L'impression directe demande Android, Chrome et une imprimante Bluetooth. "
            "Sur iPhone, passez par l'impression du navigateur ou par WhatsApp.",
        ),
        droit_requis=droit.CAISSE_ENCAISSER,
    ),
    Fiche(
        cle="stock",
        titre="Stock",
        resume="Ce que vous avez, ce qu'il a coûté, et ce qui bouge.",
        gestes=(
            ("Chercher", "Par nom, référence, code-barres — et par les autres désignations de l'article là où votre métier en gère."),
            ("Recevoir", "Ouvrez l'article, puis Entrée de stock : quantité reçue et coût d'achat unitaire.", droit.STOCK_MOUVEMENTER),
            ("Compter", "Stock › Inventaire. Les écarts sont chiffrés et écrits, jamais effacés.", droit.STOCK_MOUVEMENTER),
            ("Corriger un article", "Sélectionnez la ligne, puis Modifier. Une seule ligne à la fois.", droit.STOCK_MOUVEMENTER),
        ),
        pieges=(
            "Le coût d'achat que vous saisissez recalcule le coût moyen pondéré, qui "
            "sert ensuite à valoriser tout le stock et à calculer chaque marge. Un "
            "coût de travers fausse la marge pendant des mois sans que rien ne le dise.",
            "La quantité ne se corrige pas en la retapant : elle est l'addition de "
            "mouvements. On la corrige par une entrée ou par un inventaire.",
            "Un article qui a déjà bougé en stock est « retiré de la vente », pas "
            "supprimé : effacer son libellé rendrait muets des tickets imprimés.",
            "Le stock peut devenir négatif. C'est une anomalie signalée, pas un bogue : "
            "elle dit que ce qui est sorti ne correspond pas à ce qui était entré.",
        ),
        droit_requis=droit.STOCK_VOIR,
    ),
    Fiche(
        cle="peremptions",
        titre="Péremptions",
        resume="Ce qui est déjà perdu, et ce qu'on peut encore écouler.",
        gestes=(
            ("Lire l'écran", "Les deux listes sont séparées : le périmé d'un côté, ce qui approche de l'autre."),
            ("Agir", "Écouler, remiser, ou retourner au grossiste — l'écran ne décide pas à votre place."),
        ),
        pieges=(
            "Les sorties consomment toujours le lot « le plus proche de périmer », "
            "jamais le plus récent. C'est automatique, il n'y a rien à choisir.",
        ),
        droit_requis=droit.STOCK_VOIR,
        fonction_requise=metiers.PEREMPTION,
    ),
    Fiche(
        cle="production",
        titre="Production",
        resume="Fabriquer consomme les ingrédients et calcule le coût de revient.",
        gestes=(
            ("Fiche technique", "Ce qu'il faut pour une fournée : les ingrédients et leurs quantités."),
            ("Produire", "Sort réellement les ingrédients du stock et fait entrer le produit fini.", droit.STOCK_MOUVEMENTER),
            ("Invendus", "À déclarer en fin de journée.", droit.STOCK_MOUVEMENTER),
        ),
        pieges=(
            "Le coût de revient est recalculé sur les prix du jour, jamais figé sur la "
            "fiche : un boulanger qui fixe son prix sur la farine du mois dernier vend "
            "à perte sans le voir.",
            "Un invendu sort en « perte », jamais en écart de comptage. C'est la seule "
            "manière de savoir en fin de mois ce que la fabrication a jeté.",
        ),
        droit_requis=droit.STOCK_VOIR,
        fonction_requise=metiers.RECETTE,
    ),
    Fiche(
        cle="ventes",
        titre="Ventes",
        resume="Le journal de ce qui a été encaissé.",
        gestes=(
            ("Filtrer", "Par période, par état, par caissier. Les filtres vivent dans l'adresse : le lien se partage."),
            ("Ouvrir un ticket", "Le détail, et la réimpression."),
        ),
        pieges=(
            "Ce journal est en ajout seul : il n'offre que des filtres. Une vente ne "
            "se modifie ni ne se supprime — c'est ce qui rend vos comptes opposables.",
        ),
        droit_requis=droit.VENTES_VOIR,
    ),
    Fiche(
        cle="ordonnancier",
        titre="Ordonnancier",
        resume="Les délivrances sur ordonnance qui restent à consigner.",
        gestes=(
            ("Consigner", "Ajoutez le prescripteur et le numéro d'ordonnance."),
        ),
        pieges=(
            "Une vente arrivée sans mention n'est pas refusée : la boîte est partie "
            "avec le client, et la refuser n'effacerait que la trace. C'est ici qu'on "
            "rattrape ce qui manque.",
            "Un médicament marqué « sur ordonnance » disparaît de la vente en ligne : "
            "le pharmacien doit voir l'ordonnance, et un panier ne la montre pas.",
        ),
        droit_requis=droit.VENTES_VOIR,
        fonction_requise=metiers.ORDONNANCE,
    ),
    Fiche(
        cle="garantie",
        titre="Garantie et atelier",
        resume="Retrouver un appareil par son numéro, et suivre ses réparations.",
        gestes=(
            ("Chercher", "Par numéro de série ou IMEI. L'écran dit d'où vient l'appareil et à qui il a été vendu."),
            ("Atelier", "Entrée et sortie, avec le motif et le résultat."),
        ),
        pieges=(
            "L'échéance de garantie est « figée le jour de la vente ». Ramener la "
            "garantie du catalogue de douze à six mois vaut pour les ventes futures, "
            "pas pour les engagements déjà pris.",
            "La couverture d'une réparation est figée au dépôt : un appareil déposé la "
            "veille de l'échéance est réparé sous garantie, même rendu trois semaines "
            "plus tard.",
            "Une livraison saisie sans les numéros n'est pas refusée — elle produit un "
            "écart, que l'écran chiffre et qui se rattrape depuis la fiche de l'article.",
        ),
        # `VENTES_VOIR` et non `STOCK_VOIR` : l'écran de garantie part d'un
        # exemplaire **vendu** — à qui, quand, sous quelle garantie. C'est une
        # lecture de l'historique des ventes, pas du stock, et le décorateur de
        # la vue le dit. Un test compare les deux, parce que s'en remettre à la
        # mémoire a déjà produit ici l'erreur inverse.
        droit_requis=droit.VENTES_VOIR,
        fonction_requise=metiers.SERIE,
    ),
    Fiche(
        cle="commandes",
        titre="Commandes en ligne",
        resume="Les commandes des clients de la vitrine, étape par étape.",
        gestes=(
            ("Avancer", "En attente → acceptée → préparée → expédiée → livrée."),
            ("Annuler", "Possible tant que la commande n'est pas expédiée."),
        ),
        pieges=(
            "Chaque étape a son effet, et c'est « à l'expédition » que le stock sort "
            "réellement. Avancer une commande n'est pas un changement d'étiquette.",
        ),
        droit_requis=droit.COMMANDES_TRAITER,
    ),
    Fiche(
        cle="comptabilite",
        titre="Comptabilité",
        resume="Les écritures SYSCOHADA, générées à chaque vente.",
        gestes=(
            ("Balance", "Les soldes par compte."),
            ("Écritures", "Les dernières lignes du journal. Le détail complet part à l'export."),
        ),
        pieges=(
            "Il n'y a rien à saisir : les écritures sont générées par les ventes.",
            "Une écriture ne se modifie pas — la base elle-même refuse. On écrit "
            "l'écriture qui la corrige, comme sur un livre de comptes papier.",
            "La plateforme « prépare » votre comptabilité ; elle ne la certifie pas. "
            "Un expert-comptable la révise et l'atteste.",
        ),
        droit_requis=droit.COMPTABILITE_VOIR,
    ),
    Fiche(
        cle="boutique",
        titre="Ma boutique",
        resume="Identité, dépôts, équipe, et export de vos données.",
        gestes=(
            ("Équipe", "Embaucher, changer un rôle, régénérer un mot de passe, retirer un accès.", droit.BOUTIQUE_ADMINISTRER),
            ("Dépôts", "Ajouter une réserve, si votre emplacement l'autorise.", droit.BOUTIQUE_ADMINISTRER),
            ("Identité", "Logo, couleur de marque, adresse publique et liens courts.", droit.BOUTIQUE_ADMINISTRER),
            ("Exporter", "Archive ZIP en CSV : catalogue, stock, mouvements, ventes, écritures.", droit.EXPORTER),
        ),
        pieges=(
            "Retirer un accès ne supprime pas la personne : ses ventes passées restent "
            "à son nom, sinon le journal des ventes deviendrait muet.",
            "Le dernier gérant ne peut pas être retiré — y compris dans une sélection "
            "multiple, où le logiciel vérifie ce qui resterait après tout le lot.",
            "L'export est intégral et gratuit, à tout moment, y compris si vous "
            "résiliez. C'est écrit dans le contrat de bail.",
        ),
        droit_requis=droit.BOUTIQUE_VOIR,
    ),
)


@dataclass(frozen=True)
class FicheVue:
    """Une fiche déjà filtrée, prête à afficher.

    Les gabarits Django ne savent pas appeler une méthode avec argument : sans
    cette étape, le filtrage des gestes se ferait dans la vue par un attribut
    posé après coup — sur un objet gelé, donc pas du tout. Le calcul est fait
    ici, à un seul endroit, et le gabarit se contente de boucler.
    """

    cle: str
    titre: str
    resume: str
    gestes: list[tuple[str, str]]
    pieges: tuple[str, ...]


def _vue(fiche: Fiche, droits) -> FicheVue:
    return FicheVue(
        cle=fiche.cle,
        titre=fiche.titre,
        resume=fiche.resume,
        gestes=fiche.gestes_pour(droits),
        pieges=fiche.pieges,
    )


def fiches_pour(droits, metier) -> list[FicheVue]:
    """Les fiches que cette personne peut réellement ouvrir, dans l'ordre du menu.

    Filtrées à deux étages : la fiche pour l'écran, le geste pour l'action.
    """
    return [_vue(f, droits) for f in FICHES if f.visible_pour(droits, metier)]


def fiche_de(cle: str, droits, metier) -> FicheVue | None:
    """La fiche d'un écran donné, ou rien si elle ne lui est pas ouverte."""
    for fiche in FICHES:
        if fiche.cle == cle and fiche.visible_pour(droits, metier):
            return _vue(fiche, droits)
    return None
