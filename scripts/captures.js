/**
 * Captures d'écran du back-office : chaque page, en clair et en sombre, plus
 * deux vues mobiles.
 *
 * Le validateur de palette contrôle la couleur ; il ne voit ni les collisions
 * d'étiquettes, ni les débordements. Ces captures sont le seul moyen de les
 * attraper (docs/19, §8).
 *
 *   python manage.py runserver 8000 --noreload   # redémarrer si le Python a changé
 *   node scripts/captures.js
 */
const path = require('node:path');
const { chromium } = require('playwright');

const BASE = 'http://127.0.0.1:8000';
const SORTIE = path.join(__dirname, '..', 'captures');

const PAGES = [
  { nom: 'tableau-de-bord', url: '/' },
  { nom: 'caisse', url: '/caisse/' },
  { nom: 'caisse-session', url: '/caisse/session/' },
  { nom: 'stock', url: '/stock/' },
  { nom: 'stock-nouvel-article', url: '/stock/nouvel-article/' },
  { nom: 'stock-inventaire', url: '/stock/inventaire/' },
  { nom: 'ventes', url: '/ventes/' },
  { nom: 'comptabilite', url: '/comptabilite/' },
  { nom: 'boutique', url: '/boutique/' },
];

async function connecter(page) {
  await page.goto(BASE + '/connexion/', { waitUntil: 'networkidle' });
  await page.fill('#telephone', '+237699110011');
  await page.fill('#mot_de_passe', 'demo1234');
  await Promise.all([page.waitForURL(BASE + '/'), page.click('button[type=submit]')]);
}

(async () => {
  const navigateur = await chromium.launch();

  for (const theme of ['light', 'dark']) {
    const contexte = await navigateur.newContext({
      viewport: { width: 1440, height: 940 },
      deviceScaleFactor: 2,
      colorScheme: theme,
      locale: 'fr-FR',
    });
    const page = await contexte.newPage();
    await page.goto(BASE + '/connexion/');
    await page.evaluate((t) => localStorage.setItem('hm-theme', t), theme);

    // Page de connexion
    await page.goto(BASE + '/connexion/', { waitUntil: 'networkidle' });
    await page.screenshot({ path: `${SORTIE}/connexion-${theme}.png` });

    await connecter(page);

    for (const p of PAGES) {
      await page.goto(BASE + p.url, { waitUntil: 'networkidle' });
      await page.waitForTimeout(280);

      if (p.nom === 'caisse') {
        // Un ticket en cours : l'écran vide ne montre pas ce que fait le produit.
        const tuiles = await page.$$('.article-tuile');
        for (const i of [0, 2, 1, 2]) {
          if (tuiles[i]) await tuiles[i].click();
        }
        await page.waitForTimeout(180);
      }
      if (p.nom === 'tableau-de-bord') {
        // L'info-bulle se déclenche sur mouseenter/mousemove : on dispatche
        // directement, la zone SVG transparente n'étant pas survolable par
        // Playwright.
        await page.evaluate(() => {
          const zone = document.querySelector('.zone-survol[data-rang="10"]');
          if (!zone) return;
          const cadre = zone.getBoundingClientRect();
          zone.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
          zone.dispatchEvent(new MouseEvent('mousemove', {
            bubbles: true,
            clientX: cadre.left + cadre.width / 2,
            clientY: cadre.top + cadre.height * 0.55,
          }));
        });
        await page.waitForTimeout(250);
      }

      await page.screenshot({ path: `${SORTIE}/${p.nom}-${theme}.png` });
    }
    await contexte.close();
  }

  // Mobile — la caisse est utilisée debout, sur un téléphone d'entrée de gamme.
  const mobile = await navigateur.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    colorScheme: 'light',
    locale: 'fr-FR',
  });
  const pm = await mobile.newPage();
  await connecter(pm);
  await pm.goto(BASE + '/', { waitUntil: 'networkidle' });
  await pm.waitForTimeout(250);
  await pm.screenshot({ path: `${SORTIE}/mobile-tableau-de-bord.png` });

  await pm.goto(BASE + '/caisse/', { waitUntil: 'networkidle' });
  const t = await pm.$$('.article-tuile');
  for (const i of [0, 1]) { if (t[i]) await t[i].click(); }
  await pm.waitForTimeout(250);
  await pm.screenshot({ path: `${SORTIE}/mobile-caisse.png` });

  // Le ticket imprimable : format bande, sur la dernière vente clôturée.
  await pm.goto(BASE + '/ventes/', { waitUntil: 'networkidle' });
  const lienTicket = await pm.$('.tableau tbody tr a[href*="/ticket/"]');
  if (lienTicket) {
    await lienTicket.click();
    await pm.waitForLoadState('networkidle');
    await pm.waitForTimeout(200);
    await pm.screenshot({ path: `${SORTIE}/ticket.png`, fullPage: true });
  }

  await navigateur.close();
  console.log('Captures terminées.');
})();
