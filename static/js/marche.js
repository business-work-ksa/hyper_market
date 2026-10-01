/* HyperMarché — comportements du marché (docs/26-design-system-marche.md, §5).
 *
 * Amélioration progressive, sans exception : chaque page fonctionne sans ce script. Il ajoute
 * le confort — entrées en scène, thème, modales, sélecteur de quantité, rechargement de la
 * grille sans quitter la page — et rien qui soit indispensable pour acheter.
 *
 * Aucune dépendance, aucune requête tierce. ~4 Ko non minifié.
 */
(function () {
  "use strict";

  var racine = document.documentElement;
  var mouvementReduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* --- 1. Entrées en scène ------------------------------------------------------------------ */
  // Un élément `[data-apparition]` apparaît quand il entre dans la fenêtre, une seule fois.
  // La classe `js` (posée en tête de page) est ce qui les cache au départ : sans script, tout
  // est visible d'emblée.
  var observateur = null;
  function observer(portee) {
    var elements = (portee || document).querySelectorAll("[data-apparition]:not(.est-visible)");
    if (!("IntersectionObserver" in window) || mouvementReduit) {
      elements.forEach(function (el) { el.classList.add("est-visible"); });
      return;
    }
    if (!observateur) {
      observateur = new IntersectionObserver(function (entrees) {
        entrees.forEach(function (entree) {
          if (entree.isIntersecting) {
            entree.target.classList.add("est-visible");
            observateur.unobserve(entree.target);
          }
        });
      }, { rootMargin: "0px 0px -6% 0px", threshold: 0.08 });
    }
    elements.forEach(function (el) { observateur.observe(el); });
  }

  /* --- 2. Thème : automatique → clair → sombre ---------------------------------------------- */
  var CLE_THEME = "hm-theme-marche";
  var ICONES = { systeme: "#ic-systeme", light: "#ic-clair", dark: "#ic-sombre" };
  function themeCourant() { return racine.getAttribute("data-theme") || "systeme"; }
  function refleterTheme(bouton) {
    var t = themeCourant();
    var cle = t === "light" ? "clair" : t === "dark" ? "sombre" : "systeme";
    bouton.setAttribute("aria-label", bouton.getAttribute("data-libelle-" + cle) || bouton.getAttribute("aria-label"));
    var use = bouton.querySelector("use");
    if (use) use.setAttribute("href", ICONES[t] || ICONES.systeme);
  }
  document.querySelectorAll("[data-theme-bascule]").forEach(function (bouton) {
    refleterTheme(bouton);
    bouton.addEventListener("click", function () {
      var suivant = { systeme: "light", light: "dark", dark: "systeme" }[themeCourant()];
      if (suivant === "systeme") racine.removeAttribute("data-theme");
      else racine.setAttribute("data-theme", suivant);
      try {
        if (suivant === "systeme") localStorage.removeItem(CLE_THEME);
        else localStorage.setItem(CLE_THEME, suivant);
      } catch (e) {}
      refleterTheme(bouton);
    });
  });

  /* --- 3. Modales (<dialog> natif) ---------------------------------------------------------- */
  document.addEventListener("click", function (e) {
    var ouvrir = e.target.closest("[data-modale-ouvrir]");
    if (ouvrir) {
      var modale = document.getElementById(ouvrir.getAttribute("data-modale-ouvrir"));
      if (modale && typeof modale.showModal === "function") {
        e.preventDefault();
        modale.showModal();
      }
      return;
    }
    if (e.target.closest("[data-modale-fermer]")) {
      var d = e.target.closest("dialog");
      if (d) d.close();
      return;
    }
    // Clic sur le voile (hors de la boîte) : ferme.
    if (e.target.tagName === "DIALOG" && e.target.open) {
      var r = e.target.getBoundingClientRect();
      var dedans = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
      if (!dedans) e.target.close();
    }
  });

  /* --- 4. Sélecteur de quantité ------------------------------------------------------------- */
  document.addEventListener("click", function (e) {
    var bouton = e.target.closest(".quantite [data-pas]");
    if (!bouton) return;
    var champ = bouton.parentElement.querySelector("input");
    var min = parseInt(champ.min || "0", 10);
    var max = parseInt(champ.max || "99", 10);
    var valeur = (parseInt(champ.value, 10) || 0) + parseInt(bouton.getAttribute("data-pas"), 10);
    champ.value = Math.max(min, Math.min(max, valeur));
    champ.dispatchEvent(new Event("change", { bubbles: true }));
  });

  /* --- 5. Bouton occupé à l'envoi d'un formulaire ------------------------------------------- */
  // Sur 3G, un envoi prend plusieurs secondes : sans retour visible, on clique deux fois.
  document.addEventListener("submit", function (e) {
    var bouton = e.submitter;
    if (bouton && bouton.classList.contains("btn") && !e.defaultPrevented) {
      setTimeout(function () { bouton.setAttribute("aria-busy", "true"); }, 0);
    }
  });
  // Retour arrière depuis la page suivante (cache de navigation) : le bouton ne doit pas rester
  // occupé. Seulement dans ce cas — au premier affichage, un `aria-busy` voulu reste en place.
  window.addEventListener("pageshow", function (e) {
    if (!e.persisted) return;
    document.querySelectorAll('.btn[aria-busy="true"]').forEach(function (b) { b.removeAttribute("aria-busy"); });
  });

  /* --- 6. Grille du catalogue : rayon et recherche sans quitter la page ---------------------- */
  // La grille se recharge par fragment (en-tête `X-Fragment`), un squelette tient la place le
  // temps de la réponse. L'adresse change (historique), le retour arrière fonctionne, et la
  // région annonce le nombre de résultats aux lecteurs d'écran.
  var region = document.querySelector("[data-catalogue]");
  var gabarit = document.getElementById("squelette-grille");
  var annonce = document.querySelector("[data-catalogue-annonce]");
  var enCours = null;

  function charger(url, pousser) {
    if (!region || !window.fetch) { window.location.href = url; return; }
    if (enCours) enCours.abort();
    enCours = "AbortController" in window ? new AbortController() : null;
    region.setAttribute("aria-busy", "true");
    if (gabarit) region.replaceChildren(gabarit.content.cloneNode(true));
    if (annonce) annonce.textContent = annonce.getAttribute("data-chargement") || "";
    fetch(url, { headers: { "X-Fragment": "1" }, credentials: "same-origin", signal: enCours && enCours.signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        region.innerHTML = html;
        region.removeAttribute("aria-busy");
        var titre = region.querySelector("[data-titre-resultats]");
        if (titre) document.title = titre.getAttribute("data-titre-resultats");
        if (annonce) {
          var compte = region.querySelector("[data-nombre-resultats]");
          annonce.textContent = compte ? compte.textContent.trim() : "";
        }
        if (pousser) history.pushState({ catalogue: true }, "", url);
        majPuces(url);
        observer(region);
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;
        window.location.href = url;
      });
  }

  function majPuces(url) {
    var cible = new URL(url, window.location.href);
    var rayon = cible.searchParams.get("rayon") || "";
    var q = cible.searchParams.get("q") || "";
    document.querySelectorAll("a[data-filtre]").forEach(function (a) {
      var r = new URL(a.href, window.location.href).searchParams.get("rayon") || "";
      if (r === rayon && !q) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
  }

  if (region) {
    document.addEventListener("click", function (e) {
      var lien = e.target.closest("a[data-filtre]");
      if (!lien || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      charger(lien.href, true);
    });
    document.querySelectorAll("form[data-recherche]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var url = new URL(form.action, window.location.href);
        url.search = new URLSearchParams(new FormData(form)).toString();
        charger(url.toString(), true);
        var champ = form.querySelector("input[type=search]");
        if (champ) champ.blur();
      });
    });
    window.addEventListener("popstate", function () { charger(window.location.href, false); });
  }

  observer(document);
})();
