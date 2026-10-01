"""La langue du marché : français ou anglais, au choix de l'acheteur.

Le Cameroun est bilingue, et le marché s'adresse aussi à Buea, Bamenda et Limbé. La vitrine se lit
donc en français ou en anglais. Le back-office, lui, reste en français : ses écrans, ses messages
d'erreur et sa documentation n'existent que dans cette langue, et un écran à moitié traduit est
pire qu'un écran d'une seule langue.

D'où un intergiciel et non `LocaleMiddleware` tel quel : celui-ci appliquerait la langue du
navigateur partout, et un commerçant au téléphone réglé en anglais verrait les messages de
validation de Django en anglais au milieu d'un formulaire français.

Ordre de décision, sur les pages du marché seulement :
  1. le choix explicite de l'acheteur (cookie posé par la vue `set_language` de Django) ;
  2. la langue préférée de son navigateur, si c'est le français ou l'anglais ;
  3. le français.
"""

from django.conf import settings
from django.utils import translation

PREFIXES = ("/marche/",)


class LangueDuMarcheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(PREFIXES):
            langue = translation.get_language_from_request(request, check_path=False)
        else:
            langue = settings.LANGUAGE_CODE
        translation.activate(langue)
        request.LANGUAGE_CODE = translation.get_language()
        try:
            response = self.get_response(request)
            if request.path.startswith(PREFIXES):
                response.headers.setdefault("Content-Language", request.LANGUAGE_CODE)
                vary = response.headers.get("Vary", "")
                if "Accept-Language" not in vary:
                    response.headers["Vary"] = f"{vary}, Accept-Language" if vary else "Accept-Language"
            return response
        finally:
            translation.deactivate()
