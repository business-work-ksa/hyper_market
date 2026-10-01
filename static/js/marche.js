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

  /* --- 6. Catalogue : filtres, tri, « Voir plus », sans quitter la page ------------------- */
  // Le corps du catalogue (filtres + résultats) se recharge par fragment (en-tête `X-Fragment`) ;
  // un squelette tient la place des résultats le temps de la réponse. L'adresse change (on la
  // partage, on revient en arrière), et la région annonce le nombre de résultats.
  var region = document.querySelector("[data-catalogue]");
  var gabarit = document.getElementById("squelette-grille");
  var annonce = document.querySelector("[data-catalogue-annonce]");
  var tiroirCorps = document.querySelector("[data-tiroir-corps]");
  var enCours = null;

  function urlDuFormulaire(form) {
    var url = new URL(form.action, window.location.href);
    var params = new URLSearchParams();
    new FormData(form).forEach(function (valeur, cle) { if (valeur !== "") params.append(cle, valeur); });
    url.search = params.toString();
    return url.toString();
  }

  function charger(url, pousser) {
    if (!region || !window.fetch) { window.location.href = url; return; }
    if (enCours) enCours.abort();
    enCours = "AbortController" in window ? new AbortController() : null;
    var focus = document.activeElement && document.activeElement.id;
    var resultats = region.querySelector("[data-resultats]") || region;
    region.setAttribute("aria-busy", "true");
    if (gabarit) resultats.replaceChildren(gabarit.content.cloneNode(true));
    if (annonce) annonce.textContent = annonce.getAttribute("data-chargement") || "";
    fetch(url, { headers: { "X-Fragment": "1" }, credentials: "same-origin", signal: enCours && enCours.signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        region.innerHTML = html;
        region.removeAttribute("aria-busy");
        var source = region.querySelector("[data-tiroir-source]");
        if (source && tiroirCorps) tiroirCorps.replaceChildren(source.content.cloneNode(true));
        var titre = region.querySelector("[data-titre-resultats]");
        if (titre) document.title = titre.getAttribute("data-titre-resultats");
        if (annonce) {
          var compte = region.querySelector("[data-nombre-resultats]");
          annonce.textContent = compte ? compte.textContent.trim() : "";
        }
        if (pousser) history.pushState({ catalogue: true }, "", url);
        if (focus && document.getElementById(focus)) document.getElementById(focus).focus({ preventScroll: true });
        observer(region);
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;
        window.location.href = url;
      });
  }

  if (region) {
    // Puces de filtres actifs, « Tout effacer ».
    document.addEventListener("click", function (e) {
      var lien = e.target.closest("[data-catalogue] a[data-filtre]");
      if (!lien || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      charger(lien.href, true);
    });
    // Colonne de filtres : chaque changement s'applique ; les prix, à la sortie du champ.
    document.addEventListener("change", function (e) {
      var form = e.target.closest("[data-catalogue] form[data-filtres]");
      if (form) { charger(urlDuFormulaire(form), true); return; }
      if (e.target.matches("[data-tri]")) {
        var url = new URL(window.location.href);
        url.searchParams.set("tri", e.target.value);
        url.searchParams.delete("page");
        charger(url.toString(), true);
      }
    });
    // Tiroir mobile : on règle tout, puis « Voir les résultats ».
    var tiroir = document.getElementById("tiroir-filtres");
    if (tiroir) {
      tiroir.addEventListener("close", function () {
        var form = tiroir.querySelector("form[data-filtres]");
        var url = form && urlDuFormulaire(form);
        if (url && url !== window.location.href) charger(url, true);
      });
    }
    document.addEventListener("submit", function (e) {
      var form = e.target.closest("form[data-filtres]");
      if (!form) return;
      e.preventDefault();
      var d = form.closest("dialog");
      if (d) d.close(); else charger(urlDuFormulaire(form), true);
    });
    // « Voir plus » : la page suivante s'ajoute à la grille, sans remplacer ce qu'on a vu.
    document.addEventListener("click", function (e) {
      var bouton = e.target.closest("[data-voir-plus]");
      if (!bouton || !window.fetch) return;
      e.preventDefault();
      bouton.setAttribute("aria-busy", "true");
      fetch(bouton.href, { headers: { "X-Fragment": "suite" }, credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) {
          var grille = region.querySelector("[data-grille]");
          var tampon = document.createElement("div");
          tampon.innerHTML = html;
          var suite = tampon.querySelector("[data-suite]");
          if (suite) suite.remove();
          var premiere = tampon.firstElementChild;
          while (tampon.firstChild) grille.appendChild(tampon.firstChild);
          observer(grille);
          if (premiere) { var lien = premiere.querySelector("h3 a"); if (lien) lien.focus({ preventScroll: true }); }
          if (suite) { bouton.href = suite.getAttribute("data-suite"); bouton.removeAttribute("aria-busy"); }
          else bouton.parentElement.remove();
        })
        .catch(function () { window.location.href = bouton.href; });
    });
    window.addEventListener("popstate", function () { charger(window.location.href, false); });
  }

  /* --- 7. Mégamenu des rayons ------------------------------------------------------------- */
  var boutonMenu = document.querySelector("[data-megamenu-bouton]");
  var menu = document.querySelector("[data-megamenu]");
  if (boutonMenu && menu) {
    boutonMenu.setAttribute("role", "button");
    var minuterie = null;
    var chevron = boutonMenu.querySelector("svg:last-child");
    function ouvrir() {
      clearTimeout(minuterie);
      if (!menu.hidden) return;
      menu.hidden = false;
      boutonMenu.setAttribute("aria-expanded", "true");
      if (chevron) chevron.style.transform = "rotate(-90deg)";
    }
    function fermer(rendreFocus) {
      clearTimeout(minuterie);
      if (menu.hidden) return;
      menu.hidden = true;
      boutonMenu.setAttribute("aria-expanded", "false");
      if (chevron) chevron.style.transform = "";
      if (rendreFocus) boutonMenu.focus();
    }
    boutonMenu.addEventListener("click", function (e) {
      e.preventDefault();
      if (menu.hidden) { ouvrir(); var premier = menu.querySelector(".megamenu-rayon"); if (premier && e.detail === 0) premier.focus(); }
      else fermer(false);
    });
    // Survol avec intention : on ouvre après un court arrêt, on ferme après un court départ —
    // traverser l'en-tête en allant ailleurs n'ouvre rien.
    var zone = boutonMenu.closest("nav");
    boutonMenu.addEventListener("mouseenter", function () { clearTimeout(minuterie); minuterie = setTimeout(ouvrir, 140); });
    zone.addEventListener("mouseleave", function () { clearTimeout(minuterie); minuterie = setTimeout(function () { fermer(false); }, 260); });
    menu.addEventListener("mouseenter", function () { clearTimeout(minuterie); });
    function montrer(lien) {
      var cible = document.getElementById(lien.getAttribute("data-volet"));
      if (!cible) return;
      menu.querySelectorAll(".megamenu-volet").forEach(function (v) { v.hidden = v !== cible; });
      menu.querySelectorAll(".megamenu-rayon").forEach(function (l) {
        if (l === lien) l.setAttribute("aria-current", "true"); else l.removeAttribute("aria-current");
      });
    }
    menu.querySelectorAll(".megamenu-rayon").forEach(function (lien) {
      lien.addEventListener("mouseenter", function () { montrer(lien); });
      lien.addEventListener("focus", function () { montrer(lien); });
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !menu.hidden) fermer(true); });
    document.addEventListener("click", function (e) {
      if (!menu.hidden && !menu.contains(e.target) && !boutonMenu.contains(e.target)) fermer(false);
    });
    menu.addEventListener("focusout", function (e) {
      if (e.relatedTarget && !menu.contains(e.relatedTarget) && e.relatedTarget !== boutonMenu) fermer(false);
    });
  }

  /* --- 8. Profondeur : l'illustration du bandeau glisse plus lentement que la page ---------- */
  var plans = document.querySelectorAll("[data-parallaxe]");
  if (plans.length && !mouvementReduit) {
    var demande = false;
    window.addEventListener("scroll", function () {
      if (demande) return;
      demande = true;
      requestAnimationFrame(function () {
        var y = window.scrollY;
        plans.forEach(function (p) { if (y < 900) p.style.transform = "translateY(" + (y * 0.18).toFixed(1) + "px) scale(1.06)"; });
        demande = false;
      });
    }, { passive: true });
  }

  /* --- 9. Le panier vient de recevoir un article : sa pastille rebondit --------------------- */
  var pastille = document.querySelector("[data-pastille-panier]");
  if (pastille && document.querySelector("[data-message-succes]") && !mouvementReduit) {
    pastille.classList.add("rebond");
  }

  observer(document);
})();
