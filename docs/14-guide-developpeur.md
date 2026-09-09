# 14 — Guide du développeur

Mise en route du socle technique et règles à respecter dans le code.

---

## 1. Démarrage

```bash
make installer          # environnement virtuel + dépendances
cp .env.example .env    # DEBUG=True, sinon les fichiers statiques ne sont pas servis

docker compose up -d db redis   # PostgreSQL 16 + Redis
make migrer
make demo               # référentiels + 2 boutiques de démonstration
make servir             # http://localhost:8000/
```

Sans `DATABASE_URL`, le projet bascule sur SQLite. C'est commode pour lancer les tests sans
infrastructure, **et ce n'est jamais acceptable en production** : ni les triggers qui rendent le
journal comptable inaltérable, ni les politiques d'isolation au niveau ligne ne s'y installent.
Sur SQLite, 17 tests sont ignorés — ceux qui attaquent la base par en dessous.

```bash
make tester      # 304 tests (17 ignorés sur SQLite)
make verifier    # contrôles Django + détection de migration manquante
make securite    # la barrière 3 est-elle réellement active ?
```

> **Le rôle applicatif ne doit être ni `SUPERUSER` ni `BYPASSRLS`.** Ces attributs annulent les
> politiques d'isolation **sans lever la moindre erreur** : tout fonctionne, les tests passent, et
> plus rien n'est isolé. `docker compose` s'en charge (`infrastructure/postgres/`) ; sur une base
> existante, `ALTER ROLE <role> NOSUPERUSER NOBYPASSRLS CREATEDB;`, puis `make securite`.

Comptes de démonstration (mot de passe `demo1234`) :

| Téléphone | Rôle | Ce qu'il voit |
|---|---|---|
| `+237699110011` | Gérant, Quincaillerie Ateba (Douala) | Tout |
| `+237699110022` | Caissière, Quincaillerie Ateba | Caisse, ventes, stock — **ni coût, ni marge** |
| `+237699110033` | Magasinier, Quincaillerie Ateba | Stock et coûts d'achat — **pas la marge**, pas la caisse |
| `+237677220022` | Gérante, Bella Cosmétiques (Yaoundé) | Tout |
| `+237677220033` | Comptable, Bella Cosmétiques | Comptabilité, marge, export — pas le stock |

Se connecter successivement avec ces comptes est le moyen le plus rapide de voir
ce que la matrice de droits change réellement à l'écran.

Pour l'administration : `python manage.py createsuperuser` (l'identifiant est le téléphone).

---

## 2. Structure

```
config/            réglages, urls, celery
apps/
  core/            modèles de base, tenancy, audit, synchronisation, consentements
  accounts/        utilisateurs (identifiés par téléphone), rôles, appartenances, KYC
                   permissions.py — matrice des droits, source de vérité      ★
  marketplace/     rayons, types d'emplacement, boutiques, baux, loyers
  catalog/         référentiel mutualisé, produits, variantes
  inventory/       dépôts, mouvements, CMP, inventaires   ★
  pos/             caisse, sessions, tickets                ★
  orders/          commandes, sous-commandes, retours
                   services.py — éclatement, commission figée, effets par étape
  payments/        prestataires, transactions, séquestre, portefeuilles
                   adaptateurs.py — contrat multi-PSP, disjoncteur, simulateur
  accounting/      plan SYSCOHADA, journaux, écritures, balance
  affiliation/     filiation, attribution, commissions, revendeurs
  backoffice/      vues et formulaires du back-office marchand
                   acces.py — boutique courante, dépôt courant, porte des droits
                   vues_equipe.py — embauche, rôles, retrait d'accès
                   vues_commandes.py — traitement des commandes en ligne
  api/             API REST v1 (DRF)
                   models.py — jeton porteur de la boutique (ADR-010)
                   acces.py — la même porte, les mêmes droits
  vitrine/         catalogue public, panier, tunnel de commande
                   catalogue.py — la seule porte du catalogue public
                   panier.py — panier en session, relu à chaque affichage
static/            CSS écrit à la main, service worker, file hors ligne (IndexedDB),
                   pilote d'imprimante thermique ESC/POS, icônes
templates/         gabarits Django
scripts/           captures d'écran et vérification du mode hors ligne
tests/             tests transverses (isolation, droits, CMP, comptabilité, affiliation, dépôts)
docs/              dossier projet
```

★ Briques critiques : c'est sur elles que repose tout le reste (docs/04, §9).

---

## 3. Les six règles à ne jamais enfreindre

### 3.1 — Toute donnée métier appartient à une boutique

Un modèle métier hérite de `TenantScopedModel`. Son gestionnaire par défaut est filtré sur la
boutique courante.

```python
from apps.core.tenancy import contexte_boutique, contexte_plateforme

with contexte_boutique(boutique):
    Produit.objects.count()      # borné à cette boutique

with contexte_plateforme():
    Produit.objects.count()      # accès transverse, à justifier et journaliser

Produit.objects.count()          # hors contexte : renvoie 0, jamais tout
```

**Dans les vues**, on s'appuie sur le contexte : c'est le garde-fou. **Dans les services**, on
filtre explicitement avec `objects_all_tenants` et un `boutique_id` connu : le code de confiance
sait quel tenant il manipule, et ne doit pas dépendre d'un contexte ambiant.

Attention : les gestionnaires inverses (`ticket.lignes`, `ecriture.lignes`) héritent du
gestionnaire filtré. Dans un service, préférer
`LigneTicket.objects_all_tenants.filter(ticket=ticket)`.

**Mais `objects_all_tenants` ne contourne que le gestionnaire, jamais la base.** Sur PostgreSQL,
la barrière 3 (`apps/core/rls.py`) filtre au niveau de la ligne, et un service qui n'annonce pas sa
boutique ne voit rien et n'écrit rien. Un service de confiance qui reçoit un tenant explicite
l'établit donc autour de sa transaction :

```python
def passer_ecriture(*, boutique_id, **arguments):
    with contexte_boutique(boutique_id):      # autour, jamais dedans : un SET est transactionnel
        return _passer_ecriture(boutique_id=boutique_id, **arguments)
```

Connaître son tenant ne suffit plus : il faut le déclarer.

### 3.2 — Le journal comptable est en ajout seul

Aucune écriture validée n'est modifiée ni supprimée. On corrige par contre-passation :

```python
from apps.accounting.services import contrepasser, passer_ecriture

ecriture = passer_ecriture(
    boutique_id=boutique.pk,
    code_journal="OD",
    date_ecriture=date.today(),
    libelle="Régularisation",
    lignes=[("571", Decimal("1000"), Decimal("0")),
            ("701", Decimal("0"), Decimal("1000"))],
)
contrepasser(ecriture, motif="Erreur de saisie")
```

Toute conception permettant un `UPDATE` ou un `DELETE` sur une écriture validée est **rejetée en
revue de code**. Trois protections : le code Python, un trigger PostgreSQL, une contrainte
d'équilibre.

### 3.3 — Le stock est un journal, pas un compteur

`MouvementStock` est la source de vérité ; `NiveauStock` n'est qu'un agrégat reconstructible.
Aucune écriture directe sur `NiveauStock` : tout passe par `apps.inventory.services`.

```python
from apps.inventory.services import entrer_stock, sortir_stock, transferer_stock

entrer_stock(depot=depot, variante=variante, quantite=10, cout_unitaire=Decimal("6800"))
sortir_stock(depot=depot, variante=variante, quantite=3)
```

Le stock peut devenir négatif (ADR-005) : c'est une anomalie à régulariser, pas une erreur à
bloquer. Refuser une vente déjà encaissée serait pire qu'un compteur temporairement faux.

### 3.4 — Toute opération issue du terrain porte une clé d'idempotence

La caisse fonctionne hors ligne ; une opération est retransmise autant de fois qu'il le faut. Le
serveur doit la rejouer **au plus une fois**.

```python
entrer_stock(..., operation_id=uuid_du_client)   # rejouable sans effet de bord
caisse.cloturer_ticket(ticket)                    # idempotent
```

### 3.5 — Les dépendances entre applications ne remontent jamais

`catalog` ne connaît pas `orders`. `core` ne connaît personne. La communication montante passe par
un import tardif dans un service ou par un signal de domaine, jamais par un import de module.

### 3.6 — Un écran ne décide jamais seul de ce qu'il montre

Le rattachement à une boutique n'est pas un droit sur tout ce qu'elle contient. Toute vue passe par
la porte, et tout affichage sensible lit le **même** ensemble de droits qu'elle :

```python
from apps.accounts import permissions as droit
from apps.backoffice.acces import contexte_commun, exige, exige_json

@exige(droit.STOCK_MOUVEMENTER)          # connexion + boutique + droit, avant la vue
def entree_stock(request, variante_id):
    contexte = contexte_commun(request, "stock")   # porte `droits` aux gabarits
    ...

@exige_json(droit.CAISSE_ENCAISSER)      # refus en JSON : la file hors ligne lit le code
def caisse_encaisser(request):
    ...
```

```django
{% if 'cout.voir' in droits %}<td class="num">{{ niveau.cmp|fcfa }}</td>{% endif %}
```

Deux points qui ne se négocient pas :

- **La source de vérité est `apps/accounts/permissions.py`, en code.** `Role.permissions` en base
  n'en est qu'un miroir d'affichage, jamais relu pour décider : une table modifiable à chaud n'a
  pas à pouvoir ouvrir la marge à un caissier.
- **Masquer ne suffit pas : on ne calcule pas.** Le tableau de bord d'un magasinier ne contient pas
  de marge cachée en CSS — la valeur n'est jamais mise dans le contexte. Un `display:none` voyage
  quand même sur le réseau et se lit dans la source de la page.

---

## 4. Recettes courantes

**Ouvrir une boutique de bout en bout**

```python
from apps.accounting.referentiel import initialiser_boutique

boutique = Boutique.objects.create(...)
Bail.objects.create(boutique=boutique, ..., etat=Bail.ACTIF)
initialiser_boutique(boutique)   # plan de comptes, journaux, exercice ouvert
```

**Encaisser une vente au comptoir** — une seule chaîne produit stock et comptabilité :

```python
from apps.pos import services as caisse

session = caisse.ouvrir_session(depot=depot, caissier=utilisateur)
ticket = caisse.creer_ticket(session=session)
caisse.ajouter_ligne(ticket=ticket, variante=variante, quantite=2)
ticket.refresh_from_db()
caisse.regler(ticket=ticket, moyen="especes", montant=ticket.total_ttc)
caisse.cloturer_ticket(ticket)   # → sortie de stock au CMP + 3 écritures
```

**Lire une balance**

```python
from apps.accounting.services import balance, solde_compte

balance(boutique_id=boutique.pk)
solde_compte("701", boutique_id=boutique.pk)   # chiffre d'affaires (au crédit, donc négatif)
```

---

## 5. Ce que la suite de tests protège

| Fichier | Protège |
|---|---|
| `test_isolation_tenant.py` | **Critère bloquant du lot 0** : aucun accès croisé entre boutiques, y compris par un simple compteur ou une somme |
| `test_stock_cmp.py` | Valorisation CMP, stock négatif assumé, immuabilité des mouvements, idempotence hors ligne, inventaires |
| `test_comptabilite.py` | Équilibre débit/crédit, immuabilité, contre-passation, chaîne caisse → stock → écritures, marge brute calculable |
| `test_affiliation.py` | Filiation à 2 niveaux, plafond de 35 %, séparation des sources de financement, délai de retour avant acquisition |
| `test_journal_ajout_seul_postgres.py` | Le trigger résiste au SQL brut (ignoré sur SQLite) |
| `test_rls_postgres.py` | **Barrière 3** : la base refuse ce que le code aurait pu laisser passer — isolation en SQL brut, `WITH CHECK` à l'insertion, rôle sans privilège de contournement, couverture de toutes les tables scopées |
| `test_backoffice.py` | Isolation vue par le navigateur, chaîne d'encaissement, géométrie du graphe |
| `test_backoffice_gestion.py` | Reprise de stock, inventaire, session de caisse, ticket, export |
| `test_permissions.py` | **Frontière d'exposition** : matrice des droits, porte des écrans, coût et marge absents des pages où ils n'ont rien à faire |
| `test_multi_depots.py` | Dépôt courant, transferts, quota d'ouverture, réception hors ligne idempotente, catalogue JSON |
| `test_equipe.py` | Embauche, changement de rôle, retrait d'accès — **un accès se retire, un compte ne se supprime pas** ; les garde-fous qui empêchent un gérant de se fermer la porte |
| `test_paiements.py` | Routage par préfixe, disjoncteur, **une clé d'idempotence ne débite qu'une fois**, un état terminal ne recule jamais |
| `test_api.py` | **Le jeton porte la boutique** : `X-Boutique` ne déplace rien, un ticket voisin est introuvable, retirer l'accès ferme le jeton à la requête suivante, le coût d'achat est absent — pas vide — des réponses faites à un caissier |
| `test_commandes.py` | Éclatement d'un panier multi-boutiques, **taux de commission figé à la commande**, chaque effet à son étape (écritures au paiement, stock à l'expédition, délai de retour à la livraison), retours au coût de sortie |
| `test_backoffice_commandes.py` | L'écran de traitement : un bouton périmé n'agit pas, la part d'un confrère est introuvable, refus avant expédition et retour après |
| `test_vitrine.py` | **La seule page qui lit en contexte plateforme** : ce qui est en vitrine, ce qui n'en sort pas (stock, coût), et ce que le tunnel produit — commande éclatée, parrainage figé, compte créé sans session |

Le mode hors ligne ne se teste pas là : `node scripts/verifier-hors-ligne.js` coupe réellement le
réseau du navigateur et rejoue le parcours d'un caissier en panne de connexion.

Un test qui échoue dans `test_isolation_tenant.py`, `test_permissions.py`, `test_rls_postgres.py`
ou dans les invariants d'affiliation n'est jamais « à ajuster » : c'est une règle produit ou
juridique qui vient d'être enfreinte. Dans les trois premiers cas, c'est une fuite de données.

---

## 6. API REST

Base : `/api/v1/`. Implémentation dans `apps/api/`, décision dans
[ADR-010](adr/010-jeton-d-api-porteur-de-la-boutique.md).

### 6.1 — Obtenir un jeton

```bash
python manage.py creer_jeton_api +237699110011 --libelle "Tablette du comptoir 2"
```

Le secret s'affiche **une seule fois**. La base n'en conserve qu'une empreinte SHA-256 : un jeton
perdu se remplace, il ne se retrouve pas. Il s'utilise en en-tête :

```
Authorization: Bearer hm_<préfixe>_<secret>
```

> **Le jeton porte la boutique.** Un client n'a aucun moyen d'en désigner une autre — l'en-tête
> `X-Boutique`, que le middleware lit pour le back-office, n'est pas consulté par l'API. Un
> comptable qui suit trois boutiques détient trois jetons.

### 6.2 — Points d'entrée

| Méthode | Adresse | Droit exigé |
|---|---|---|
| `GET` | `/api/v1/moi/` | *aucun* — dit qui vous êtes et ce que vous pouvez faire |
| `GET` | `/api/v1/depots/` | `stock.voir` |
| `GET` | `/api/v1/articles/` | `stock.voir` |
| `GET` | `/api/v1/stock/mouvements/` | `stock.voir` |
| `POST` | `/api/v1/stock/entrees/` | `stock.mouvementer` + `cout.voir` |
| `GET` | `/api/v1/ventes/` | `ventes.voir` |
| `POST` | `/api/v1/ventes/` | `caisse.encaisser` |
| `GET` | `/api/v1/ventes/<id>/` | `ventes.voir` |
| `GET` | `/api/v1/commandes/` | `commandes.traiter` |
| `POST` | `/api/v1/commandes/<id>/avancer/` | `commandes.traiter` |
| `GET` | `/api/v1/comptabilite/balance/` | `comptabilite.voir` |

Filtres : `?q=` et `?alerte=1` sur les articles, `?depot=`, `?variante=`, `?type=` sur les
mouvements, `?etat=`, `?depuis=` sur les ventes. Pagination `?limit=&offset=`, 50 par défaut,
200 au maximum.

**`GET /moi/` est le premier appel de tout client**, et le seul qui n'exige aucun droit. Il
existe pour la même raison que le tableau de bord composé par rôle : un client doit construire
son interface à partir de ce que le serveur autorise, plutôt qu'afficher des écrans qui
refuseront de s'ouvrir.

### 6.3 — Ce qu'un rôle ne voit pas est **absent**, pas vide

```jsonc
// GET /api/v1/articles/ vu par une caissière
{ "libelle": "Brouette galvanisée", "prix_vente": "34500.00", "quantite": "18.0000" }

// le même, vu par la gérante
{ "libelle": "Brouette galvanisée", "prix_vente": "34500.00", "quantite": "18.0000",
  "cmp": "13745.0980", "valeur_stock": "247411.76" }
```

Le champ n'est ni `null` ni vide : il n'est pas là. Un champ à `null` dirait au client qu'il
existe et l'inviterait à le demander autrement. Sur un ticket, `marge` et `cout_marchandise` sont
retirés du sérialiseur **avant** lecture — la requête qui les calcule n'a pas lieu.

Un refus nomme le droit qui manque, plutôt que de rester muet :

```json
{ "detail": "Votre rôle ne permet pas cette opération.",
  "droits_manquants": [{"code": "comptabilite.voir", "libelle": "Consulter la comptabilité"}] }
```

### 6.4 — Écrire : toujours avec une clé d'idempotence

```bash
curl -X POST http://localhost:8000/api/v1/ventes/ \
  -H "Authorization: Bearer $JETON" -H "Content-Type: application/json" \
  -d '{"operation_id": "01a08547-...", "moyen": "especes",
       "encaisse_le": "2026-01-15T10:30:00Z",
       "lignes": [{"variante": "01a08174-...", "quantite": "2"}]}'
```

`201` à la création, **`200` et `"rejoue": true`** si la même `operation_id` revient : rien n'a
été créé cette fois-ci, et un client qui compte ses créations peut s'y fier. C'est la même clé et
le même service que la caisse hors ligne (ADR-004).

`encaisse_le` porte l'heure **réelle** de la vente. À fournir pour une vente hors ligne : les
écritures comptables la portent, et le journal en ajout seul refusera de la corriger ensuite
(ADR-003).

### 6.5 — Ce que l'API ne fait pas

Elle ne réimplémente aucune règle métier. Encaisser passe par `apps.pos.services.encaisser`,
recevoir par `apps.inventory.services.entrer_stock`, lire une balance par
`apps.accounting.services.balance` — les fonctions qu'appelle le back-office. C'est la seule
façon d'éviter la dérive qui guette toute API greffée sur une application existante : une seconde
implémentation, plus simple parce qu'elle ignore un cas limite, qui produit peu à peu des données
que l'interface n'aurait jamais écrites.

Un écart de politique subsiste, et il est délibéré : **une référence inconnue dans un panier est
ignorée au comptoir et refusée par l'API.** Le caissier a le client devant lui ; un client d'API
n'a personne pour rattraper un article silencieusement absent du ticket.

Sur `POST /commandes/<id>/avancer/`, l'action envoyée est confrontée à l'état réel et un
décalage répond **409**, en nommant l'action attendue. Un client qui a lu la liste il y a dix
minutes ne doit pas pouvoir expédier une commande refusée depuis.

---

## 7. Commandes en ligne

Moteur dans `apps/orders/services.py`, écran marchand dans `apps/backoffice/vues_commandes.py`.

### 7.1 — Un panier traverse les boutiques

L'acheteur voit une commande et paie une fois ; chaque marchand ne gère que sa part. D'où
l'éclatement en `SousCommande`, qui est **l'unité de travail du marchand et l'assiette de tout le
reste** — comptabilité, commission de place, affiliation.

```python
commande = passer_commande(
    acheteur=client,
    lignes=[(brouette, Decimal("1")), (creme, Decimal("2"))],   # deux boutiques
    code_apporteur="HM-768LPW",
    operation_id=uuid_du_client,       # le double clic ne commande pas deux fois
)
marquer_payee(commande)
```

### 7.2 — Chaque effet tombe à son étape

| Étape | Effet |
|---|---|
| Commande | Éclatement, **taux de commission figé**, attribution d'affiliation figée |
| Paiement | Écritures de vente, séquestre et commission ; commissions d'affiliation à l'état *attendue* |
| Expédition | **Sortie de stock au CMP**, et son écriture |
| Livraison | Démarrage du délai de retour, au terme duquel les commissions s'acquièrent |

Un effet avancé ou retardé produit des comptes faux qu'aucun rapprochement ne rattrape, puisque
le journal est en ajout seul (ADR-003).

**Le taux de commission est recopié du bail à la commande et ne bouge plus.** Une renégociation
ne doit pas changer rétroactivement ce que la plateforme a prélevé sur des mois clos.

### 7.3 — Le stock sort à l'expédition, pas à la commande

C'est le choix le plus discutable du module, et il est assumé. Réserver le stock dès la commande
le rendrait indisponible au comptoir alors que rien n'est parti, et une réservation jamais
libérée est un stock fantôme que personne ne retrouve.

Le prix de ce choix est la survente : le comptoir peut vendre le dernier article avant que la
commande ne soit préparée. Le marchand refuse alors la sous-commande — un geste explicite plutôt
qu'un compteur silencieusement faux (ADR-005).

Deux chemins en découlent, jamais les deux à la fois :

* **avant expédition, on refuse** — rien n'est sorti, il n'y a rien à réintégrer ;
* **après expédition, on retourne** — la marchandise revient **au coût auquel elle est sortie**,
  pas au CMP du jour, qui inventerait une plus-value que rien n'a produite.

### 7.4 — La vente en ligne ne touche pas la caisse

L'argent arrive sur le séquestre de la plateforme (`5313`), qui reversera net de sa commission.
Le marchand voit une **créance**, pas de la trésorerie. La commission de place est une charge
(`632`), pas une réduction du chiffre d'affaires : confondre les deux fausserait le chiffre
d'affaires déclaré, donc la TVA.

Le reversement (`5311` / `401` / `5313`) n'est pas écrit : il a lieu quand la plateforme paie
effectivement, ce que le palier 1 ne fait pas encore.

> **Manque connu, antérieur à ce module.** Aucune **entrée** en stock n'écrit sa contrepartie
> comptable : le débit `311` / crédit `6031` de la table du document 07 §3.4 n'est pas branché,
> pas plus que le cycle d'achat `6011` + `4452` / `401`. Le compte `311` ressort donc négatif dès
> qu'on vend. Cela affecte aussi la vente au comptoir, et relève du lot 3.

---

## 8. Vitrine publique

`/marche/` — catalogue de tout le marché, panier, tunnel de commande. Implémentation dans
`apps/vitrine/`.

### 8.1 — Elle lit en contexte plateforme, et ce n'est pas une brèche

C'est le seul endroit du produit qui le fait. Il le faut : un acheteur cherche « ciment » sur
tout le marché, et les politiques d'isolation ne rendraient rien sans ce contexte.

Ce que la barrière 3 protège, ce sont les données **privées** d'un commerçant — coût d'achat,
marge, écritures, salariés. Un catalogue public n'en contient aucune : il contient ce que le
marchand a délibérément mis en vitrine, c'est-à-dire ce qu'il paie un emplacement pour montrer.

La distinction ne repose pas sur la bonne volonté de l'appelant : **elle est portée par
`apps/vitrine/catalogue.py`**, seule porte du catalogue public. Aucune vue de la vitrine n'ouvre
`contexte_plateforme()` elle-même, et aucune ne voit un `NiveauStock` ni une `EcritureComptable`.

Une conséquence pratique : **le stock n'est pas publié.** Il appartient au marchand, il varie
d'un dépôt à l'autre, et l'afficher à l'unité près reviendrait à publier le rythme de ses ventes
à ses concurrents.

### 8.2 — On ne demande l'identité qu'au moment de livrer

Le panier vit en session : demander un compte pour poser un article dedans est le moyen le plus
sûr de perdre l'acheteur. Il ne stocke que des identifiants et des quantités — un prix recopié en
session finirait par diverger de celui du marchand, et l'acheteur verrait un total en paierait un
autre.

Passer commande crée un compte si le numéro est inconnu, mais **n'ouvre aucune session** : un
numéro non vérifié ne doit pas donner accès à l'historique de son propriétaire. Et un numéro déjà
connu n'est jamais renommé par le formulaire public — ce serait une prise de contrôle discrète du
compte d'un gérant.

Le suivi est adressé par l'identifiant de la commande, pas par son numéro : `CMD-00000042`
s'incrémente, donc qui en connaît un les connaît tous.

### 8.3 — Le parrainage se capte partout, se fige une fois

`?ref=CODE` est retenu en session depuis **n'importe quelle** page — un revendeur partage le lien
d'un produit, pas celui de l'accueil. L'attribution ne se fige qu'à la commande, et une
attribution existante n'est jamais écrasée (docs/06, §6).

### 8.4 — Ce que la vitrine ne fait pas

**Elle n'encaisse pas.** La commande est enregistrée et arrive immédiatement sur l'écran de
traitement du marchand ; le paiement est constaté hors ligne, comme au comptoir. C'est la même
frontière que pour les appels d'opérateur : tant que la couche Mobile Money n'est pas écrite
contre un bac à sable, un bouton « Payer » ici serait un mensonge.

**Elle n'installe rien.** Ni service worker, ni file hors ligne : le hors-ligne est un besoin du
commerçant à son comptoir, pas du visiteur qui découvre le marché.

---

## 9. Reste à faire sur le socle

| Sujet | État | Référence |
|---|---|---|
| Appels HTTP vers MTN / Orange / Camtel | Contrat, routage, disjoncteur, idempotence et prestataire simulé écrits et testés ; **les appels réseau attendent un bac à sable d'opérateur** — ils ne seront pas écrits à l'aveugle | docs/09, §6 |
| Impression thermique hors Bluetooth LE | Le pilote ESC/POS couvre le Bluetooth basse consommation sur Chromium ; USB, Wi-Fi, SPP et iOS demandent une application native | docs/18, §9 |
| Entrée en stock et cycle d'achat en comptabilité | Le débit `311` / crédit `6031` d'une réception n'est pas écrit, ni la facture fournisseur `6011` + `4452` / `401` : le compte de stock ressort négatif | docs/07, §3.4 |
| Encaissement en ligne | La commande est passée puis payée hors ligne. Le paiement dans le tunnel attend la même chose que le socle de paiement : un bac à sable d'opérateur | docs/09, §6 |
| Reversement du séquestre au marchand | Les ventes en ligne alimentent le `5313` ; le virement `5311` / `401` / `5313` n'est pas écrit tant qu'aucun versement réel n'a lieu | docs/07, §3.2 |
| Logistique, séquestre avancé, WhatsApp, B2B | **Lot 2.** Critère de sortie : coût unitaire du dernier kilomètre prouvé (arbitrage A7) | docs/11, §5 |
| Déclaration de TVA, espace de révision du cabinet | **Lot 3.** Le socle comptable est écrit ; ce qui reste doit être validé par le cabinet partenaire sur un exercice complet | docs/11, §6 |
| RH, paie, entrepôt mutualisé | **Lot 4**, ouverture conditionnée à l'arbitrage A6 | docs/11, §7 |
| Retail media, financement de stock | **Lot 5.** Sans partenaire bancaire signé, la ligne crédit n'ouvre pas (arbitrage A3) | docs/11, §8 |

Les quatre dernières lignes ne sont pas du code en attente d'être écrit : ce sont des lots de
feuille de route, chacun avec un préalable que le projet s'est lui-même imposé. Les ouvrir avant
que leur préalable ne soit levé reviendrait à contredire les arbitrages du document 04.
