"""Garantie et service après-vente : retrouver un appareil par son numéro.

Écran réservé au métier qui l'active. Il répond à une scène précise, et à une
seule : quelqu'un pose un téléphone sur le comptoir et demande s'il est encore
garanti. Tout le reste de l'écran découle de cette scène.

**La recherche est la page.** Pas un filtre dans un coin, pas un onglet : le
champ est la première chose, il prend le focus au chargement, et une douchette
qui envoie l'IMEI suivi d'Entrée suffit à obtenir la réponse. Un vendeur debout
avec un client devant lui ne navigue pas.

**Ce qui attend à l'atelier passe avant ce qui est vendu.** Les appareils en
réparation sont la seule partie de l'écran sur laquelle il reste quelque chose à
faire ; les ventes récentes ne sont là que pour le jour où le client a perdu son
ticket et se souvient seulement du jour.

**Les écarts de numérotation sont montrés, pas corrigés.** Un appareil en stock
sans numéro n'est pas une erreur à réparer de force : c'est une réception passée
sans les IMEI. Le dire permet de la rattraper depuis la fiche de l'article ;
bloquer aurait seulement fait renoncer au suivi.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from apps.accounts import permissions as droit
from apps.backoffice.acces import contexte_commun, exige
from apps.backoffice.filtres import FiltresExemplairesForm
from apps.backoffice.forms import AtelierForm, SortieAtelierForm
from apps.inventory import series
from apps.inventory.models import NumeroSerie
from apps.marketplace import metiers
from django.utils.translation import gettext as _

# Un commerce d'électronique vend quelques appareils par jour : cinquante lignes
# couvrent plusieurs semaines. Au-delà, la liste ne se lit plus — c'est la
# recherche qui prend le relais, et elle, elle est exhaustive.
VENTES_AFFICHEES = 50


def _exiger_le_metier(contexte):
    metier = contexte["metier"]
    if metier is None or not metier.a(metiers.SERIE):
        raise Http404("Ce métier ne suit pas les appareils à l'unité.")
    return metier


@exige(droit.VENTES_VOIR)
def garantie(request):
    contexte = contexte_commun(request, "garantie")
    metier = _exiger_le_metier(contexte)

    recherche = (request.GET.get("numero") or "").strip()
    trouve = series.rechercher(recherche) if recherche else None

    filtres = FiltresExemplairesForm(request.GET)
    ventes = _ventes_filtrees(filtres.valeurs)

    contexte.update(
        {
            "recherche": recherche,
            "trouve": trouve,
            # Distinguer « pas cherché » de « cherché, rien trouvé » : le second
            # mérite une phrase, le premier n'a rien à dire.
            "introuvable": bool(recherche) and trouve is None,
            "passages": list(trouve.passages.all()[:10]) if trouve else [],
            "suit_la_garantie": metier.a(metiers.GARANTIE),
            "en_atelier": list(series.en_atelier()) if metier.a(metiers.GARANTIE) else [],
            "ventes": list(ventes[:VENTES_AFFICHEES]),
            "filtres": filtres,
            "url_garantie": reverse("garantie"),
            "conserver_dans_filtres": {"numero": recherche} if recherche else {},
            "ecarts": series.ecarts_de_numerotation(depot=contexte["depot_courant"]),
            "peut_agir": droit.CAISSE_ENCAISSER in contexte["droits"],
            "formulaire_atelier": AtelierForm(),
            "formulaire_sortie": SortieAtelierForm(),
        }
    )
    return render(request, "garantie.html", contexte)


def _ventes_filtrees(valeurs):
    """Appareils vendus, filtrés — la liste du bas de l'écran.

    La recherche par numéro, elle, reste **au-dessus et hors filtres** : c'est
    la question du client au comptoir, et elle doit trouver un appareil quel que
    soit son état. Un filtre posé la veille ne doit pas la faire échouer.
    """
    ventes = NumeroSerie.objects.filter(etat=NumeroSerie.VENDU)
    if valeurs.get("etat"):
        ventes = NumeroSerie.objects.filter(etat=valeurs["etat"])
    if valeurs.get("q"):
        ventes = ventes.filter(numero__icontains=series.normaliser(valeurs["q"]))

    from django.utils import timezone

    aujourd_hui = timezone.localdate()
    if valeurs.get("garantie") == "en_cours":
        ventes = ventes.filter(garantie_fin__gte=aujourd_hui)
    elif valeurs.get("garantie") == "expiree":
        ventes = ventes.filter(garantie_fin__lt=aujourd_hui)
    elif valeurs.get("garantie") == "aucune":
        ventes = ventes.filter(garantie_fin__isnull=True)

    return ventes.select_related("variante__produit").order_by("-vendu_le")


def _exemplaire_de(request, exemplaire_id) -> NumeroSerie:
    return get_object_or_404(
        NumeroSerie.objects.select_related("variante__produit"), pk=exemplaire_id
    )


@require_POST
@exige(droit.CAISSE_ENCAISSER)
def atelier_entrer(request, exemplaire_id):
    contexte = contexte_commun(request, "garantie")
    _exiger_le_metier(contexte)

    exemplaire = _exemplaire_de(request, exemplaire_id)
    formulaire = AtelierForm(request.POST)
    if not formulaire.is_valid():
        messages.error(request, _("Indiquez la panne constatée : c'est elle qui se retrouve."))
        return _retour(exemplaire)

    try:
        passage = series.entrer_a_l_atelier(
            exemplaire, motif=formulaire.cleaned_data["motif"], cree_par=request.user
        )
    except series.NumeroInvalide as erreur:
        messages.error(request, str(erreur))
        return _retour(exemplaire)

    couverture = "sous garantie" if passage.sous_garantie else "hors garantie"
    messages.success(request, _("%(numero)s déposé à l'atelier, %(couverture)s.") % {"numero": exemplaire.numero, "couverture": couverture})
    return _retour(exemplaire)


@require_POST
@exige(droit.CAISSE_ENCAISSER)
def atelier_sortir(request, exemplaire_id):
    contexte = contexte_commun(request, "garantie")
    _exiger_le_metier(contexte)

    exemplaire = _exemplaire_de(request, exemplaire_id)
    formulaire = SortieAtelierForm(request.POST)
    resultat = formulaire.cleaned_data.get("resultat", "") if formulaire.is_valid() else ""

    passage = series.sortir_de_l_atelier(exemplaire, resultat=resultat)
    if passage is None:
        messages.error(request, _("%(numero)s n'est pas à l'atelier.") % {"numero": exemplaire.numero})
    else:
        messages.success(request, _("%(numero)s est ressorti de l'atelier.") % {"numero": exemplaire.numero})
    return _retour(exemplaire)


def _retour(exemplaire):
    """Revient sur la fiche de l'appareil, pas sur une liste.

    Le geste qui vient de se faire concerne cet appareil-là ; renvoyer vers la
    liste obligerait à le rechercher une seconde fois pour vérifier que c'est
    bien passé.
    """
    return redirect(f"{reverse('garantie')}?{urlencode({'numero': exemplaire.numero})}")
