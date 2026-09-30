"""Un petit moteur d'assistant pas à pas, sans cadriciel et sans JavaScript obligatoire.

Les gestes de la console qui engagent plusieurs choses à la fois — ouvrir une boutique, c'est une
boutique, un bail, un gérant, un plan comptable et un dépôt — se font en étapes, pour une raison
simple : un formulaire de trente champs sur un écran de téléphone, on le remplit mal, et on ne
sait plus ce qu'on a signé. Découpé, chaque écran pose une question et la vérifie.

Les règles du moteur, et pourquoi
---------------------------------

* **Une étape = une adresse.** `…/assistants/boutique/offre/`. Le bouton « Précédent » du
  navigateur fait ce qu'on attend, et une étape se partage ou se rouvre.
* **Un POST valide redirige** (PRG). Recharger la page ne renvoie jamais un formulaire.
* **L'état vit en session**, sous une clé par assistant, sous forme de **saisies brutes** — les
  chaînes que l'utilisateur a tapées, pas des objets. Revenir en arrière réaffiche exactement ce
  qu'il avait écrit.
* **Tout est revalidé à la confirmation.** La session a pu vieillir pendant la pause de midi, un
  autre administrateur a pu prendre le même numéro, un rayon a pu fermer. Chaque étape est donc
  rejouée contre la base du moment ; la première qui ne tient plus est rouverte, avec son erreur.
* **Aucun secret en clair.** Un mot de passe initial n'entre jamais en session : le formulaire
  n'y dépose que son empreinte (`make_password`), et c'est elle que le service pose. Une session
  lisible — sur disque, dans un cache partagé — ne livre donc aucun mot de passe.
* **Rien n'est créé avant la confirmation**, et la confirmation s'exécute en une transaction
  (`services.py`). Abandonner ne laisse aucune trace, puisqu'il n'y a rien à défaire.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.plateforme.acces import LIBELLES_CONSOLE, contexte_console

# Au-delà, l'assistant repart de zéro : une saisie de la veille décrit un monde qui a pu changer,
# et la revalidation attraperait l'essentiel — mais un administrateur qui retrouve un récapitulatif
# à moitié oublié risque de confirmer ce qu'il ne relit plus.
DUREE_DE_VIE = timedelta(hours=12)
VERSION = 1


# ----------------------------------------------------------------------------
# Le formulaire d'une étape
# ----------------------------------------------------------------------------
class FormulaireEtape(forms.Form):
    """Formulaire d'une étape : il sait se ranger en session et se lier à ses aides.

    * `secrets` : les champs qui ne vont **jamais** en session (les mots de passe).
    * `extras_session()` : ce que le formulaire veut garder en plus de la saisie brute — une
      empreinte de mot de passe, par exemple. Rangé sous des clés en `_`, que le formulaire relit
      depuis `memoire` (la session), **jamais** depuis la requête : une empreinte postée par le
      navigateur serait un mot de passe choisi sans validation.
    """

    secrets: tuple[str, ...] = ()
    required_css_class = ""

    def __init__(self, *args, assistant=None, memoire=None, **kwargs):
        self.assistant = assistant
        self.memoire = memoire or {}
        super().__init__(*args, **kwargs)

    # --- La session -------------------------------------------------------------------------
    def saisie_brute(self) -> dict:
        return {
            nom: self.data.get(nom)
            for nom in self.fields
            if nom not in self.secrets and self.data.get(nom) not in (None, "")
        }

    def vers_session(self) -> dict:
        return {**self.saisie_brute(), **self.extras_session()}

    def extras_session(self) -> dict:
        return {}

    # --- L'affichage accessible -------------------------------------------------------------
    def preparer_affichage(self) -> None:
        """Lie chaque champ à son aide et à son erreur, et pose le focus sur la première erreur.

        Fait côté serveur : `autofocus` et `aria-describedby` fonctionnent sans JavaScript, et un
        lecteur d'écran lit l'erreur en arrivant sur le champ au lieu de la chercher.
        """
        self.premier_en_erreur = None
        for nom, champ in self.fields.items():
            lie = self[nom]
            ids = []
            if champ.help_text:
                ids.append(f"{lie.auto_id}_aide")
            if lie.errors:
                ids.append(f"{lie.auto_id}_erreur")
                champ.widget.attrs["aria-invalid"] = "true"
                if self.premier_en_erreur is None:
                    self.premier_en_erreur = nom
                    champ.widget.attrs["autofocus"] = True
            if ids:
                champ.widget.attrs["aria-describedby"] = " ".join(ids)


class Confirmation(FormulaireEtape):
    """Le récapitulatif sans question : on relit, on confirme."""


# ----------------------------------------------------------------------------
# L'assistant
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Etape:
    code: str
    titre: str
    aide: str
    formulaire: type[FormulaireEtape]
    recapitulatif: bool = False


class Assistant:
    """À dériver : `nom`, `cle_session`, `url_etape`, `page`, `titre`, `etapes`, `executer()`,
    `recapitulatif()`. Les gabarits sont `plateforme/assistants/<nom>_<étape>.html`."""

    nom: str
    cle_session: str
    url_etape: str
    page: str
    titre: str
    sur_titre: str = "Assistant"
    etapes: tuple[Etape, ...] = ()
    url_abandon: str = "plateforme:tableau_de_bord"
    libelle_confirmer: str = "Confirmer"

    def __init__(self, request):
        self.request = request
        self._cache_etat = None

    # --- L'état en session ------------------------------------------------------------------
    @property
    def etat(self) -> dict:
        if self._cache_etat is not None:
            return self._cache_etat
        etat = self.request.session.get(self.cle_session)
        if not self._etat_valide(etat):
            if etat:
                messages.info(
                    self.request,
                    "La saisie précédente était trop ancienne : l'assistant repart de zéro.",
                )
            etat = self._etat_neuf()
            self.request.session[self.cle_session] = etat
        self._cache_etat = etat
        return etat

    def _etat_neuf(self) -> dict:
        return {
            "v": VERSION,
            "debut": timezone.now().isoformat(),
            "saisies": {},
            "faites": [],
            "brouillons": {},
            "a_revoir": [],
        }

    def _etat_valide(self, etat) -> bool:
        """Une session illisible ou périmée ne se répare pas : elle se recommence."""
        if not isinstance(etat, dict) or etat.get("v") != VERSION:
            return False
        if not all(isinstance(etat.get(k), t) for k, t in
                   (("saisies", dict), ("faites", list), ("brouillons", dict), ("a_revoir", list))):
            return False
        try:
            debut = timezone.datetime.fromisoformat(etat["debut"])
        except (KeyError, TypeError, ValueError):
            return False
        return timezone.now() - debut <= DUREE_DE_VIE

    def _sauver(self) -> None:
        self.request.session[self.cle_session] = self.etat
        self.request.session.modified = True

    def abandonner(self) -> None:
        self.request.session.pop(self.cle_session, None)
        self._cache_etat = None

    def saisie(self, code: str) -> dict:
        valeur = self.etat["saisies"].get(code)
        return valeur if isinstance(valeur, dict) else {}

    def enregistrer(self, code: str, formulaire: FormulaireEtape) -> None:
        etat = self.etat
        etat["saisies"][code] = formulaire.vers_session()
        etat["brouillons"].pop(code, None)
        if code not in etat["faites"]:
            etat["faites"].append(code)
        if code in etat["a_revoir"]:
            etat["a_revoir"].remove(code)
        self._sauver()

    def garder_brouillon(self, code: str, formulaire: FormulaireEtape) -> None:
        """Une saisie invalide qu'on quitte par « Précédent » : gardée, mais l'étape redevient à
        faire — on ne marque pas faite une étape qui ne passe pas."""
        etat = self.etat
        etat["brouillons"][code] = formulaire.saisie_brute()
        if code in etat["faites"]:
            etat["faites"].remove(code)
        self._sauver()

    def preremplir(self, code: str, donnees: dict) -> bool:
        """Valide et enregistre une étape d'office (un lien « Vendre un emplacement » depuis la
        fiche d'une boutique arrive avec la boutique déjà choisie). `False` si elle ne passe pas."""
        etape = self.etape(code)
        formulaire = self.construire(etape, data=donnees)
        if not formulaire.is_valid():
            return False
        self.enregistrer(code, formulaire)
        return True

    # --- Navigation -------------------------------------------------------------------------
    def etape(self, code: str) -> Etape | None:
        return next((e for e in self.etapes if e.code == code), None)

    def index(self, code: str) -> int:
        return next(i for i, e in enumerate(self.etapes) if e.code == code)

    def faite(self, code: str) -> bool:
        return code in self.etat["faites"]

    def accessible(self, code: str) -> bool:
        """Une étape s'ouvre quand toutes celles d'avant sont faites. On ne saute pas l'offre
        pour arriver au récapitulatif par l'adresse."""
        return all(self.faite(e.code) for e in self.etapes[: self.index(code)])

    def premiere_a_faire(self) -> Etape:
        return next((e for e in self.etapes if not self.faite(e.code)), self.etapes[-1])

    def url(self, code: str) -> str:
        return reverse(self.url_etape, args=[code])

    # --- Formulaires ------------------------------------------------------------------------
    def construire(self, etape: Etape, *, data=None, initial=None) -> FormulaireEtape:
        return etape.formulaire(
            data=data, initial=initial, assistant=self, memoire=self.saisie(etape.code)
        )

    def valides(self) -> tuple[dict[str, FormulaireEtape], Etape | None]:
        """Rejoue toutes les étapes contre la base du moment.

        Renvoie les formulaires validés, et la première étape qui ne tient plus (ou `None`).
        """
        resultat = {}
        for etape in self.etapes:
            if etape.recapitulatif:
                continue
            if not self.faite(etape.code):
                return resultat, etape
            formulaire = self.construire(etape, data=self.saisie(etape.code))
            if not formulaire.is_valid():
                return resultat, etape
            resultat[etape.code] = formulaire
        return resultat, None

    def rouvrir(self, etape: Etape):
        """Renvoie à une étape qui ne tient plus, en disant pourquoi."""
        etat = self.etat
        if etape.code in etat["faites"]:
            etat["faites"].remove(etape.code)
        if etape.code in self.etat["saisies"] and etape.code not in etat["a_revoir"]:
            etat["a_revoir"].append(etape.code)
        self._sauver()
        messages.error(
            self.request,
            f"L'étape « {etape.titre} » n'est plus valable — la base a changé depuis la saisie, "
            "ou elle est incomplète. Corrigez-la : rien n'a encore été créé.",
        )
        return redirect(self.url(etape.code))

    # --- À dériver --------------------------------------------------------------------------
    def executer(self, formulaires: dict[str, FormulaireEtape], confirmation: FormulaireEtape):
        """Appelle le service et renvoie la réponse (une redirection vers ce qui a été créé)."""
        raise NotImplementedError

    def recapitulatif(self, formulaires: dict[str, FormulaireEtape]) -> list[dict]:
        """Sections du récapitulatif : `{"etape", "titre", "lignes": [(clé, valeur)]}`."""
        raise NotImplementedError

    def contexte_etape(self, etape: Etape, formulaire: FormulaireEtape) -> dict:
        """Contexte propre à une étape (cartes, aperçus). Par défaut, rien."""
        return {}

    # --- Le point d'entrée ------------------------------------------------------------------
    def repondre(self, code: str | None):
        if code is None:
            return redirect(self.url(self.premiere_a_faire().code))
        etape = self.etape(code)
        if etape is None:
            raise Http404("Étape inconnue.")

        if self.request.method == "POST" and "_abandonner" in self.request.POST:
            self.abandonner()
            messages.info(self.request, f"{self.titre} : abandonné. Rien n'a été créé.")
            return redirect(self.url_abandon)

        if not self.accessible(code):
            return redirect(self.url(self.premiere_a_faire().code))

        if etape.recapitulatif:
            if self.request.method == "POST" and "_precedent" in self.request.POST:
                return redirect(self.url(self.etapes[self.index(code) - 1].code))
            return self._recapitulatif(etape)

        if self.request.method == "POST":
            formulaire = self.construire(etape, data=self.request.POST)
            valide = formulaire.is_valid()
            if "_precedent" in self.request.POST:
                if valide:
                    self.enregistrer(code, formulaire)
                else:
                    self.garder_brouillon(code, formulaire)
                i = self.index(code)
                return redirect(self.url(self.etapes[max(i - 1, 0)].code))
            if valide:
                self.enregistrer(code, formulaire)
                suivante = self.etapes[self.index(code) + 1]
                return redirect(self.url(suivante.code))
            return self._afficher(etape, formulaire)

        # GET : une étape rouverte par la revalidation montre son erreur ; sinon la saisie.
        if code in self.etat["a_revoir"]:
            formulaire = self.construire(etape, data=self.saisie(code))
            formulaire.is_valid()
        else:
            initial = self.etat["brouillons"].get(code) or self.saisie(code) or None
            formulaire = self.construire(etape, initial=initial)
        return self._afficher(etape, formulaire)

    def _recapitulatif(self, etape: Etape):
        formulaires, en_defaut = self.valides()
        if en_defaut is not None:
            return self.rouvrir(en_defaut)

        refus = []
        if self.request.method == "POST":
            confirmation = self.construire(etape, data=self.request.POST)
            if confirmation.is_valid():
                try:
                    reponse = self.executer(formulaires, confirmation)
                except ValidationError as erreur:
                    # La transaction a tout annulé : on le dit, et on reste sur le récapitulatif.
                    refus = erreur.messages
                except PermissionDenied as erreur:
                    refus = [str(erreur) or "Ce geste n'est pas ouvert à votre compte."]
                else:
                    self.abandonner()
                    return reponse
        else:
            initial = self.saisie(etape.code) or None
            confirmation = self.construire(etape, initial=initial)
        return self._afficher(
            etape,
            confirmation,
            sections=self.recapitulatif(formulaires),
            formulaires=formulaires,
            refus=refus,
        )

    # --- Le rendu ---------------------------------------------------------------------------
    def _afficher(self, etape: Etape, formulaire: FormulaireEtape, **extra):
        formulaire.preparer_affichage()
        i = self.index(etape.code)
        total = len(self.etapes)
        pastilles = []
        for n, e in enumerate(self.etapes):
            if e.code == etape.code:
                statut = "courante"
            elif self.faite(e.code):
                statut = "faite"
            else:
                statut = "a_venir"
            pastilles.append(
                {
                    "numero": n + 1,
                    "code": e.code,
                    "titre": e.titre,
                    "aide": e.aide,
                    "statut": statut,
                    # Seules les étapes faites et atteignables sont des liens : on revient en
                    # arrière d'un clic, on ne saute pas en avant.
                    "url": self.url(e.code) if statut == "faite" and self.accessible(e.code) else "",
                }
            )
        precedente = self.etapes[i - 1] if i > 0 else None
        contexte = contexte_console(
            self.request,
            page=self.page,
            assistant=self,
            etape=etape,
            form=formulaire,
            pastilles=pastilles,
            numero=i + 1,
            total=total,
            progression=round(100 * (i + 1) / total),
            precedente=precedente,
            url_precedente=self.url(precedente.code) if precedente else "",
            derniere_avant_recap=(i + 1 < total and self.etapes[i + 1].recapitulatif),
            libelles_console=LIBELLES_CONSOLE,
            libelle_confirmer=self.libelle_confirmer,
            **self.contexte_etape(etape, formulaire),
            **extra,
        )
        return render(
            self.request,
            f"plateforme/assistants/{self.nom}_{etape.code}.html",
            contexte,
            status=200,
        )
