# ADR-007 — Pas de SPA sur le front marchand

**Statut :** Actée · **Détail :** docs/09, §1 et §9 ; docs/19

---

## Contexte

Les utilisateurs visés travaillent sur des Android d'entrée de gamme, en 3G intermittente, avec
de la donnée payante au mégaoctet. Un commerçant qui voit son forfait fondre parce que le
logiciel de sa boutique télécharge deux mégaoctets de JavaScript à chaque mise à jour n'a pas
besoin qu'on lui explique le compromis technique : il désinstalle.

L'objectif tenu par le document 09 §9 est explicite : **page catalogue affichée en moins de
2,5 secondes sur 3G.** Une application monopage n'y arrive qu'au prix d'un travail d'optimisation
permanent — découpage du paquet, rendu côté serveur, hydratation — c'est-à-dire en réinventant ce
qu'un rendu serveur donne gratuitement.

## Décision

**Rendu serveur avec les gabarits Django.** Pas d'application monopage. L'interactivité locale
est écrite en JavaScript simple, chargée par page, sans cadriciel.

Le document 09 mentionnait HTMX et Alpine.js comme outils d'appoint pour les fragments dynamiques.
**En pratique, ils n'ont pas été nécessaires et ne sont pas installés** : la caisse, le seul
écran réellement interactif, tient dans quelques dizaines de lignes de JavaScript en clair
(`static/js/caisse.js`, `hors-ligne.js`, `imprimante.js`). La décision structurante — celle qui
est coûteuse à défaire — est « pas de SPA » ; le choix d'une micro-bibliothèque au-dessus ne
l'est pas, et reste ouvert le jour où un écran le justifiera.

Écarté : React ou Vue avec rendu serveur. Écarté aussi : une dépendance CDN, quelle qu'elle soit
— elle ajoute une résolution DNS et un point de panne hors du contrôle de la plateforme, sur un
réseau qui n'en a pas besoin.

## Conséquences

**Aucune dépendance front, donc aucune chaîne de compilation.** Pas de `node_modules` en
production, pas de paquet à reconstruire, pas de mise à jour de sécurité transitive. Le CSS est
écrit à la main (`static/css/hypermarche.css`, documenté dans docs/19).

**Le hors-ligne se construit avec les primitives du navigateur** : service worker, IndexedDB,
`fetch`. C'est plus de code que l'équivalent avec une bibliothèque de synchronisation, et c'est
du code qu'on comprend entièrement — ce qui compte sur un chemin où une erreur perd une vente.

**Un piège de chargement, rencontré et documenté.** Les scripts communs sont chargés en `defer`
dans l'en-tête ; les scripts en ligne d'une page s'exécutent **pendant** l'analyse du document,
donc **avant** eux. Des gardes `if (window.FileVentes)` renvoyaient silencieusement, et le
compteur d'opérations en attente ne s'abonnait jamais. Correction : les scripts de page
s'accrochent à `DOMContentLoaded`, et la garde journalise une erreur au lieu de se taire.
Détail en docs/19, §7.6.

**Chaque écran est composé par rôle, pas grisé.** C'est une conséquence directe du rendu serveur :
un droit refusé n'est pas caché en CSS, il **n'est pas calculé** — la donnée ne quitte jamais le
serveur. Une SPA aurait rendu la tentation inverse trop facile.

## Vérification

- `scripts/verifier-hors-ligne.js` — quinze vérifications dans Chromium réel, réseau coupé puis
  rétabli.
- `tests/test_permissions.py`, `tests/test_backoffice.py` — un droit refusé ferme la porte côté
  serveur, avec un 403 explicite plutôt qu'une redirection silencieuse.
