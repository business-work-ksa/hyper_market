/**
 * Vérification de bout en bout du mode hors ligne.
 *
 * Ce que les tests Django ne peuvent pas prouver : que la file tient quand le
 * réseau tombe entre les mains du caissier. On coupe donc vraiment le réseau du
 * navigateur, on encaisse, et on regarde ce qui se passe.
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

  await navigateur.close();
  console.log(echecs === 0 ? '\nTout est vert.' : `\n${echecs} vérification(s) en échec.`);
  process.exit(echecs === 0 ? 0 : 1);
})();
