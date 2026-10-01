# 24 — Paiement en ligne : MTN MoMo et Orange Money

Ce document dit comment le paiement en ligne fonctionne, et **comment l'ouvrir pour de vrai**. Le code
est écrit ; ce qui manque ne s'écrit pas : ce sont des contrats et des clés que seul le titulaire du
compte marchand obtient.

---

## 1. Ce qui se passe quand un acheteur paie d'avance

1. Il passe commande en choisissant « Payer d'avance par Mobile Money ». Ce choix n'est proposé que
   si un moyen de paiement est **réellement ouvert** (`paiement_en_ligne.operateurs_ouverts`) : on
   n'engage pas un acheteur dans une commande qu'il ne pourrait pas régler.
2. Sa page de commande lui propose de payer le montant de ses parts prépayées. **Le numéro décide de
   l'opérateur** (préfixes du référentiel) :
   - **MTN** pousse une demande sur son téléphone ; il la valide avec son code secret ; la page se met
     à jour seule (et un bouton le fait sans JavaScript) ;
   - **Orange** le renvoie vers sa page de paiement, puis sur la page de commande.
3. L'issue arrive par la **notification** de l'opérateur, par la **page** qui interroge, ou par la
   **tâche quotidienne**. Dans les trois cas, **le statut est relu auprès de l'opérateur** : une
   notification n'est qu'une sonnette, jamais une preuve (MTN ne signe pas les siennes).
4. Un paiement réussi **du bon montant** ouvre le séquestre de chaque part (ADR-013). Un montant
   différent est signalé et n'ouvre rien : un humain tranche.

Garde-fous : une seule demande vivante par commande (deux clics ne font pas deux demandes sur le
téléphone), une clé d'idempotence par tentative, une demande non validée expire au bout de 24 heures.

## 2. Les versements aux marchands

- **MTN MoMo** : depuis la fiche d'un versement dans la console, « Envoyer par MTN MoMo » fait le
  virement par l'API de versement de MTN. Mêmes quatre yeux qu'à la main ; le versement n'est marqué
  exécuté qu'une fois MTN relu à « réussi », avec sa référence financière.
- **Orange Money** : l'offre Web Payment ne verse pas. Le versement se fait à la main chez Orange, et
  la console constate l'exécution avec la référence.

## 3. Ouvrir le paiement pour de vrai — dans cet ordre

| Étape | Qui | Quoi |
|---|---|---|
| 1 | Vous | Ouvrir un compte sur le portail développeur de MTN MoMo et y souscrire aux produits **Collections** et **Disbursements** (bac à sable). Créer l'utilisateur d'API et sa clé, avec `providerCallbackHost` = le nom d'hôte du site. |
| 2 | Vous | Ouvrir un compte sur le portail développeur d'Orange et souscrire à **Orange Money Web Payment** (Cameroun). Récupérer l'identifiant client, le secret et la clé marchand. |
| 3 | Vous | Poser les variables ci-dessous **dans Vercel** (Settings → Environment Variables), jamais dans le dépôt ni dans une conversation. |
| 4 | Équipe technique | Lancer `python manage.py essayer_prestataire mtn` puis `orange` contre les bacs à sable. **Tant que ces deux allers-retours n'ont pas réussi, on n'ouvre rien en production.** |
| 5 | Vous + partenaire | Contrat de production (MTN, Orange ou un agrégateur agréé), compte de cantonnement du séquestre chez le partenaire (docs/08, §5.2). |
| 6 | Équipe technique | Basculer les variables en production (`MTN_MOMO_ENVIRONNEMENT=mtncameroon`, `ORANGE_MONEY_CHEMIN=orange-money-webpay/cm/v1`), **retirer `PAIEMENTS_SIMULES`**, redéployer. |

### Variables d'environnement

| Variable | Exemple | Rôle |
|---|---|---|
| `URL_PUBLIQUE` | `https://hypermarche.vercel.app` | Adresse de retour et de notification. Orange refuse de démarrer sans elle. |
| `MTN_MOMO_ENVIRONNEMENT` | `sandbox` puis `mtncameroon` | |
| `MTN_MOMO_URL_BASE` | *(défaut : bac à sable)* | URL de production communiquée par MTN. |
| `MTN_MOMO_CLE_ABONNEMENT_COLLECTE`, `MTN_MOMO_UTILISATEUR_API_COLLECTE`, `MTN_MOMO_CLE_API_COLLECTE` | | Collecte. |
| `MTN_MOMO_CLE_ABONNEMENT_VERSEMENT`, `MTN_MOMO_UTILISATEUR_API_VERSEMENT`, `MTN_MOMO_CLE_API_VERSEMENT` | | Versements — **d'autres clés** : une clé de collecte volée ne permet pas de verser. |
| `ORANGE_MONEY_ID_CLIENT`, `ORANGE_MONEY_SECRET_CLIENT`, `ORANGE_MONEY_CLE_MARCHAND` | | |
| `ORANGE_MONEY_CHEMIN` | `orange-money-webpay/dev/v1` puis `…/cm/v1` | |
| `PAIEMENTS_SIMULES` | `True` en démonstration seulement | Le simulateur remplace les opérateurs, et la page le dit en toutes lettres. **Jamais avec des clés réelles.** |

## 4. Ce qui n'a pas pu être vérifié

Les deux clients HTTP (`apps/payments/operateurs.py`) sont écrits d'après les spécifications publiées
par MTN et Orange, et testés contre des réponses simulées (`tests/test_operateurs.py`). **Ils n'ont
jamais parlé à un vrai bac à sable** : c'est l'objet de l'étape 4. Points à confirmer à ce moment :

- le format exact de `X-Reference-Id` accepté par MTN (UUID v4 envoyé) ;
- la longueur maximale de `order_id` chez Orange (30 caractères envoyés) ;
- le corps exact de la notification Orange (`notif_token`, `status`, `txnid` attendus) ;
- la devise du bac à sable (EUR chez MTN, « OUV » chez Orange) et celle de production (XAF).

## 5. Limites connues

- **Frais de livraison** : ils ne sont pas répartis entre les parts d'une commande et se règlent à la
  livraison.
- **Plafond de séquestre et paiements simultanés** : deux commandes payées au même instant peuvent
  dépasser ensemble le plafond d'une boutique ; le dépassement reste de l'argent bloqué, pas de
  l'argent parti.
- **Remboursement par API** : non branché ; un remboursement ordonné se fait par versement vers le
  numéro du payeur, depuis la console.
- **Camtel** : aucune spécification publique, l'adaptateur reste une coquille.
