/**
 * Service worker de HyperMarché.
 *
 * La connectivité est intermittente et la data est payante : le réseau est traité
 * comme une ressource rare, pas comme un acquis (ADR-004, docs/09 §4).
 *
 * Deux stratégies, choisies selon ce que coûte une donnée périmée :
 *
 *   — statique (CSS, JS, icônes) : **cache d'abord**. Ces fichiers sont versionnés
 *     par le nom du cache ; servir l'ancien pendant une seconde ne coûte rien et
 *     économise de la data à chaque ouverture.
 *   — pages : **réseau d'abord, cache en repli**. Un stock périmé affiché comme
 *     frais serait pire qu'une page un peu lente.
 *
 * Ce que le service worker ne fait PAS : mettre en cache les réponses de
 * `/caisse/encaisser/`. Une vente n'est pas une ressource, c'est une écriture.
 * Sa mise en attente est gérée par la file de `hors-ligne.js`, qui sait la
 * rejouer avec sa clé d'idempotence.
 */

const VERSION = "hm-v2";
const CACHE_STATIQUE = `${VERSION}-statique`;
const CACHE_PAGES = `${VERSION}-pages`;

// La coquille minimale pour que la caisse s'ouvre sans réseau.
const COQUILLE = [
  "/caisse/",
  "/stock/",
  "/static/css/hypermarche.css",
  "/static/js/hors-ligne.js",
  "/static/js/imprimante.js",
  "/static/icones/hm-192.png",
  "/static/manifest.webmanifest",
];

// Points d'entrée de données : jamais servis depuis le cache. Le catalogue est
// rangé dans IndexedDB par la page, avec sa date de fraîcheur affichée ; une
// réponse périmée servie comme fraîche serait invisible et donc pire.
const DONNEES_VIVES = ["/caisse/catalogue.json"];

self.addEventListener("install", (evenement) => {
  evenement.waitUntil(
    caches
      .open(CACHE_STATIQUE)
      // `addAll` échoue en bloc si une seule requête échoue : on tolère les
      // absences plutôt que de laisser l'installation entière échouer.
      .then((cache) => Promise.allSettled(COQUILLE.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (evenement) => {
  evenement.waitUntil(
    caches
      .keys()
      .then((noms) =>
        Promise.all(
          noms.filter((nom) => !nom.startsWith(VERSION)).map((nom) => caches.delete(nom))
        )
      )
      .then(() => self.clients.claim())
  );
});

function estStatique(url) {
  return url.pathname.startsWith("/static/") || url.pathname.endsWith(".webmanifest");
}

self.addEventListener("fetch", (evenement) => {
  const requete = evenement.request;
  if (requete.method !== "GET") return; // les écritures ne passent jamais par le cache

  const url = new URL(requete.url);
  if (url.origin !== self.location.origin) return;
  if (DONNEES_VIVES.includes(url.pathname)) return; // au réseau, ou pas du tout

  if (estStatique(url)) {
    evenement.respondWith(
      caches.match(requete).then(
        (enCache) =>
          enCache ||
          fetch(requete).then((reponse) => {
            const copie = reponse.clone();
            caches.open(CACHE_STATIQUE).then((cache) => cache.put(requete, copie));
            return reponse;
          })
      )
    );
    return;
  }

  if (requete.mode === "navigate") {
    evenement.respondWith(
      fetch(requete)
        .then((reponse) => {
          const copie = reponse.clone();
          caches.open(CACHE_PAGES).then((cache) => cache.put(requete, copie));
          return reponse;
        })
        .catch(() =>
          caches
            .match(requete)
            .then((enCache) => enCache || caches.match("/caisse/"))
        )
    );
  }
});
