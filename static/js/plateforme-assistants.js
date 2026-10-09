/* HyperMarché — console : assistants et gestes.
 *
 * Amélioration seulement. Sans ce fichier, tout fonctionne : le serveur applique le loyer et le
 * taux de l'offre aux champs laissés vides, exige le motif d'une dérogation, montre l'effet d'un
 * taux avant de l'appliquer, et confirme par une page. Ici, on ne fait que le dire plus tôt.
 */
(function () {
  "use strict";

  // Traductions : le catalogue de Django (`/jsi18n/`) n'est chargé qu'en anglais. En français,
  // le texte source est la traduction : les repli rendent la chaîne telle quelle.
  var gettext = window.gettext || function (s) { return s; };
  var ngettext = window.ngettext || function (s, p, n) { return n > 1 ? p : s; };
  var f = window.interpolate || function (modele, valeurs) {
    return modele.replace(/%\((\w+)\)s/g, function (_, cle) { return valeurs[cle]; });
  };

  function tous(sel, racine) { return Array.prototype.slice.call((racine || document).querySelectorAll(sel)); }
  function nombre(texte) {
    if (texte == null) return NaN;
    var propre = String(texte).replace(/[\s  ]/g, "").replace(",", ".");
    return propre === "" ? NaN : Number(propre);
  }
  function pourcent(n) {
    var arrondi = Math.round(n * 100) / 100;
    return String(arrondi).replace(".", ",") + " %";
  }
  function milliers(n) {
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  // --- Abandonner : une confirmation, parce que les saisies partent ------------------------
  tous("[data-confirmer]").forEach(function (bouton) {
    bouton.addEventListener("click", function (e) {
      if (!window.confirm(bouton.getAttribute("data-confirmer"))) e.preventDefault();
    });
  });

  // --- Compteur de caractères d'un motif -------------------------------------------------
  tous("textarea[data-compteur][maxlength]").forEach(function (zone) {
    var max = Number(zone.getAttribute("maxlength"));
    var compteur = document.createElement("span");
    compteur.className = "a-compteur";
    compteur.setAttribute("aria-hidden", "true");
    zone.insertAdjacentElement("afterend", compteur);
    function maj() {
      var n = zone.value.length;
      compteur.textContent = n + " / " + max;
      compteur.classList.toggle("a-compteur--proche", n > max * 0.9);
    }
    zone.addEventListener("input", maj);
    maj();
  });

  // --- Aperçu de l'adresse de la vitrine --------------------------------------------------
  // Même dérivation que `slugify` côté serveur, à un détail près : l'unicité (suffixe « -2 »)
  // n'est connue que du serveur, qui l'affiche au récapitulatif.
  var enseigne = document.querySelector('input[name="enseigne"]');
  var apercuSlug = document.querySelector("[data-apercu-slug]");
  if (enseigne && apercuSlug) {
    var cible = apercuSlug.querySelector("[data-slug]");
    var majSlug = function () {
      var slug = enseigne.value.normalize("NFKD").replace(/[̀-ͯ]/g, "")
        .toLowerCase().replace(/[^a-z0-9\s-]/g, "").trim().replace(/[\s-]+/g, "-");
      cible.textContent = slug || "…";
      apercuSlug.hidden = !slug;
    };
    enseigne.addEventListener("input", majSlug);
    majSlug();
  }

  // --- Offre : préremplir le loyer et le taux, signaler la dérogation --------------------
  var offres = tous('input[name="offre"]');
  if (offres.length) {
    var loyer = document.querySelector('input[name="loyer_mensuel"]');
    var taux = document.querySelector('input[name="taux_commission"]');
    var signal = document.querySelector("[data-derogation-signal]");
    var reference = signal && signal.querySelector("[data-taux-reference]");
    var motif = document.querySelector('textarea[name="motif_derogation"]');
    var precedente = null;

    var offreChoisie = function () {
      return offres.filter(function (o) { return o.checked; })[0] || null;
    };
    var majDerogation = function () {
      var o = offreChoisie();
      if (!o || !taux || !signal) return;
      var ref = nombre(o.getAttribute("data-taux"));
      var saisi = nombre(taux.value);
      var ecart = !isNaN(saisi) && Math.abs(saisi - ref) > 1e-9;
      signal.hidden = !ecart;
      if (reference) reference.textContent = pourcent(ref);
      if (motif) motif.required = ecart;
    };
    var appliquerOffre = function () {
      var o = offreChoisie();
      if (!o) return;
      // On ne remplace une valeur que si elle est vide ou si elle venait de l'offre précédente :
      // un loyer négocié à la main ne s'efface pas parce qu'on a cliqué sur une autre carte.
      [[loyer, "data-loyer"], [taux, "data-taux"]].forEach(function (paire) {
        var champ = paire[0], attribut = paire[1];
        if (!champ) return;
        var ancienne = precedente ? precedente.getAttribute(attribut) : null;
        if (champ.value === "" || (ancienne !== null && nombre(champ.value) === nombre(ancienne))) {
          champ.value = attribut === "data-loyer" ? milliers(nombre(o.getAttribute(attribut))) : o.getAttribute(attribut).replace(".", ",");
        }
      });
      precedente = o;
      majDerogation();
    };
    offres.forEach(function (o) { o.addEventListener("change", appliquerOffre); });
    if (taux) taux.addEventListener("input", majDerogation);
    precedente = offreChoisie();
    appliquerOffre();
  }

  // --- Compte existant / nouveau : replier ce qui ne sert pas -----------------------------
  var modes = tous('input[name="mode"]');
  var nouveau = document.querySelector("[data-nouveau-compte]");
  if (modes.length && nouveau) {
    var majMode = function () {
      var choisi = modes.filter(function (m) { return m.checked; })[0];
      nouveau.hidden = !(choisi && choisi.value === "nouveau");
    };
    modes.forEach(function (m) { m.addEventListener("change", majMode); });
    majMode();
  }

  // --- Emplacement : le rayon n'a pas de sens pour la page d'accueil ----------------------
  var types = tous('input[name="type"][data-rayon]');
  var blocRayon = document.querySelector("[data-rayon-emplacement]");
  if (types.length && blocRayon) {
    var majType = function () {
      var choisi = types.filter(function (t) { return t.checked; })[0];
      blocRayon.hidden = !!choisi && choisi.getAttribute("data-rayon") === "non";
    };
    types.forEach(function (t) { t.addEventListener("change", majType); });
    majType();
  }

  // --- Période : la durée, en jours --------------------------------------------------------
  var debut = document.querySelector('input[name="debut"][type="date"]');
  var fin = document.querySelector('input[name="fin"][type="date"]');
  var duree = document.querySelector("[data-duree]");
  if (debut && fin && duree) {
    var majDuree = function () {
      var d = Date.parse(debut.value), f = Date.parse(fin.value);
      if (isNaN(d) || isNaN(f)) { duree.hidden = true; return; }
      var jours = Math.round((f - d) / 86400000) + 1;
      duree.hidden = false;
      duree.querySelector("[data-duree-texte]").textContent = jours > 1
        ? f(gettext("%(n)s jours, du premier au dernier inclus"), { n: jours }, true) +
          (jours % 7 === 0 ? " — " + f(ngettext("%(n)s semaine", "%(n)s semaines", jours / 7), { n: jours / 7 }, true) : "")
        : gettext("La fin doit venir après le début.");
    };
    debut.addEventListener("input", majDuree);
    fin.addEventListener("input", majDuree);
    majDuree();
  }

  // --- Taux d'un rayon : l'effet, en direct ------------------------------------------------
  var formTaux = document.querySelector("[data-taux-rayon]");
  if (formTaux) {
    var saisie = formTaux.querySelector('input[name="pourcent"]');
    var nouveauTaux = formTaux.querySelector("[data-apercu-nouveau]");
    var majTaux = function () {
      var n = nombre(saisie.value);
      nouveauTaux.textContent = isNaN(n) ? "…" : pourcent(n);
    };
    if (saisie && nouveauTaux) {
      saisie.addEventListener("input", majTaux);
      if (saisie.value) majTaux();
    }
  }
})();
