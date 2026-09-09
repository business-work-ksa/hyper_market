# ADR-005 — Stock négatif autorisé, régularisation par inventaire

**Statut :** Actée · **Détail :** docs/09, §5 ; `apps/inventory/services.py`

---

## Contexte

Deux caisses travaillent hors ligne dans la même boutique. Toutes deux vendent le dernier sac de
ciment. Le réseau revient, les deux ventes arrivent.

Il n'y a pas de bonne réponse au niveau du logiciel, parce que **le fait s'est déjà produit** :
la marchandise est physiquement sortie, l'argent est encaissé, les deux clients sont partis avec
leur sac ou avec la promesse d'un sac. Le système n'arbitre pas un conflit futur, il enregistre
un passé.

La réaction réflexe — refuser la seconde vente pour cause de stock insuffisant — revient à
rejeter une opération déjà encaissée. La caisse afficherait une erreur sur une vente terminée,
le caissier ne saurait qu'en faire, et la vente disparaîtrait du système sans disparaître de la
réalité. C'est strictement pire qu'un compteur temporairement faux.

## Décision

**Le stock peut devenir négatif.** `sortir_stock` ne bloque jamais sur stock insuffisant. Le
niveau négatif est conservé tel quel et signalé comme une anomalie
(`NiveauStock.en_anomalie`), à charge pour le gérant de régulariser par un inventaire.

Écarté : le refus de la sortie. Écarté aussi : la réservation optimiste avec compensation — elle
suppose qu'on puisse annuler une vente déjà encaissée, ce qui n'est pas le cas au comptoir.

## Conséquences

**Un stock négatif est une information, pas un bogue.** Il dit exactement une chose : « ce qui est
sorti ne correspond pas à ce qui était entré ». Les causes sont réelles et fréquentes — vente
hors ligne non couverte, réception non saisie, vol, casse non déclarée, erreur de comptage à la
reprise. Le système les rend visibles au lieu de les masquer.

**Le calcul du coût moyen pondéré doit tenir le cas.** Une entrée sur un stock négatif ne peut pas
être pondérée par une quantité négative : cela produirait un CMP aberrant, voire négatif, qui
contaminerait ensuite toutes les sorties et donc la marge. `_cmp_apres_entree` traite le cas
explicitement : **si le stock avant est négatif ou nul, le CMP repart du coût de l'entrée.**
C'est le seul choix qui ne propage pas l'anomalie dans la valorisation.

**La régularisation est un mouvement, pas une correction.** `regulariser_inventaire` écrit un
mouvement d'ajustement par ligne en écart, valorisé au CMP courant. Le journal du stock reste en
ajout seul, comme le journal comptable : on n'efface pas l'anomalie, on écrit ce qui la corrige.

**L'écart d'inventaire devient une donnée exploitable.** Un dépôt dont les ajustements sont
systématiquement négatifs sur les mêmes références ne pose pas un problème de logiciel.

## Vérification

`tests/test_stock_cmp.py` — la sortie sur stock insuffisant passe et laisse un niveau négatif, le
CMP repart du coût d'entrée après un passage en négatif, et la régularisation d'inventaire écrit
les mouvements d'ajustement attendus.
