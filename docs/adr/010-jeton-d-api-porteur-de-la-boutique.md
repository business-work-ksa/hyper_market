# ADR-010 — Le jeton d'API porte la boutique, le client ne la déclare pas

**Statut :** Actée · **Détail :** `apps/api/` ; docs/14, §5

---

## Contexte

L'application web résout la boutique courante par un en-tête `X-Boutique`, une valeur en session,
ou l'appartenance unique de l'utilisateur (`apps/core/middleware.py`). Cela fonctionne pour un
navigateur : le middleware pose le contexte, et la porte du back-office recalcule ensuite les
droits sur cette boutique — un en-tête falsifié n'ouvre donc rien, faute de droits.

Pour une API, ce montage pose deux problèmes.

**Un problème d'ordre.** Le middleware s'exécute **avant** l'authentification. Avec un jeton
porteur, l'utilisateur n'est pas encore connu quand le contexte est posé : il ne reste que
l'en-tête fourni par le client, c'est-à-dire une valeur qu'on ne contrôle pas.

**Un problème de surface.** Même sauvée par le recalcul des droits, la logique « le client
annonce le tenant, le serveur vérifie » demande que **chaque** point d'entrée refasse la
vérification. Un oubli, sur un seul point d'entrée, est une fuite entre commerçants concurrents.
La sécurité qui repose sur la répétition d'un contrôle est la sécurité qui finit par céder.

## Décision

**Le jeton d'API appartient à un couple (utilisateur, boutique), et c'est lui qui détermine le
tenant.** Le client n'a aucun moyen de désigner une boutique : `X-Boutique` n'est pas lu par
l'API. Il n'y a donc rien à vérifier — la question ne se pose pas.

Trois conséquences de conception en découlent :

1. **Le contexte de tenant est ouvert après l'authentification**, dans `VueApi.initial`, et
   refermé dans un `finally` de `dispatch`. Le `finally` n'est pas une précaution de style : les
   connexions sont persistantes et le contexte est répercuté sur la connexion PostgreSQL
   (ADR-002). Une requête qui échouerait sans restaurer laisserait la **suivante** hériter de sa
   boutique.
2. **Les droits sont recalculés à chaque requête**, à partir des appartenances actives — jamais
   figés dans le jeton. Un salarié dont l'accès est retiré ce matin ne lit pas les ventes cet
   après-midi avec un jeton émis la semaine dernière.
3. **La table des jetons n'est pas scopée**, alors qu'elle porte une boutique. Elle est lue
   *avant* que le contexte n'existe — c'est elle qui va l'établir. `Appartenance` est hors du
   scope pour la même raison : **les tables qui servent à décider de l'accès ne peuvent pas
   dépendre de l'accès.**

### Pourquoi pas `rest_framework.authtoken`

Deux raisons, et la première suffirait.

**Il stocke la clé en clair.** Une lecture de la table donne des jetons utilisables. Ici, la base
ne conserve qu'un SHA-256 du secret. Pas de fonction de dérivation lente : un secret de
32 caractères tirés au hasard n'est pas devinable par force brute, et un `bcrypt` n'ajouterait
que du temps de calcul à chaque requête.

**Il est lié à un utilisateur, pas à un tenant.** C'est précisément la propriété qui manque.

Le format retenu est `hm_<préfixe>_<secret>`. Le préfixe, stocké en clair et indexé, rend
l'authentification possible en un accès unique — sans lui, il faudrait hacher le secret présenté
puis parcourir la table. Il sert aussi à l'humain : c'est ce qui identifie un jeton dans une
liste, quand plus personne ne peut voir le secret.

## Conséquences

**Un porteur, une boutique.** Un comptable qui suit trois boutiques détient trois jetons. C'est
plus de jetons à gérer, et c'est le prix de la propriété : chaque jeton perdu ou révoqué n'affecte
qu'une boutique, et un journal d'accès dit sans ambiguïté quelle boutique a été lue.

**Les droits sont ceux de l'écran, pas une seconde matrice.** L'API lit
`apps.accounts.permissions`, comme le back-office. Un caissier ne voit pas la marge parce qu'elle
**n'est pas calculée** pour lui : le champ est retiré du sérialiseur avant toute lecture de
l'objet, et le calcul du coût de marchandise — qui interroge les mouvements de stock — n'a pas
lieu. Un champ à `null` aurait dit au client qu'il existe ; un champ absent dit ce qui est vrai.

**Un échec d'authentification dit toujours la même chose.** Préfixe inconnu, secret faux, jeton
révoqué : le même message. Distinguer les cas indiquerait à un attaquant lesquels de ses essais
ont touché un préfixe réel.

## Vérification

`tests/test_api.py` — 39 tests, dont : un en-tête `X-Boutique` pointant sur la boutique voisine ne
change rien au catalogue servi ; un ticket voisin répond 404 et non 403 (un 403 confirmerait son
existence) ; retirer l'appartenance ferme le jeton à la requête suivante ; le coût d'achat est
**absent** de la réponse faite à un caissier ; et le contexte de tenant est refermé après la
requête, y compris après un refus.
