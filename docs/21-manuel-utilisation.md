# 21 — Manuel d'utilisation

> **Pour qui :** le commerçant et son équipe — gérant, caissier, vendeur, magasinier, comptable.
> Pas les développeurs : leur porte d'entrée est le
> [guide du développeur](14-guide-developpeur.md).
>
> **Comment il est organisé :** par **journée de travail**, pas par menu. Un manuel qui suit la
> barre de navigation est une liste de boutons ; celui-ci suit ce qu'on fait réellement, dans
> l'ordre où on le fait.
>
> **Et dans le logiciel :** le bouton ⓘ de l'en-tête de chaque écran ouvre l'aide de cet
> écran-là — brève, et disponible même sans réseau. Ce manuel-ci est l'autre moitié : il se lit
> une fois, posément. L'aide en ligne répond debout, au milieu d'un geste.

---

## 1. Se connecter

L'identifiant est un **numéro de téléphone**, celui qui a été déclaré à l'inscription. Pas
d'adresse e-mail : dans une boutique, le numéro est ce que tout le monde connaît déjà.

Après la connexion, chacun arrive **sur le premier écran qu'il peut réellement utiliser**. Gérant,
magasinier et comptable ouvrent sur le tableau de bord ; caissier et vendeur ouvrent directement
sur la caisse. Personne n'atterrit sur un écran dont toutes les tuiles lui seraient fermées.

**Si vous vous trompez dix fois de mot de passe**, le compte se ferme **un quart d'heure**, puis se
rouvre tout seul. Rien à demander à personne. C'est ce qui empêche quelqu'un d'essayer des milliers
de mots de passe sur votre numéro — et le message à l'écran le dit clairement, au lieu de laisser
croire à une panne.

**Mot de passe oublié ?** Le gérant le régénère depuis **Ma boutique › Équipe** et vous le remet en
main propre. Il n'y a pas d'envoi par SMS : sans passerelle, ce serait une promesse qu'on ne peut
pas tenir. Le gérant, lui, change le sien depuis son compte.

---

## 2. Pourquoi votre écran n'est pas celui du voisin

Ce n'est pas un réglage d'affichage : **ce qui ne vous est pas ouvert n'est pas calculé**. Un
caissier ne voit pas la marge parce que la marge n'est jamais envoyée à son écran.

La raison est concrète : le coût d'achat d'un article, affiché sur un écran ouvert au comptoir,
circule dans le quartier avant la fin de la journée.

| | Gérant | Caissier | Vendeur | Magasinier | Comptable |
|---|:--:|:--:|:--:|:--:|:--:|
| Tableau de bord | ✓ | | | ✓ | ✓ |
| Encaisser | ✓ | ✓ | ✓ | | |
| Voir le stock | ✓ | ✓ | ✓ | ✓ | |
| Recevoir, inventorier, transférer | ✓ | | | ✓ | |
| Journal des ventes | ✓ | ✓ | ✓ | | ✓ |
| Commandes en ligne | ✓ | | ✓ | ✓ | |
| Comptabilité | ✓ | | | | ✓ |
| **Coûts d'achat** | ✓ | | | ✓ | ✓ |
| **Marge** | ✓ | | | | ✓ |
| Ma boutique | ✓ | | | | ✓ (lecture) |
| Équipe et dépôts | ✓ | | | | |
| Export des données | ✓ | | | | ✓ |

Le **coût** et la **marge** sont deux droits séparés, et ce n'est pas un détail : le magasinier
saisit des prix d'achat, il lui faut le premier ; il n'a aucune raison d'accéder au second.

Deux autres rôles existent, plus étroits : **RH** (fiche de la boutique seulement) et **cabinet
comptable** (ventes, comptabilité, coûts et export — pas le stock, pas l'équipe). Une même personne
peut cumuler des rôles, et ses droits s'additionnent ; elle peut aussi être gérante dans une
boutique et caissière dans une autre, les droits étant toujours calculés **pour la boutique
ouverte**.

---

## 3. La journée d'un caissier

### Ouvrir la caisse

Avant la première vente : **Caisse › Ouvrir la session**, et saisir le **fonds de caisse** — les
espèces présentes dans le tiroir. C'est ce chiffre qui rendra l'écart lisible le soir.

### Encaisser

Cherchez l'article par son nom, sa référence ou en scannant son code-barres, ajoutez-le au panier,
choisissez le moyen de règlement : **espèces**, **Mobile Money**, **carte bancaire** ou **à
crédit**.

Le ticket est numéroté, imprimable, et la vente est immédiatement inscrite au stock et à la
comptabilité. Vous n'avez rien d'autre à faire : pas de double saisie le soir.

### Quand le réseau tombe

**Continuez à encaisser.** C'est prévu, et c'est le cas le plus fréquent, pas l'exception.

Les ventes sont gardées sur l'appareil et repartent seules dès que le réseau revient. Le catalogue
reste consultable — il a été mis de côté pour cela. Un bandeau indique que vous êtes hors ligne et
combien de ventes attendent.

Trois choses à savoir :

- **une vente enregistrée n'est jamais perdue.** Elle part, ou elle attend. Elle ne disparaît pas ;
- **les ventes repartent dans l'ordre**, pour que la numérotation des tickets reste juste ;
- **ne fermez pas l'application tant que le bandeau annonce des ventes en attente.** Elles
  survivent à une fermeture, mais elles ne repartiront qu'à la réouverture.

### Imprimer le ticket

Sur **Android avec Chrome** et une **imprimante Bluetooth**, le bouton *Imprimer* parle directement
à la bobine. Il faut appuyer sur le bouton : le navigateur exige un geste, la page ne peut pas se
connecter seule.

Sur **iPhone**, ou avec une imprimante USB ou Wi-Fi, cela ne fonctionne pas — aucun navigateur iOS
n'ouvre le Bluetooth aux pages web. Reste l'impression classique du navigateur, ou l'envoi du
ticket par WhatsApp.

### Fermer la caisse

Le soir : **comptez les espèces du tiroir, puis saisissez le montant**. Dans cet ordre — et c'est
une discipline, pas une contrainte technique.

L'écran affiche en effet le **théorique en caisse** (fonds d'ouverture + ventes en espèces) à côté
du champ de saisie. Le formulaire vous demande de compter d'abord, mais rien ne vous en empêche :
un chiffre qu'on a sous les yeux est un chiffre qu'on recopie, et un écart recopié n'existe pas.

L'écart est pourtant ce qui a de la valeur : il se voit, il se discute, il se corrige. Comptez
avant de regarder.

---

## 4. La journée d'un magasinier

### Recevoir de la marchandise

**Stock › l'article › Entrée de stock.** Saisissez la quantité reçue et le **coût d'achat
unitaire**.

Ce coût n'est pas décoratif : il recalcule le **coût moyen pondéré**, qui sert ensuite à valoriser
tout le stock et à calculer la marge de chaque vente. Un coût saisi de travers fausse la marge
pendant des mois, sans que rien ne le signale.

Une réception saisie pendant une coupure réseau **n'est pas perdue** : elle attend comme une vente,
et repart au retour du réseau.

### Compter le stock

**Stock › Inventaire.** Saisissez les quantités réellement comptées ; l'écran chiffre les écarts et
écrit un mouvement d'ajustement pour chaque ligne qui diffère.

Un écart **n'est pas effacé** : il est écrit. Un dépôt dont les ajustements sont toujours négatifs
sur les mêmes références ne pose pas un problème de logiciel.

### Transférer entre dépôts

**Stock › l'article › Transférer**, si votre boutique a plus d'un dépôt. Le transfert sort d'un
dépôt et entre dans l'autre, au coût moyen d'origine : déplacer de la marchandise ne crée pas de
valeur.

---

## 5. La journée d'un gérant

### Le tableau de bord

Ventes du jour, marge du jour, valeur du stock, articles à réapprovisionner. Le graphique couvre
quatorze jours. Les tuiles à droite disent **ce qu'il faut commander en priorité** — en rupture
d'abord, sous le seuil ensuite.

### Ajouter un article

**Stock › Nouvel article.** Le formulaire s'adapte à votre métier : une pharmacie se voit proposer
une date de péremption et un numéro de lot, un magasin de pièces une référence constructeur. Ce qui
n'a pas de sens chez vous n'apparaît pas.

Le **seuil d'alerte** est ce qui déclenchera l'avertissement de réapprovisionnement. Le poser à
zéro revient à ne jamais être prévenu.

### L'équipe

**Ma boutique › Équipe.** Ajouter quelqu'un, changer son rôle, régénérer son mot de passe, ou lui
retirer l'accès.

Retirer un accès **ne supprime pas la personne** : ses ventes passées restent à son nom, sinon le
journal des ventes deviendrait muet. Et le logiciel refuse de retirer le dernier gérant — y compris
quand on sélectionne plusieurs personnes d'un coup, en vérifiant ce qui resterait **après** tout le
lot.

### Les commandes en ligne

**Commandes.** Chaque commande avance par étapes : *en attente → acceptée → préparée → expédiée →
livrée*. Chaque étape a son effet — c'est à l'expédition que le stock sort réellement.

### La comptabilité

**Comptabilité.** Les écritures SYSCOHADA sont générées à chaque vente : il n'y a rien à saisir.
L'écran montre la balance et les dernières écritures.

> **Ce que la plateforme fait, et ce qu'elle ne fait pas.** Elle **prépare** votre comptabilité.
> Elle ne la certifie pas. Un expert-comptable la révise et l'atteste — les chiffres réglementaires
> (TVA, CNPS, IRPP) doivent être validés par un professionnel avant tout usage fiscal.

### Emporter ses données

**Ma boutique › Exporter.** Une archive ZIP, en CSV, ouvrable dans Excel : catalogue, stock,
mouvements, ventes, détail des ventes, exemplaires suivis, désignations, écritures comptables.

Intégral, gratuit, à tout moment, **y compris si vous résiliez**. Ce n'est pas une faveur, c'est
écrit dans le contrat de bail.

---

## 6. Les gestes communs à toutes les listes

Chaque tableau porte la même barre d'outils : **créer**, **modifier**, **supprimer**, **filtrer**.

- **Sélectionnez une ligne** et la barre dit ce qu'elle va faire d'elle, nommément.
- **On ne modifie qu'une ligne à la fois.** Deux lignes n'ont pas la même correction à apporter ;
  le bouton se grise **en disant pourquoi** plutôt que de laisser croire à une panne.
- **On supprime autant de lignes qu'on veut.** Faire le ménage est justement le geste qui en
  concerne plusieurs.

### La règle qui gouverne toutes les suppressions

**On supprime ce qui n'a pas d'histoire, on retire ce qui en a une.**

Une référence créée par erreur il y a trois minutes disparaît vraiment. Un article vendu l'an
dernier est **retiré de la vente**, pas effacé : effacer son libellé rendrait muets des tickets
imprimés et des écritures validées.

Le logiciel tranche ligne par ligne, l'annonce **avant** — sur la ligne et dans la confirmation —
et dit **après** lequel des deux il a fait. La confirmation **nomme** les lignes plutôt que de les
compter : un « tout sélectionner » trop large se voit avant d'être appliqué.

### Les filtres

Ils vivent **dans l'adresse de la page**. Elle se partage, se met en favori, survit à un retour en
arrière. Deux personnes qui ouvrent le même lien voient la même liste.

Les journaux en ajout seul — ventes, écritures, mouvements — n'offrent que les filtres, et disent
pourquoi.

---

## 7. Ce que votre métier ajoute

Une boutique déclare **ce qu'elle vend**, et l'interface suit. Seul ce qui vous concerne apparaît.

**Dates de péremption** *(pharmacie, cosmétique, restauration, boulangerie, produits frais)* — un
écran **Péremptions** sépare ce qui est déjà perdu de ce qu'on peut encore écouler. Les sorties
consomment **le lot le plus proche de périmer**, jamais le plus récent.

**Numéro de lot** *(pharmacie, cosmétique)* — saisi à la réception, suivi lot par lot. Le lot ne
porte pas de coût : la valorisation reste au coût moyen pondéré, le lot répond seulement à « quoi
périme quand ».

**Ordonnances** *(pharmacie)* — un médicament marqué *sur ordonnance* disparaît de la vente en
ligne, et la caisse réclame le prescripteur. Une vente arrivée sans mention **n'est pas refusée** :
la boîte est partie avec le client, et la refuser n'effacerait que la trace. L'écran
**Ordonnancier** remonte ce qui reste à consigner.

**Équivalents** *(pharmacie)* — saisissez la **dénomination commune internationale** d'une boîte et
elle rejoint d'un coup toutes celles qui portent la même molécule, y compris celles qui arriveront
demain. Aucune paire à déclarer. Le client demande du Doliprane, vous voyez l'Efferalgan.

**Références croisées** *(pièces auto)* — même mécanisme : le client pose un filtre marqué
« W 68/3 », vous le tenez sous la référence Toyota, la recherche les rapproche. On cherche aussi
**par la voiture du client** : marque, modèle, année. Une compatibilité sans modèle couvre toute la
marque ; une année absente ne borne rien.

**Numéros de série et garantie** *(électronique)* — relevez l'IMEI à la réception, la caisse le
réclame, et l'écran **Garantie** dit ensuite d'où vient l'appareil, à qui il a été vendu, si la
garantie court, et ses passages à l'atelier. **L'échéance est figée le jour de la vente** : ramener
la garantie du catalogue de douze à six mois vaut pour les ventes futures, pas pour les engagements
déjà pris.

**Fiches techniques** *(restauration, boulangerie)* — une fiche dit ce qu'il faut pour une fournée,
et **produire sort réellement les ingrédients du stock**. Le produit fini entre à exactement ce que
les ingrédients ont coûté. Le coût de revient est recalculé sur les prix du jour : un boulanger qui
fixe son prix sur la farine du mois dernier vend à perte sans le voir. Un invendu sort en **perte**,
jamais en écart de comptage.

**Vente au poids** *(quincaillerie, boulangerie, produits frais)* — quantités décimales, vente au
kilo, au litre ou au mètre.

**Déclinaisons** *(mode, cosmétique, électronique)* — taille, couleur, contenance d'un même modèle.

---

## 8. Ce que le logiciel refuse de faire, et pourquoi

Ces refus ne sont pas des pannes. Les connaître évite de chercher un bouton qui n'existera jamais.

**On ne modifie pas une écriture comptable.** Le journal est en **ajout seul** : la base elle-même
refuse. Une erreur se corrige par une écriture qui la contredit, comme sur un livre de comptes
papier. C'est ce qui rend vos comptes opposables.

**On ne corrige pas une quantité en la retapant.** Une quantité n'est pas un attribut, c'est
l'addition de mouvements. On la corrige par un **autre mouvement** — une entrée, ou un inventaire.
L'écran de modification d'un article ne propose donc pas de champ « quantité ».

**Le stock peut devenir négatif, et c'est voulu.** Deux caisses hors ligne vendent le dernier sac de
ciment : la marchandise est sortie, l'argent encaissé, les clients partis. Refuser la seconde vente
reviendrait à rejeter une opération déjà faite. Le négatif est signalé comme une anomalie et se
régularise par un inventaire — un compteur temporairement faux vaut mieux qu'une vente effacée.

**Un exemplaire vendu ne s'efface pas.** Il est cité par un ticket et porte une garantie due à
quelqu'un. Un IMEI mal recopié et jamais vendu, lui, disparaît sans problème.

**Le dernier gérant ne peut pas être retiré.** Sinon plus personne n'ouvre la boutique.

---

## 9. Quand quelque chose ne va pas

| Ce que vous voyez | Ce qui se passe |
|---|---|
| « Trop d'essais sur ce numéro » | Dix mots de passe faux. Attendez un quart d'heure, cela se rouvre seul. |
| Un bandeau « hors ligne » | Normal. Continuez à encaisser, tout repartira seul. |
| Des ventes « en attente » | Elles attendent le réseau. Ne fermez pas l'application. |
| Le bouton *Imprimer* ne fait rien | iPhone, imprimante USB/Wi-Fi, ou page non sécurisée. Voir §3. |
| Un bouton grisé | Survolez-le : il dit pourquoi. Le plus souvent, aucune ligne n'est sélectionnée. |
| Une liste vide alors qu'elle ne devrait pas l'être | Un filtre est encore posé. La pastille de la barre d'outils les compte. |
| « Cet article a déjà bougé en stock » | Il sera **retiré de la vente**, pas supprimé. Voir §6. |

---

## 10. Vos données vous appartiennent

Trois promesses, tenues par le code et non par la page commerciale :

**L'export est intégral et gratuit**, à tout moment, y compris en cas de résiliation.

**Votre boutique ne voit que ses propres données.** Trois barrières indépendantes le garantissent,
dont une posée dans la base elle-même — celle qui tient même face à une erreur de programmation. Le
serveur **refuse de démarrer** si cette barrière n'est pas en place.

**Suspendre n'est pas supprimer.** Une boutique en retard de loyer disparaît de la vitrine mais
garde son back-office : couper la gestion d'un commerçant reviendrait à lui couper l'accès à sa
propre comptabilité.
