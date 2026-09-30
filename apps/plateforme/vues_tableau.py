"""Tableau de bord de la console, journal des accès et santé technique.

Aucun de ces trois écrans ne lit une table scopée : ils lisent les contrats du bailleur (boutiques,
baux, loyers, emplacements) et le journal lui-même. Ils n'écrivent donc aucune ligne au journal —
le journal ne trace que les regards portés *chez* un commerçant, et le remplir de consultations
du tableau de bord le rendrait illisible.
"""

from __future__ import annotations

import os
import platform
import uuid
from datetime import datetime, time, timedelta

import django
from django.conf import settings
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.accounts.models import DossierKyc, RolePlateforme, Utilisateur
from apps.core.models import AccesPlateforme
from apps.marketplace.models import Bail, Boutique, EmplacementPremium, FactureLoyer
from apps.plateforme import indicateurs as ind
from apps.plateforme.acces import CONSOLE_TECHNIQUE, contexte_console, exige_console

JOURS_SEMAINE = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

# Les écrans journalisés, nommés pour un lecteur humain. Un écran inconnu s'affiche tel quel :
# mieux vaut un identifiant brut qu'une ligne de journal masquée.
LIBELLES_ECRANS = {
    "plateforme:activite": "Activité des boutiques",
    "plateforme:boutique_activite": "Activité d'une boutique",
}


def libelle_ecran(ecran: str) -> str:
    return LIBELLES_ECRANS.get(ecran, ecran)


def date_longue(jour) -> str:
    return f"{JOURS_SEMAINE[jour.weekday()]} {jour.day} {ind.MOIS_LONGS[jour.month - 1]} {jour.year}"


def _accord(n: int, singulier: str, pluriel: str) -> str:
    return f"{n} {singulier if n == 1 else pluriel}"


def _lien_admin(nom: str, requete: str = "") -> str | None:
    """Lien vers une liste de `/admin/`, ou `None` si ce modèle n'y est pas inscrit."""
    try:
        return reverse(f"admin:{nom}") + requete
    except NoReverseMatch:
        return None


def noms_des_boutiques(ids) -> dict:
    """`{id: enseigne}` en une requête. Le journal ne porte que l'identifiant, par construction :
    il doit survivre à la boutique qu'il décrit (voir `AccesPlateforme`)."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(Boutique.objects.filter(pk__in=ids).values_list("pk", "enseigne"))


def lignes_de_journal(acces) -> list[dict]:
    acces = list(acces)
    noms = noms_des_boutiques(a.boutique_id for a in acces)
    return [
        {
            "horodatage": a.horodatage,
            "utilisateur": a.utilisateur,
            "boutique_id": a.boutique_id,
            "boutique": noms.get(a.boutique_id) if a.boutique_id else None,
            "boutique_disparue": bool(a.boutique_id and a.boutique_id not in noms),
            "ecran": libelle_ecran(a.ecran),
            "motif": a.motif,
        }
        for a in acces
    ]


# ----------------------------------------------------------------------------
# Tableau de bord
# ----------------------------------------------------------------------------
def file_a_traiter(droits, aujourdhui) -> list[dict]:
    """Ce qui attend un geste, du plus urgent au moins urgent, selon les droits de l'écran.

    Seules les lignes non nulles sont rendues : une file qui affiche « 0 » cinq fois apprend à ne
    plus la lire, et le jour où il y a quelque chose, personne ne regarde.
    """
    file = []
    if "plateforme.boutiques" in droits:
        impayes = ind.synthese_impayes(aujourdhui)
        if impayes["nombre"]:
            file.append(
                {
                    "ton": "critique",
                    "icone": "ic-argent",
                    "nombre": impayes["nombre"],
                    "titre": _accord(impayes["nombre"], "facture de loyer échue", "factures de loyer échues"),
                    "montant": impayes["montant"],
                    "detail": _accord(impayes["boutiques"], "boutique concernée", "boutiques concernées"),
                    "url": reverse("plateforme:loyers") + "?mois=tous&etat=echues",
                }
            )
        candidatures = Boutique.objects.filter(etat=Boutique.CANDIDATURE).count()
        if candidatures:
            file.append(
                {
                    "ton": "or",
                    "icone": "ic-boutique",
                    "nombre": candidatures,
                    "titre": _accord(candidatures, "candidature à valider", "candidatures à valider"),
                    "detail": "Vérifier l'identité légale, puis valider ou refuser",
                    "url": reverse("plateforme:boutiques") + "?etat=candidature",
                }
            )
        kyc = DossierKyc.objects.filter(etat=DossierKyc.EN_ATTENTE).count()
        url_kyc = _lien_admin("accounts_dossierkyc_changelist", "?etat__exact=en_attente")
        if kyc and url_kyc:
            file.append(
                {
                    "ton": "or",
                    "icone": "ic-document",
                    "nombre": kyc,
                    "titre": _accord(kyc, "dossier d'identité à instruire", "dossiers d'identité à instruire"),
                    "detail": "Pièces d'identité, RCCM et NIU déposés",
                    "url": url_kyc,
                }
            )
        # Les signaux de risque ouverts : des indices que la tâche de nuit a trouvés et qu'un humain
        # doit trancher. Placés avant les baux, parce qu'une fausse boutique encaisse pendant qu'on
        # attend ; le ton suit la gravité la plus haute, pour qu'un signal critique ne se lise pas
        # comme une échéance de bail.
        from apps.confiance.models import SignalRisque

        ouverts = dict(
            SignalRisque.objects.filter(etat=SignalRisque.OUVERT)
            .order_by()
            .values_list("gravite")
            .annotate(n=Count("id"))
        )
        nb_signaux = sum(ouverts.values())
        if nb_signaux:
            critiques = ouverts.get(SignalRisque.CRITIQUE, 0)
            file.append(
                {
                    "ton": "critique" if critiques else "alerte",
                    "icone": "ic-alerte",
                    "nombre": nb_signaux,
                    "titre": _accord(nb_signaux, "signal de risque à trancher", "signaux de risque à trancher"),
                    "detail": (
                        (_accord(critiques, "critique", "critiques") + " · " if critiques else "")
                        + "Des indices, pas des preuves : écarter ou confirmer, avec un motif"
                    ),
                    "url": reverse("plateforme:signaux"),
                }
            )
        horizon = aujourdhui + timedelta(days=30)
        baux = Bail.objects.filter(etat=Bail.ACTIF, fin__gte=aujourdhui, fin__lte=horizon).count()
        if baux:
            file.append(
                {
                    "ton": "alerte",
                    "icone": "ic-calendrier",
                    "nombre": baux,
                    "titre": _accord(baux, "bail se termine sous 30 jours", "baux se terminent sous 30 jours"),
                    "detail": "Renouveler ou préparer l'état des lieux de sortie",
                    "url": reverse("plateforme:boutiques") + "?etat=active&tri=fin_bail",
                }
            )
    if "plateforme.apporteurs" in droits:
        from apps.affiliation.models import SignalFraude

        signaux = SignalFraude.objects.filter(traite_par__isnull=True).count()
        url_fraude = _lien_admin("affiliation_signalfraude_changelist", "?traite_par__isnull=True")
        if signaux and url_fraude:
            file.append(
                {
                    "ton": "critique",
                    "icone": "ic-alerte",
                    "nombre": signaux,
                    "titre": _accord(signaux, "signalement de fraude ouvert", "signalements de fraude ouverts"),
                    "detail": "Réseau d'apporteurs : décision à consigner",
                    "url": url_fraude,
                }
            )
    return file


def raccourcis(droits) -> list[dict]:
    """Les assistants du héros : seulement ceux que les droits ouvrent, le plus fréquent d'abord."""
    liens = []
    if "plateforme.boutiques" in droits:
        liens.append({"url": reverse("plateforme:assistant_boutique"), "icone": "ic-baguette",
                      "libelle": "Ouvrir une boutique", "primaire": True})
    if "plateforme.emplacements" in droits:
        liens.append({"url": reverse("plateforme:assistant_emplacement"), "icone": "ic-etoile",
                      "libelle": "Vendre un emplacement"})
    liens.append({"url": reverse("plateforme:activite"), "icone": "ic-pouls",
                  "libelle": "Suivre l'activité"})
    return liens


def gouvernance(aujourdhui) -> dict:
    """Qui administre, et qui a regardé quoi cette semaine — le résumé du superadministrateur."""
    depuis = timezone.make_aware(datetime.combine(aujourdhui - timedelta(days=6), time.min))
    roles = list(
        RolePlateforme.objects.filter(actif=True)
        .select_related("utilisateur", "role")
        .order_by("utilisateur__nom_complet")
    )
    acces = {
        ligne["utilisateur_id"]: ligne["n"]
        for ligne in AccesPlateforme.objects.filter(horodatage__gte=depuis)
        .order_by()
        .values("utilisateur_id")
        .annotate(n=Count("id"))
    }
    superadmins = list(
        Utilisateur.objects.filter(is_superuser=True, is_active=True).order_by("nom_complet")
    )
    personnes = [
        {"utilisateur": u, "niveau": "Superadministrateur", "acces": acces.get(u.pk, 0)}
        for u in superadmins
    ] + [
        {"utilisateur": r.utilisateur, "niveau": r.role.libelle, "acces": acces.get(r.utilisateur_id, 0),
         "depuis": r.depuis}
        for r in roles
    ]
    maximum = max((p["acces"] for p in personnes), default=0)
    for p in personnes:
        p["largeur"] = round(p["acces"] / maximum * 100, 1) if maximum else 0
    return {
        "personnes": personnes,
        "nb_administrateurs": len(roles),
        "acces_semaine": sum(acces.values()),
    }


@exige_console()
def tableau_de_bord(request):
    droits = request._droits_console
    aujourdhui = timezone.localdate()
    mois = ind.debut_du_mois(aujourdhui)
    nb_mois = 6 if request.GET.get("periode") == "6" else 12

    boutiques = ind.compteurs_boutiques()
    loyers = ind.synthese_loyers(mois)
    impayes = ind.synthese_impayes(aujourdhui)
    serie = ind.loyers_encaisses_par_mois(mois, nb_mois)
    premium = ind.revenu_premium(mois)
    emplacements = ind.compteurs_emplacements(aujourdhui)
    loyers_ht_encaisses = serie[-1]["valeur"]

    actives = Boutique.objects.filter(etat=Boutique.ACTIVE)
    heure = timezone.localtime().hour
    contexte = contexte_console(
        request,
        page="plateforme:tableau_de_bord",
        salut="Bonsoir" if heure >= 18 else "Bonjour",
        prenom=(request.user.nom_complet or "").split(" ")[0],
        date_du_jour=date_longue(aujourdhui),
        libelle_mois=ind.libelle_mois(mois, long=True),
        raccourcis=raccourcis(droits),
        boutiques=boutiques,
        loyers=loyers,
        impayes=impayes,
        revenus_mois=loyers_ht_encaisses + premium,
        revenus_loyers=loyers_ht_encaisses,
        revenus_premium=premium,
        trace_revenus=ind.trace(serie),
        emplacements=emplacements,
        file=file_a_traiter(droits, aujourdhui),
        graphe=ind.graphe_de(serie, etiquette=30),
        nb_mois=nb_mois,
        par_rayon=ind.repartition(actives, "rayon_principal__libelle", vide="Sans rayon"),
        par_ville=ind.repartition(actives, "ville"),
        derniers_acces=lignes_de_journal(
            AccesPlateforme.objects.select_related("utilisateur")[:5]
        ),
    )
    if CONSOLE_TECHNIQUE in droits:
        contexte["gouvernance"] = gouvernance(aujourdhui)
    return render(request, "plateforme/tableau_de_bord.html", contexte)


# ----------------------------------------------------------------------------
# Journal des accès
# ----------------------------------------------------------------------------
def _lire_uuid(texte):
    try:
        return uuid.UUID(texte) if texte else None
    except ValueError:
        return None


def _lire_date(texte):
    try:
        return datetime.strptime(texte, "%Y-%m-%d").date() if texte else None
    except ValueError:
        return None


@exige_console()
def journal(request):
    """La chronologie des regards portés chez les commerçants.

    L'administrateur du marché la lit en entier, y compris les lignes de ses collègues et du
    superadministrateur : c'est de la transparence, pas de la surveillance, et son groupe porte
    déjà `core.view_accesplateforme`. Un journal que seuls ses auteurs peuvent relire ne protège
    personne.
    """
    qs = AccesPlateforme.objects.select_related("utilisateur")
    filtres = {
        "utilisateur": request.GET.get("utilisateur", ""),
        "boutique": request.GET.get("boutique", ""),
        "ecran": request.GET.get("ecran", ""),
        "du": _lire_date(request.GET.get("du")),
        "au": _lire_date(request.GET.get("au")),
    }
    # Un identifiant illisible dans l'adresse (lien tronqué, recopié à la main) donne une liste
    # vide, pas une erreur 500 : c'est un filtre, pas une requête qu'on a le droit de rater.
    utilisateur_id = _lire_uuid(filtres["utilisateur"])
    boutique_id = _lire_uuid(filtres["boutique"])
    if filtres["utilisateur"]:
        qs = qs.filter(utilisateur_id=utilisateur_id) if utilisateur_id else qs.none()
    if filtres["boutique"] == "ensemble":
        qs = qs.filter(boutique_id__isnull=True)
    elif filtres["boutique"]:
        qs = qs.filter(boutique_id=boutique_id) if boutique_id else qs.none()
    if filtres["ecran"]:
        qs = qs.filter(ecran=filtres["ecran"])
    if filtres["du"]:
        qs = qs.filter(horodatage__gte=timezone.make_aware(datetime.combine(filtres["du"], time.min)))
    if filtres["au"]:
        qs = qs.filter(horodatage__lt=timezone.make_aware(datetime.combine(filtres["au"] + timedelta(days=1), time.min)))

    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    lignes = lignes_de_journal(page.object_list)
    # Regroupées par jour : c'est ainsi qu'on relit un journal — « qu'est-ce qui s'est passé
    # mardi ? » — et une date répétée sur chaque ligne noie l'heure, qui est l'information.
    jours = []
    for ligne in lignes:
        jour = timezone.localtime(ligne["horodatage"]).date()
        if not jours or jours[-1]["jour"] != jour:
            jours.append({"jour": jour, "libelle": date_longue(jour).capitalize(), "lignes": []})
        jours[-1]["lignes"].append(ligne)

    auteurs = Utilisateur.objects.filter(
        pk__in=AccesPlateforme.objects.values("utilisateur_id")
    ).order_by("nom_complet")
    boutiques_vues = Boutique.objects.filter(
        pk__in=AccesPlateforme.objects.filter(boutique_id__isnull=False).values("boutique_id")
    ).order_by("enseigne")
    ecrans = [
        (e, libelle_ecran(e))
        for e in AccesPlateforme.objects.order_by("ecran").values_list("ecran", flat=True).distinct()
    ]
    parametres = request.GET.copy()
    parametres.pop("page", None)
    return render(
        request,
        "plateforme/journal.html",
        contexte_console(
            request,
            page="plateforme:journal",
            page_obj=page,
            jours=jours,
            filtres=filtres,
            nb_filtres=sum(1 for v in filtres.values() if v),
            auteurs=auteurs,
            boutiques_vues=boutiques_vues,
            ecrans=ecrans,
            parametres=parametres.urlencode(),
            total=AccesPlateforme.objects.count(),
        ),
    )


# ----------------------------------------------------------------------------
# Santé technique
# ----------------------------------------------------------------------------
def etat_rls() -> dict:
    """L'état réel de la barrière 3, ou « non vérifiable » — jamais une exception à l'écran.

    Même lecture que `manage.py verifier_rls`, rendue plutôt qu'imprimée.
    """
    from apps.core.rls import (
        TABLES_SCOPEES,
        etat_des_tables,
        role_contourne_la_securite,
        tables_des_modeles_scopes,
    )

    attendues = set(tables_des_modeles_scopes())
    resultat = {
        "verifiable": False,
        "moteur": connection.vendor,
        "attendues": len(attendues | set(TABLES_SCOPEES)),
        "oubliees": sorted(attendues - set(TABLES_SCOPEES)),
        "defaillantes": [],
        "contourne": None,
        "protegees": 0,
    }
    if connection.vendor != "postgresql":
        resultat["raison"] = "La base n'est pas PostgreSQL : la barrière 3 n'existe pas ici."
        return resultat
    try:
        resultat["contourne"] = role_contourne_la_securite(connection)
        etat = etat_des_tables(connection)
    except Exception:  # noqa: BLE001 — catalogue illisible : on le dit, on ne plante pas
        resultat["raison"] = "Le catalogue PostgreSQL n'a pas pu être lu avec ce rôle."
        return resultat
    for table in sorted(attendues | set(TABLES_SCOPEES)):
        ligne = etat.get(table)
        if ligne is None:
            resultat["defaillantes"].append((table, "table absente"))
        elif not ligne["activee"]:
            resultat["defaillantes"].append((table, "RLS désactivée"))
        elif not ligne["forcee"]:
            resultat["defaillantes"].append((table, "FORCE manquant"))
        elif not ligne["politique"]:
            resultat["defaillantes"].append((table, "politique absente"))
        else:
            resultat["protegees"] += 1
    resultat["verifiable"] = True
    return resultat


def migrations_en_attente() -> dict:
    from django.db.migrations.executor import MigrationExecutor

    try:
        executeur = MigrationExecutor(connection)
        plan = executeur.migration_plan(executeur.loader.graph.leaf_nodes())
    except Exception:  # noqa: BLE001
        return {"verifiable": False, "liste": []}
    return {"verifiable": True, "liste": [f"{m.app_label}.{m.name}" for m, _ in plan]}


def reglages_sensibles() -> list[dict]:
    """Les réglages qui changent la sécurité d'un déploiement — valeurs booléennes ou numériques
    seulement. Aucune chaîne libre n'est affichée : c'est là que vivent les secrets.

    `bon` vaut `True`, `False`, ou `None` pour « sans objet » : en développement, un
    `SECURE_SSL_REDIRECT` éteint n'est pas une faute, et une coche verte à côté de « non » y
    ferait croire qu'il est allumé.
    """
    debug = bool(settings.DEBUG)

    def https(nom, aide):
        actif = bool(getattr(settings, nom, False))
        return {"nom": nom, "valeur": "oui" if actif else "non",
                "bon": True if actif else (None if debug else False), "aide": aide}

    hsts = int(getattr(settings, "SECURE_HSTS_SECONDS", 0) or 0)
    return [
        {"nom": "DEBUG", "valeur": "activé" if debug else "désactivé", "bon": not debug,
         "aide": "Activé, une erreur affiche le code et les réglages à qui la provoque."},
        https("SECURE_SSL_REDIRECT", "Renvoie tout accès en clair vers HTTPS."),
        https("SESSION_COOKIE_SECURE", "Le cookie de session ne circule qu'en HTTPS."),
        https("CSRF_COOKIE_SECURE", "Même règle pour le jeton anti-falsification."),
        {"nom": "SECURE_HSTS_SECONDS", "valeur": f"{hsts} s",
         "bon": True if hsts > 0 else (None if debug else False),
         "aide": "Le navigateur retient d'imposer HTTPS pendant cette durée."},
        {"nom": "ALLOWED_HOSTS", "valeur": f"{len(settings.ALLOWED_HOSTS)} hôte(s)",
         "bon": True if settings.ALLOWED_HOSTS else (None if debug else False),
         "aide": "Nombre de noms d'hôte acceptés — les noms eux-mêmes ne sont pas affichés."},
        {"nom": "SANS_SERVEUR", "valeur": "oui" if getattr(settings, "SANS_SERVEUR", False) else "non",
         "bon": None, "aide": "Fonctions sans serveur : connexions non persistantes, cache en base."},
        {"nom": "CONN_MAX_AGE", "valeur": f"{settings.DATABASES['default'].get('CONN_MAX_AGE', 0)} s",
         "bon": None, "aide": "Durée de vie d'une connexion à la base."},
    ]


@exige_console(CONSOLE_TECHNIQUE)
def technique(request):
    """Réservé au superadministrateur : c'est le recours technique, pas l'écran du marché.

    Rien de ce qui s'affiche ici n'est un secret — ni adresse de base, ni clé, ni jeton. Un
    écran d'administration finit toujours en capture d'écran dans une discussion ; il doit
    pouvoir y finir sans dommage.
    """
    commit = os.environ.get("VERCEL_GIT_COMMIT_SHA", "")
    rls = etat_rls()
    migrations = migrations_en_attente()
    reglages = reglages_sensibles()
    volumes = [
        ("Boutiques", Boutique.objects.count()),
        ("Utilisateurs", Utilisateur.objects.count()),
        ("Baux", Bail.objects.count()),
        ("Factures de loyer", FactureLoyer.objects.count()),
        ("Emplacements premium", EmplacementPremium.objects.count()),
        ("Lignes du journal des accès", AccesPlateforme.objects.count()),
    ]
    alertes = (
        len(rls["defaillantes"])
        + len(rls["oubliees"])
        + (1 if rls["contourne"] else 0)
        + len(migrations["liste"])
        + sum(1 for r in reglages if r["bon"] is False)
    )
    return render(
        request,
        "plateforme/technique.html",
        contexte_console(
            request,
            page="plateforme:technique",
            rls=rls,
            migrations=migrations,
            reglages=reglages,
            volumes=volumes,
            alertes=alertes,
            deploiement={
                "commit": commit[:7],
                "branche": os.environ.get("VERCEL_GIT_COMMIT_REF", ""),
                "environnement": os.environ.get("VERCEL_ENV", ""),
            },
            versions={
                "django": django.get_version(),
                "python": platform.python_version(),
                "moteur": connection.vendor,
            },
        ),
    )
