# 06 — Affiliation, marketing et comptes revendeurs

Spécification du « lien de filiation » demandé dans l'idée initiale. Ce document définit le
modèle, les règles de calcul, les garde-fous juridiques et les mécanismes anti-fraude.

---

## 1. Les trois rôles à ne pas confondre

L'idée initiale mélange trois métiers différents. Les séparer est indispensable, car ils n'ont ni
la même rémunération, ni le même risque juridique, ni le même intérêt économique.

| Rôle | Ce qu'il fait | Porte-t-il du stock ? | Rémunération | Risque juridique |
|---|---|---|---|---|
| **Apporteur (affilié)** | Partage un lien, un code ou un QR code. Amène des acheteurs, des revendeurs ou des marchands. | Non | % de la **commission plateforme** | Faible si limité à 2 niveaux |
| **Revendeur** | Vend activement le catalogue d'autrui à son réseau, encaisse, assure le service client de premier niveau. | Non | **Marge commerciale** sur le prix HT | Nul |
| **Marchand** | Loue un emplacement, détient le stock, fixe ses prix. | Oui | Sa marge, moins loyer et commission | Nul |

Un même utilisateur peut cumuler les trois rôles. Les compteurs restent séparés.

---

## 2. Le lien de filiation

### 2.1 — Principe

Chaque compte reçoit à la création un **code d'apporteur** unique, immuable, court et prononçable
(format `HM-XXXXXX`, alphabet sans caractères ambigus : ni O/0, ni I/1). À partir de ce code, la
plateforme dérive :

- un **lien web** : `https://hypermarche.cm/r/HM-A7K3M9`
- un **QR code** imprimable (affiche, carte de visite, devanture)
- un **code oral**, saisissable à l'inscription ou dicté au livreur

### 2.2 — Profondeur : deux niveaux, jamais plus

```
        Awa  ──parraine──▶  Junior  ──parraine──▶  Sandrine  ──parraine──▶ Éric
         │                    │                       │
     [N2 de Sandrine]    [N1 de Sandrine]        [vendeur/acheteur]
         │                    │
    3 % de la          10 % de la              (Awa ne touche rien
    commission         commission               sur Éric : niveau 3)
```

**Règle absolue :** la filiation s'arrête à deux niveaux ascendants. Éric ne rémunère qu'Awa et
Junior — pas leurs propres parrains. Cette règle est **codée en dur** et non paramétrable par
l'administration, précisément pour qu'aucune décision commerciale ne puisse la contourner.

### 2.3 — Pourquoi cette limite

Un système de rémunération devient une **vente pyramidale** — prohibée et pénalement
sanctionnée — dès lors qu'il réunit ces caractéristiques :

| Caractéristique du schéma pyramidal | Choix HyperMarché |
|---|---|
| Rémunération assise sur le **recrutement** de nouveaux membres | ❌ Interdit. La commission est assise **uniquement sur du chiffre d'affaires réellement encaissé et non annulé** |
| **Droit d'entrée** ou achat obligatoire pour devenir affilié | ❌ Inscription gratuite, sans achat |
| **Stock imposé** au distributeur | ❌ Le revendeur ne porte jamais de stock |
| Profondeur de réseau illimitée | ❌ Deux niveaux maximum |
| Rémunération croissante avec la taille du réseau plutôt qu'avec les ventes | ❌ Pas de rangs, pas de titres, pas de bonus de volume d'équipe |
| Promesse de gains | ❌ Interdit dans toute communication ; seuls des gains réalisés et vérifiables sont affichés |

**Ces six lignes sont un test de conformité à repasser à chaque évolution du programme.**

---

## 3. Attribution : qui a droit à la commission

### 3.1 — Règle d'attribution

Ordre de priorité, du plus fort au plus faible :

1. **Code saisi explicitement** à la commande ou à l'inscription → priorité absolue, durée de vie
   illimitée pour l'affiliation de compte
2. **Rattachement permanent** : si l'acheteur a déjà un apporteur enregistré sur son compte, il
   reste attaché à cet apporteur pendant **12 mois** à compter de sa première commande
3. **Dernier clic non direct** : cookie de 30 jours, écrasé par un clic plus récent d'un autre
   apporteur
4. **Aucune attribution** : la commission reste intégralement à la plateforme

### 3.2 — Fenêtres

| Type d'attribution | Fenêtre | Renouvellement |
|---|---|---|
| Acheteur → apporteur | 12 mois après la 1ʳᵉ commande | Non renouvelable |
| Marchand → apporteur | 12 mois après le 1ᵉʳ loyer encaissé | Non renouvelable |
| Revendeur → apporteur | 12 mois après la 1ʳᵉ vente du revendeur | Non renouvelable |
| Clic web | 30 jours | Écrasé par un clic plus récent |

La non-reconductibilité est un choix économique : elle évite la constitution de rentes perpétuelles
qui grèveraient la marge à mesure que la base grandit.

---

## 4. Le moteur de commissions

### 4.1 — Base de calcul

Deux rémunérations, deux assiettes, **deux sources de financement différentes**. Les confondre
rend le plafond incalculable — c'est le piège classique de ces programmes.

```
Montant HT encaissé et non annulé
        │
        ├──▶ Marge marchand
        │         │
        │         └──▶ Part revendeur : marge fixée par le marchand, produit par produit
        │                               (assiette = HT vendu ; plafond = ce que le marchand consent)
        │
        └──▶ Commission plateforme (3 % à 8 % selon rayon)
                    │
                    ├──▶ Part apporteur N1 : 10 % de la commission
                    ├──▶ Part apporteur N2 :  3 % de la commission
                    │         └── cumul N1 + N2 plafonné à 35 % de la commission
                    │
                    └──▶ Marge nette plateforme (≥ 65 % de la commission)
```

**Le revendeur est payé par le marchand, l'apporteur est payé par la plateforme.** Le revendeur ne
consomme donc pas la commission de la plateforme et n'entre pas dans le plafond de 35 % ; son
propre plafond est la marge que le marchand a lui-même consentie sur chaque produit
(`Produit.marge_revendeur`, bornée à 100 % du HT par une contrainte de base de données).

**Trois invariants, testés automatiquement :**

1. Aucune rémunération d'affiliation ne s'ajoute **jamais** au prix payé par l'acheteur.
2. Le cumul des reversements **financés par la plateforme** (N1 + N2) ne dépasse **jamais 35 %** de
   la commission plateforme sur une transaction donnée. Quand le plafond mord, c'est le **parrain
   direct qui est servi en priorité** : c'est lui qui a réellement amené la vente.
3. Une commission n'existe que sur du **chiffre d'affaires encaissé** et sorti du délai de
   rétractation ou de retour.

### 4.2 — Cycle de vie d'une commission

| État | Déclencheur | Réversible ? |
|---|---|---|
| `attendue` | Commande confirmée | Oui |
| `acquise` | Livraison confirmée + délai de retour expiré (7 jours) | Oui, sur litige |
| `payable` | Solde du portefeuille ≥ seuil de retrait (10 000 F) | Oui |
| `payée` | Virement Mobile Money exécuté | Non |
| `annulée` | Commande annulée, retournée, impayée ou frauduleuse | — |
| `reprise` | Annulation postérieure à un paiement → dette imputée sur les gains futurs | — |

**Aucune commission n'est payée avant l'expiration du délai de retour.** C'est la protection
principale contre la fraude par commande fictive.

### 4.3 — Barème par rayon

| Rayon | Commission plateforme | Part N1 | Part N2 | Marge revendeur indicative |
|---|---:|---:|---:|---:|
| Cosmétique & beauté | 8 % | 10 % | 3 % | 10-12 % |
| Mode & accessoires | 8 % | 10 % | 3 % | 10-12 % |
| Quincaillerie & bricolage | 6 % | 10 % | 3 % | 7-9 % |
| Pièces détachées | 6 % | 10 % | 3 % | 7-9 % |
| Maison & décoration | 6 % | 10 % | 3 % | 8-10 % |
| Petit électronique | 4 % | 10 % | 3 % | 5-6 % |
| Électroménager | 3 % | 10 % | 3 % | 4-5 % |
| Alimentaire *(lot 4)* | 3 % | 10 % | 3 % | 4 % |

---

## 5. Le compte revendeur

### 5.1 — Ce que c'est

Le revendeur est une **force de vente distribuée**, pas un affilié passif. C'est la réponse
structurelle à deux réalités du marché : la confiance passe par les relations personnelles, et
le coût d'acquisition d'un acheteur par publicité digitale est prohibitif.

Junior, 26 ans, 3 200 contacts WhatsApp, ne veut ni stock ni trésorerie. Il veut une vitrine à
son nom, un catalogue qu'il peut partager, et voir son argent arriver sur son MoMo.

### 5.2 — Fonctionnement

1. **Inscription** en 5 minutes : téléphone, OTP, pièce d'identité, compte Mobile Money.
2. **Sélection du catalogue** : le revendeur choisit parmi les produits dont les marchands ont
   autorisé la revente. Chaque produit porte une marge revendeur définie par le marchand.
3. **Vitrine personnelle** : une mini-boutique à son nom, partageable en un lien, sans stock ni
   engagement.
4. **Prise de commande** : par sa vitrine, ou saisie manuelle pour un client qui l'a appelé.
5. **Encaissement** : par la plateforme uniquement. **Le revendeur ne manipule jamais l'argent de
   la commande** — règle anti-fraude et anti-détournement fondamentale.
6. **Commission** : créditée sur son portefeuille au statut `acquise`, retirable dès 10 000 F.

### 5.3 — Garde-fous

| Risque | Contre-mesure |
|---|---|
| Le revendeur encaisse en direct et disparaît | L'encaissement passe exclusivement par la plateforme ; aucune commande hors flux n'est commissionnée |
| Il promet des délais intenables | Les délais affichés sont ceux de la plateforme, non modifiables |
| Il casse les prix et dégrade le marchand | Prix plancher défini par le marchand ; la remise du revendeur est prise sur sa propre marge, dans une limite paramétrée |
| Il vend des produits interdits | Le catalogue autorisé est une liste blanche, jamais une liste noire |
| Il monopolise un marchand | Plafond de part de chiffre d'affaires d'un marchand issu d'un revendeur unique : alerte au-delà de 40 % |

---

## 6. Lutte contre la fraude

Le programme d'affiliation est le module le plus exposé à l'abus. Détection systématique, avec
mise en quarantaine automatique des gains.

| Schéma de fraude | Signal détecté | Action |
|---|---|---|
| **Auto-parrainage** | Même numéro, même appareil, même IP, même compte MoMo, même adresse de livraison entre parrain et filleul | Blocage de la commission, revue manuelle |
| **Comptes multiples** | Empreinte d'appareil récurrente, numéros consécutifs, création en rafale | Limitation du débit d'inscription, vérification KYC renforcée |
| **Commandes fictives** | Taux d'annulation d'un apporteur > 25 % ; livraisons systématiquement à la même adresse | Suspension du compte, reprise des gains versés |
| **Retours systématiques** | Ratio retours/ventes anormal sur un filleul | Gel du portefeuille |
| **Vol d'attribution** | Injection de code d'apporteur sur un trafic déjà attribué | Priorité au code explicite, journal d'attribution horodaté et opposable |
| **Blanchiment via commissions** | Volumes importants sans logique commerciale, retraits immédiats | Seuil de vigilance, déclaration si nécessaire |

**Plafonds de sécurité :**
- Gains d'un apporteur particulier plafonnés à **500 000 F/mois** sans vérification d'identité
  renforcée
- Aucun retrait dans les **72 h** suivant la création d'un compte
- Reprise automatique sur gains futurs en cas d'annulation postérieure au paiement

---

## 7. Marketing plateforme

### 7.1 — Outils marchands

| Outil | Description | Lot |
|---|---|---|
| Codes promo | Montant ou pourcentage, période, quota, cumul contrôlé | 1 |
| Ventes flash | Créneau horaire, prix barré, stock dédié | 2 |
| Retail media | Produits sponsorisés, bandeau de rayon, tête de gondole | 5 |
| Campagnes SMS / WhatsApp | Vers la base clients de la boutique, avec consentement | 5 |
| Paniers abandonnés | Relance automatique | 5 |

### 7.2 — Outils plateforme

| Outil | Description | Lot |
|---|---|---|
| Opérations commerciales de rayon | Financées par la plateforme ou co-financées par les marchands | 2 |
| Programme de fidélité acheteur | Points, cagnotte, statuts | 5 |
| Parrainage acheteur → acheteur | Avoir mutuel, sans commission monétaire | 2 |
| Programme cabinets comptables | Commission d'apport + interface de révision | 3 |

### 7.3 — Consentement et données personnelles

Toute sollicitation marketing exige un **consentement explicite, spécifique et non équivoque**,
recueilli séparément de l'acceptation des conditions générales, révocable en un clic et tracé
avec horodatage. La loi camerounaise 2024/017 s'applique pleinement à compter du
**23 juin 2026** — soit avant le lancement du produit. Le registre des consentements est un
objet de première classe du modèle de données, pas une case à cocher.

---

## 8. Objectifs de pilotage

| Indicateur | Cible A1 | Cible A3 | Cible A5 |
|---|---:|---:|---:|
| Apporteurs actifs (≥ 1 vente attribuée / mois) | 120 | 1 500 | 4 000 |
| Revendeurs actifs | 60 | 900 | 2 500 |
| Part du GMV attribuée à l'affiliation | 15 % | 30 % | 35 % |
| Coût d'acquisition d'un acheteur par ce canal | 1 200 F | 900 F | 750 F |
| Part des commissions reversée (plafond 35 %) | 22 % | 28 % | 30 % |
| Taux de fraude détectée sur les gains | < 4 % | < 2,5 % | < 1,5 % |

> **Comparaison :** le coût d'acquisition d'un acheteur par publicité digitale est estimé entre
> 3 500 et 6 000 F sur ce marché. Le réseau d'affiliation vise 750 à 1 200 F. C'est le principal
> gisement d'efficience du plan marketing du [business plan](03-business-plan.md).
