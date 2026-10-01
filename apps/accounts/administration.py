"""Les trois niveaux d'administration, et ce qui les sépare réellement.

Ils étaient confondus en un seul dans le premier jet de l'ADR-012, et la confusion coûtait
cher : elle faisait du geste quotidien d'exploitation un acte de superutilisateur.

+---------------------------+------------------------------+--------------------------------+
| Qui                       | Comment il est marqué        | Ce qu'il voit                  |
+===========================+==============================+================================+
| **Superadministrateur**   | `is_superuser` + `is_staff`  | Tout, sans exception, par      |
|                           |                              | construction Django.           |
+---------------------------+------------------------------+--------------------------------+
| **Administrateur du       | `is_staff` + `RolePlateforme`| Ce que le groupe ci-dessous    |
| marché**                  | `ADMIN_MARCHE`               | ouvre. Ni comptabilité, ni     |
|                           | **sans** `is_superuser`      | stock, ni cahier de crédit.    |
+---------------------------+------------------------------+--------------------------------+
| **Gérant d'une boutique** | `Appartenance` de rôle       | Sa boutique, entièrement.      |
|                           | `GERANT`                     | Aucune autre.                  |
+---------------------------+------------------------------+--------------------------------+

Pourquoi un groupe de permissions, et pas un drapeau
----------------------------------------------------

Un compte `is_staff` **sans** `is_superuser` ne voit **rien** dans `/admin/` : Django exige une
permission par modèle. C'est précisément le levier qui rend la distinction opérante au lieu de
déclarative. Le superadministrateur voit tout parce que Django court-circuite le contrôle pour
lui ; l'administrateur du marché voit ce que cette liste nomme, et rien de plus.

D'où une liste **écrite**, relue, et vérifiée par un test. Ce n'est pas une commodité
d'installation : c'est la frontière.

Le principe qui a décidé chaque ligne
-------------------------------------

« L'administrateur administre les administrateurs des boutiques » — il travaille donc sur les
**comptes**, les **rattachements** et les **contrats**. Il ne travaille jamais sur ce que les
boutiques vendent, doivent ou gagnent. Aucune permission sur `accounting`, `inventory`, `pos`
(le cahier de crédit y vit), `catalog` ni `orders` : non par oubli, mais parce qu'un exploitant
qui est aussi commerçant sur sa place ne doit pas pouvoir lire les chiffres de ses concurrents
par la porte de service.

Et la règle de suppression du projet s'applique ici comme partout : **on supprime ce qui n'a pas
d'histoire, on retire ce qui en a une.** Un `Appartenance` révolue se désactive (`actif`), elle ne
s'efface pas — sinon on perd qui tenait la caisse le jour d'un écart. Le droit de suppression
n'est donc accordé à presque rien.
"""

from __future__ import annotations

NOM_GROUPE = "Administration du marché"

# (app_label, model, [actions]) — `view`, `add`, `change`, `delete`.
#
# Chaque ligne porte la raison de ce qu'elle accorde **et** de ce qu'elle refuse. Une liste de
# permissions sans justification devient, au premier besoin pressé, une liste qui contient tout.
PERMISSIONS = [
    # --- Les comptes et leurs rattachements : le cœur du métier de l'administrateur ---------
    # Pas de `delete` : un compte porte des ventes, des tickets, des écritures. On le désactive
    # (`is_active`), on ne l'efface pas.
    ("accounts", "utilisateur", ["view", "add", "change"]),
    # Pas de `delete` non plus : une appartenance révolue dit qui tenait la caisse le jour d'un
    # écart de fonds. Elle se retire par `actif`.
    ("accounts", "appartenance", ["view", "add", "change"]),
    # Lecture seule : `Role.permissions` est un **miroir** de `apps/accounts/permissions.py`,
    # écrit par `initialiser_referentiels` et jamais lu pour décider. Le rendre modifiable ici
    # laisserait croire qu'on peut ouvrir la marge à un caissier depuis une table.
    ("accounts", "role", ["view"]),
    # Qui exploite le marché. Modifiable, parce que c'est le geste de confier ou de retirer
    # l'exploitation — et chaque changement est visible dans une table faite pour être relue.
    ("accounts", "roleplateforme", ["view", "add", "change"]),
    # Vérification d'identité des marchands : c'est lui qui valide, donc il change l'état.
    ("accounts", "dossierkyc", ["view", "change"]),
    # --- Les boutiques comme locataires, pas comme commerces --------------------------------
    # Il valide une candidature, corrige une raison sociale, suspend pour loyer impayé. Il ne
    # supprime pas une boutique : tout ce qu'elle a vendu lui est rattaché.
    ("marketplace", "boutique", ["view", "add", "change"]),
    ("marketplace", "bail", ["view", "add", "change"]),
    ("marketplace", "etatdeslieux", ["view", "add", "change"]),
    ("marketplace", "factureloyer", ["view", "change"]),
    # Le taux d'un rayon gouverne la rentabilité de toutes ses boutiques. Modifiable, mais le
    # garde-fou du juge et partie vit dans `apps/marketplace/gouvernance.py` : une permission
    # Django n'a aucun moyen de savoir que cette personne vend dans ce rayon.
    ("marketplace", "rayon", ["view", "change"]),
    # Lecture seule : les trois offres sont la grille tarifaire du document 03. Les changer est
    # une décision d'entreprise, pas un geste d'administration courante.
    ("marketplace", "typeemplacement", ["view"]),
    # Le retail media, première recette de la plateforme. La contrainte de tarif non nul est en
    # base : même une attribution interne s'enregistre à son prix.
    ("marketplace", "emplacementpremium", ["view", "add", "change"]),
    # --- Le réseau d'apporteurs -------------------------------------------------------------
    ("affiliation", "apporteur", ["view", "add", "change"]),
    ("affiliation", "revendeur", ["view", "add", "change"]),
    # Les commissions sont **calculées**, pas saisies : les ouvrir en écriture laisserait
    # corriger à la main ce que le moteur a établi, et personne ne saurait plus lequel a raison.
    ("affiliation", "commission", ["view"]),
    ("affiliation", "attribution", ["view"]),
    # Un signalement de fraude s'instruit : on change son état, on ne le fabrique pas.
    ("affiliation", "signalfraude", ["view", "change"]),
    # --- Le journal des accès ---------------------------------------------------------------
    # Lecture seule, et la base le garantit aussi (ADR-012) : le journal est en ajout seul, y
    # compris contre celui qui voudrait effacer sa propre trace.
    ("core", "accesplateforme", ["view"]),
]

# Ce qui n'est **pas** dans la liste, écrit noir sur blanc pour qu'un ajout futur soit un choix
# et non une distraction. Un test vérifie que ces applications restent absentes.
APPLICATIONS_INTERDITES = frozenset(
    {
        "accounting",  # la comptabilité d'un commerçant ne regarde pas son bailleur
        "inventory",  # ni son stock
        "pos",  # ni sa caisse, ni le cahier de crédit de ses clients
        "catalog",  # ni son assortiment, qui est son fonds de commerce
        "orders",  # les litiges passent par `plateforme.litiges`, avec motif et trace
        "payments",
    }
)


def codes_de_permission() -> list[str]:
    """Les permissions sous la forme `app_label.codename`, dans l'ordre de la liste."""
    return [
        f"{app}.{action}_{modele}" for app, modele, actions in PERMISSIONS for action in actions
    ]


def synchroniser_le_groupe():
    """Crée ou met à jour le groupe, et renvoie `(groupe, manquantes)`.

    Les permissions absentes de la base sont **renvoyées plutôt que tues** : un nom de modèle
    mal orthographié ici produirait sinon un groupe silencieusement incomplet, c'est-à-dire un
    administrateur qui ne peut pas faire son travail sans que rien ne l'explique.
    """
    from django.contrib.auth.models import Group, Permission

    groupe, _ = Group.objects.get_or_create(name=NOM_GROUPE)

    trouvees, manquantes = [], []
    for app, modele, actions in PERMISSIONS:
        for action in actions:
            permission = Permission.objects.filter(
                content_type__app_label=app, codename=f"{action}_{modele}"
            ).first()
            if permission is None:
                manquantes.append(f"{app}.{action}_{modele}")
            else:
                trouvees.append(permission)

    groupe.permissions.set(trouvees)
    return groupe, manquantes


# ----------------------------------------------------------------------------
# Poser et retirer un administrateur du marché
# ----------------------------------------------------------------------------
# Écrit ici, et non dans la commande ou dans la console, parce que les deux le font : la commande
# `preparer_administrateur` à chaque mise en ligne, la console quand le superadministrateur nomme
# quelqu'un. Deux copies de « ce qu'est un administrateur du marché » divergeraient au premier
# ajout — et la divergence porterait précisément sur `is_superuser`, la marque qu'il ne faut pas
# poser.
#
# Les rôles qu'on peut confier ainsi. `CABINET` est de portée plateforme mais n'est pas un métier
# d'exploitation : il se pose par le partenariat comptable, pas par la console.
LIBELLES_ROLES_ADMINISTRATION = {
    "ADMIN_MARCHE": "Gestionnaire du marché",
    "RESP_RAYON": "Responsable de rayon",
}


class PoseAdministrateur:
    """Ce que la pose a réellement changé — pour que l'appelant le dise, pas le devine."""

    def __init__(self, role_plateforme, *, nouveau, superuser_retire, staff_pose, role_cree):
        self.role_plateforme = role_plateforme
        self.nouveau = nouveau
        self.superuser_retire = superuser_retire
        self.staff_pose = staff_pose
        self.role_cree = role_cree


def poser_administrateur_du_marche(compte, *, code_role="ADMIN_MARCHE", motif, groupe=None):
    """Fait de `compte` un administrateur du marché. Idempotent.

    Trois marques, et l'absence d'une quatrième :

    * `is_staff`, sans quoi `/admin/` est fermé ;
    * le groupe de permissions, sans quoi `/admin/` est **vide** — c'est ce qui rend la
      distinction opérante plutôt que déclarative ;
    * le `RolePlateforme`, qui porte les droits d'exploitation de l'ADR-012 ;
    * et **pas** `is_superuser`, qui rendrait les trois décoratifs. S'il est posé, il est retiré,
      et le résultat le dit : c'est exactement la confusion que cette fonction répare.

    La console refuse en amont un compte superadministrateur (lui retirer ce drapeau depuis un
    écran pourrait laisser l'application sans recours) ; la commande, elle, l'assume.
    """
    from apps.accounts.models import Role, RolePlateforme

    if code_role not in LIBELLES_ROLES_ADMINISTRATION:
        raise ValueError(f"« {code_role} » n'est pas un rôle d'administration du marché.")
    if groupe is None:
        groupe, _ = synchroniser_le_groupe()

    champs = []
    staff_pose = not compte.is_staff
    if staff_pose:
        compte.is_staff = True
        champs.append("is_staff")
    superuser_retire = compte.is_superuser
    if superuser_retire:
        compte.is_superuser = False
        champs.append("is_superuser")
    if champs:
        compte.save(update_fields=champs)

    # Le groupe ouvre dans `/admin/` les comptes, les baux et le réseau d'apporteurs : c'est le
    # périmètre du gestionnaire du marché, pas celui d'un responsable de rayon, dont les deux
    # droits (commissions, emplacements) s'exercent dans la console. Lui donner le groupe
    # élargirait son rôle par la porte de service.
    if code_role == "ADMIN_MARCHE":
        compte.groups.add(groupe)

    role, role_cree = Role.objects.get_or_create(
        code=code_role,
        defaults={"libelle": LIBELLES_ROLES_ADMINISTRATION[code_role], "portee": Role.PLATEFORME},
    )
    role_plateforme, nouveau = RolePlateforme.objects.get_or_create(
        utilisateur=compte,
        role=role,
        actif=True,
        defaults={"motif": (motif or "").strip()[:300]},
    )
    return PoseAdministrateur(
        role_plateforme,
        nouveau=nouveau,
        superuser_retire=superuser_retire,
        staff_pose=staff_pose,
        role_cree=role_cree,
    )


def retirer_role_plateforme(role_plateforme, *, le=None) -> bool:
    """Retire un rôle de plateforme — **sans rien supprimer** — et renvoie `True` si le compte a
    perdu du même geste son accès à l'administration.

    On retire ce qui a une histoire : la ligne reste, `actif` passe à faux et `jusqu_a` date la
    fin. Le journal des accès nomme ce compte ; effacer son rôle rendrait ces lignes
    inexplicables.

    `is_staff` et le groupe ne partent que s'il ne reste **aucun** rôle actif : quelqu'un qui
    était gestionnaire et responsable de rayon garde sa porte s'il perd l'un des deux. Et jamais
    sur un superadministrateur, dont `is_staff` n'a pas été posé par un rôle et ne doit pas
    tomber avec lui.
    """
    from django.contrib.auth.models import Group
    from django.utils import timezone

    if role_plateforme.actif:
        role_plateforme.actif = False
        role_plateforme.jusqu_a = le or timezone.localdate()
        role_plateforme.save(update_fields=["actif", "jusqu_a"])

    compte = role_plateforme.utilisateur
    if compte.is_superuser:
        return False
    if not compte.roles_plateforme.filter(actif=True, role__code="ADMIN_MARCHE").exists():
        # Plus de gestionnaire du marché : le groupe part, même s'il reste un rôle de rayon.
        groupe = Group.objects.filter(name=NOM_GROUPE).first()
        if groupe is not None:
            compte.groups.remove(groupe)
    if compte.roles_plateforme.filter(actif=True).exists():
        return False

    groupe = Group.objects.filter(name=NOM_GROUPE).first()
    if groupe is not None:
        compte.groups.remove(groupe)
    if compte.is_staff:
        compte.is_staff = False
        compte.save(update_fields=["is_staff"])
    return True
