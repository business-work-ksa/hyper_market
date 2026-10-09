# ADR-012 — L'accès transverse est nommé, borné et journalisé ; il ne découle pas d'un booléen

**Statut :** Actée · **Détail :** `apps/core/tenancy.py` (`acces_plateforme`) ; `apps/core/models.py` (`AccesPlateforme`) ; `apps/accounts/permissions.py` (droits `plateforme.*`) ; `apps/accounts/administration.py` (les trois niveaux) ; `apps/plateforme/` (la console)

---

## Contexte

Le multi-tenant de cette application tient sur trois barrières, et la troisième — la sécurité au
niveau ligne — est décrite ainsi dans `apps/core/rls.py` :

> réglage égal à `plateforme` → **accès transverse assumé, journalisé par l'appelant**

`contexte_plateforme()` répète la promesse dans sa propre docstring : *« il doit être justifié,
restreint aux rôles plateforme et journalisé par l'appelant »*.

À la relecture, aucune de ces trois exigences n'était tenue.

**Rien n'était journalisé.** Aucun appelant n'écrivait de trace, et il n'existait **aucun modèle
d'audit dans tout le dépôt**. La garantie était documentée et absente — le pire des deux états,
parce qu'on cesse de la chercher quand on croit l'avoir.

**Rien n'était justifié.** `contexte_plateforme()` ne prend aucun motif. Ouvrir l'accès transverse
coûtait une ligne, sans rien avoir à dire.

**Rien n'était restreint.** `droits_de()` commençait par :

```python
if utilisateur.is_superuser:
    return TOUS
```

Un booléen sur un compte donnait tous les droits sur toutes les boutiques — dont `MARGE_VOIR` et
`COUT_VOIR`, précisément les deux que le reste du fichier protège avec le plus de soin, parce qu'un
coût d'achat affiché au comptoir circule dans le quartier avant la fin de la journée.

Et le rôle prévu pour cela, `ADMIN_MARCHE`, était une coquille : `frozenset()` de droits, aucune vue
ne le consommant.

Deux faits ont rendu la question urgente plutôt que théorique.

Le premier : **l'exploitant de la place de marché est aussi commerçant sur sa propre place.** C'est
assumé et utile — ses boutiques amorcent le catalogue quand personne n'est encore inscrit. Mais avec
un accès total et sans trace, il voit les prix, les marges et les meilleures ventes de ses
concurrents. Ce n'est pas d'abord une question morale : le jour où un commerçant de Douala le
comprend, il part, et il le raconte.

Le second : **le cahier de crédit client** (docs/22, §2.1) fait entrer dans la base les dettes des
clients des commerçants. Un accès transverse non journalisé à cela n'est plus une dette technique.

## Décision

**L'accès transverse devient un geste distinct, qui se nomme, et qui laisse une trace.**

Six points, indissociables.

### 1. Deux fonctions, parce qu'il y a deux gestes

`contexte_plateforme()` reste, inchangée, pour ce qui est **technique** : la vitrine publique qui
liste les boutiques en état de vendre, les tâches de fond, les commandes d'exploitation. Ce n'est pas
un humain qui va lire les données privées d'un commerçant, c'est la façade du marché.

`acces_plateforme(utilisateur=…, motif=…, ecran=…)` est **nouvelle**, et c'est la seule voie pour un
humain qui demande à voir à travers les boutiques. Le motif n'a pas de défaut : on ne peut pas
l'appeler sans dire pourquoi.

Rien n'empêche techniquement un développeur d'appeler la première là où la seconde est due. Le
garde-fou est donc un test qui lit le code des vues et refuse `contexte_plateforme()` dans le
back-office — le même procédé que le test qui vérifie déjà la concordance entre les fiches d'aide et
les `@exige(...)` des vues, et pour la même raison : une règle qu'aucun test ne défend n'est qu'un
souhait.

### 2. `AccesPlateforme`, en ajout seul

Un modèle, non scopé par boutique — il appartient à la plateforme, pas à un commerçant. Qui, quand,
quelle boutique, quel écran, quel motif.

Et protégé par **le même déclencheur PL/pgSQL que le journal comptable** (ADR-003) : `UPDATE` et
`DELETE` rejetés au niveau de la base, y compris en SQL brut, y compris depuis un client `psql`. Un
journal d'audit qu'on peut effacer ne prouve rien — il donne seulement l'illusion d'une preuve.

Le coût est faible parce que le motif technique est déjà écrit et éprouvé.

### 3. Des droits de plateforme explicites, et le retrait du court-circuit

Cinq droits nouveaux, nommés par ce qu'ils ouvrent :

| Droit | Ce qu'il ouvre |
|---|---|
| `plateforme.boutiques` | Valider, suspendre, résilier un bail |
| `plateforme.commissions` | Fixer les taux de rayon et les taux négociés |
| `plateforme.emplacements` | Vendre et attribuer les emplacements premium |
| `plateforme.litiges` | Accéder à une commande contestée — motif obligatoire |
| `plateforme.apporteurs` | Le réseau d'affiliation et ses versements |
| `plateforme.versements` | Exécuter les versements aux marchands (ajouté avec le séquestre, ADR-013) |

**Aucun d'eux n'ouvre `MARGE_VOIR`, `COUT_VOIR`, ni le cahier d'une boutique.** J'ai listé ce que
l'exploitant fait réellement — valider une boutique, suspendre pour loyer impayé, ajuster une
commission, vendre une tête de gondole, arbitrer un litige — et rien là-dedans n'exige de lire la
marge ou la liste de clients d'un commerçant. Le rôle plateforme peut donc être étroit, et il l'est.

`droits_de()` cesse d'honorer `is_superuser` pour les droits **de boutique**. Le superutilisateur
garde `/admin/` — c'est Django, c'est le dernier recours d'exploitation, et le retirer laisserait
l'application sans issue de secours — mais il n'obtient plus la marge d'un commerçant par un booléen.

### 4. Trois niveaux d'administration, et non deux

Le premier jet de cet ADR n'en distinguait que deux — le superutilisateur et le reste — et cette
confusion coûtait cher : elle faisait du geste quotidien d'exploitation un acte de
superutilisateur.

| Qui | Comment il est marqué | Ce qu'il voit |
|---|---|---|
| **Superadministrateur** | `is_superuser` + `is_staff` | Tout, sans exception, par construction Django |
| **Administrateur du marché** | `is_staff` + `RolePlateforme(ADMIN_MARCHE)`, **sans** `is_superuser` | Ce que le groupe de permissions ouvre. Ni comptabilité, ni stock, ni cahier de crédit |
| **Gérant d'une boutique** | `Appartenance` de rôle `GERANT` | Sa boutique, entièrement. Aucune autre |

Ce ne sont pas trois degrés d'un même pouvoir, ce sont **trois métiers**. Le superadministrateur
est un recours technique : il existe pour le jour où quelque chose est cassé, et ce jour-là il doit
tout pouvoir. L'administrateur du marché est un métier quotidien : il valide des boutiques, suspend
pour loyer impayé, vend des emplacements. Le gérant tient un commerce.

**Ce qui rend la distinction opérante plutôt que déclarative :** un compte `is_staff` **sans**
`is_superuser` ne voit **rien** dans `/admin/` — Django exige une permission par modèle. La
frontière est donc une liste écrite, relue et défendue par un test
(`apps/accounts/administration.py`, `tests/test_administration.py`), et non un drapeau.

Cette liste donne à l'administrateur du marché les comptes, les rattachements, les baux, les
rayons, les emplacements premium et le réseau d'apporteurs. Elle lui refuse `accounting`,
`inventory`, `pos` — où vit le cahier de crédit —, `catalog`, `orders` et `payments`. Ce refus est
le cœur de la décision : un exploitant qui vend aussi sur sa place ne doit pas lire les chiffres de
ses concurrents par la porte de service.

La règle de suppression du projet s'y applique aussi : **on supprime ce qui n'a pas d'histoire, on
retire ce qui en a une.** Un compte porte des ventes, une appartenance dit qui tenait la caisse le
jour d'un écart de fonds, une boutique porte tout ce qu'elle a vendu — aucun des trois ne
s'efface.

### 5. Deux casquettes, deux comptes

L'exploitant qui possède des boutiques a **deux comptes distincts** : l'un administrateur de
plateforme (`is_staff`, rôle `ADMIN_MARCHE`, aucun droit de boutique), l'autre commerçant ordinaire
avec ses `Appartenance(GERANT)`.

Ce n'est pas de la bureaucratie, c'est ce qui rend le journal **lisible**. Avec un seul compte, chaque
ligne du journal est ambiguë : agissait-il comme exploitant ou comme concurrent ? Avec deux, la
question ne se pose plus — et le jour où un commerçant la pose, la réponse existe.

### 6. La console : l'écran de travail, et le motif une fois par session

`/admin/` est un recours technique, pas un écran de travail : il montre des tables, pas un marché.
Les deux administrateurs travaillent donc dans une **console dans le site** (`apps/plateforme`,
`/plateforme/`), distincte du back-office d'une boutique au premier coup d'œil — rail sombre,
sceau doré — pour qu'on ne confonde jamais « je regarde le marché » et « je suis chez un
commerçant ».

Trois règles la gouvernent.

**Ce qui se lit sans trace.** Les boutiques, les baux, les factures de loyer, les emplacements,
les rayons et les offres ne sont pas scopés : ce sont les contrats du bailleur. Les lire ne
franchit aucune barrière, et la plupart des écrans de la console n'en franchissent donc aucune.

**Ce qui se lit avec un motif.** L'activité d'une boutique — chiffre d'affaires, nombre de ventes,
dernière vente — vit dans des tables scopées. La lire passe par `acces_plateforme()`, sous un motif
choisi dans une liste fermée (plus « Autre », à préciser). Le motif est demandé **une fois pour
trente minutes**, puis rappelé en permanence dans le bandeau ; **chaque écran affiché** pendant ce
temps écrit sa ligne au journal. On a écarté le motif à chaque clic : un administrateur qui doit
justifier dix fois de suite la même consultation finit par taper « . », et un journal rempli de
points ne vaut pas mieux qu'un journal absent. Et seulement des **agrégats** : jamais la marge, le
coût, le stock détaillé ni les clients d'un commerçant.

**Chaque geste laisse une trace.** Ouvrir une boutique, la suspendre, encaisser un loyer, fixer un
taux, vendre un emplacement, nommer ou retirer un administrateur : une ligne au même journal, avec
son motif. Un test interdit `contexte_plateforme()` dans toute la console — sans dérogation
possible, contrairement au back-office.

Le superadministrateur y reçoit tous les droits de plateforme et deux écrans réservés : nommer les
administrateurs du marché, et la santé technique. Cela ne rouvre pas le court-circuit du §3 : ces
droits sont ceux du bailleur, aucun n'ouvre les chiffres d'une boutique.

## Conséquences

**Ce que cela coûte.** Un geste de plus pour l'exploitant, qui doit changer de compte pour changer de
rôle. C'est le prix de la lisibilité du journal, et il est payé une fois par session, pas par action.

**Ce que cela n'interdit pas.** L'exploitant reste commerçant sur sa place. Ce n'est pas le problème ;
le problème était de vendre sans règles écrites. Les règles sont maintenant écrites, et trois
d'entre elles sont défendues par du code plutôt que par une politique :

* un `EmplacementPremium` attribué à une boutique de l'exploitant s'enregistre **avec son tarif**,
  jamais à zéro — sinon le compte de résultat de la plateforme mentirait sur sa rentabilité réelle ;
* une commission négociée qui s'écarte du taux de l'offre exige un **motif enregistré** ;
* le taux d'un rayon ne peut pas être modifié par quelqu'un qui vend dans ce rayon.

La quatrième reste une politique, parce qu'elle ne se code pas : **publier la règle**. Un
exploitant-commerçant qui annonce d'emblée ce qu'il s'interdit est plus crédible que celui qui se
fait découvrir.

**Ce que cela a rendu possible.** La console du §6 consomme les cinq droits ci-dessus et n'a
jamais besoin du superutilisateur pour le travail quotidien. Le superadministrateur reste le recours
du jour où quelque chose est cassé — pas le compte avec lequel on valide une candidature.

## Ce qui a été écarté

**Interdire à l'exploitant d'être commerçant.** C'est le modèle choisi, il est légitime, et il est
utile au démarrage. Le conflit d'intérêts ne se supprime pas en interdisant l'activité, il se borne
en la rendant visible.

**Rendre le motif obligatoire sur `contexte_plateforme()` elle-même.** Quinze appels existants, dont
la plupart sont la vitrine publique et des tâches de fond. Exiger un motif là où il n'y a pas de
demandeur humain produit quinze chaînes de caractères inventées — c'est-à-dire un journal rempli de
bruit, qu'on cesse de lire. Un journal qu'on ne lit pas ne vaut pas mieux qu'un journal absent.

**Un journal en table scopée.** Il aurait été invisible à celui qui en a besoin : l'auditeur regarde
à travers les boutiques, par construction.
