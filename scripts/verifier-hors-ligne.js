/**
 * Vérification de bout en bout du mode hors ligne.
 *
 * Ce que les tests Django ne peuvent pas prouver : que la file tient quand le
 * réseau tombe entre les mains du caissier. On coupe donc vraiment le réseau du
 * navigateur, on encaisse, on reçoit de la marchandise, et on regarde ce qui se
 * passe.
 *
 * Le commentaire de la réception porte un horodatage : le script est rejouable
 * sur la même base sans confondre son mouvement avec celui de la fois d'avant.
 *
 *   python manage.py runserver 8000 --noreload
 *   node scripts/verifier-hors-ligne.js
 */
const { chromium } = require('playwright');

const BASE = 'http://127.0.0.1:8000';
const IDENTIFIANT = '+237699110011';
const MOT_DE_PASSE = 'demo1234';

let echecs = 0;

function verifier(intitule, condition, detail) {
  const marque = condition ? '  ok  ' : ' ÉCHEC';
  console.log(`${marque}  ${intitule}${detail ? ` — ${detail}` : ''}`);
  if (!condition) echecs += 1;
}

/**
 * Plus grand numéro de ticket visible au journal des ventes.
 *
 * On compare des numéros plutôt qu'un nombre de lignes — le journal est plafonné
 * à l'affichage — et on prend le maximum plutôt que la première ligne : le
 * journal est trié par date, et une vente encaissée à 3 h du matin s'affiche
 * sous une vente de la veille à 17 h.
 */
async function plusGrandTicket(page) {
  await page.goto(`${BASE}/ventes/`, { waitUntil: 'networkidle' });
  return page.$$eval('.tableau tbody tr td:first-child', (cellules) =>
    cellules.reduce((maxi, c) => {
      const n = parseInt(c.textContent.replace(/\D/g, ''), 10);
      return Number.isNaN(n) ? maxi : Math.max(maxi, n);
    }, 0)
  );
}

async function encaisserUnArticle(page) {
  await page.goto(`${BASE}/caisse/`, { waitUntil: 'networkidle' });
  const tuiles = await page.$$('.article-tuile');
  await tuiles[0].click();
  await page.click('#encaisser');
  await page.waitForTimeout(700);
  return page.textContent('#message-caisse');
}

(async () => {
  const navigateur = await chromium.launch();
  const contexte = await navigateur.newContext({ viewport: { width: 1440, height: 940 } });
  const page = await contexte.newPage();

  await page.goto(`${BASE}/connexion/`);
  await page.fill('#telephone', IDENTIFIANT);
  await page.fill('#mot_de_passe', MOT_DE_PASSE);
  await Promise.all([page.waitForURL(`${BASE}/`), page.click('button[type=submit]')]);

  const avant = await plusGrandTicket(page);

  // --- 1. Vente en ligne : elle part tout de suite --------------------------
  let message = await encaisserUnArticle(page);
  verifier('une vente en ligne est transmise immédiatement', /encaissé/.test(message), message.trim());
  verifier(
    'la file est vide après une vente en ligne',
    (await page.evaluate(() => window.FileVentes.enAttente())) === 0
  );

  // --- 2. Réseau coupé : la vente est conservée ----------------------------
  await contexte.setOffline(true);
  message = await encaisserUnArticle(page);
  verifier('hors ligne, la vente est conservée', /conservée/.test(message), message.trim());

  let enAttente = await page.evaluate(() => window.FileVentes.enAttente());
  verifier('la file contient la vente hors ligne', enAttente === 1, `${enAttente} en attente`);

  await encaisserUnArticle(page);
  enAttente = await page.evaluate(() => window.FileVentes.enAttente());
  verifier('une seconde vente hors ligne s\'empile', enAttente === 2, `${enAttente} en attente`);

  // --- 3. La file survit à un rechargement ---------------------------------
  await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => {});
  await page.waitForTimeout(400);
  enAttente = await page.evaluate(() => window.FileVentes.enAttente());
  verifier(
    'la file survit au rechargement de la page',
    enAttente === 2,
    `${enAttente} en attente`
  );

  // --- 4. Retour du réseau : la file se vide seule --------------------------
  await contexte.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await page.waitForTimeout(2500);

  enAttente = await page.evaluate(() => window.FileVentes.enAttente());
  verifier('la file se vide au retour du réseau', enAttente === 0, `${enAttente} restantes`);

  const apres = await plusGrandTicket(page);
  verifier(
    'les trois ventes sont arrivées au serveur',
    apres === avant + 3,
    `ticket ${avant} → ${apres}`
  );

  // --- 5. Idempotence : rejouer la file ne double rien ---------------------
  await page.goto(`${BASE}/caisse/`, { waitUntil: 'networkidle' });
  const resultat = await page.evaluate(async () => {
    const tuile = document.querySelector('.article-tuile');
    const charge = {
      operation_id: crypto.randomUUID(),
      lignes: [{ variante: tuile.dataset.id, quantite: 1 }],
      moyen: 'especes',
    };
    const un = await window.FileVentes.encaisser(charge);
    const deux = await window.FileVentes.encaisser(charge); // même clé
    return [un, deux];
  });
  verifier(
    'la même clé d\'idempotence ne crée qu\'un ticket',
    resultat[0].corps.numero === resultat[1].corps.numero && resultat[1].corps.rejoue === true,
    `${resultat[0].corps.numero} / ${resultat[1].corps.numero}`
  );

  // --- 6. Catalogue hors ligne ---------------------------------------------
  // Une page servie depuis le cache fige aussi son catalogue : la grille est
  // donc reconstruite à partir de celui rangé dans IndexedDB.
  const variante = await page.$eval('.article-tuile', (t) => t.dataset.id);

  await contexte.setOffline(true);
  await page.goto(`${BASE}/caisse/`, { waitUntil: 'domcontentloaded' }).catch(() => {});
  await page.waitForTimeout(900);

  const tuilesHorsLigne = await page.$$eval('.article-tuile', (t) => t.length);
  verifier(
    'la caisse affiche son catalogue sans réseau',
    tuilesHorsLigne > 0,
    `${tuilesHorsLigne} article(s)`
  );
  verifier(
    'la fraîcheur du catalogue est annoncée',
    await page.$eval('#etat-catalogue', (n) => !n.hidden).catch(() => false)
  );

  // --- 7. Réception de marchandise hors ligne ------------------------------
  // Jusqu'ici, seules les ventes étaient en file : une réception saisie pendant
  // la coupure était perdue, et le camion, lui, était bien reparti.
  await contexte.setOffline(false);
  await page.goto(`${BASE}/stock/${variante}/entree/`, { waitUntil: 'networkidle' });
  await contexte.setOffline(true);

  const motif = `Bon de livraison ${Date.now()}`;
  await page.fill('#id_quantite', '5');
  await page.fill('#id_cout_unitaire', '1000');
  await page.fill('#id_commentaire', motif);
  await page.click('#valider-entree');
  await page.waitForTimeout(700);

  verifier(
    'hors ligne, la réception est conservée',
    /conservée/.test(await page.textContent('#message-entree')),
    (await page.textContent('#message-entree')).trim()
  );
  verifier(
    'la file mélange ventes et mouvements de stock',
    (await page.evaluate(() => window.HorsLigne.enAttente())) === 1
  );

  await contexte.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await page.waitForTimeout(2500);

  verifier(
    'la réception part au retour du réseau',
    (await page.evaluate(() => window.HorsLigne.enAttente())) === 0
  );

  await page.goto(`${BASE}/stock/${variante}/`, { waitUntil: 'networkidle' });
  verifier(
    'le mouvement est bien inscrit au journal du stock',
    (await page.content()).includes(motif.slice(0, 24))
  );

  await navigateur.close();
  console.log(echecs === 0 ? '\nTout est vert.' : `\n${echecs} vérification(s) en échec.`);
  process.exit(echecs === 0 ? 0 : 1);
})();
