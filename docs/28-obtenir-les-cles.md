# 28 — Obtenir les clés et les poser dans Vercel

Ce document dit **où obtenir chaque clé** dont HyperMarché a besoin, **dans quel ordre**, et **où la
poser**. Il complète `docs/24-paiement-mobile-money.md` (paiement) et `docs/22` §2.2 bis (WhatsApp).

> **Trois règles, sans exception**
>
> 1. Une clé se pose **uniquement dans Vercel** (Settings → Environment Variables), cochée
>    **Sensitive**. Jamais dans le dépôt, jamais dans un courriel, **jamais dans une conversation**
>    — y compris avec un assistant : personne n'a besoin de la voir pour vous aider.
> 2. Une clé de **bac à sable** et une clé de **production** ne se mélangent pas. On teste avec les
>    premières ; on ne passe aux secondes qu'après un aller-retour réussi.
> 3. `PAIEMENTS_SIMULES` **ne coexiste jamais** avec des clés réelles. Le jour où les clés réelles
>    sont posées, cette variable est supprimée.

Les démarches marquées *(contrat)* demandent l'entreprise exploitante, pas une personne : RCCM,
NIU, statuts, pièce du dirigeant, RIB. Préparez ce dossier une fois, il sert aux trois opérateurs.

**État vérifié le 5 octobre 2026** sur les pages publiques des opérateurs (sources en fin de
document). Les portails changent : si un écran ne correspond plus, suivez la logique, pas le clic.

---

## 1. Les clés que vous générez vous-même (5 minutes)

Elles ne viennent d'aucun opérateur. Générez chacune **sur votre ordinateur** :

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

| Variable | Rôle | Attention |
|---|---|---|
| `SECRET_KEY` | Signe les sessions et les jetons de Django. | Une nouvelle valeur déconnecte tout le monde : c'est voulu après une fuite. |
| `CRON_SECRET` | Ferme l'adresse de la tâche quotidienne (`/taches/quotidiennes/`). Vercel l'envoie seul. | Sans elle, la tâche refuse de tourner. |
| `KYC_CLE_NUMEROS` | Empreinte des numéros de pièces d'identité (détection des doublons). | **Ne plus jamais la changer** une fois des pièces enregistrées : on perdrait la détection des doublons sur tout l'historique. Gardez-en une copie dans un coffre (gestionnaire de mots de passe). |

Et une variable qui n'est pas un secret :

| Variable | Valeur |
|---|---|
| `URL_PUBLIQUE` | L'adresse du site, avec `https://` et sans `/` final : `https://hypermarche.vercel.app`, puis votre domaine. Les opérateurs y renvoient l'acheteur et y envoient leurs notifications. |

---

## 2. MTN Mobile Money (encaisser et verser)

HyperMarché utilise deux produits MTN : **Collections** (l'acheteur paie) et **Disbursements**
(la plateforme verse au commerçant). Ce sont **deux jeux de clés distincts** : une clé de collecte
volée ne permet pas de verser.

### 2.1 Bac à sable (gratuit, immédiat)

1. Créez un compte sur **momodeveloper.mtn.com** (adresse professionnelle de préférence).
2. Menu **Products** → abonnez-vous à **Collections**, puis à **Disbursements**.
3. Dans **Profile**, chaque abonnement affiche une **Primary key** : c'est la *clé d'abonnement*
   (`Ocp-Apim-Subscription-Key`). Notez celle de Collections et celle de Disbursements.
4. En bac à sable, l'**utilisateur d'API** et sa **clé d'API** se créent par deux appels, depuis
   votre ordinateur (remplacez les valeurs entre chevrons ; l'identifiant est un UUID v4 que vous
   inventez, par exemple avec `python3 -c "import uuid; print(uuid.uuid4())"`) :

   ```bash
   # 1) créer l'utilisateur d'API — providerCallbackHost = le nom d'hôte du site, sans https://
   curl -X POST https://sandbox.momodeveloper.mtn.com/v1_0/apiuser \
     -H "X-Reference-Id: <UUID>" \
     -H "Ocp-Apim-Subscription-Key: <PRIMARY KEY COLLECTIONS>" \
     -H "Content-Type: application/json" \
     -d '{"providerCallbackHost": "hypermarche.vercel.app"}'

   # 2) obtenir sa clé d'API (réponse : {"apiKey": "…"})
   curl -X POST https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/<UUID>/apikey \
     -H "Ocp-Apim-Subscription-Key: <PRIMARY KEY COLLECTIONS>"
   ```

   Refaites les deux appels avec la Primary key de **Disbursements** et un **autre** UUID.
5. Posez dans Vercel (Sensitive) :

   | Variable | Valeur |
   |---|---|
   | `MTN_MOMO_ENVIRONNEMENT` | `sandbox` |
   | `MTN_MOMO_CLE_ABONNEMENT_COLLECTE` | Primary key de Collections |
   | `MTN_MOMO_UTILISATEUR_API_COLLECTE` | l'UUID du premier utilisateur |
   | `MTN_MOMO_CLE_API_COLLECTE` | son `apiKey` |
   | `MTN_MOMO_CLE_ABONNEMENT_VERSEMENT` | Primary key de Disbursements |
   | `MTN_MOMO_UTILISATEUR_API_VERSEMENT` | l'UUID du second utilisateur |
   | `MTN_MOMO_CLE_API_VERSEMENT` | son `apiKey` |

   `MTN_MOMO_URL_BASE` et `MTN_MOMO_DEVISE` se laissent vides : le bac à sable est le défaut (la
   devise du bac à sable est l'euro, c'est normal).
6. Redéployez, puis faites tester par l'équipe technique :
   `python manage.py essayer_prestataire mtn`. **Pas de production tant que ce test n'a pas réussi.**

### 2.2 Production *(contrat)*

1. Sur le portail développeur, connecté, lancez **Go Live** et déposez le dossier KYC de
   l'entreprise (RCCM, NIU, statuts, pièce du dirigeant, justificatif d'adresse). MTN Cameroon
   l'instruit ; comptez plusieurs semaines et un échange avec un commercial *MoMo Business*.
2. Une fois accepté, MTN vous ouvre le **Partner Portal** (gestion des accès d'API) et le tableau de
   bord de production sur **momoapi.mtn.com**.
3. Sur **momoapi.mtn.com**, relevez les **Primary keys de production** (Collections et
   Disbursements).
4. Dans le **Partner Portal** → *API Access* / *User Management* → **Create API User** : le portail
   affiche l'identifiant de l'utilisateur et, **une seule fois**, sa clé d'API. En production, ces
   utilisateurs **ne se créent pas par l'API** (contrainte KYC de MTN). Un utilisateur pour la
   collecte, un autre pour les versements.
5. Demandez à MTN l'**URL de base de production** et confirmez la **valeur d'environnement**
   (`mtncameroon` pour le Cameroun).
6. Remplacez dans Vercel : `MTN_MOMO_ENVIRONNEMENT=mtncameroon`, `MTN_MOMO_URL_BASE=<url donnée par
   MTN>`, `MTN_MOMO_DEVISE=XAF`, et les six clés par celles de production. Supprimez
   `PAIEMENTS_SIMULES`. Redéployez.

---

## 3. Orange Money (encaisser)

HyperMarché utilise **Orange Money Web Payment** : l'acheteur est redirigé vers la page de paiement
d'Orange, puis revient sur le site. Il faut **trois valeurs** : l'identifiant client, le secret
client et la **clé marchand** (*merchant key*) — cette dernière n'est **pas** la *consumer key*.

1. Créez un compte sur **developer.orange.com** au nom de l'entreprise.
2. **My apps** → **Add an app** (nom : HyperMarché) → abonnez l'application à l'API
   **Orange Money Web Payment / M Payment**, pays **Cameroun**.
3. La page de l'application affiche le **Client ID** et le **Client secret** (onglet
   *Credentials*). L'API répond d'abord en **bac à sable** (`dev`).
4. La **clé marchand** est délivrée avec le compte marchand Orange Money *(contrat)* : contrat de
   **PSE** (point de service électronique) à signer auprès d'Orange Cameroun / Orange Business ;
   comptez deux à quatre semaines de validation. Tant qu'elle n'est pas délivrée, le bac à sable
   sert à tester.
5. Posez dans Vercel (Sensitive) :

   | Variable | Valeur |
   |---|---|
   | `ORANGE_MONEY_ID_CLIENT` | Client ID |
   | `ORANGE_MONEY_SECRET_CLIENT` | Client secret |
   | `ORANGE_MONEY_CLE_MARCHAND` | Merchant key |
   | `ORANGE_MONEY_CHEMIN` | `orange-money-webpay/dev/v1` (bac à sable) |

   `URL_PUBLIQUE` est **obligatoire** : sans elle, Orange refuse de démarrer un paiement.
6. Redéployez, faites tester : `python manage.py essayer_prestataire orange`.
7. En production : `ORANGE_MONEY_CHEMIN=orange-money-webpay/cm/v1` (ou le chemin exact affiché par
   Orange pour votre application), `ORANGE_MONEY_DEVISE=XAF` ; supprimez `PAIEMENTS_SIMULES` ;
   redéployez.

Les **versements** aux commerçants partent par MTN (§ 2). Un commerçant payé sur Orange Money est
réglé à la main par un administrateur, qui saisit la référence de l'opération (écran *Versements*).

---

## 4. WhatsApp Business (avis de commande à l'équipe)

Sans ces clés, rien ne casse : la fiche de commande propose un bouton qui ouvre WhatsApp, message
déjà écrit. Avec elles, l'avis part seul.

1. **Meta Business** : créez (ou utilisez) un portefeuille sur **business.facebook.com** et faites
   **vérifier l'entreprise** (*Paramètres → Centre de sécurité → Vérification*) — documents de
   l'entreprise *(contrat)*.
2. **developers.facebook.com** → **Mes apps** → **Créer une app** → type *Business* → ajoutez le
   produit **WhatsApp**.
3. **WhatsApp → Configuration de l'API** : ajoutez un **numéro dédié** (un numéro qui n'est pas déjà
   sur l'application WhatsApp ordinaire), validez-le par SMS ou appel. La page affiche alors
   l'**identifiant du numéro de téléphone** (*Phone number ID*) — c'est `WHATSAPP_NUMERO_ID`.
4. **Jeton permanent** — le jeton affiché sur la page de test expire en 24 h, **ne l'utilisez pas** :
   *Business Settings → Utilisateurs → Utilisateurs système* → **Ajouter** (rôle *Admin*) →
   **Attribuer des éléments** : l'application WhatsApp, contrôle total → **Générer un jeton** avec
   les autorisations `whatsapp_business_messaging` et `whatsapp_business_management`, expiration
   **jamais**. Copiez-le directement dans Vercel : c'est `WHATSAPP_JETON`.
5. **Gabarit** : *WhatsApp Manager → Modèles de messages → Créer* — catégorie **Utilitaire**,
   langue **français**, nom par exemple `nouvelle_commande`, texte à **six variables**, dans cet
   ordre (numéro, boutique, articles, total, paiement, lien) :

   > Nouvelle commande {{1}} pour {{2}} : {{3}}. Total {{4}} FCFA, {{5}}. À traiter ici : {{6}}

   Attendez le statut **Approuvé** (quelques minutes à quelques heures).
6. Posez dans Vercel (Sensitive) : `WHATSAPP_JETON`, `WHATSAPP_NUMERO_ID`,
   `WHATSAPP_GABARIT_COMMANDE=nouvelle_commande`. Facultatives : `WHATSAPP_VERSION` (défaut `v21.0`),
   `WHATSAPP_LANGUE` (défaut `fr`).
7. Dans le back-office, chaque gérant coche, dans *Équipe*, qui reçoit les commandes.

Coût : Meta facture les messages *Utilitaire* envoyés hors d'une conversation ouverte par le client
— de l'ordre d'un message par commande et par personne prévenue.

---

## 5. Poser une variable dans Vercel

1. **vercel.com** → projet **hypermarche** → **Settings** → **Environment Variables**.
2. **Key** : le nom exact de la variable (majuscules). **Value** : la clé, collée directement depuis
   le portail de l'opérateur.
3. Cochez **Sensitive**. Environnement : **Production** (et *Preview* seulement pour des clés de
   bac à sable).
4. **Save**, puis **Deployments → ⋯ → Redeploy** : une variable n'est lue qu'au déploiement suivant.
5. Vérifiez sans afficher de secret : la console *Plateforme → Santé technique* dit quels réglages
   sont présents, jamais leur valeur.

Une clé **exposée** (collée dans une conversation, un courriel, une capture d'écran) se considère
comme volée : régénérez-la chez l'opérateur, remplacez-la dans Vercel, redéployez.

---

## 6. Récapitulatif

| Variable | Où l'obtenir | Délai |
|---|---|---|
| `SECRET_KEY`, `CRON_SECRET`, `KYC_CLE_NUMEROS` | Générées par vous (§ 1) | 5 min |
| `URL_PUBLIQUE` | L'adresse du site | — |
| `MTN_MOMO_*` (bac à sable) | momodeveloper.mtn.com | 1 h |
| `MTN_MOMO_*` (production) | Go Live → Partner Portal + momoapi.mtn.com | plusieurs semaines |
| `ORANGE_MONEY_ID_CLIENT`, `…_SECRET_CLIENT` | developer.orange.com → My apps | 1 h |
| `ORANGE_MONEY_CLE_MARCHAND` | Contrat PSE Orange Cameroun | 2 à 4 semaines |
| `WHATSAPP_*` | Meta Business + developers.facebook.com | 1 à 7 jours (vérification) |

### Sources consultées

- MTN MoMo — FAQ des identifiants et passage en production : <https://momoapi.mtn.com/faqs>
- MTN MoMo — clés de bac à sable et de production :
  <https://momodevelopercommunity.mtn.com/how-to-59/understanding-momo-open-api-keys-sandbox-and-production-455>
- Orange — Orange Money Web Payment / M Payment : <https://developer.orange.com/apis/om-webpay>
- Meta — démarrer avec la WhatsApp Cloud API :
  <https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started.md>
