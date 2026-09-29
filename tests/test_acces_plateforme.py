"""L'accès transverse est nommé, borné et journalisé (ADR-012).

Avant cet ADR, les trois promesses de `apps/core/rls.py` étaient fausses : rien n'était journalisé
(aucun modèle d'audit n'existait dans le dépôt), rien n'était justifié (aucun motif n'était demandé)
et rien n'était restreint (`is_superuser` renvoyait tous les droits sur toutes les boutiques).

Ces tests sont la seule raison pour laquelle elles resteront vraies.
"""

import pathlib
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.accounts.models import Appartenance, Role, RolePlateforme
from apps.accounts.permissions import (
    COUT_VOIR,
    MARGE_VOIR,
    PLATEFORME_COMMISSIONS,
    TOUS,
    TOUS_PLATEFORME,
    droits_de,
    droits_plateforme_de,
)
from apps.core.models import AccesPlateforme
from apps.core.tenancy import acces_plateforme, contexte_boutique
from apps.marketplace.gouvernance import en_conflit_sur_le_rayon, fixer_taux_rayon
from apps.marketplace.models import Boutique
from tests import fabrique


def _role(code, libelle, portee=Role.BOUTIQUE):
    role, _ = Role.objects.get_or_create(
        code=code, defaults={"libelle": libelle, "portee": portee}
    )
    return role


class SuperutilisateurTest(TestCase):
    """Le cœur de l'ADR-012 : un booléen ne donne plus la marge d'un commerçant."""

    def setUp(self):
        self.boutique = fabrique.creer_boutique("Boutique d'un tiers")
        self.exploitant = fabrique.creer_utilisateur("Exploitant")
        self.exploitant.is_superuser = True
        self.exploitant.is_staff = True
        self.exploitant.save(update_fields=["is_superuser", "is_staff"])

    def test_le_superutilisateur_n_a_aucun_droit_sur_une_boutique_ou_il_n_est_pas(self):
        droits = droits_de(self.exploitant, self.boutique)
        self.assertEqual(droits, frozenset())
        self.assertNotIn(MARGE_VOIR, droits)
        self.assertNotIn(COUT_VOIR, droits)

    def test_il_garde_ses_droits_la_ou_il_est_rattache(self):
        """Il peut être commerçant : c'est son appartenance qui le dit, pas son booléen."""
        Appartenance.objects.create(
            utilisateur=self.exploitant,
            boutique=self.boutique,
            role=_role(Role.GERANT, "Gérant"),
        )
        self.assertEqual(droits_de(self.exploitant, self.boutique), TOUS)


class DroitsDePlateformeTest(TestCase):
    def setUp(self):
        self.exploitant = fabrique.creer_utilisateur("Exploitant")

    def test_sans_role_plateforme_aucun_droit_d_exploitation(self):
        self.assertEqual(droits_plateforme_de(self.exploitant), frozenset())

    def test_admin_marche_ouvre_les_cinq_droits(self):
        RolePlateforme.objects.create(
            utilisateur=self.exploitant,
            role=_role(Role.ADMIN_MARCHE, "Gestionnaire du marché", Role.PLATEFORME),
        )
        self.assertEqual(droits_plateforme_de(self.exploitant), TOUS_PLATEFORME)

    def test_les_droits_de_plateforme_n_ouvrent_aucun_droit_de_boutique(self):
        """C'est l'inventaire de l'ADR : rien dans l'exploitation n'exige la marge d'autrui."""
        self.assertEqual(TOUS_PLATEFORME & TOUS, frozenset())
        for droit in TOUS_PLATEFORME:
            self.assertTrue(droit.startswith("plateforme."), droit)

    def test_un_role_de_boutique_est_refuse_comme_role_plateforme(self):
        porteur = RolePlateforme(
            utilisateur=self.exploitant, role=_role(Role.CAISSIER, "Caissier")
        )
        with self.assertRaises(ValidationError):
            porteur.clean()


class JournalDesAccesTest(TestCase):
    def setUp(self):
        self.boutique = fabrique.creer_boutique("Boutique observée")
        self.exploitant = fabrique.creer_utilisateur("Exploitant")

    def test_l_acces_ecrit_une_ligne(self):
        with acces_plateforme(
            utilisateur=self.exploitant,
            motif="Litige commande 4312 : le client conteste la livraison.",
            ecran="backoffice/commandes/4312",
            boutique_id=self.boutique.pk,
        ):
            pass

        trace = AccesPlateforme.objects.get()
        self.assertEqual(trace.utilisateur, self.exploitant)
        self.assertEqual(trace.boutique_id, self.boutique.pk)
        self.assertIn("4312", trace.motif)

    def test_un_motif_vide_est_refuse(self):
        """Une trace sans raison ne répond pas à la question qu'on posera un jour."""
        for motif in ("", "   ", None):
            with self.subTest(motif=motif):
                with self.assertRaises(ValueError):
                    with acces_plateforme(
                        utilisateur=self.exploitant, motif=motif, ecran="x"
                    ):
                        pass
        self.assertEqual(AccesPlateforme.objects.count(), 0)

    def test_un_utilisateur_anonyme_est_refuse(self):
        with self.assertRaises(ValueError):
            with acces_plateforme(utilisateur=None, motif="curiosité", ecran="x"):
                pass

    def test_la_trace_survit_a_l_echec_du_bloc(self):
        """C'est l'accès qu'on journalise, pas son succès."""
        with self.assertRaises(RuntimeError):
            with acces_plateforme(
                utilisateur=self.exploitant, motif="Vérification", ecran="x"
            ):
                raise RuntimeError("le code du bloc a échoué")
        self.assertEqual(AccesPlateforme.objects.count(), 1)

    def test_la_trace_ne_se_modifie_pas(self):
        with acces_plateforme(utilisateur=self.exploitant, motif="Audit", ecran="x"):
            pass
        trace = AccesPlateforme.objects.get()
        trace.motif = "autre chose"
        with self.assertRaises(ValueError):
            trace.save()

    def test_la_trace_ne_se_supprime_pas(self):
        with acces_plateforme(utilisateur=self.exploitant, motif="Audit", ecran="x"):
            pass
        with self.assertRaises(ValueError):
            AccesPlateforme.objects.get().delete()


class ContexteInterditDansLesVuesTest(TestCase):
    """Une règle qu'aucun test ne défend n'est qu'un souhait.

    `contexte_plateforme()` reste légitime pour la vitrine publique et les tâches de fond. Dans le
    back-office, où c'est un humain qui demande à voir les données d'un commerçant, la voie est
    `acces_plateforme()`.
    """

    # La dérogation se demande en écrivant ce marqueur **dans le fichier**, accompagné de sa
    # raison. Une liste d'exemptions tenue ici aurait dérivé au premier renommage, et surtout
    # elle aurait mis la justification loin du code qu'elle justifie. Ainsi, la dérogation est
    # visible par celui qui relit la vue, et non par celui qui relit les tests.
    MARQUEUR = "ACCES_PLATEFORME_PUBLIC_JUSTIFIE"

    def test_le_backoffice_n_ouvre_pas_le_contexte_plateforme_sans_trace(self):
        coupables = []
        for fichier in sorted(pathlib.Path("apps/backoffice").rglob("*.py")):
            source = fichier.read_text()
            if "contexte_plateforme" in source and self.MARQUEUR not in source:
                coupables.append(str(fichier))
        self.assertEqual(
            coupables,
            [],
            "Ces modules ouvrent l'accès transverse sans motif ni trace. Utilisez "
            f"acces_plateforme() (ADR-012), ou écrivez {self.MARQUEUR} avec sa raison si "
            "l'accès est réellement public : " + ", ".join(coupables),
        )

    def test_la_derogation_existante_est_bien_une_vue_publique(self):
        """Le marqueur ne doit pas devenir un laissez-passer qu'on recopie.

        Un fichier qui le porte doit aussi expliquer pourquoi : on vérifie que la raison est
        écrite, pas seulement le mot de passe.
        """
        for fichier in sorted(pathlib.Path("apps/backoffice").rglob("*.py")):
            source = fichier.read_text()
            if self.MARQUEUR in source:
                with self.subTest(fichier=str(fichier)):
                    self.assertIn(
                        "ADR-012",
                        source,
                        "une dérogation doit citer l'ADR à laquelle elle déroge",
                    )
                    self.assertIn(
                        "publique",
                        source,
                        "une dérogation doit dire en quoi l'accès est public",
                    )


class ConflitDInteretTest(TestCase):
    """L'exploitant vend sur sa propre place. Trois portes sont fermées par du code."""

    def setUp(self):
        self.rayon = fabrique.creer_rayon(taux="0.0500")
        self.exploitant = fabrique.creer_utilisateur("Exploitant")
        RolePlateforme.objects.create(
            utilisateur=self.exploitant,
            role=_role(Role.ADMIN_MARCHE, "Gestionnaire du marché", Role.PLATEFORME),
        )
        self.arbitre = fabrique.creer_utilisateur("Arbitre")
        RolePlateforme.objects.create(
            utilisateur=self.arbitre,
            role=_role(Role.ADMIN_MARCHE, "Gestionnaire du marché", Role.PLATEFORME),
        )

    def _boutique_dans_le_rayon(self):
        boutique = fabrique.creer_boutique("La sienne")
        Boutique.objects.filter(pk=boutique.pk).update(
            rayon_principal_id=self.rayon.pk
        )
        Appartenance.objects.create(
            utilisateur=self.exploitant, boutique=boutique, role=_role(Role.GERANT, "Gérant")
        )
        return boutique

    def test_celui_qui_vend_dans_le_rayon_n_en_fixe_pas_la_commission(self):
        self._boutique_dans_le_rayon()
        self.assertTrue(en_conflit_sur_le_rayon(self.exploitant, self.rayon))
        with self.assertRaises(PermissionDenied) as leve:
            fixer_taux_rayon(
                self.rayon, Decimal("0.02"), par=self.exploitant, motif="Baisse commerciale"
            )
        self.assertIn("vous n'en fixez pas la commission", str(leve.exception).lower())

    def test_quelqu_un_sans_interet_peut_le_faire_et_laisse_une_trace(self):
        self._boutique_dans_le_rayon()
        fixer_taux_rayon(
            self.rayon,
            Decimal("0.0400"),
            par=self.arbitre,
            motif="Alignement sur la concurrence de Douala.",
        )
        self.rayon.refresh_from_db()
        self.assertEqual(self.rayon.taux_commission, Decimal("0.0400"))

        trace = AccesPlateforme.objects.get()
        self.assertIn("5.00%", trace.motif)
        self.assertIn("4.00%", trace.motif)

    def test_un_taux_saisi_en_pourcentage_est_refuse(self):
        """« 8 » au lieu de « 0,08 » prendrait 800 % de commission."""
        with self.assertRaises(ValidationError):
            fixer_taux_rayon(self.rayon, Decimal("8"), par=self.arbitre, motif="Erreur de saisie")

    def test_un_changement_sans_motif_est_refuse(self):
        with self.assertRaises(ValidationError):
            fixer_taux_rayon(self.rayon, Decimal("0.03"), par=self.arbitre, motif="  ")

    def test_sans_droit_d_exploitation_c_est_refuse(self):
        quidam = fabrique.creer_utilisateur("Quidam")
        with self.assertRaises(PermissionDenied):
            fixer_taux_rayon(self.rayon, Decimal("0.03"), par=quidam, motif="Pourquoi pas")


class EmplacementPremiumTest(TestCase):
    def test_un_emplacement_a_tarif_nul_est_refuse_par_la_base(self):
        """Sinon le compte de résultat de la plateforme mentirait sur sa rentabilité."""
        from django.db import IntegrityError, transaction
        from django.utils import timezone

        from apps.marketplace.models import EmplacementPremium

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EmplacementPremium.objects.create(
                    type=EmplacementPremium.TETE_DE_GONDOLE,
                    debut=timezone.localdate(),
                    fin=timezone.localdate(),
                    tarif=Decimal("0"),
                )


class DerogationCommissionTest(TestCase):
    def test_un_taux_qui_s_ecarte_de_l_offre_exige_un_motif(self):
        from apps.marketplace.models import Bail, TypeEmplacement

        boutique = fabrique.creer_boutique("Négociatrice")
        offre = boutique.offre
        bail = Bail(
            boutique=boutique,
            type_emplacement=TypeEmplacement.objects.first(),
            loyer_mensuel=Decimal("45000"),
            taux_commission=offre.taux_commission_defaut - Decimal("0.0100"),
        )
        with self.assertRaises(ValidationError) as leve:
            bail.clean()
        self.assertIn("motif_derogation_commission", leve.exception.message_dict)

    def test_le_taux_de_l_offre_ne_demande_rien(self):
        from apps.marketplace.models import Bail, TypeEmplacement

        boutique = fabrique.creer_boutique("Standard")
        bail = Bail(
            boutique=boutique,
            type_emplacement=TypeEmplacement.objects.first(),
            loyer_mensuel=Decimal("45000"),
            taux_commission=boutique.offre.taux_commission_defaut,
        )
        bail.clean()  # ne lève pas
