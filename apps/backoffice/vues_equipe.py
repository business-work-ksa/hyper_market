"""Gestion de l'équipe d'une boutique, depuis le back-office.

Les droits étaient appliqués et affichés, mais leur attribution passait encore
par l'administration Django : un gérant ne pouvait ni embaucher, ni changer un
rôle, ni retirer un accès sans nous appeler. C'est une dépendance intenable pour
un produit vendu à des commerçants — un départ se règle le jour même, pas au
prochain passage.

Trois garde-fous, qui découlent tous du même principe : **un accès se retire, il
ne se supprime jamais.** L'employé qui part a encaissé des ventes ; son nom est
sur des tickets, son identité sur des mouvements de stock. Effacer son compte
effacerait la traçabilité de ce qu'il a fait.
"""

import secrets

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts import permissions as droit
from apps.accounts.models import ALPHABET_CODE, Appartenance, Role, Utilisateur
from apps.backoffice.acces import contexte_commun, exige
from apps.backoffice.filtres import FiltresEquipeForm
from apps.backoffice.forms import ChangementDeRoleForm, MembreEquipeForm
from apps.orders.avis import roles_qui_traitent
from django.utils.translation import gettext as _

CLE_MOT_DE_PASSE = "mot_de_passe_provisoire"


def roles_attribuables():
    """Rôles qu'un gérant peut attribuer dans sa boutique.

    Les rôles de portée plateforme (gestionnaire de marché, cabinet partenaire)
    en sont exclus : ils relèvent de l'exploitation de la place de marché, pas
    d'un commerçant.
    """
    return list(Role.objects.filter(portee=Role.BOUTIQUE).order_by("libelle"))


def generer_mot_de_passe() -> str:
    """Mot de passe provisoire, lisible à voix haute.

    Il n'y a ni passerelle SMS ni courriel fiable à ce palier : le gérant remet
    ce mot de passe **de la main à la main**. Il doit donc se dicter sans
    ambiguïté — même alphabet que les codes d'apporteur, ni O/0 ni I/1 — et rester
    court. Il est affiché une seule fois.
    """
    groupes = ["".join(secrets.choice(ALPHABET_CODE) for _ in range(4)) for _ in range(3)]
    return "-".join(groupes)


def _detail_des_roles(roles) -> list[dict]:
    """Ce que chaque rôle ouvre, en français, lu depuis la matrice de code.

    Le gérant qui attribue un rôle doit voir ce qu'il donne. Les libellés
    viennent de `apps/accounts/permissions.py`, pas du miroir stocké en base :
    c'est la même source que la porte qui les vérifie.
    """
    from apps.accounts.permissions import LIBELLES, droits_du_role

    return [
        {
            "code": role.code,
            "libelle": role.libelle,
            "droits": [LIBELLES[d] for d in sorted(droits_du_role(role.code))],
        }
        for role in roles
    ]


def _gerants_actifs(boutique, sauf=None):
    membres = Appartenance.objects.filter(
        boutique=boutique, actif=True, role_id=Role.GERANT
    )
    if sauf is not None:
        membres = membres.exclude(pk=sauf.pk)
    return membres


@exige(droit.BOUTIQUE_ADMINISTRER)
def equipe(request):
    """Liste de l'équipe, et rattachement d'une nouvelle personne."""
    contexte = contexte_commun(request, "boutique")
    boutique = contexte["boutique"]

    bail = boutique.bail_actif
    quota = bail.type_emplacement.quota_utilisateurs if bail else 1
    actifs = Appartenance.objects.filter(boutique=boutique, actif=True).count()
    roles = roles_attribuables()

    if request.method == "POST":
        formulaire = MembreEquipeForm(request.POST, roles=roles, boutique=boutique)
        if actifs >= quota:
            formulaire.add_error(
                None,
                _('Votre emplacement autorise %(quota)s utilisateur(s). Retirez un accès, ou passez à une offre supérieure.') % {"quota": quota},
            )
        elif formulaire.is_valid():
            _rattacher(request, boutique, formulaire)
            return redirect("equipe")
    else:
        formulaire = MembreEquipeForm(roles=roles, boutique=boutique)

    filtres = FiltresEquipeForm(request.GET, roles=roles)
    membres = list(_filtrer(_tous_les_membres(boutique), filtres.valeurs))
    qui_traitent = set(roles_qui_traitent())
    for membre in membres:
        membre.traite_commandes = membre.role.code in qui_traitent

    contexte.update(
        {
            "formulaire": formulaire,
            "filtres": filtres,
            "roles": roles,
            "roles_detail": _detail_des_roles(roles),
            "membres": membres,
            "quota_utilisateurs": quota,
            "actifs": actifs,
            "places_restantes": max(quota - actifs, 0),
            "url_equipe": reverse("equipe"),
            "url_creer": "#modale-nouveau-membre",
            "url_retirer": reverse("equipe_retirer_lot"),
            # Affiché une seule fois, puis retiré de la session : le gérant doit
            # le noter maintenant, personne ne pourra le lui relire ensuite.
            "mot_de_passe_provisoire": request.session.pop(CLE_MOT_DE_PASSE, None),
        }
    )
    return render(request, "equipe.html", contexte)


def _tous_les_membres(boutique):
    return (
        Appartenance.objects.filter(boutique=boutique)
        .select_related("utilisateur", "role")
        .order_by("-actif", "utilisateur__nom_complet")
    )


def _filtrer(membres, valeurs):
    """Applique les filtres de l'écran de l'équipe.

    Le nom **et** le téléphone : dans une boutique, on cherche « Marie » aussi
    souvent qu'on cherche les quatre derniers chiffres d'un numéro qu'on a sous
    les yeux.
    """
    if valeurs.get("q"):
        from django.db.models import Q

        terme = valeurs["q"]
        membres = membres.filter(
            Q(utilisateur__nom_complet__icontains=terme)
            | Q(utilisateur__telephone__icontains=terme)
        )
    if valeurs.get("role"):
        membres = membres.filter(role_id=valeurs["role"])
    if valeurs.get("etat") == "actif":
        membres = membres.filter(actif=True)
    elif valeurs.get("etat") == "retire":
        membres = membres.filter(actif=False)
    return membres


@exige(droit.BOUTIQUE_ADMINISTRER)
@require_POST
def equipe_retirer_lot(request):
    """Retire l'accès de plusieurs membres d'un coup. **Aucun compte n'est supprimé.**

    C'est le seul geste de cet écran qui porte sur plusieurs lignes, et c'est
    le bon : une fin de saison retire trois accès le même jour. Les garde-fous
    restent appliqués **ligne par ligne** — se fermer la porte à soi-même ou
    retirer le dernier gérant reste refusé, et le refus est nommé plutôt que
    fondu dans un compte global.
    """
    contexte = contexte_commun(request, "boutique")
    boutique = contexte["boutique"]

    membres = list(
        Appartenance.objects.filter(
            pk__in=request.POST.getlist("ids"), boutique=boutique, actif=True
        ).select_related("utilisateur", "role")
    )
    if not membres:
        messages.error(request, _("Aucun accès actif à retirer."))
        return redirect("equipe")

    retires, refuses = [], []
    for membre in membres:
        motif = _pourquoi_pas_retirable(request, boutique, membre, membres)
        if motif:
            refuses.append(f"{membre.utilisateur.nom_complet} ({motif})")
            continue
        membre.actif = False
        membre.jusqu_a = timezone.localdate()
        membre.save(update_fields=["actif", "jusqu_a"])
        retires.append(membre.utilisateur.nom_complet)

    if retires:
        messages.success(
            request,
            _('Accès retiré à %(join)s. Leur historique de ventes et de mouvements reste intact.') % {"join": ', '.join(retires)},
        )
    for refus in refuses:
        messages.error(request, _('Accès conservé pour %(refus)s.') % {"refus": refus})
    return redirect("equipe")


def _pourquoi_pas_retirable(request, boutique, membre, lot) -> str:
    """Motif du refus, ou chaîne vide.

    `lot` compte : retirer les deux derniers gérants **dans la même sélection**
    fermerait la boutique aussi sûrement que de les retirer l'un après l'autre.
    On regarde donc ce qui restera une fois le lot entier appliqué, pas
    seulement une fois cette ligne-là retirée.
    """
    if membre.utilisateur_id == request.user.pk:
        return "on ne retire pas son propre accès"
    if membre.role_id != Role.GERANT:
        return ""

    vises = {m.pk for m in lot if m.role_id == Role.GERANT}
    restants = _gerants_actifs(boutique).exclude(pk__in=vises)
    return "" if restants.exists() else "c'est le dernier gérant de la boutique"


@transaction.atomic
def _rattacher(request, boutique, formulaire) -> None:
    donnees = formulaire.cleaned_data
    utilisateur = formulaire.utilisateur_existant

    if utilisateur is None:
        mot_de_passe = generer_mot_de_passe()
        utilisateur = Utilisateur.objects.create_user(
            telephone=donnees["telephone"],
            password=mot_de_passe,
            nom_complet=donnees["nom_complet"],
        )
        request.session[CLE_MOT_DE_PASSE] = {
            "nom": utilisateur.nom_complet,
            "telephone": utilisateur.telephone,
            "valeur": mot_de_passe,
        }
        messages.success(request, _('Compte créé pour %(nom_complet)s.') % {"nom_complet": utilisateur.nom_complet})
    else:
        messages.success(
            request,
            _('%(nom_complet)s avait déjà un compte HyperMarché : il est rattaché à votre boutique, avec son mot de passe habituel.') % {"nom_complet": utilisateur.nom_complet},
        )

    # Un ancien accès au même rôle est réactivé plutôt que dupliqué : l'employé
    # qui revient retrouve son historique, il ne repart pas de zéro.
    ancienne = Appartenance.objects.filter(
        utilisateur=utilisateur, boutique=boutique, role=donnees["role"], actif=False
    ).first()
    if ancienne is not None:
        ancienne.actif = True
        ancienne.jusqu_a = None
        ancienne.save(update_fields=["actif", "jusqu_a"])
    else:
        Appartenance.objects.create(
            utilisateur=utilisateur, boutique=boutique, role=donnees["role"]
        )


@exige(droit.BOUTIQUE_ADMINISTRER)
@require_POST
def equipe_role(request, appartenance_id):
    """Change le rôle d'un membre — donc ce qu'il voit, immédiatement."""
    contexte = contexte_commun(request, "boutique")
    boutique = contexte["boutique"]
    membre = get_object_or_404(
        Appartenance, pk=appartenance_id, boutique=boutique, actif=True
    )

    formulaire = ChangementDeRoleForm(request.POST, roles=roles_attribuables())
    if not formulaire.is_valid():
        messages.error(request, _("Rôle inconnu."))
        return redirect("equipe")

    nouveau = formulaire.cleaned_data["role"]
    if (
        membre.role_id == Role.GERANT
        and nouveau.code != Role.GERANT
        and not _gerants_actifs(boutique, sauf=membre).exists()
    ):
        messages.error(
            request,
            _("C'est le dernier gérant de la boutique : nommez d'abord quelqu'un d'autre."),
        )
        return redirect("equipe")

    if Appartenance.objects.filter(
        utilisateur=membre.utilisateur, boutique=boutique, role=nouveau, actif=True
    ).exists():
        messages.error(request, _('%(nom_complet)s a déjà ce rôle.') % {"nom_complet": membre.utilisateur.nom_complet})
        return redirect("equipe")

    ancien = membre.role.libelle
    membre.role = nouveau
    membre.save(update_fields=["role"])
    messages.success(
        request,
        _('%(nom_complet)s passe de « %(ancien)s » à « %(libelle)s ».') % {"nom_complet": membre.utilisateur.nom_complet, "ancien": ancien, "libelle": nouveau.libelle},
    )
    return redirect("equipe")


@exige(droit.BOUTIQUE_ADMINISTRER)
@require_POST
def equipe_retirer(request, appartenance_id):
    """Retire l'accès d'un membre. **Ne supprime jamais son compte.**"""
    contexte = contexte_commun(request, "boutique")
    boutique = contexte["boutique"]
    membre = get_object_or_404(
        Appartenance, pk=appartenance_id, boutique=boutique, actif=True
    )

    if membre.utilisateur_id == request.user.pk:
        # Se retirer soi-même fermerait la porte de l'intérieur, sans personne
        # dehors pour la rouvrir.
        messages.error(request, _("Vous ne pouvez pas retirer votre propre accès."))
        return redirect("equipe")

    if membre.role_id == Role.GERANT and not _gerants_actifs(boutique, sauf=membre).exists():
        messages.error(request, _("C'est le dernier gérant de la boutique."))
        return redirect("equipe")

    membre.actif = False
    membre.jusqu_a = timezone.localdate()
    membre.save(update_fields=["actif", "jusqu_a"])
    messages.success(
        request,
        _('Accès retiré à %(nom_complet)s. Son historique de ventes et de mouvements reste intact.') % {"nom_complet": membre.utilisateur.nom_complet},
    )
    return redirect("equipe")


@exige(droit.BOUTIQUE_ADMINISTRER)
@require_POST
def equipe_reactiver(request, appartenance_id):
    contexte = contexte_commun(request, "boutique")
    boutique = contexte["boutique"]
    membre = get_object_or_404(
        Appartenance, pk=appartenance_id, boutique=boutique, actif=False
    )

    bail = boutique.bail_actif
    quota = bail.type_emplacement.quota_utilisateurs if bail else 1
    if Appartenance.objects.filter(boutique=boutique, actif=True).count() >= quota:
        messages.error(request, _('Votre emplacement autorise %(quota)s utilisateur(s).') % {"quota": quota})
        return redirect("equipe")

    membre.actif = True
    membre.jusqu_a = None
    membre.save(update_fields=["actif", "jusqu_a"])
    messages.success(request, _('%(nom_complet)s retrouve son accès.') % {"nom_complet": membre.utilisateur.nom_complet})
    return redirect("equipe")


@exige(droit.BOUTIQUE_ADMINISTRER)
@require_POST
def equipe_mot_de_passe(request, appartenance_id):
    """Réinitialise le mot de passe d'un membre.

    Sans passerelle SMS, un employé qui oublie son mot de passe n'a aucun moyen
    de le récupérer seul. Le gérant lui en génère un nouveau et le lui remet
    en main propre — c'est le seul canal fiable à ce palier.
    """
    contexte = contexte_commun(request, "boutique")
    membre = get_object_or_404(
        Appartenance, pk=appartenance_id, boutique=contexte["boutique"]
    )

    if membre.utilisateur_id == request.user.pk:
        messages.error(
            request, _("Changez votre propre mot de passe depuis votre compte, pas depuis ici.")
        )
        return redirect("equipe")

    mot_de_passe = generer_mot_de_passe()
    membre.utilisateur.set_password(mot_de_passe)
    membre.utilisateur.save(update_fields=["password"])
    request.session[CLE_MOT_DE_PASSE] = {
        "nom": membre.utilisateur.nom_complet,
        "telephone": membre.utilisateur.telephone,
        "valeur": mot_de_passe,
    }
    return redirect("equipe")


@exige(droit.BOUTIQUE_ADMINISTRER)
@require_POST
def equipe_avis_commandes(request, appartenance_id):
    """Prévenir — ou ne plus prévenir — cette personne des nouvelles commandes, sur WhatsApp."""
    contexte = contexte_commun(request, "boutique")
    membre = get_object_or_404(
        Appartenance, pk=appartenance_id, boutique=contexte["boutique"], actif=True
    )
    if membre.role.code not in roles_qui_traitent():
        messages.error(request, _("Son rôle ne traite pas les commandes : il n'y a rien à lui envoyer."))
        return redirect("equipe")
    membre.avis_commandes = not membre.avis_commandes
    membre.save(update_fields=["avis_commandes"])
    nom = membre.utilisateur.nom_complet
    messages.success(
        request,
        f"{nom} sera prévenu des nouvelles commandes sur WhatsApp."
        if membre.avis_commandes
        else f"{nom} ne sera plus prévenu des nouvelles commandes.",
    )
    return redirect("equipe")
