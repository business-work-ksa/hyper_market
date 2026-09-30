"""Le marché, ses rayons et ses emplacements.

La `Boutique` est le **tenant** : toute donnée métier lui appartient. Le `Bail` matérialise la
métaphore centrale du produit — on ne vend pas un abonnement logiciel, on loue un emplacement,
avec loyer, dépôt de garantie, préavis et résiliation (docs/01, §4.1).
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel, TenantScopedModel
from apps.core.uuid7 import uuid7
from apps.marketplace.cemac import LIBELLES_OPERATEURS
from apps.marketplace.confiance import CHOIX_PALIERS
from apps.marketplace.metiers import METIER_DEFAUT, metier_de


class Rayon(models.Model):
    """Rayon du marché. C'est lui qui porte le taux de commission (docs/06, §4.3)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    code = models.SlugField(max_length=48, unique=True)
    libelle = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="sous_rayons"
    )
    taux_commission = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("0.30"))],
        help_text="Part du montant HT revenant à la plateforme (0.05 = 5 %).",
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rayons_geres",
        help_text="Responsable de rayon (category manager) côté plateforme.",
    )
    ouvert = models.BooleanField(
        default=True,
        help_text="Un rayon fermé n'accepte plus de nouvelles boutiques (arbitrage A8).",
    )
    ordre = models.PositiveSmallIntegerField(default=100)

    class Meta:
        verbose_name = "rayon"
        ordering = ["ordre", "libelle"]

    def __str__(self):
        return self.libelle


class TypeEmplacement(models.Model):
    """Offre commerciale : Étal, Boutique, Grande surface (grille du docs/03, §1.1)."""

    ETAL = "ETAL"
    BOUTIQUE = "BOUTIQUE"
    GRANDE_SURFACE = "GRANDE_SURFACE"

    code = models.CharField(max_length=32, primary_key=True)
    libelle = models.CharField(max_length=64)
    loyer_mensuel = models.DecimalField(max_digits=12, decimal_places=2)
    taux_commission_defaut = models.DecimalField(max_digits=5, decimal_places=4)
    quota_utilisateurs = models.PositiveSmallIntegerField(default=1)
    quota_depots = models.PositiveSmallIntegerField(default=1)
    modules_inclus = models.JSONField(
        default=list, blank=True, help_text='Ex. ["catalogue", "stock", "caisse", "comptabilite"]'
    )
    ordre = models.PositiveSmallIntegerField(default=100)

    class Meta:
        verbose_name = "type d'emplacement"
        verbose_name_plural = "types d'emplacement"
        ordering = ["ordre"]

    def __str__(self):
        return f"{self.libelle} — {self.loyer_mensuel:,.0f} FCFA/mois".replace(",", " ")

    def module_inclus(self, code_module: str) -> bool:
        return code_module in (self.modules_inclus or [])


class Boutique(BaseModel):
    """Le tenant. Toute donnée métier du produit lui est rattachée."""

    CANDIDATURE = "candidature"
    ACTIVE = "active"
    SUSPENDUE = "suspendue"
    RESILIEE = "resiliee"
    ETATS = [
        (CANDIDATURE, "Candidature"),
        (ACTIVE, "Active"),
        (SUSPENDUE, "Suspendue"),
        (RESILIEE, "Résiliée"),
    ]

    # L'impôt libératoire et l'ancien régime simplifié ont été fusionnés dans l'IGS
    # (loi n° 2024/020, structurée par la loi de finances 2026) — voir docs/07, §5.
    IGS = "igs"
    REEL_SIMPLIFIE = "reel_simplifie"
    REEL_NORMAL = "reel_normal"
    REGIMES = [
        (IGS, "IGS — impôt général synthétique (CA ≤ 50 M)"),
        (REEL_SIMPLIFIE, "Réel simplifié (CA 50-100 M)"),
        (REEL_NORMAL, "Réel normal (CA > 100 M)"),
    ]

    raison_sociale = models.CharField(max_length=180)
    enseigne = models.CharField(max_length=120, help_text="Nom commercial affiché aux acheteurs.")
    slug = models.SlugField(max_length=140, unique=True)
    metier = models.CharField(
        max_length=32,
        default=METIER_DEFAUT,
        db_index=True,
        verbose_name="métier",
        help_text=(
            "Ce que la boutique vend. Détermine le vocabulaire des écrans, les "
            "valeurs par défaut et les fonctions activées (apps/marketplace/metiers.py)."
        ),
    )
    rccm = models.CharField(max_length=64, blank=True, verbose_name="RCCM")
    niu = models.CharField(max_length=32, blank=True, verbose_name="NIU")
    regime_fiscal = models.CharField(max_length=24, choices=REGIMES, default=REEL_SIMPLIFIE)
    rayon_principal = models.ForeignKey(
        Rayon, on_delete=models.PROTECT, related_name="boutiques", null=True, blank=True
    )
    telephone = models.CharField(max_length=16, blank=True)
    ville = models.CharField(max_length=80, default="Douala")
    pays = models.CharField(max_length=2, default="CM")
    devise = models.CharField(max_length=3, default="XAF")
    etat = models.CharField(max_length=16, choices=ETATS, default=CANDIDATURE, db_index=True)
    # Ce qu'on confie à la boutique, selon ce qu'elle a prouvé (`apps/marketplace/confiance.py`).
    # Calculé par `apps/confiance/`, lu par les paiements ; jamais saisi à la main.
    palier_confiance = models.PositiveSmallIntegerField(default=0, choices=CHOIX_PALIERS)
    palier_evalue_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "boutique"
        ordering = ["enseigne"]

    def __str__(self):
        return self.enseigne

    def clean(self):
        """Le verrou d'activation, pour l'administration Django (docs/08, §5.3).

        La console passe par `apps/confiance/verification.exiger_activable` ; l'administration
        technique passe par ici, et doit dire la même chose : une boutique ne **devient** active
        que vérifiée. Seule la transition est verrouillée — une boutique déjà active dont on
        corrige l'enseigne n'est pas coupée pour autant, elle paraît dans la file « à
        régulariser » de la console.
        """
        super().clean()
        if self.etat != self.ACTIVE:
            return
        avant = Boutique.objects.filter(pk=self.pk).values_list("etat", flat=True).first()
        if avant == self.ACTIVE:
            return
        from apps.confiance.verification import manques_pour_activer

        manques = manques_pour_activer(self)
        if manques:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                {"etat": ["Vérification incomplète : la boutique ne peut pas devenir active."] + manques}
            )

    @property
    def metier_choisi(self):
        """Le métier, lu depuis le référentiel de code — jamais depuis la base.

        `metier` ne stocke qu'un code. Tout ce qui en découle — vocabulaire,
        valeurs par défaut, fonctions actives — se lit dans
        `apps/marketplace/metiers.py`, pour la même raison que la matrice des
        droits : ce sont des règles, pas des données.
        """
        return metier_de(self.metier)

    @property
    def bail_actif(self):
        return self.baux.filter(etat=Bail.ACTIF).order_by("-debut").first()

    @property
    def peut_vendre(self) -> bool:
        """Une boutique suspendue conserve son back-office mais disparaît de la vitrine.

        C'est un choix produit : couper la gestion d'un marchand en retard de loyer reviendrait à
        lui couper l'accès à sa propre comptabilité (docs/05, M02).
        """
        return self.etat == self.ACTIVE and self.bail_actif is not None


class Bail(BaseModel):
    """Contrat de location d'un emplacement."""

    BROUILLON = "brouillon"
    ACTIF = "actif"
    RESILIE = "resilie"
    ETATS = [(BROUILLON, "Brouillon"), (ACTIF, "Actif"), (RESILIE, "Résilié")]

    boutique = models.ForeignKey(Boutique, on_delete=models.PROTECT, related_name="baux")
    type_emplacement = models.ForeignKey(TypeEmplacement, on_delete=models.PROTECT)
    debut = models.DateField(default=timezone.localdate)
    fin = models.DateField(null=True, blank=True)
    loyer_mensuel = models.DecimalField(max_digits=12, decimal_places=2)
    depot_garantie = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    taux_commission = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        help_text="Négocié au contrat ; prime sur le taux du rayon.",
    )
    motif_derogation_commission = models.CharField(
        max_length=300,
        blank=True,
        help_text=(
            "Obligatoire dès que le taux négocié s'écarte de celui de l'offre. "
            "Une faveur commerciale est légitime ; une faveur sans raison écrite ne l'est pas."
        ),
    )
    preavis_jours = models.PositiveSmallIntegerField(default=30)
    etat = models.CharField(max_length=16, choices=ETATS, default=BROUILLON, db_index=True)
    motif_resiliation = models.TextField(blank=True)

    class Meta:
        verbose_name = "bail"
        verbose_name_plural = "baux"
        ordering = ["-debut"]

    def __str__(self):
        return f"Bail {self.boutique} · {self.type_emplacement.libelle}"

    def clean(self):
        """Une dérogation de commission doit dire pourquoi (ADR-012, garde-fou 2).

        L'exploitant de la place de marché y vend aussi. Accorder un taux plus doux à
        une boutique — la sienne ou celle d'un proche — reste possible : c'est une
        décision commerciale, et la lui interdire serait naïf. Ce qui est refusé, c'est
        de le faire sans l'écrire, parce qu'alors personne ne peut relire la liste des
        faveurs accordées.

        Le contrôle est ici et non en base : comparer deux tables dans une contrainte
        `CHECK` n'est pas possible, et un déclencheur pour cela serait plus coûteux à
        maintenir que la règle ne vaut.
        """
        from django.core.exceptions import ValidationError

        if self.taux_commission is None or self.type_emplacement_id is None:
            return
        # La référence est le taux de l'**offre**, que porte le type d'emplacement du bail —
        # pas la boutique. Une boutique n'a pas d'offre en propre : elle en loue une, et c'est
        # le bail qui matérialise ce choix. (Premier jet de ce contrôle : `boutique.offre`,
        # qui n'existe pas. Le test l'a dit avant la production.)
        reference = self.type_emplacement.taux_commission_defaut
        if reference is None:
            return
        if self.taux_commission != reference and not self.motif_derogation_commission.strip():
            raise ValidationError(
                {
                    "motif_derogation_commission": (
                        f"Le taux négocié ({self.taux_commission:.2%}) s'écarte de celui de "
                        f"l'offre ({reference:.2%}). Dites pourquoi : la dérogation est "
                        "légitime, son absence de motif ne l'est pas."
                    )
                }
            )


class FactureLoyer(BaseModel):
    """Facture mensuelle de loyer. L'impayé déclenche la suspension (docs/08, §8)."""

    EMISE = "emise"
    PAYEE = "payee"
    IMPAYEE = "impayee"
    ANNULEE = "annulee"
    ETATS = [(EMISE, "Émise"), (PAYEE, "Payée"), (IMPAYEE, "Impayée"), (ANNULEE, "Annulée")]

    bail = models.ForeignKey(Bail, on_delete=models.PROTECT, related_name="factures")
    periode = models.DateField(help_text="Premier jour du mois facturé.")
    montant_ht = models.DecimalField(max_digits=12, decimal_places=2)
    taux_tva = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.1925"))
    echeance = models.DateField()
    etat = models.CharField(max_length=16, choices=ETATS, default=EMISE, db_index=True)
    paye_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "facture de loyer"
        verbose_name_plural = "factures de loyer"
        ordering = ["-periode"]
        constraints = [
            models.UniqueConstraint(fields=["bail", "periode"], name="loyer_unique_par_periode")
        ]

    def __str__(self):
        return f"Loyer {self.periode:%m/%Y} · {self.bail.boutique}"

    @property
    def montant_tva(self) -> Decimal:
        return (self.montant_ht * self.taux_tva).quantize(Decimal("0.01"))

    @property
    def montant_ttc(self) -> Decimal:
        return self.montant_ht + self.montant_tva


class EtatDesLieux(BaseModel):
    """Audit d'entrée ou de sortie d'un emplacement.

    À l'entrée : reprise du stock existant et des soldes comptables de départ. À la sortie :
    constat contradictoire avant restitution du dépôt de garantie.
    """

    ENTREE = "entree"
    SORTIE = "sortie"
    TYPES = [(ENTREE, "Entrée"), (SORTIE, "Sortie")]

    bail = models.ForeignKey(Bail, on_delete=models.CASCADE, related_name="etats_des_lieux")
    type = models.CharField(max_length=8, choices=TYPES)
    stock_initial = models.JSONField(default=list, blank=True)
    comptes_initiaux = models.JSONField(default=list, blank=True)
    constate_le = models.DateTimeField(default=timezone.now)
    commentaire = models.TextField(blank=True)

    class Meta:
        verbose_name = "état des lieux"
        verbose_name_plural = "états des lieux"

    def __str__(self):
        return f"État des lieux {self.get_type_display().lower()} · {self.bail.boutique}"


class EmplacementPremium(BaseModel):
    """Emplacement de mise en avant loué à la semaine (tête de gondole, bandeau de rayon).

    Première recette de retail media, avant le module publicitaire complet du lot 5.
    """

    TETE_DE_GONDOLE = "tete_de_gondole"
    BANDEAU_RAYON = "bandeau_rayon"
    ACCUEIL = "accueil"
    TYPES = [
        (TETE_DE_GONDOLE, "Tête de gondole"),
        (BANDEAU_RAYON, "Bandeau de rayon"),
        (ACCUEIL, "Page d'accueil"),
    ]

    rayon = models.ForeignKey(
        Rayon, null=True, blank=True, on_delete=models.CASCADE, related_name="emplacements_premium"
    )
    type = models.CharField(max_length=24, choices=TYPES)
    debut = models.DateField()
    fin = models.DateField()
    tarif = models.DecimalField(max_digits=12, decimal_places=2)
    boutique_occupante = models.ForeignKey(
        Boutique, null=True, blank=True, on_delete=models.SET_NULL, related_name="emplacements_premium"
    )

    class Meta:
        verbose_name = "emplacement premium"
        verbose_name_plural = "emplacements premium"
        ordering = ["-debut"]
        constraints = [
            # Garde-fou 1 de l'ADR-012. L'exploitant de la place de marché y vend aussi :
            # rien ne l'empêche de s'attribuer la meilleure tête de gondole, et c'est
            # acceptable — il en est le propriétaire. Ce qui ne l'est pas, c'est de se
            # l'attribuer **à zéro franc**, parce qu'alors le compte de résultat de la
            # plateforme ment sur sa rentabilité réelle : il montre un emplacement occupé
            # qui ne rapporte rien, et on en conclut que le retail media ne marche pas.
            #
            # La contrainte est en base et non en Python parce qu'elle porte sur une seule
            # colonne : c'est le cas où la base sait le faire, donc c'est elle qui le fait.
            models.CheckConstraint(
                condition=models.Q(tarif__gt=0),
                name="emplacement_premium_tarif_non_nul",
            )
        ]

    def __str__(self):
        return f"{self.get_type_display()} {self.debut:%d/%m} → {self.fin:%d/%m}"


class IdentiteVisuelle(TenantScopedModel):
    """Logo et charte graphique d'une boutique.

    Le commerçant loue un emplacement ; il est chez lui. Que son back-office et
    sa vitrine portent ses couleurs n'est pas un ornement, c'est la différence
    entre un outil qu'on lui prête et un outil qui est le sien.

    **Les couleurs stockées ici sont déjà validées.** Elles ne sont jamais celles
    du logo telles quelles : `apps/marketplace/charte.py` leur applique les mêmes
    règles que le produit s'applique à lui-même — plancher de chroma, contraste
    minimal, variante sombre choisie et non inversée — et corrige ce qui doit
    l'être. La correction est conservée dans `motif_ajustement` pour être
    montrée au commerçant : une couleur changée sans explication passe pour un
    bogue.
    """

    logo = models.ImageField(upload_to="logos/%Y/%m/", blank=True)
    couleur_marque = models.CharField(max_length=7, default="#00806a")
    couleur_marque_sombre = models.CharField(max_length=7, default="#2fa98e")
    teinte = models.CharField(max_length=7, default="#e2f0ec")
    teinte_sombre = models.CharField(max_length=7, default="#14251f")
    police = models.CharField(max_length=24, default="systeme")
    motif_ajustement = models.CharField(
        max_length=255,
        blank=True,
        help_text="Ce que la validation a corrigé, et pourquoi. Montré au commerçant.",
    )

    class Meta:
        verbose_name = "identité visuelle"
        verbose_name_plural = "identités visuelles"
        constraints = [
            models.UniqueConstraint(fields=["boutique"], name="une_identite_par_boutique")
        ]

    def __str__(self):
        return f"Charte de {self.boutique}"

    @property
    def pile_police(self) -> str:
        from apps.marketplace.charte import PILES_POLICES

        return PILES_POLICES.get(self.police, PILES_POLICES["systeme"])

    @property
    def personnalisee(self) -> bool:
        from apps.marketplace.charte import PALETTE_PAR_DEFAUT

        return (
            self.couleur_marque != PALETTE_PAR_DEFAUT["marque"]
            or self.police != "systeme"
            or bool(self.logo)
        )


class LienMarketing(TenantScopedModel):
    """Lien court d'une boutique, à coller dans WhatsApp ou sur un flyer.

    Un commerçant ne partage pas `…/marche/boutique/quincaillerie-ateba/` : il
    partage quelque chose qui tient dans un message et qu'il peut dicter. D'où le
    code court, et d'où le compteur — sans lui, il n'a aucun moyen de savoir si
    le flyer a servi ou si c'est le groupe WhatsApp qui travaille.

    **Le compteur est un compteur de clics, pas de ventes.** Rattacher une vente
    à un lien demande de suivre l'acheteur du clic à la commande, ce qui est le
    travail de l'attribution d'affiliation (docs/06) et non celui-ci. Le libellé
    de l'écran le dit, faute de quoi un commerçant lirait « 40 » et comprendrait
    « 40 clients ».
    """

    libelle = models.CharField(
        max_length=120, help_text="À quoi sert ce lien : « Flyer marché », « Statut WhatsApp »…"
    )
    code = models.CharField(max_length=16, unique=True, db_index=True)
    article = models.ForeignKey(
        "catalog.Variante",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="liens",
        help_text="Vide : le lien ouvre la vitrine de la boutique.",
    )
    code_apporteur = models.CharField(
        max_length=12,
        blank=True,
        help_text="Facultatif : rattache les commandes issues de ce lien à un apporteur.",
    )
    clics = models.PositiveIntegerField(default=0)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "lien marketing"
        verbose_name_plural = "liens marketing"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.libelle} (/l/{self.code})"

    def chemin(self) -> str:
        return f"/l/{self.code}/"


class CompteVersement(BaseModel):
    """Où la plateforme verse à une boutique l'argent qui lui revient.

    C'est la cible préférée d'un détournement, y compris de l'intérieur : changer le numéro de
    versement la veille d'un gros versement suffit à tout emporter. D'où trois règles, appliquées
    par `apps/confiance/verification.py` :

    * le **titulaire** déclaré chez l'opérateur doit être la personne dont la pièce d'identité a
      été vérifiée — un compte Mobile Money est lui-même adossé à une identité ;
    * un compte n'est **utilisable** qu'après vérification par un administrateur *autre* que celui
      qui l'a déclaré, et après un **délai de carence** (`utilisable_le`) ;
    * on ne supprime jamais un compte : on le **retire**. Le journal des versements doit pouvoir
      dire, dans un an, où est parti chaque franc.
    """

    EN_ATTENTE = "en_attente"
    VERIFIE = "verifie"
    REJETE = "rejete"
    RETIRE = "retire"
    ETATS = [
        (EN_ATTENTE, "En attente de vérification"),
        (VERIFIE, "Vérifié"),
        (REJETE, "Rejeté"),
        (RETIRE, "Retiré"),
    ]

    boutique = models.ForeignKey(Boutique, on_delete=models.PROTECT, related_name="comptes_versement")
    pays = models.CharField(max_length=2, default="CM")
    operateur = models.CharField(max_length=24, choices=list(LIBELLES_OPERATEURS.items()))
    numero = models.CharField(
        max_length=34, help_text="Numéro Mobile Money au format international, ou IBAN / RIB."
    )
    titulaire = models.CharField(
        max_length=160, help_text="Nom du titulaire tel qu'il est enregistré chez l'opérateur."
    )
    etat = models.CharField(max_length=16, choices=ETATS, default=EN_ATTENTE, db_index=True)
    declare_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )
    verifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    verifie_le = models.DateTimeField(null=True, blank=True)
    utilisable_le = models.DateTimeField(
        null=True, blank=True, help_text="Fin du délai de carence après vérification."
    )
    motif = models.CharField(max_length=300, blank=True, help_text="Motif du rejet ou du retrait.")
    retire_le = models.DateTimeField(null=True, blank=True)
    # La réponse du gérant à l'avis « un compte de versement a été déclaré pour votre boutique ».
    # C'est la seule personne qui sait avec certitude si ce numéro est le sien : quand quelqu'un
    # d'autre — un employé, un administrateur, un compte volé — déclare un compte, le gérant le
    # voit, et peut dire « ce n'est pas moi » pendant le délai de carence, avant que l'argent parte.
    confirme_par_gerant_le = models.DateTimeField(null=True, blank=True)
    conteste_le = models.DateTimeField(null=True, blank=True)
    conteste_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "compte de versement"
        verbose_name_plural = "comptes de versement"
        ordering = ["-cree_le"]
        constraints = [
            # Un seul compte vérifié à la fois : sinon, lequel reçoit le prochain versement ?
            models.UniqueConstraint(
                fields=["boutique"],
                condition=models.Q(etat="verifie"),
                name="un_compte_de_versement_verifie_par_boutique",
            )
        ]

    def __str__(self):
        return f"{self.get_operateur_display()} {self.numero} · {self.boutique}"
