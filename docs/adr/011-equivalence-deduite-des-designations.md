# ADR-011 — L'équivalence entre articles se déduit, elle ne se stocke pas

**Statut :** Actée · **Détail :** `apps/catalog/equivalences.py` ; `apps/catalog/models.py` (`Designation`)

---

## Contexte

Deux comptoirs, deux scènes, la même vente perdue.

En officine, quelqu'un demande du Doliprane. La pharmacie n'en a pas, elle a de l'Efferalgan —
même molécule, même dosage, même boîte de vingt. Le vendeur le sait s'il est pharmacien et s'il a
la référence en tête ; le préparateur embauché la semaine dernière ne le sait pas.

Au comptoir des pièces détachées, un client pose un filtre à huile marqué **W 68/3**. C'est la
référence Mann. La boutique tient le même filtre sous la référence Toyota, `90915-YZZD4`. La
recherche ne donne rien, et la pièce est à deux mètres.

Dans les deux cas la marchandise est en rayon, et le système répond qu'elle n'y est pas.

Ces deux besoins sont arrivés séparément, portés par deux métiers différents, et ont d'abord été
instruits séparément : une « DCI » pour la pharmacie, des « références croisées » pour les pièces
auto. Deux tables, deux écrans, deux vocabulaires. À l'écriture, il est apparu que c'était **le
même geste** — donner à un article un nom supplémentaire sous lequel quelqu'un le cherchera — et
que seul le mot change d'un métier à l'autre.

Restait la question qui décide de la structure : comment dit-on que deux articles se valent ?

## Décision

**Une seule table, `Designation`** : `(variante, type, valeur, source)`, où `type` vaut `dci`,
`reference` (celle d'un autre fabricant) ou `commercial`. La valeur est normalisée à l'écriture —
casse et espaces multiples repliés — pour que deux saisies de la même chose soient la même chose.

**L'équivalence n'est pas stockée.** Il n'existe aucune table de paires d'articles équivalents.
Deux articles se valent **parce qu'ils portent la même désignation**, et cela se calcule au
moment où on le demande (`equivalences.equivalents_de`).

**Le nom commercial ne rapproche pas deux articles.** Seuls `dci` et `reference` entrent dans
`TYPES_EQUIVALENTS`. « Doliprane » est un autre nom du *même* article ; le poser en équivalence
proposerait au pharmacien de substituer une boîte par elle-même.

Écarté : une table `Equivalence(variante_a, variante_b)`. Elle demande **N² déclarations** — dix
génériques du paracétamol, ce sont quarante-cinq paires à saisir à la main — et surtout elle se
désynchronise au premier article ajouté : la onzième boîte n'est équivalente à rien tant que
personne n'a écrit dix lignes de plus. Une donnée qui se dégrade dès qu'on ne la nourrit pas est
une donnée qui sera fausse au bout de six mois, silencieusement.

Écarté aussi : deux mécanismes séparés, un par métier. Le code aurait doublé pour une différence
qui tient dans un intitulé de champ, et la troisième demande — les équivalents fournisseurs en
quincaillerie — aurait fabriqué un troisième.

## Conséquences

**Saisir une désignation suffit.** Renseigner la DCI d'une boîte la rattache d'un coup à toutes
celles qui la portent déjà, **et à toutes celles qui arriveront**. C'est le seul point de saisie,
et il est proportionnel au nombre d'articles, pas à son carré.

**Défaire se fait au même endroit.** Retirer la désignation défait le rapprochement. Il n'y a rien
d'autre à nettoyer, parce qu'il n'y a rien d'autre d'écrit.

**L'écran des équivalents n'est pas un tableau à gestes.** Personne ne les a saisis : il n'y a ni
correction ni suppression à y offrir. Ils sont affichés en pied de la carte des désignations, avec
la mention de ce qui les rapproche — un pharmacien ne substitue pas une boîte sur la foi d'un
écran, il vérifie.

**La recherche du stock interroge ces noms-là.** Sans cela la saisie ne servirait qu'à la fiche
article, c'est-à-dire à l'écran qu'on ouvre *après* avoir trouvé. La correspondance est faite en
sous-chaîne sur la forme normalisée : un vendeur tape ce qu'il lit, et ce qu'il lit est souvent
partiel — « 68/3 » plutôt que « W 68/3 ».

**Le coût est une sous-requête par recherche, et il est assumé.** L'appariement n'est pas gratuit
puisqu'il n'est pas précalculé. Il est borné à une boutique, indexé sur `(boutique, type, valeur)`,
et n'est même pas composé là où le métier n'active pas la fonction. Si un jour un catalogue le
justifie, la parade est une vue matérialisée — pas une table de paires à tenir à la main.

**La fonction est câblée au métier, pas offerte à tous.** `PHARMACIE` déclare `DCI`, `PIECES_AUTO`
déclare `EQUIVALENCE` ; ailleurs, ni la carte ni la porte n'existent. Un quincaillier n'a pas à
trancher une question qui ne se pose pas chez lui.

## Vérification

`tests/test_designations.py` — un article ajouté après coup rejoint ses confrères sans qu'on
redéclare quoi que ce soit ; retirer la désignation défait le rapprochement ; deux articles qui
partagent un nom *commercial* ne se valent pas ; un article n'est jamais son propre équivalent ;
la recherche du stock trouve par la désignation sans dupliquer la ligne ; et dans un métier qui
n'active pas la fonction, la carte n'est pas composée **et** la porte répond 404.
