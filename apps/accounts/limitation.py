"""Freiner les essais de mot de passe, compte par compte.

Sans ce module, la page de connexion accepte un nombre illimité d'essais. Ce
n'est pas une faiblesse théorique ici : l'identifiant est un **numéro de
téléphone**, et les numéros camerounais tiennent dans un espace minuscule —
`+2376XXXXXXXX`. Un attaquant qui a vu passer une carte de visite connaît déjà
l'identifiant ; il ne lui reste que le mot de passe.

Deux dangers, et le second est le moins attendu
-----------------------------------------------

**La force brute.** Un mot de passe de commerce fait six à huit signes. À cent
essais par seconde, il tombe. À dix essais par quart d'heure, il ne tombe pas.

**L'épuisement du processeur.** Django hache le mot de passe présenté *même
quand le compte n'existe pas*, pour que la durée de la réponse ne trahisse pas
l'existence du compte. C'est la bonne décision, et elle a un coût : chaque essai
consomme un PBKDF2 complet, soit plusieurs centaines de millisecondes. Trois
`workers` gunicorn saturent donc à quelques requêtes par seconde — envoyées par
quelqu'un qui n'est pas connecté et n'a aucun compte. Un refus **avant** le
hachage est ce qui rend cette attaque sans effet.

Pourquoi par compte, et pas par adresse IP
------------------------------------------

Parce que l'adresse IP ne veut rien dire ici. En production l'application est
derrière un proxy : `REMOTE_ADDR` est celui du proxy, identique pour tout le
monde, et limiter dessus reviendrait à fermer la boutique à tous ses caissiers
dès le premier attaquant. Quant à `X-Forwarded-For`, il est écrit par le client
— s'en servir pour compter, c'est laisser l'attaquant choisir son compteur.

Le compte visé, lui, n'est pas falsifiable : c'est celui qu'on attaque. Le
compteur porte donc sur lui, et sur rien d'autre.

Ce que cela n'attrape pas, et c'est assumé : un essai d'un **même** mot de passe
sur des **milliers** de numéros différents. Cette attaque-là demande une liste de
numéros réellement inscrits, et se voit dans les journaux — pas dans un
compteur.

Le prix à payer, et pourquoi on le paie
---------------------------------------

Un verrou par compte se retourne : quelqu'un qui connaît le numéro d'un
commerçant peut lui fermer sa caisse un quart d'heure en tapant dix fois à côté.
Sur une caisse, un quart d'heure un samedi n'est pas rien.

Trois choses bornent ce coût, et il faut les avoir posées ensemble pour que le
verrou soit défendable :

* **il expire tout seul.** Un verrou qu'il faut lever à la main transformerait
  la même farce en journée perdue ;
* **la fenêtre ne se prolonge pas.** Le premier échec fixe l'échéance ; les
  suivants ne la repoussent pas. Sans cela, un attaquant qui frappe une fois par
  minute maintiendrait le compte fermé pour toujours — l'attaque réussirait en
  échouant ;
* **il reste une porte.** Le gérant peut régénérer le mot de passe d'un membre
  depuis l'écran de l'équipe, et ce geste-là n'est pas verrouillé : il vient
  d'une session déjà authentifiée.

L'alternative — ne rien limiter — laisse tomber n'importe quel mot de passe de
commerce en une nuit. Entre un quart d'heure de gêne et un compte pris, le choix
est fait ici, et il est réversible : `ESSAIS_MAX` et `FENETRE_SECONDES` sont deux
constantes.

Ce que le verrou ne dit pas
---------------------------

**Il ne dit pas si le compte existe.** Le message et le code de réponse sont les
mêmes pour un numéro inscrit et un numéro inventé — y compris le `429`, qui est
posé sur un numéro jamais vu comme sur un autre.
"""

from django.core.cache import cache

__all__ = ["ESSAIS_MAX", "FENETRE_SECONDES", "trop_d_essais", "compter_un_echec", "oublier"]

# Dix essais par quart d'heure. Le chiffre n'est pas tiré au sort : un commerçant
# qui tape mal son mot de passe s'en aperçoit en deux ou trois fois, jamais en
# dix ; une attaque, elle, en demande des milliers. La marge est du côté de
# l'humain qui se trompe.
ESSAIS_MAX = 10
FENETRE_SECONDES = 15 * 60

_PREFIXE = "connexion-echecs:"


def _cle(telephone: str) -> str:
    # Le numéro est repris tel quel après nettoyage : c'est une donnée publique,
    # pas un secret, et le cache n'est pas lisible depuis l'extérieur.
    return _PREFIXE + (telephone or "").strip()


def trop_d_essais(telephone: str) -> bool:
    """Ce compte a-t-il déjà épuisé ses essais ?

    Appelé **avant** `authenticate`, jamais après : tout l'intérêt est de ne pas
    payer le hachage.
    """
    return cache.get(_cle(telephone), 0) >= ESSAIS_MAX


def compter_un_echec(telephone: str) -> int:
    """Enregistre un échec et renvoie le total dans la fenêtre courante.

    La fenêtre est **glissante par pose**, pas par échec : le premier échec fixe
    l'échéance, les suivants ne la repoussent pas. Sans cela, un attaquant
    régulier maintiendrait le verrou indéfiniment et le commerçant ne pourrait
    plus jamais se connecter — l'attaque échouerait en réussissant.
    """
    cle = _cle(telephone)
    # `add` ne fait rien si la clé existe : c'est ce qui pose l'échéance une
    # seule fois. `incr` la laisse ensuite inchangée.
    cache.add(cle, 0, FENETRE_SECONDES)
    try:
        return cache.incr(cle)
    except ValueError:
        # La clé a expiré entre le `add` et le `incr`. Rare, et sans gravité :
        # on repart d'un échec.
        cache.set(cle, 1, FENETRE_SECONDES)
        return 1


def oublier(telephone: str) -> None:
    """Efface le compteur. Appelé après une connexion réussie.

    Celui qui vient de prouver qu'il connaît le mot de passe ne doit pas traîner
    les essais ratés d'avant — sinon deux fautes de frappe le matin le
    rapprochent d'un verrou l'après-midi.
    """
    cache.delete(_cle(telephone))
