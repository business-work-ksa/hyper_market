/* Console de la plateforme — enrichissements des tableaux de bord.
 *
 * Tout ce que fait ce fichier est facultatif : les graphes sont dessinés par le serveur, les
 * filtres sont des formulaires GET avec leur bouton. Sans JavaScript, rien ne manque ; avec, on
 * gagne une info-bulle au survol et un clic de moins sur les filtres.
 */
(function () {
  "use strict";

  // --- Survol des graphes ---------------------------------------------------
  // Une zone de saisie par créneau, plus large que la barre (la cible dépasse la marque).
  // Sur un écran tactile il n'y a pas de survol : l'info-bulle resterait collée au premier
  // effleurement. L'étiquette du maximum et le tableau « Voir les chiffres » portent déjà tout.
  var survol = window.matchMedia && window.matchMedia("(hover: hover)").matches;

  document.querySelectorAll("[data-graphe]").forEach(function (boite) {
    var bulle = boite.querySelector("[data-bulle]");
    if (!bulle) return;
    if (!survol) { bulle.remove(); return; }

    boite.querySelectorAll("svg.graphe").forEach(function (svg) {
      var barres = svg.querySelectorAll(".barre");
      svg.querySelectorAll(".zone-survol").forEach(function (zone) {
        var rang = zone.getAttribute("data-rang");
        zone.addEventListener("mouseenter", function () {
          barres.forEach(function (b) {
            b.classList.toggle("barre--attenuee", b.getAttribute("data-rang") !== rang);
          });
          bulle.textContent = "";
          var cle = document.createElement("div");
          cle.className = "info-bulle__cle";
          cle.textContent = zone.getAttribute("data-jour");
          var val = document.createElement("div");
          val.className = "info-bulle__val";
          val.textContent = zone.getAttribute("data-valeur") + " FCFA";
          bulle.appendChild(cle);
          bulle.appendChild(val);
          bulle.setAttribute("data-visible", "true");
        });
        zone.addEventListener("mousemove", function (evt) {
          var cadre = boite.getBoundingClientRect();
          var x = evt.clientX - cadre.left;
          var y = evt.clientY - cadre.top;
          bulle.style.left = Math.max(4, Math.min(x + 14, cadre.width - bulle.offsetWidth - 8)) + "px";
          bulle.style.top = Math.max(y - bulle.offsetHeight - 10, 4) + "px";
        });
        zone.addEventListener("mouseleave", function () {
          barres.forEach(function (b) { b.classList.remove("barre--attenuee"); });
          bulle.setAttribute("data-visible", "false");
        });
      });
    });
  });

  // --- Filtres qui s'appliquent d'eux-mêmes ---------------------------------
  // Un sélecteur marqué `data-auto` soumet son formulaire au changement. Le bouton
  // « Appliquer » reste pour le clavier et pour l'absence de script ; on le masque seulement
  // quand plus rien ne l'exige.
  document.querySelectorAll("form[data-filtres]").forEach(function (formulaire) {
    var auto = formulaire.querySelectorAll("select[data-auto]");
    auto.forEach(function (champ) {
      champ.addEventListener("change", function () {
        if (formulaire.requestSubmit) formulaire.requestSubmit(); else formulaire.submit();
      });
    });
    var bouton = formulaire.querySelector("[data-appliquer]");
    if (bouton && auto.length && !formulaire.querySelector("input[type=search], input[type=date]")) {
      bouton.hidden = true;
    }
  });
})();
