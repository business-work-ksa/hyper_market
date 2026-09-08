# 18 — Le produit du palier 1, écran par écran

Ce document raffine le plan du [démarrage sans capital](17-demarrage-sans-capital.md) : il dit
exactement ce qu'on installe chez les trois premiers clients, et à quoi on reconnaît que c'est
fini. Il remplace, pour cette phase, le périmètre du lot 1 du
[document 05](05-perimetre-fonctionnel.md), qui suppose une équipe financée.

---

## 1. Le produit n'est pas un logiciel, c'est une installation

Le palier 1 se vend 150 000 F d'installation puis 30 000 F par mois. **Ce que le commerçant achète
d'abord, c'est la journée où quelqu'un vient compter son stock avec lui.** Le logiciel est ce qui
reste quand cette personne repart.

Le parcours d'installation est donc le produit, et il tient en 90 minutes :

| Étape | Durée | Ce qui se passe | Ce que ça produit |
|---|---|---|---|
| 1. Compte | 5 min | Création du compte au numéro du gérant, création de la boutique | Une boutique active, un bail signé |
| 2. Catalogue | 25 min | Saisie des 20 à 60 références qui font 80 % du chiffre d'affaires — **pas tout le stock** | Produits, variantes, prix TTC |
| 3. Comptage | 35 min | Comptage physique avec le gérant, article par article, coût d'achat renseigné | Stock initial valorisé au coût réel |
| 4. Seuils | 10 min | « En dessous de combien tu recommandes ? » pour chaque référence | Alertes de réapprovisionnement |
| 5. Première vente | 10 min | Le vendeur encaisse une vraie vente, seul, pendant qu'on regarde | Un ticket, un mouvement, trois écritures |
| 6. Remise | 5 min | On montre le tableau de bord : « voilà ce que tu as gagné aujourd'hui » | L'adhésion |

> **L'étape 6 est celle qui vend l'abonnement.** Un commerçant qui voit sa marge réelle du jour
> pour la première fois ne discute plus le prix. Tout le reste du produit existe pour rendre cette
> minute possible.

**Règle de l'étape 2 :** on ne saisit jamais tout le stock à l'installation. 40 références bien
tenues valent mieux que 400 abandonnées au bout d'une semaine. Le reste se saisit au fil de l'eau.

---

## 2. Les six écrans, et rien d'autre

### 2.1 — Connexion

Identification par **numéro de téléphone**, pas par adresse électronique : c'est l'identifiant
réel d'un commerçant camerounais.

| Critère d'acceptation |
|---|
| Un gérant se connecte avec son numéro et arrive sur sa boutique sans choisir quoi que ce soit |
| Un compte sans boutique active est refusé avec un message explicite, pas une page blanche |
| La promesse produit et la mention « votre expert-comptable révise et atteste » sont visibles |

### 2.2 — Tableau de bord

Quatre indicateurs, un graphe, deux listes. **Pas douze tuiles** : un tableau de bord qui dit tout
ne dit rien.

| Bloc | Contenu | Pourquoi celui-là |
|---|---|---|
| Ventes du jour | Total TTC encaissé + écart avec la veille | La question que le gérant se pose en fermant |
| **Marge du jour** | Ventes − coût des marchandises **au CMP réel** | **L'information qu'il n'a jamais eue** |
| Valeur du stock | Somme quantité × CMP | Ce que vaut son magasin, chiffré |
| À réapprovisionner | Ruptures + sous le seuil | Le déclencheur d'action |
| Graphe 14 jours | Chiffre d'affaires quotidien, une seule série | Voir la saisonnalité de sa semaine |
| Santé du stock | Piste composite + trois articles à commander | Transformer un constat en course à faire |
| Meilleures ventes | Classement sur 14 jours | Savoir sur quoi il gagne vraiment |

| Critère d'acceptation |
|---|
| La marge affichée est lue sur les mouvements de stock réels, jamais sur un prix d'achat théorique |
| Le graphe est lisible sans JavaScript (géométrie calculée côté serveur) |
| Aucune tuile n'affiche « — » sur une boutique fraîchement installée : l'état initial est prévu |

### 2.3 — Caisse ★

**L'écran qui décide de l'adoption.** Contrainte imposée par le conseil d'experts : une ligne
saisie en moins de 4 secondes.

- grille d'articles à cibles tactiles larges, prix en évidence, stock visible ;
- recherche par libellé ou référence ; **la touche Entrée ajoute l'article s'il ne reste qu'un
  résultat visible** — c'est le comportement d'une douchette de code-barres ;
- ticket à droite (en bas sur mobile), quantité modifiable au pas-à-pas ;
- totaux HT / TVA / à payer **calculés depuis le TTC**, parce que c'est le prix affiché qui fait foi ;
- trois moyens de paiement : espèces, Mobile Money, carte ;
- **clé d'idempotence générée côté client** : une retransmission après coupure ne crée pas deux ventes.

| Critère d'acceptation |
|---|
| Un encaissement produit, en une transaction : le ticket, la sortie de stock au CMP, les écritures comptables |
| Un même `operation_id` renvoyé deux fois ne dédouble ni le ticket, ni le stock, ni les écritures |
| Un règlement incomplet est refusé avec le montant manquant |
| L'état du réseau est visible en permanence, pas découvert au moment de l'échec |

### 2.4 — Stock

Liste, recherche, trois filtres (tous / sous le seuil / rupture), valeur totale au CMP.
Chaque ligne porte son état sous forme de **puce icône + libellé** — jamais la couleur seule.

| Critère d'acceptation |
|---|
| Un stock négatif s'affiche comme une anomalie à régulariser, pas comme une erreur bloquante |
| La fiche article montre l'historique complet des mouvements, avec CMP après chaque ligne |

### 2.5 — Ventes

Journal des tickets clôturés, avec HT, TVA et total. C'est l'écran que le gérant ouvre quand il
doute d'un caissier.

### 2.6 — Comptabilité (lecture seule)

Balance générale SYSCOHADA, dernières écritures, et quatre agrégats : chiffre d'affaires, coût des
ventes, marge brute, TVA collectée.

> **Aucune saisie comptable au palier 1.** On montre ce que le système a produit tout seul. C'est
> une démonstration, pas un module de tenue — et l'écran porte la mention imposée par l'arbitrage
> A5 : *« la plateforme prépare, votre expert-comptable révise et atteste. »*

| Critère d'acceptation |
|---|
| La balance est équilibrée, et le déséquilibre serait affiché s'il survenait |
| Chaque écriture affiche son journal, sa pièce et son état — validée signifie immuable |
| Une boutique au régime **IGS** ne voit pas de TVA à déclarer |

---

## 3. Ce qui est explicitement dehors

| Hors périmètre | Quand |
|---|---|
| Vitrine publique, catalogue en ligne, panier acheteur | Palier 3 au plus tôt |
| Livraison, transporteurs, zones, preuve de livraison | Après la preuve du coût unitaire (arbitrage A7) |
| Encaissement en ligne, séquestre, portefeuille marchand | Quand on acceptera de manipuler l'argent d'autrui |
| Commission sur GMV | Le palier 1 ne facture qu'un abonnement |
| Affiliation, revendeurs, retail media | Palier 5 |
| Paie, bulletins, déclarations sociales | Bloqué par l'arbitrage A6 |
| Achats, commandes fournisseurs, réception | Palier 2 — la reprise de stock suffit d'abord |
| Multi-dépôts, transferts | Le modèle les porte ; l'interface non |

**Le code du dépôt va plus loin que cette liste** : les modèles de commandes, de paiement et
d'affiliation existent et sont testés. Ils ne sont simplement pas exposés dans l'interface. C'est
délibéré : on ne montre pas au client une fonction qu'on ne sait pas encore opérer.

---

## 4. Ce que la construction de l'interface a changé au plan

Trois enseignements de la mise en œuvre, qui modifient les documents antérieurs.

### 4.1 — La marge du jour est le vrai produit d'appel, pas le stock

Le document 04 disait « le stock crée l'usage quotidien ». Vrai. Mais en construisant le tableau
de bord, l'écran qui frappe n'est pas la liste de stock : c'est **la tuile de marge**. Le stock est
ce qu'on installe ; la marge est ce qu'on vend.

**Conséquence sur l'argumentaire commercial :** la première phrase du commercial devient
*« vous savez ce que vous avez vendu hier ; savez-vous ce que vous avez gagné ? »*, et la
démonstration commence par le tableau de bord, pas par la caisse.

### 4.2 — Le régime IGS n'est pas un cas limite, c'est le cas courant

Le [document 07](07-comptabilite-paie-syscohada.md) a été corrigé : l'IGS couvre tout le chiffre
d'affaires jusqu'à 50 M F et dispense de TVA. **Une bonne part des premiers clients ne facturera
donc pas de TVA du tout.** L'interface doit le refléter (elle le fait déjà sur l'écran
comptabilité) et le moteur de facturation devra traiter ce cas dès le palier 2, pas comme une
exception tardive.

### 4.3 — L'offre « Étal » à 15 000 F n'a pas de sens au palier 1

La grille du [business plan](03-business-plan.md) prévoit trois offres. Au palier 1, il n'y en a
qu'une : **30 000 F/mois, tout compris**. Trois offres à vendre quand on est seul, c'est trois
conversations au lieu d'une, et un client qui choisit le moins cher pour de mauvaises raisons.
La segmentation revient au palier 3, quand il y aura quelqu'un pour la porter.

---

## 5. Ce qu'on mesure chez les trois premiers clients

L'hypothèse H2 — l'adoption réelle du back-office — se teste ici, pas dans un questionnaire.

| Indicateur | Seuil | Lu où |
|---|---|---|
| Tickets encaissés par semaine et par boutique | **≥ 20** | Journal des ventes |
| Jours d'écart entre le stock théorique et le dernier inventaire | ≤ 7 | Mouvements d'ajustement |
| Part des ventes saisies à la caisse vs déclarées oralement | ≥ 80 % | Comparaison au relevé Mobile Money du gérant |
| Temps de saisie d'une ligne | < 4 s | Chronométré sur place, à l'œil |
| Connexions par semaine par le gérant lui-même | ≥ 3 | Journal d'audit |

**Si le gérant ne se connecte jamais et laisse le caissier faire, l'abonnement ne sera pas
renouvelé.** C'est le signal d'alerte le plus fiable, et il apparaît dès le deuxième mois.

---

## 6. Reste à faire avant la première installation réelle

| Chantier | Pourquoi c'est bloquant |
|---|---|
| **Mode hors ligne effectif** (PWA, file d'opérations locale) | Le serveur est prêt et idempotent ; le client, non. Sans lui, une coupure fait perdre une vente |
| **Écran de reprise de stock** | Aujourd'hui l'entrée en stock passe par la commande de démonstration ou l'admin ; il faut un écran de comptage utilisable à deux, debout dans une réserve |
| **Impression du ticket** | Imprimante Bluetooth ou envoi par WhatsApp — un client qui ne repart avec rien doute |
| **Ouverture et fermeture de caisse** | Le modèle existe, l'écran manque ; sans lui, pas d'écart de caisse, donc pas de contrôle du caissier |
| **Export intégral des données** | C'est une promesse écrite dans l'interface. Elle doit être vraie avant le premier client payant |

Ces cinq chantiers sont le contenu réel des semaines qui suivent. **Aucun ne demande d'argent, tous
demandent du temps** — ce qui est exactement la contrainte du document 17.
