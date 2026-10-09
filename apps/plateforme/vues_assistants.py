"""Les gestes de la console, pas à pas.

Trois assistants — ouvrir une boutique, vendre un emplacement, nommer un administrateur — et
quatre gestes d'une page — changer l'état d'une boutique, encaisser un loyer, fixer le taux d'un
rayon, retirer un administrateur.

Les vues ne décident de rien : elles recueillent, affichent et appellent `services.py`, qui
revérifie les droits, rejoue les règles et écrit la trace. La porte `exige_console` filtre à
l'entrée ; le service refiltre derrière — un bouton masqué n'a jamais protégé personne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.administration import LIBELLES_ROLES_ADMINISTRATION
from apps.accounts.models import RolePlateforme
from apps.accounts.permissions import (
    LIBELLES,
    PLATEFORME_BOUTIQUES,
    PLATEFORME_COMMISSIONS,
    PLATEFORME_EMPLACEMENTS,
    droits_du_role,
    droits_plateforme_de,
)
from apps.backoffice.templatetags.hm import fcfa
from apps.confiance import verification
from apps.core.models import AccesPlateforme
from apps.marketplace import gouvernance
from apps.marketplace.metiers import METIERS
from apps.marketplace.models import Bail, Boutique, EmplacementPremium, FactureLoyer, Rayon
from apps.plateforme import services
from apps.plateforme.acces import CONSOLE_ADMINISTRATEURS, contexte_console, exige_console
from apps.plateforme.assistant import Assistant, Confirmation, Etape
from apps.plateforme.formulaires import (
    EXPLICATIONS_REGIMES,
    AdministrateurCompteForm,
    BoutiqueOccupanteForm,
    GerantForm,
    IdentiteForm,
    LegalForm,
    MotifForm,
    OffreForm,
    OuvertureForm,
    PeriodeForm,
    RoleForm,
    TarifForm,
    TauxRayonForm,
    TypeEmplacementForm,
    pourcent,
)
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.utils.translation import gettext_lazy

STYLES = "css/plateforme-assistants.css"


def _montant(valeur) -> str:
    return f"{fcfa(valeur)} FCFA"


def _date(valeur) -> str:
    return f"{valeur:%d/%m/%Y}" if valeur else "—"


# ============================================================================
# 1. Ouvrir une boutique
# ============================================================================
class AssistantBoutique(Assistant):
    nom = "boutique"
    cle_session = "assistant_boutique"
    url_etape = "plateforme:assistant_boutique_etape"
    page = "plateforme:assistant_boutique"
    titre = "Ouvrir une boutique"
    url_abandon = "plateforme:boutiques"
    libelle_confirmer = "Ouvrir la boutique"
    etapes = (
        Etape("identite", "Identité", "Enseigne, métier, ville", IdentiteForm),
        Etape("legal", "Légal et fiscal", "RCCM, NIU, régime", LegalForm),
        Etape("offre", "Offre et bail", "Loyer, rayon, commission", OffreForm),
        Etape("gerant", "Gérant", "Le compte qui tiendra la boutique", GerantForm),
        Etape("recapitulatif", "Récapitulatif", "Relire, puis ouvrir", OuvertureForm, recapitulatif=True),
    )

    def contexte_etape(self, etape, formulaire):
        if etape.code == "identite":
            return {
                "cartes_metiers": [
                    {"valeur": code, "titre": m.libelle, "texte": m.resume}
                    for code, m in METIERS.items()
                ]
            }
        if etape.code == "legal":
            return {
                "cartes_regimes": [
                    {"valeur": code, "titre": libelle, "texte": EXPLICATIONS_REGIMES.get(code, "")}
                    for code, libelle in Boutique.REGIMES
                ]
            }
        if etape.code == "offre":
            return {
                "cartes_offres": [
                    {
                        "valeur": o.code,
                        "titre": o.libelle_affiche,
                        "prix": _montant(o.loyer_mensuel),
                        "suffixe": _("HT / mois"),
                        "lignes": [
                            _("Commission %(taux)s") % {"taux": pourcent(o.taux_commission_defaut)},
                            ngettext("%(n)s compte", "%(n)s comptes", o.quota_utilisateurs) % {"n": o.quota_utilisateurs}
                            + " · "
                            + ngettext("%(n)s dépôt", "%(n)s dépôts", o.quota_depots) % {"n": o.quota_depots},
                            _("Modules : %(modules)s") % {"modules": ", ".join(o.modules_inclus or []) or "—"},
                        ],
                        "donnees": {
                            "loyer": f"{o.loyer_mensuel:.0f}",
                            "taux": f"{o.taux_commission_defaut * 100:.2f}".rstrip("0").rstrip("."),
                        },
                    }
                    for o in formulaire.offres.values()
                ]
            }
        if etape.code == "gerant":
            return {"cartes_mode": _cartes_mode("gérant")}
        if etape.code == "recapitulatif":
            # Le verrou d'activation, dit avant la confirmation plutôt qu'après : une boutique qui
            # naît n'a encore ni pièce vérifiée ni compte de versement, et le second regard doit
            # venir d'un autre administrateur que celui qui l'ouvre. « Ouvrir tout de suite » ne
            # peut donc pas aboutir ici ; le service le refuserait de toute façon.
            return {"verrou_activation": True}
        return {}

    def recapitulatif(self, f):
        identite, legal, offre, gerant = (f[c].cleaned_data for c in ("identite", "legal", "offre", "gerant"))
        o = offre["offre_objet"]
        commission = pourcent(offre["taux_fraction"])
        if offre["derogation"]:
            commission += f" — dérogation (offre : {pourcent(o.taux_commission_defaut)})"
        lignes_offre = [
            ("Offre", o.libelle_affiche),
            ("Rayon principal", offre["rayon_objet"].libelle),
            ("Début du bail", _date(offre["debut"])),
            ("Loyer mensuel HT", _montant(offre["loyer_mensuel"])),
            ("Dépôt de garantie", _montant(offre["depot_garantie"])),
            ("Commission", commission),
        ]
        if offre["derogation"]:
            lignes_offre.append(("Motif de la dérogation", offre["motif_derogation"]))
        return [
            {
                "etape": "identite",
                "titre": _("Identité"),
                "lignes": [
                    ("Enseigne", identite["enseigne"]),
                    ("Adresse de la vitrine", f"/marche/boutique/{services.slug_libre(identite['enseigne'])}/"),
                    ("Raison sociale", identite["raison_sociale"]),
                    ("Métier", METIERS[identite["metier"]].libelle),
                    ("Ville", identite["ville"]),
                    ("Téléphone", identite["telephone"] or "—"),
                ],
            },
            {
                "etape": "legal",
                "titre": _("Légal et fiscal"),
                "lignes": [
                    ("RCCM", legal["rccm"] or "— à compléter"),
                    ("NIU", legal["niu"] or "— à compléter"),
                    ("Régime fiscal", dict(Boutique.REGIMES)[legal["regime_fiscal"]]),
                ],
            },
            {"etape": "offre", "titre": _("Offre et bail"), "lignes": lignes_offre},
            {"etape": "gerant", "titre": _("Gérant"), "lignes": f["gerant"].resume()},
        ]

    def executer(self, f, confirmation):
        identite, legal, offre, gerant = (f[c].cleaned_data for c in ("identite", "legal", "offre", "gerant"))
        demande = services.DemandeOuverture(
            enseigne=identite["enseigne"],
            raison_sociale=identite["raison_sociale"],
            metier=identite["metier"],
            ville=identite["ville"],
            telephone=identite["telephone"],
            rccm=legal["rccm"],
            niu=legal["niu"],
            regime_fiscal=legal["regime_fiscal"],
            offre=offre["offre_objet"],
            rayon=offre["rayon_objet"],
            debut=offre["debut"],
            loyer_mensuel=offre["loyer_mensuel"],
            depot_garantie=offre["depot_garantie"],
            taux_commission=offre["taux_fraction"],
            motif_derogation=offre["motif_derogation"],
            gerant_existant=f["gerant"].compte,
            gerant_telephone=gerant["telephone"],
            gerant_nom=(gerant.get("nom") or "").strip(),
            gerant_mot_de_passe_hache=f["gerant"].mot_de_passe_hache,
            activer=confirmation.cleaned_data["ouverture"] == OuvertureForm.ACTIVE,
        )
        boutique = services.ouvrir_boutique(demande, par=self.request.user)
        if boutique.etat == Boutique.ACTIVE:
            messages.success(
                self.request,
                _('« %(enseigne)s » est ouverte : bail actif, gérant rattaché, plan comptable et magasin principal prêts. Elle paraît en vitrine dès maintenant.') % {"enseigne": boutique.enseigne},
            )
        else:
            messages.success(
                self.request,
                _('« %(enseigne)s » est enregistrée en candidature, avec son bail en brouillon. Complétez sa vérification (pièce du gérant, appel, RCCM, identifiant fiscal, compte de versement) dans « Vérifications », puis validez-la depuis sa fiche.') % {"enseigne": boutique.enseigne},
            )
        return redirect("plateforme:boutique", boutique_id=boutique.pk)


def _cartes_mode(qui: str) -> list[dict]:
    return [
        {
            "valeur": "existant",
            "titre": _("Un compte existant"),
            "texte": _('Le %(qui)s a déjà un compte HyperMarché : on le retrouve par son numéro.') % {"qui": qui},
            "icone": "ic-recherche",
        },
        {
            "valeur": "nouveau",
            "titre": _("Un nouveau compte"),
            "texte": _("Créé à la confirmation, avec un mot de passe initial à lui transmettre."),
            "icone": "ic-plus",
        },
    ]


@exige_console(PLATEFORME_BOUTIQUES)
def ouvrir_boutique(request, etape=None):
    return AssistantBoutique(request).repondre(etape)


# ============================================================================
# 2. Vendre un emplacement premium
# ============================================================================
EXPLICATIONS_EMPLACEMENTS = {
    EmplacementPremium.TETE_DE_GONDOLE: ("ic-etoile", "En tête d'un rayon, la place la plus vue du rayon."),
    EmplacementPremium.BANDEAU_RAYON: ("ic-rayons", "Le bandeau qui surmonte un rayon, sur toute sa largeur."),
    EmplacementPremium.ACCUEIL: ("ic-boutique", "La page d'accueil du marché, avant tout rayon."),
}


class AssistantEmplacement(Assistant):
    nom = "emplacement"
    cle_session = "assistant_emplacement"
    url_etape = "plateforme:assistant_emplacement_etape"
    page = "plateforme:assistant_emplacement"
    titre = "Vendre un emplacement"
    url_abandon = "plateforme:emplacements"
    libelle_confirmer = "Vendre l'emplacement"
    etapes = (
        Etape("boutique", "Boutique", "Qui occupera l'emplacement", BoutiqueOccupanteForm),
        Etape("type", "Emplacement", "Où, et dans quel rayon", TypeEmplacementForm),
        Etape("periode", "Période", "Du premier au dernier jour", PeriodeForm),
        Etape("tarif", "Tarif", "Toujours à son prix", TarifForm),
        Etape("recapitulatif", "Récapitulatif", "Relire, puis vendre", Confirmation, recapitulatif=True),
    )

    def contexte_etape(self, etape, formulaire):
        if etape.code == "boutique":
            q = (self.request.GET.get("q") or "").strip()
            actives = Boutique.objects.filter(etat=Boutique.ACTIVE).select_related("rayon_principal")
            if q:
                actives = actives.filter(Q(enseigne__icontains=q) | Q(raison_sociale__icontains=q) | Q(ville__icontains=q))
            actives = list(actives.order_by("enseigne")[:24])
            choisie = str(formulaire["boutique"].value() or "")
            # La boutique déjà choisie reste visible même si la recherche ne la retrouve pas :
            # sinon, revenir à cette étape ferait disparaître le choix qu'on vient de faire.
            if choisie and choisie not in {str(b.pk) for b in actives}:
                deja = Boutique.objects.filter(pk=choisie, etat=Boutique.ACTIVE).select_related("rayon_principal").first()
                if deja:
                    actives.insert(0, deja)
            return {
                "q": q,
                "cartes_boutiques": [
                    {
                        "valeur": str(b.pk),
                        "titre": b.enseigne,
                        "texte": " · ".join(filter(None, [b.rayon_principal.libelle_affiche if b.rayon_principal else "", b.ville])),
                        "monogramme": b.enseigne,
                    }
                    for b in actives
                ],
                "total_actives": Boutique.objects.filter(etat=Boutique.ACTIVE).count(),
            }
        if etape.code == "type":
            return {
                "cartes_types": [
                    {
                        "valeur": code,
                        "titre": libelle,
                        "texte": EXPLICATIONS_EMPLACEMENTS[code][1],
                        "icone": EXPLICATIONS_EMPLACEMENTS[code][0],
                        "donnees": {"rayon": "oui" if code in services.TYPES_A_RAYON else "non"},
                    }
                    for code, libelle in EmplacementPremium.TYPES
                ]
            }
        if etape.code == "tarif":
            periode = self.saisie("periode")
            try:
                debut, fin = date.fromisoformat(periode["debut"]), date.fromisoformat(periode["fin"])
            except (KeyError, TypeError, ValueError):
                return {}
            return {"periode_texte": _('du %(date)s au %(date2)s, soit %(valeur)s jours') % {"date": _date(debut), "date2": _date(fin), "valeur": (fin - debut).days + 1}}
        return {}

    def recapitulatif(self, f):
        boutique = f["boutique"].cleaned_data["boutique"]
        type_ = f["type"].cleaned_data
        periode = f["periode"].cleaned_data
        tarif = f["tarif"].cleaned_data["tarif"]
        return [
            {"etape": "boutique", "titre": _("Boutique"), "lignes": [("Occupante", boutique.enseigne), ("Ville", boutique.ville)]},
            {
                "etape": "type",
                "titre": _("Emplacement"),
                "lignes": [("Type", dict(EmplacementPremium.TYPES)[type_["type"]])]
                + ([("Rayon", type_["rayon_objet"].libelle)] if type_["rayon_objet"] else []),
            },
            {
                "etape": "periode",
                "titre": _("Période"),
                "lignes": [
                    ("Du", _date(periode["debut"])),
                    ("Au (inclus)", _date(periode["fin"])),
                    ("Durée", f"{periode['jours']} jours"),
                ],
            },
            {"etape": "tarif", "titre": _("Tarif"), "lignes": [("Tarif HT", _montant(tarif))]},
        ]

    def executer(self, f, confirmation):
        type_ = f["type"].cleaned_data
        periode = f["periode"].cleaned_data
        emplacement = services.vendre_emplacement(
            par=self.request.user,
            boutique=f["boutique"].cleaned_data["boutique"],
            type_emplacement=type_["type"],
            rayon=type_["rayon_objet"],
            debut=periode["debut"],
            fin=periode["fin"],
            tarif=f["tarif"].cleaned_data["tarif"],
        )
        messages.success(
            self.request,
            _('Emplacement vendu : %(lower)s pour « %(enseigne)s », %(montant)s HT.') % {"lower": emplacement.get_type_display().lower(), "enseigne": emplacement.boutique_occupante.enseigne, "montant": _montant(emplacement.tarif)},
        )
        return redirect("plateforme:emplacements")


@exige_console(PLATEFORME_EMPLACEMENTS)
def vendre_emplacement(request, etape=None):
    assistant = AssistantEmplacement(request)
    # Depuis la fiche d'une boutique : on arrive avec elle déjà choisie.
    if etape is None and request.method == "GET" and request.GET.get("boutique"):
        if assistant.preremplir("boutique", {"boutique": request.GET["boutique"]}):
            return redirect(assistant.url("type"))
    return assistant.repondre(etape)


# ============================================================================
# 3. Nommer un administrateur du marché
# ============================================================================
EXPLICATIONS_ROLES = {
    "ADMIN_MARCHE": "Le métier quotidien de l'exploitation : il valide, suspend, encaisse, vend.",
    "RESP_RAYON": "Le gestionnaire d'un assortiment : commissions et emplacements, rien d'autre.",
}


def _cartes_roles() -> list[dict]:
    return [
        {
            "valeur": code,
            "titre": libelle,
            "texte": EXPLICATIONS_ROLES[code],
            "lignes": sorted(LIBELLES.get(d, d) for d in droits_du_role(code)),
        }
        for code, libelle in LIBELLES_ROLES_ADMINISTRATION.items()
    ]


class AssistantAdministrateur(Assistant):
    nom = "administrateur"
    cle_session = "assistant_administrateur"
    url_etape = "plateforme:assistant_administrateur_etape"
    page = "plateforme:administrateurs"
    titre = "Nommer un administrateur"
    url_abandon = "plateforme:administrateurs"
    libelle_confirmer = "Nommer l'administrateur"
    etapes = (
        Etape("compte", "Compte", "Qui, et avec quel numéro", AdministrateurCompteForm),
        Etape("role", "Rôle et motif", "Ce qu'il pourra faire, et pourquoi", RoleForm),
        Etape("recapitulatif", "Récapitulatif", "Relire, puis nommer", Confirmation, recapitulatif=True),
    )

    def contexte_etape(self, etape, formulaire):
        if etape.code == "compte":
            return {"cartes_mode": _cartes_mode("futur administrateur")}
        if etape.code == "role":
            return {"cartes_roles": _cartes_roles()}
        return {}

    def recapitulatif(self, f):
        role = f["role"].cleaned_data
        return [
            {"etape": "compte", "titre": _("Compte"), "lignes": f["compte"].resume()},
            {
                "etape": "role",
                "titre": _("Rôle et motif"),
                "lignes": [
                    ("Rôle", LIBELLES_ROLES_ADMINISTRATION[role["role"]]),
                    ("Ce qu'il ouvre", " · ".join(sorted(LIBELLES.get(d, d) for d in droits_du_role(role["role"])))),
                    ("Motif", role["motif"]),
                ],
            },
        ]

    def executer(self, f, confirmation):
        compte = f["compte"]
        role = services.nommer_administrateur(
            par=self.request.user,
            code_role=f["role"].cleaned_data["role"],
            motif=f["role"].cleaned_data["motif"],
            compte_existant=compte.compte,
            telephone=compte.cleaned_data["telephone"],
            nom=(compte.cleaned_data.get("nom") or "").strip(),
            mot_de_passe_hache=compte.mot_de_passe_hache,
        )
        messages.success(
            self.request,
            _('%(nom_complet)s est nommé : %(lower)s. Accès à la console et groupe de permissions posés — jamais le superutilisateur.') % {"nom_complet": role.utilisateur.nom_complet, "lower": role.role.libelle_affiche.lower()},
        )
        return redirect(f"{reverse('plateforme:administrateurs')}#role-{role.pk}")


@exige_console(CONSOLE_ADMINISTRATEURS)
def nommer_administrateur(request, etape=None):
    return AssistantAdministrateur(request).repondre(etape)


# ============================================================================
# 4. Les administrateurs
# ============================================================================
def _page_administrateurs(request, *, retrait=None, formulaire_retrait=None, status=200):
    Utilisateur = get_user_model()
    derniers = dict(
        AccesPlateforme.objects.values("utilisateur_id")
        .annotate(dernier=Max("horodatage"))
        .values_list("utilisateur_id", "dernier")
    )
    superadmins = list(
        Utilisateur.objects.filter(is_superuser=True)
        .annotate(boutiques=Count("appartenances", filter=Q(appartenances__actif=True)))
        .order_by("nom_complet")
    )
    for compte in superadmins:
        compte.dernier_acces = derniers.get(compte.pk)
    roles = list(
        RolePlateforme.objects.select_related("utilisateur", "role").order_by("-actif", "-depuis", "utilisateur__nom_complet")
    )
    for role in roles:
        role.dernier_acces = derniers.get(role.utilisateur_id)
        role.droits = sorted(LIBELLES.get(d, d) for d in droits_du_role(role.role_id))
        if role.actif:
            # Un formulaire par ligne, chacun avec ses propres identifiants : deux `id_motif` sur
            # la même page casseraient le lien entre une étiquette et son champ.
            role.formulaire = (
                formulaire_retrait
                if role.pk == retrait and formulaire_retrait is not None
                else MotifForm(auto_id=f"retrait-{role.pk.hex[:10]}-%s", aide=AIDE_RETRAIT)
            )
            role.formulaire.fields["motif"].label = "Motif du retrait"
            role.formulaire.preparer_affichage()
    return render(
        request,
        "plateforme/administrateurs.html",
        contexte_console(
            request,
            page="plateforme:administrateurs",
            superadmins=superadmins,
            actifs=[r for r in roles if r.actif],
            revolus=[r for r in roles if not r.actif],
            retrait=retrait,
            styles=STYLES,
        ),
        status=status,
    )


AIDE_RETRAIT = "Inscrit au journal des accès, à votre nom. Le rôle reste lisible, daté, dans les rôles révolus."


@exige_console(CONSOLE_ADMINISTRATEURS)
def administrateurs(request):
    return _page_administrateurs(request)


@exige_console(CONSOLE_ADMINISTRATEURS)
def retirer_administrateur(request, role_id):
    role = get_object_or_404(RolePlateforme.objects.select_related("utilisateur", "role"), pk=role_id)
    if request.method != "POST":
        return redirect(f"{reverse('plateforme:administrateurs')}#role-{role.pk}")
    formulaire = MotifForm(request.POST, auto_id=f"retrait-{role.pk.hex[:10]}-%s", aide=AIDE_RETRAIT)
    if formulaire.is_valid():
        try:
            acces_retire = services.retirer_administrateur(role, par=request.user, motif=formulaire.cleaned_data["motif"])
        except ValidationError as erreur:
            for message in erreur.messages:
                formulaire.add_error("motif", message)
        else:
            suite = (
                " Il n'a plus aucun rôle : accès à l'administration et groupe retirés."
                if acces_retire
                else " Il garde l'accès que lui ouvrent ses autres rôles."
            )
            messages.success(request, _('Rôle retiré à %(nom_complet)s (%(libelle)s).%(suite)s') % {"nom_complet": role.utilisateur.nom_complet, "libelle": role.role.libelle_affiche, "suite": suite})
            return redirect("plateforme:administrateurs")
    return _page_administrateurs(request, retrait=role.pk, formulaire_retrait=formulaire, status=400)


# ============================================================================
# 5. Changer l'état d'une boutique
# ============================================================================
ACTIONS = {
    services.VALIDER: {
        "titre": gettext_lazy("Valider la candidature"),
        "bouton": gettext_lazy("Valider et ouvrir"),
        "icone": "ic-check",
        "ton": "primaire",
        "consequences": [
            "La boutique passe à l'état « active » et entre en vitrine : ses articles deviennent visibles et commandables.",
            "Son bail en brouillon devient actif ; son taux sert au calcul de la commission des commandes en ligne.",
            "L'équipe garde les accès qu'elle a déjà : le back-office était ouvert pendant la candidature.",
        ],
    },
    services.SUSPENDRE: {
        "titre": gettext_lazy("Suspendre la boutique"),
        "bouton": gettext_lazy("Suspendre"),
        "icone": "ic-pause",
        "ton": "danger",
        "consequences": [
            "Elle disparaît de la vitrine : ni dans la liste des boutiques, ni dans les résultats, et les liens vers ses articles cessent de fonctionner.",
            "Ses articles sortent des paniers des acheteurs.",
            "Son back-office reste ouvert : l'équipe encaisse toujours au comptoir et garde sa comptabilité. Couper la gestion d'un marchand en retard de loyer reviendrait à lui couper l'accès à ses propres livres (docs/05, M02).",
            "Le bail n'est pas touché, et les commandes déjà passées ne sont pas annulées.",
            "Réversible : « Réactiver » la remet en vitrine.",
        ],
    },
    services.REACTIVER: {
        "titre": gettext_lazy("Réactiver la boutique"),
        "bouton": gettext_lazy("Réactiver"),
        "icone": "ic-lecture",
        "ton": "primaire",
        "consequences": [
            "Elle repasse à l'état « active » et revient en vitrine, avec ses articles.",
            "Rien d'autre ne change : son bail, son équipe et ses livres n'ont pas bougé pendant la suspension.",
        ],
    },
    services.RESILIER: {
        "titre": gettext_lazy("Résilier la boutique"),
        "bouton": gettext_lazy("Résilier définitivement"),
        "icone": "ic-alerte",
        "ton": "danger",
        "consequences": [
            "Son bail est clos aujourd'hui : état « résilié », date de fin et motif inscrits au bail.",
            "Elle quitte la vitrine, et n'y reviendra pas : une boutique résiliée ne se réactive pas.",
            "Rien n'est supprimé : ses ventes, ses écritures et son historique restent, parce qu'ils ont une histoire.",
            "Ce geste ne retire pas les comptes de l'équipe, et ne fait ni l'état des lieux de sortie ni la restitution du dépôt de garantie : ce sont des gestes à part.",
        ],
    },
}


@exige_console(PLATEFORME_BOUTIQUES)
def changer_etat_boutique(request, boutique_id):
    boutique = get_object_or_404(Boutique.objects.select_related("rayon_principal"), pk=boutique_id)
    action = (request.POST.get("action") or request.GET.get("action") or "").strip()
    bail = boutique.bail_actif or boutique.baux.filter(etat=Bail.BROUILLON).order_by("-debut").first()
    impayees = FactureLoyer.objects.filter(
        bail__boutique=boutique, etat__in=[FactureLoyer.EMISE, FactureLoyer.IMPAYEE], echeance__lt=timezone.localdate()
    )
    base = {
        "boutique": boutique,
        "action": action,
        "bail": bail,
        "commission_bail": pourcent(bail.taux_commission) if bail else "",
        "impayees": impayees.count(),
        "styles": STYLES,
    }

    try:
        arrivee = services.verifier_transition(boutique, action)
    except services.TransitionInterdite as refus:
        # 400 explicite : l'adresse a été fabriquée ou l'état a changé depuis l'affichage du
        # bouton. Dans les deux cas, on dit pourquoi au lieu d'afficher une page d'erreur muette.
        return render(
            request,
            "plateforme/boutique_etat.html",
            contexte_console(request, page="plateforme:boutiques", refus=refus.messages[0], **base),
            status=400,
        )

    # Le verrou d'activation, montré avant le geste : la liste de ce qui manque, et le chemin
    # vers le dossier. Le service le rejoue à la confirmation.
    manques = verification.manques_pour_activer(boutique) if arrivee == Boutique.ACTIVE else []

    obligatoire = action != services.VALIDER
    formulaire = MotifForm(
        request.POST if request.method == "POST" else None,
        obligatoire=obligatoire,
        aide=(
            "Il sera inscrit au journal des accès"
            + (" et au bail." if action == services.RESILIER else ".")
            if obligatoire
            else "Facultatif : une précision pour le journal."
        ),
    )
    if request.method == "POST" and formulaire.is_valid():
        try:
            services.changer_etat_boutique(boutique, action, par=request.user, motif=formulaire.cleaned_data["motif"])
        except verification.VerificationIncomplete as refus:
            manques = refus.manques
        except ValidationError as erreur:
            for message in erreur.messages:
                formulaire.add_error("motif", message)
        else:
            messages.success(request, _('« %(enseigne)s » : %(lower)s — fait, et inscrit au journal.') % {"enseigne": boutique.enseigne, "lower": ACTIONS[action]['titre'].lower()})
            return redirect("plateforme:boutique", boutique_id=boutique.pk)
    formulaire.preparer_affichage()
    return render(
        request,
        "plateforme/boutique_etat.html",
        contexte_console(
            request,
            page="plateforme:boutiques",
            geste=ACTIONS[action],
            arrivee=dict(Boutique.ETATS)[arrivee],
            arrivee_code=arrivee,
            form=formulaire,
            sans_bail_actif=(action == services.REACTIVER and boutique.bail_actif is None),
            manques=manques,
            **base,
        ),
        status=400 if request.method == "POST" else 200,
    )


# ============================================================================
# 6. Encaisser un loyer
# ============================================================================
def _suite_sure(request, defaut: str) -> str:
    suite = request.POST.get("suite") or request.GET.get("suite") or ""
    if suite and url_has_allowed_host_and_scheme(suite, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return suite
    return reverse(defaut)


@exige_console(PLATEFORME_BOUTIQUES)
def encaisser_loyer(request, facture_id):
    facture = get_object_or_404(FactureLoyer.objects.select_related("bail__boutique", "bail__type_emplacement"), pk=facture_id)
    suite = _suite_sure(request, "plateforme:loyers")
    refus = services.refus_encaissement(facture)
    status = 200
    if request.method == "POST" and refus is None:
        try:
            services.encaisser_loyer(facture, par=request.user)
        except ValidationError as erreur:
            refus = " ".join(erreur.messages)
        else:
            messages.success(
                request,
                _('Loyer %(periode)s de « %(enseigne)s » encaissé : %(montant)s TTC.') % {"periode": format(facture.periode, "%m/%Y"), "enseigne": facture.bail.boutique.enseigne, "montant": _montant(facture.montant_ttc)},
            )
            return redirect(suite)
    if request.method == "POST" and refus:
        status = 400
    aujourdhui = timezone.localdate()
    retard = (aujourdhui - facture.echeance).days if facture.echeance < aujourdhui else 0
    return render(
        request,
        "plateforme/loyer_encaisser.html",
        contexte_console(
            request,
            page="plateforme:loyers",
            facture=facture,
            boutique=facture.bail.boutique,
            retard=retard,
            taux_tva=pourcent(facture.taux_tva),
            refus=refus,
            suite=suite,
            styles=STYLES,
        ),
        status=status,
    )


# ============================================================================
# 7. Fixer le taux d'un rayon
# ============================================================================
@exige_console(PLATEFORME_COMMISSIONS)
def fixer_taux(request, rayon_id):
    rayon = get_object_or_404(Rayon, pk=rayon_id)
    effet = services.effet_du_taux(rayon)
    ancien = rayon.taux_commission
    conflit = gouvernance.en_conflit_sur_le_rayon(request.user, rayon)
    # `gouvernance.fixer_taux_rayon` exige le droit **par un rôle de plateforme**
    # (`droits_plateforme_de`) : un superadministrateur sans rôle y est refusé. On le dit avant la
    # saisie plutôt qu'après.
    sans_role = PLATEFORME_COMMISSIONS not in droits_plateforme_de(request.user)
    formulaire = TauxRayonForm(request.POST if request.method == "POST" else None)
    apercu, refus, status = None, None, 200

    if conflit:
        # Dit avant la saisie, pas après : laisser taper un taux et un motif pour les refuser
        # ensuite serait une petite humiliation inutile.
        refus = (
            f"Vous vendez dans le rayon « {rayon} » : vous n'en fixez pas la commission. "
            "Faites-le faire par quelqu'un qui n'y a pas d'intérêt (ADR-012)."
        )
        status = 403 if request.method == "POST" else 200
    elif sans_role:
        refus = (
            "Le taux d'un rayon se fixe au titre d'un rôle de plateforme, et votre compte n'en porte "
            "aucun : la règle de gouvernance (apps/marketplace/gouvernance.py) ne reconnaît pas le "
            "superadministrateur ici. Faites-le depuis un compte d'administrateur du marché."
        )
        status = 403 if request.method == "POST" else 200
    elif request.method == "POST" and formulaire.is_valid():
        nouveau = (formulaire.cleaned_data["pourcent"] / Decimal("100")).quantize(Decimal("0.0001"))
        if nouveau == ancien:
            formulaire.add_error("pourcent", _("C'est déjà le taux du rayon (%(pourcent)s).") % {"pourcent": pourcent(ancien)})
        elif "confirmer" in request.POST and request.POST.get("apercu_de") == str(formulaire.cleaned_data["pourcent"]):
            try:
                services.fixer_taux_rayon(rayon, formulaire.cleaned_data["pourcent"], par=request.user, motif=formulaire.cleaned_data["motif"])
            except PermissionDenied as erreur:
                refus, status = str(erreur), 403
            except ValidationError as erreur:
                refus, status = " ".join(erreur.messages), 400
            else:
                messages.success(
                    request,
                    _('Rayon « %(rayon)s » : commission %(pourcent)s → %(pourcent2)s. Inscrit au journal.') % {"rayon": rayon, "pourcent": pourcent(ancien), "pourcent2": pourcent(nouveau)},
                )
                return redirect("plateforme:rayons")
        else:
            # Premier envoi, ou taux modifié après l'aperçu : on (ré)affiche l'effet avant d'agir.
            apercu = {
                "ancien": pourcent(ancien),
                "nouveau": pourcent(nouveau),
                "hausse": nouveau > ancien,
                "saisi": str(formulaire.cleaned_data["pourcent"]),
            }
    formulaire.preparer_affichage()
    return render(
        request,
        "plateforme/rayon_taux.html",
        contexte_console(
            request,
            page="plateforme:rayons",
            rayon=rayon,
            ancien=pourcent(ancien),
            ancien_brut=f"{ancien * 100:.2f}".rstrip("0").rstrip("."),
            effet=effet,
            form=formulaire,
            apercu=apercu,
            refus=refus,
            conflit=conflit,
            bloque=conflit or sans_role,
            styles=STYLES,
        ),
        status=status,
    )
