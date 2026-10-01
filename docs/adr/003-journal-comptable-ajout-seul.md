# ADR-003 — Journal comptable en ajout seul, contre-passation obligatoire

**Statut :** Actée · **Arbitrage :** A12 (docs/04, §10) · **Détail :** docs/07, §1

---

## Contexte

Le droit comptable OHADA n'admet pas la correction d'une écriture validée. Une erreur se corrige
par une **contre-passation** : une seconde écriture, de sens inverse, qui laisse la première
lisible. Ce n'est pas une convention de présentation, c'est ce qui rend un journal opposable —
un journal qu'on peut réécrire ne prouve rien, et le cabinet partenaire qui doit le certifier le
refusera.

La tentation inverse est constante et vient toujours du même endroit : « l'utilisateur s'est
trompé de montant, laissons-le corriger ». Elle a été proposée puis rejetée en revue de code
(docs/07, §2). Un `UPDATE` sur une écriture validée est indétectable a posteriori.

## Décision

Une écriture validée est **immuable**, et la seule correction possible est la contre-passation
(`apps/accounting/services.py`, `contrepasser`). Trois protections superposées, volontairement
redondantes :

1. **`EcritureComptable.save()`** refuse toute modification si l'écriture était validée en base.
2. **`EcritureComptable.delete()`** refuse la suppression d'une écriture validée.
3. **Un trigger PL/pgSQL** (`accounting.0003`) rejette l'`UPDATE` et le `DELETE` dans la base
   elle-même, avec un trigger jumeau sur les lignes.

La troisième n'est pas une ceinture de plus : c'est la seule qui tienne face à un `UPDATE` en SQL
brut, à un script d'exploitation, à un ORM tiers — ou à un développeur pressé. Les deux premières
donnent un message d'erreur lisible dans l'application ; la troisième donne la garantie.

Deux dérogations sont inscrites dans le trigger, et seulement deux : `contrepassee_par`, champ de
suivi qui rattache l'écriture à celle qui l'annule, et `modifie_le` qui l'accompagne. Tout le
reste — journal, exercice, boutique, date, pièce, libellé, validation, origine — est figé.

## Conséquences

**La date d'écriture doit être juste du premier coup.** C'est la conséquence qui a le plus de
portée pratique, et elle s'est manifestée d'une manière instructive : le jeu de démonstration
antidatait ses écritures après coup pour étaler les ventes sur plusieurs semaines. Il n'avait
donc jamais tourné sur PostgreSQL — seulement sur SQLite, où le trigger n'existe pas. Le
correctif n'est pas d'assouplir le trigger mais de **déclarer la date au bon moment** :
`cloturer_ticket(ticket, cloture_le=…)` prend l'heure réelle de la vente, et les écritures la
portent dès leur création.

Cela vaut bien au-delà de la démonstration. Une vente encaissée hors ligne le samedi et
transmise le lundi doit arriver **avec son heure**, pas la recevoir après coup : sinon elle
tombe dans le mauvais mois, et plus rien ne peut la déplacer.

**Une écriture s'écrit équilibrée ou pas du tout.** `passer_ecriture` refuse un déséquilibre
avant validation ; après, il serait trop tard.

**Le jeu de tests doit tourner sur PostgreSQL.** Sur SQLite, la migration est un no-op et
`tests/test_journal_ajout_seul_postgres.py` est ignoré. Une suite verte avec ces tests ignorés
ne dit rien sur l'immuabilité du journal.

## Vérification

- `tests/test_journal_ajout_seul_postgres.py` — modification et suppression rejetées par la base,
  sur une écriture validée comme sur ses lignes.
- `tests/test_comptabilite.py` — la contre-passation produit bien une écriture inverse et
  rattachée, et l'équilibre est exigé à l'écriture.
