# ADR-004 — UUIDv7 générés côté client, journal d'opérations idempotent

**Statut :** Actée · **Arbitrage :** A12 (docs/04, §10) · **Détail :** docs/09, §5

---

## Contexte

Le réseau mobile camerounais tombe. Pas rarement, pas brièvement : régulièrement, et parfois pour
la journée. Une caisse qui refuse d'encaisser sans réseau est une caisse qu'on remplace par un
carnet — et les ventes du carnet n'entrent jamais dans le système.

Le mode hors ligne pose deux problèmes distincts, qu'il faut résoudre séparément.

**L'identité.** Une vente saisie hors ligne existe : elle a des lignes, un client, un montant. Si
son identifiant n'est attribué qu'à la réception par le serveur, alors le ticket imprimé au
comptoir ne peut pas le porter, et rien ne relie le papier remis au client à l'enregistrement
qui arrivera plus tard.

**La retransmission.** Le réseau revient, la file se vide, la réponse du serveur se perd. Le
client ne sait pas si sa vente est passée. S'il retransmet, il double la vente ; s'il abandonne,
il la perd. Aucune des deux options n'est acceptable au comptoir.

## Décision

**Les identifiants métier sont des UUIDv7 générés côté client.** Une vente possède son
identifiant définitif avant d'atteindre le serveur. L'UUIDv7 plutôt que l'UUIDv4 parce qu'il est
ordonné dans le temps : sur des tables de plusieurs dizaines de millions de lignes, un v4
fragmente les index B-tree, un v7 les remplit séquentiellement.

**Chaque opération porte une clé d'idempotence** (`operation_id`), et le serveur la rejoue **au
plus une fois**. Une opération déjà appliquée renvoie le résultat précédemment produit, sans
rien réexécuter : la retransmission devient sûre, et le client peut retransmettre aveuglément
jusqu'à obtenir une réponse.

Écarté : la déduplication par comparaison de contenu (même montant, même minute, même caissier).
Deux clients peuvent légitimement acheter la même chose au même prix à la même seconde. Une
heuristique aurait supprimé des ventes réelles.

## Conséquences

**L'idempotence est arbitrée par une contrainte d'unicité en base, pas par une lecture
préalable.** C'est le point qui décide de la correction du dispositif. Deux caisses qui
retransmettent la même vente au même instant passent toutes les deux le `filter()` d'existence ;
une seule insère, l'autre reçoit une `IntegrityError` et relit la ligne gagnante. Le contrôle
applicatif est un raccourci de confort ; la contrainte est la garantie.

Le motif se répète à l'identique dans chaque service concerné :

| Endroit | Clé | Effet d'un rejeu |
|---|---|---|
| `pos.services.creer_ticket` | `Ticket.operation_id` (unique) | Renvoie le ticket existant ; si déjà clôturé, renvoie son résultat sans rejouer la vente |
| `inventory.services.enregistrer_mouvement` | `operation_id` + dépôt + variante | Renvoie le mouvement existant, sans dédoubler la sortie de stock |
| `payments.services.initier_encaissement` | `Transaction.cle_idempotence` (unique) | Renvoie la transaction existante, **sans rappeler l'opérateur** |

Le dernier est le plus important : un double appel Mobile Money coûte l'argent du client.

**La file d'attente du client doit survivre au rechargement de la page.** Elle est tenue en
IndexedDB (`static/js/hors-ligne.js`), avec une clé primaire auto-incrémentée qui garantit un
rejeu **dans l'ordre de saisie** — une entrée de stock puis la vente qui la consomme ne peuvent
pas s'inverser.

**Le client doit envoyer l'heure de l'opération, pas seulement l'opération.** Le serveur ne peut
pas la reconstituer, et le journal comptable refusera de la corriger après coup (ADR-003).

## Vérification

- `tests/test_backoffice.py`, `tests/test_stock_cmp.py` — un rejeu ne dédouble ni le ticket ni le
  mouvement de stock.
- `tests/test_paiements.py` — la même clé ne débite jamais deux fois, et la course à l'insertion
  est arbitrée par la contrainte.
- `scripts/verifier-hors-ligne.js` — quinze vérifications dans un navigateur réel : la file
  survit au rechargement, se vide au retour du réseau, mélange ventes et mouvements de stock, et
  la même clé ne crée qu'un ticket.
