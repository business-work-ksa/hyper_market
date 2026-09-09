"""Espace personnalisé d'une boutique : charte graphique et liens marketing.

Le commerçant loue un emplacement, pas un abonnement logiciel. Qu'il retrouve
ses couleurs dans son back-office et sur sa vitrine n'est pas un ornement : c'est
la différence entre un outil qu'on lui prête et un outil qui est le sien.

Deux principes gouvernent l'écran.

**On propose, on n'impose pas — et on explique.** Le logo est lu, ses couleurs
dominantes sont extraites, mais c'est le commerçant qui choisit. Et quand la
couleur choisie ne tient pas les règles du produit (`apps/marketplace/charte.py`),
elle est corrigée **et la correction est affichée**. Une couleur modifiée sans
explication passe pour un bogue.

**Un lien qu'on ne peut pas dicter ne sert à rien.** Un commerçant ne partage pas
une adresse de trente caractères : il l'écrit sur un flyer, il la dit au
téléphone. D'où le code court, et d'où le compteur — sans lui, il n'a aucun
moyen de savoir si le flyer a servi.
"""

import secrets

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts import permissions as droit
from apps.accounts.models import ALPHABET_CODE
from apps.backoffice.acces import contexte_commun, exige
from apps.backoffice.forms import CharteForm, LienMarketingForm
from apps.catalog.models import Variante
from apps.marketplace import charte as service_charte
from apps.marketplace.models import IdentiteVisuelle, LienMarketing

LONGUEUR_CODE = 7


def identite_de(boutique) -> IdentiteVisuelle:
    """Charte de la boutique, créée à la volée si elle n'existe pas encore.

    Une boutique sans charte n'est pas un cas d'erreur : c'est l'état initial de
    toutes. La créer à la lecture évite d'avoir à la créer à l'inscription, donc
    d'avoir à rattraper les boutiques créées avant l'existence de cet écran.
    """
    identite, _ = IdentiteVisuelle.objects.get_or_create(boutique=boutique)
    return identite


def generer_code() -> str:
    """Code court d'un lien : dictable au téléphone, sans caractère ambigu.

    Même alphabet que les codes d'apporteur et les mots de passe provisoires —
    ni O/0 ni I/1. Un lien marketing finit toujours par être lu à voix haute une
    fois, et une confusion coûte une visite.
    """
    for _ in range(20):
        code = "".join(secrets.choice(ALPHABET_CODE) for _ in range(LONGUEUR_CODE))
        if not LienMarketing.objects_all_tenants.filter(code=code).exists():
            return code
    raise RuntimeError("Impossible de générer un code de lien unique.")


@exige(droit.BOUTIQUE_ADMINISTRER)
def identite(request):
    contexte = contexte_commun(request, "boutique")
    boutique = contexte["boutique"]
    identite_visuelle = identite_de(boutique)

    if request.method == "POST":
        formulaire = CharteForm(request.POST, request.FILES, instance=identite_visuelle)
        if formulaire.is_valid():
            enregistree = _enregistrer_charte(formulaire, identite_visuelle)
            if enregistree.motif_ajustement:
                messages.success(
                    request,
                    f"Charte enregistrée. Une correction a été appliquée : "
                    f"{enregistree.motif_ajustement}",
                )
            else:
                messages.success(request, "Charte enregistrée.")
            return redirect("identite")
    else:
        formulaire = CharteForm(instance=identite_visuelle)

    contexte.update(
        {
            "formulaire": formulaire,
            "identite": identite_visuelle,
            # Proposées à partir du logo déjà téléversé : le commerçant clique
            # sur une pastille plutôt que de recopier un code hexadécimal qu'il
            # n'a pas.
            "proposees": _proposer(identite_visuelle),
            "lien_vitrine": request.build_absolute_uri(f"/marche/boutique/{boutique.slug}/"),
            "liens": list(LienMarketing.objects.all()),
            "formulaire_lien": LienMarketingForm(boutique=boutique),
        }
    )
    return render(request, "identite.html", contexte)


def _proposer(identite_visuelle) -> list[dict]:
    """Couleurs dominantes du logo, déjà validées.

    Elles sont présentées **après correction** : montrer au commerçant une
    pastille qu'il choisit et qui change ensuite serait le pire des deux mondes.
    """
    if not identite_visuelle.logo:
        return []
    try:
        brutes = service_charte.couleurs_du_logo(identite_visuelle.logo)
    except (OSError, ValueError):
        return []

    proposees, deja_vues = [], set()
    for hexa in brutes:
        palette = service_charte.charte_depuis_couleur(hexa)
        if palette["marque"] in deja_vues:
            continue
        deja_vues.add(palette["marque"])
        proposees.append({"couleur": palette["marque"], "origine": hexa, "motif": palette["motif"]})
    return proposees


def _enregistrer_charte(formulaire, identite_visuelle) -> IdentiteVisuelle:
    """Applique la validation avant d'écrire : jamais la couleur brute en base.

    C'est le point qui justifie de passer par ici plutôt que par un `ModelForm`
    ordinaire. Ce qui est stocké est déjà utilisable ; aucun gabarit n'a à se
    demander si la couleur qu'il pose sur un bouton est lisible.
    """
    identite_visuelle = formulaire.save(commit=False)
    palette = service_charte.charte_depuis_couleur(formulaire.cleaned_data["couleur_marque"])

    identite_visuelle.couleur_marque = palette["marque"]
    identite_visuelle.couleur_marque_sombre = palette["marque_sombre"]
    identite_visuelle.teinte = palette["teinte"]
    identite_visuelle.teinte_sombre = palette["teinte_sombre"]
    identite_visuelle.motif_ajustement = palette["motif"][:255]
    identite_visuelle.save()
    return identite_visuelle


@require_POST
@exige(droit.BOUTIQUE_ADMINISTRER)
def lien_creer(request):
    contexte = contexte_commun(request, "boutique")
    formulaire = LienMarketingForm(request.POST, boutique=contexte["boutique"])
    if not formulaire.is_valid():
        for erreurs in formulaire.errors.values():
            messages.error(request, erreurs[0])
        return redirect("identite")

    article = None
    if formulaire.cleaned_data.get("article"):
        article = Variante.objects.filter(pk=formulaire.cleaned_data["article"]).first()

    lien = LienMarketing.objects.create(
        boutique=contexte["boutique"],
        libelle=formulaire.cleaned_data["libelle"],
        code=generer_code(),
        article=article,
        code_apporteur=formulaire.cleaned_data.get("code_apporteur", ""),
        cree_par=request.user,
    )
    messages.success(request, f"Lien créé : {request.build_absolute_uri(lien.chemin())}")
    return redirect("identite")


@require_POST
@exige(droit.BOUTIQUE_ADMINISTRER)
def lien_retirer(request, lien_id):
    """Un lien se désactive, il ne se supprime pas.

    Le lien est peut-être imprimé sur un flyer distribué la semaine dernière.
    L'effacer rendrait ces flyers muets sans qu'on sache pourquoi ; le désactiver
    laisse au moins la trace de ce qui a été diffusé, et son compteur.
    """
    lien = get_object_or_404(LienMarketing.objects, pk=lien_id)
    LienMarketing.objects.filter(pk=lien.pk).update(actif=False)
    messages.success(request, f"« {lien.libelle} » ne redirige plus.")
    return redirect("identite")


# ---------------------------------------------------------------------------
# Redirection publique
# ---------------------------------------------------------------------------
def suivre_lien(request, code):
    """Ouvre le lien court, compte le clic, et transmet le parrainage.

    Vue **publique** : elle est appelée par un visiteur qui n'a pas de compte, et
    lit donc en contexte plateforme comme la vitrine. Elle ne rend rien — elle
    redirige — et ne divulgue donc aucune donnée du commerçant.
    """
    from django.db.models import F

    from apps.core.tenancy import contexte_plateforme

    with contexte_plateforme():
        lien = (
            LienMarketing.objects.filter(code=code, actif=True)
            .select_related("boutique", "article")
            .first()
        )
        if lien is None:
            raise Http404("Ce lien n'existe pas ou a été retiré.")

        # Compté en base plutôt qu'en mémoire : deux visiteurs simultanés
        # incrémenteraient la même valeur relue, et le compteur perdrait des clics
        # exactement le jour où le lien marche.
        LienMarketing.objects.filter(pk=lien.pk).update(clics=F("clics") + 1)

        if lien.article_id and lien.article.actif:
            cible = f"/marche/article/{lien.article_id}/"
        else:
            cible = f"/marche/boutique/{lien.boutique.slug}/"
        parrainage = lien.code_apporteur

    if parrainage:
        cible = f"{cible}?ref={parrainage}"
    return redirect(cible)
