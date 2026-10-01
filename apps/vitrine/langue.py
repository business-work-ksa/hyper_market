"""La langue de l'application : français ou anglais, au choix de la personne.

Le Cameroun est bilingue, et HyperMarché s'adresse aussi à Buea, Bamenda et Limbé : le marché, le
back-office des commerçants et la console de la plateforme se lisent en français ou en anglais.

D'où un intergiciel et non `LocaleMiddleware` tel quel : celui-ci appliquerait la langue partout,
y compris aux adresses techniques — l'API des applications mobiles, les notifications des
opérateurs Mobile Money, la tâche quotidienne — dont les messages sont journalisés, comparés et
relus en français. Ces adresses restent en français, quoi qu'envoie l'appelant.

Ordre de décision, partout ailleurs :
  1. le choix explicite de la personne (cookie `hm_langue`, posé par la vue `set_language`) ;
  2. la langue préférée de son navigateur, si c'est le français ou l'anglais ;
  3. le français.
"""

from django.conf import settings
from django.utils import translation

TECHNIQUES = ("/api/", "/paiements/notifications/", "/taches/")


def _langue_choisie(request) -> bool:
    return not request.path.startswith(TECHNIQUES)


class LangueDuMarcheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        choisie = _langue_choisie(request)
        if choisie:
            langue = translation.get_language_from_request(request, check_path=False)
        else:
            langue = settings.LANGUAGE_CODE
        translation.activate(langue)
        request.LANGUAGE_CODE = translation.get_language()
        try:
            response = self.get_response(request)
            if choisie:
                response.headers.setdefault("Content-Language", request.LANGUAGE_CODE)
                vary = response.headers.get("Vary", "")
                if "Accept-Language" not in vary:
                    response.headers["Vary"] = f"{vary}, Accept-Language" if vary else "Accept-Language"
            return response
        finally:
            translation.deactivate()
