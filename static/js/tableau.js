/* Tableau de données : sélection, barre d'outils contextuelle, suppression.
 *
 * Un tableau qui ne fait que montrer oblige à quitter l'écran pour agir : on
 * cherche la ligne, on l'ouvre, on agit, on revient, on la recherche. Ce module
 * met les gestes là où la donnée se lit.
 *
 * Trois règles, et chacune vient d'un usage réel :
 *
 *   — **On ne modifie qu'une ligne à la fois.** Deux lignes différentes n'ont
 *     pas la même correction à apporter ; un formulaire commun à plusieurs
 *     lignes écrirait la même valeur partout, ce que personne ne demande jamais.
 *   — **On supprime autant de lignes qu'on veut**, parce que faire le ménage est
 *     exactement le geste qui porte sur plusieurs lignes.
 *   — **La barre dit ce qu'elle va faire de la ligne sélectionnée**, nommément.
 *     Un bouton grisé sans raison se lit comme une panne ; un bouton grisé qui
 *     dit « on ne modifie qu'une ligne à la fois » se lit comme une règle.
 *
 * Le tableau est rendu par le serveur et reste lisible sans ce script : la
 * colonne de cases est **posée ici**, jamais dans le gabarit, pour qu'un
 * navigateur sans JavaScript n'hérite pas de cases à cocher inertes.
 *
 * Contrat de balisage, côté gabarit :
 *
 *   <section class="carte tableau-panneau" data-tableau data-nom="article"
 *            data-noms="articles">
 *     ... barre d'outils (partials/tableau_barre.html) ...
 *     <table class="tableau">
 *       <tbody>
 *         <tr data-id="…" data-libelle="…"
 *             data-modifier="/url/"        (facultatif)
 *             data-note="conséquence"      (facultatif : l'action aura un effet
 *                                           particulier sur cette ligne-là)
 *             data-protege="motif">        (facultatif : ligne non supprimable)
 *
 * `data-note` et `data-protege` ne disent pas la même chose, et les confondre
 * coûte cher : une note **n'empêche rien**, elle prévient d'une conséquence
 * (« a déjà bougé en stock : sera retiré de la vente, pas supprimé ») ; une
 * protection retire la ligne de l'action. Traiter la première comme la seconde
 * grise un bouton qui devrait marcher, et le commerçant conclut à une panne.
 */
(function () {
  "use strict";

  var CLIQUABLES = "a, button, input, select, textarea, label, summary";

  function parametres(panneau) {
    return {
      nom: panneau.dataset.nom || "ligne",
      noms: panneau.dataset.noms || "lignes",
      accord: panneau.dataset.accord || "", // « e » pour un nom féminin
    };
  }

  function lignes(panneau) {
    return Array.prototype.slice.call(
      panneau.querySelectorAll("tbody tr[data-id]")
    );
  }

  function selectionnees(panneau) {
    return lignes(panneau).filter(function (tr) {
      return tr.getAttribute("aria-selected") === "true";
    });
  }

  // --- Pose de la colonne de sélection -------------------------------------
  function poserLesCases(panneau, table) {
    var enTete = table.querySelector("thead tr");
    if (!enTete) return null;

    table.classList.add("tableau--selectionnable");

    var thSel = document.createElement("th");
    thSel.className = "col-sel";
    thSel.setAttribute("scope", "col");
    var toutes = document.createElement("input");
    toutes.type = "checkbox";
    toutes.setAttribute("aria-label", "Tout sélectionner");
    thSel.appendChild(toutes);
    enTete.insertBefore(thSel, enTete.firstChild);

    lignes(panneau).forEach(function (tr) {
      var td = document.createElement("td");
      td.className = "col-sel";
      var case_ = document.createElement("input");
      case_.type = "checkbox";
      case_.setAttribute(
        "aria-label",
        "Sélectionner " + (tr.dataset.libelle || "cette ligne")
      );
      td.appendChild(case_);
      tr.insertBefore(td, tr.firstChild);
      tr.setAttribute("aria-selected", "false");
      if (!tr.hasAttribute("tabindex")) tr.setAttribute("tabindex", "0");
    });

    // Les lignes vides (« aucun résultat ») portent un `colspan` calculé sur le
    // nombre de colonnes d'origine : la colonne ajoutée le décalerait d'un cran
    // et laisserait un trou à droite du message.
    table.querySelectorAll("tbody td[colspan]").forEach(function (td) {
      td.colSpan = parseInt(td.colSpan, 10) + 1;
    });

    return toutes;
  }

  // --- Sélection ------------------------------------------------------------
  function poser(tr, valeur) {
    tr.setAttribute("aria-selected", valeur ? "true" : "false");
    var case_ = tr.querySelector("td.col-sel input");
    if (case_) case_.checked = !!valeur;
  }

  function viderLaSelection(panneau) {
    lignes(panneau).forEach(function (tr) {
      poser(tr, false);
    });
  }

  function selectionnerUneSeule(panneau, tr) {
    viderLaSelection(panneau);
    poser(tr, true);
  }

  function selectionnerJusqua(panneau, depuis, jusqua) {
    var toutes = lignes(panneau);
    var a = toutes.indexOf(depuis);
    var b = toutes.indexOf(jusqua);
    if (a < 0 || b < 0) return;
    var debut = Math.min(a, b);
    var fin = Math.max(a, b);
    for (var i = debut; i <= fin; i++) poser(toutes[i], true);
  }

  // --- Barre d'outils -------------------------------------------------------
  function refleter(panneau) {
    var choisies = selectionnees(panneau);
    var mots = parametres(panneau);
    var assistance = panneau.querySelector("[data-assistance]");
    var texte = panneau.querySelector("[data-assistance-texte]");
    var modifier = panneau.querySelector("[data-action='modifier']");
    var supprimer = panneau.querySelector("[data-action='supprimer']");
    var toutes = panneau.querySelector("thead .col-sel input");

    if (toutes) {
      var total = lignes(panneau).length;
      toutes.checked = total > 0 && choisies.length === total;
      toutes.indeterminate = choisies.length > 0 && choisies.length < total;
    }

    var supprimables = choisies.filter(function (tr) {
      return !tr.hasAttribute("data-protege");
    });

    if (modifier) {
      var url = choisies.length === 1 ? choisies[0].dataset.modifier : "";
      var possible = choisies.length === 1 && !!url;
      modifier.disabled = !possible;
      modifier.dataset.cible = url || "";
      modifier.title = possible
        ? "Modifier « " + choisies[0].dataset.libelle + " »"
        : choisies.length > 1
        ? "On ne modifie qu'une ligne à la fois : choisissez-en une seule."
        : choisies.length === 1
        ? "Cette ligne ne se modifie pas."
        : "Sélectionnez une ligne à modifier.";
    }

    if (supprimer) {
      supprimer.disabled = supprimables.length === 0;
      supprimer.title = supprimables.length
        ? "Supprimer " +
          supprimables.length +
          " " +
          (supprimables.length > 1 ? mots.noms : mots.nom)
        : choisies.length
        ? "Aucune des lignes choisies ne peut être supprimée."
        : "Sélectionnez au moins une ligne à supprimer.";
    }

    if (!assistance || !texte) return;

    if (choisies.length === 0) {
      assistance.dataset.selection = "0";
      texte.innerHTML = assistance.dataset.aide || "";
      return;
    }
    if (choisies.length === 1) {
      assistance.dataset.selection = "1";
      var ligne = choisies[0];
      var suite = [];
      if (ligne.dataset.modifier) suite.push("<b>Modifier</b> ouvre sa fiche");
      if (supprimer && !ligne.hasAttribute("data-protege")) {
        suite.push("<b>Supprimer</b> la retire");
      }
      // La protection empêche ; la note prévient. Les deux se disent, jamais
      // de la même façon.
      if (ligne.hasAttribute("data-protege")) suite.push(ligne.getAttribute("data-protege"));
      if (ligne.dataset.note) suite.push(echapper(ligne.dataset.note));
      // Les notes sont écrites comme des phrases et se terminent par un point ;
      // la ligne d'assistance en pose un à la fin. Sans ce rognage, elle se
      // termine par deux.
      suite = suite.map(function (bout) {
        return bout.replace(/\.\s*$/, "");
      });
      texte.innerHTML =
        "« <b>" +
        echapper(ligne.dataset.libelle || "") +
        "</b> » sélectionné" +
        mots.accord +
        (suite.length ? " — " + suite.join(", ") + "." : ".");
      return;
    }

    assistance.dataset.selection = "n";
    var protegees = choisies.length - supprimables.length;
    texte.innerHTML =
      "<b>" +
      choisies.length +
      " " +
      mots.noms +
      "</b> sélectionné" +
      mots.accord +
      "s — seule la <b>suppression</b> s'applique à plusieurs lignes" +
      (protegees
        ? ", et " +
          protegees +
          (protegees > 1 ? " ne peuvent pas être supprimées" : " ne peut pas être supprimée")
        : "") +
      ".";
  }

  function echapper(texte) {
    var noeud = document.createElement("span");
    noeud.textContent = texte;
    return noeud.innerHTML;
  }

  // --- Suppression ----------------------------------------------------------
  function preparerLaSuppression(panneau) {
    var boite = panneau.querySelector("dialog[data-modale='supprimer']");
    if (!boite) return;

    var choisies = selectionnees(panneau);
    var mots = parametres(panneau);
    var liste = boite.querySelector("[data-visees]");
    var compte = boite.querySelector("[data-compte]");
    var champs = boite.querySelector("[data-identifiants]");
    var valider = boite.querySelector("[data-valider]");

    liste.innerHTML = "";
    champs.innerHTML = "";
    var supprimables = 0;
    // Un même objet peut occuper deux lignes — un article présent dans deux
    // dépôts, par exemple. Le nommer deux fois dans la confirmation ferait
    // croire à une sélection de trop, et l'envoyer deux fois ferait compter
    // deux suppressions pour une.
    var vus = Object.create(null);

    choisies.forEach(function (tr) {
      if (vus[tr.dataset.id]) return;
      vus[tr.dataset.id] = true;

      var li = document.createElement("li");
      li.textContent = tr.dataset.libelle || tr.dataset.id;
      var motif = tr.getAttribute("data-protege");
      if (tr.dataset.note) {
        // La conséquence est écrite à côté du nom, pas cachée dans une
        // infobulle : c'est au moment de confirmer qu'elle doit se lire.
        var note = document.createElement("span");
        note.className = "t-legende";
        note.style.display = "block";
        note.textContent = tr.dataset.note;
        li.appendChild(note);
      }
      if (motif) {
        li.setAttribute("data-protege", "");
        li.title = motif;
      } else {
        supprimables++;
        var champ = document.createElement("input");
        champ.type = "hidden";
        champ.name = "ids";
        champ.value = tr.dataset.id;
        champs.appendChild(champ);
      }
      liste.appendChild(li);
    });

    compte.textContent =
      supprimables + " " + (supprimables > 1 ? mots.noms : mots.nom);
    valider.disabled = supprimables === 0;
    boite.showModal();
  }

  // --- Câblage --------------------------------------------------------------
  function equiper(panneau) {
    var table = panneau.querySelector("table.tableau");
    if (!table || lignes(panneau).length === 0) {
      // Une liste vide n'a rien à sélectionner. On laisse la barre en place —
      // « Nouveau » et « Filtrer » gardent tout leur sens sur un écran vide, et
      // c'est même là qu'ils servent le plus.
      refleter(panneau);
      activerLaBarre(panneau);
      return;
    }

    var toutes = poserLesCases(panneau, table);
    var derniere = null;

    table.addEventListener("click", function (evt) {
      var tr = evt.target.closest("tbody tr[data-id]");
      if (!tr) return;

      var surCase = evt.target.closest("td.col-sel");
      // Un lien ou un bouton dans la ligne garde son geste propre : la
      // sélection ne doit pas confisquer une action déjà offerte.
      if (!surCase && evt.target.closest(CLIQUABLES)) return;

      if (evt.shiftKey && derniere) {
        selectionnerJusqua(panneau, derniere, tr);
        // La sélection d'un intervalle au clavier surligne le texte au passage :
        // c'est laid et ça masque la sélection de lignes.
        window.getSelection().removeAllRanges();
      } else if (surCase || evt.ctrlKey || evt.metaKey) {
        poser(tr, tr.getAttribute("aria-selected") !== "true");
      } else {
        var seule =
          tr.getAttribute("aria-selected") === "true" &&
          selectionnees(panneau).length === 1;
        // Recliquer la seule ligne sélectionnée la désélectionne : c'est le
        // moyen le plus court de revenir à l'état neutre.
        if (seule) poser(tr, false);
        else selectionnerUneSeule(panneau, tr);
      }
      derniere = tr;
      refleter(panneau);
    });

    table.addEventListener("keydown", function (evt) {
      var tr = evt.target.closest("tbody tr[data-id]");
      if (!tr) return;
      if (evt.key === " ") {
        evt.preventDefault();
        poser(tr, tr.getAttribute("aria-selected") !== "true");
        derniere = tr;
        refleter(panneau);
      } else if (evt.key === "Enter" && tr.dataset.ouvrir) {
        window.location.href = tr.dataset.ouvrir;
      }
    });

    if (toutes) {
      toutes.addEventListener("change", function () {
        lignes(panneau).forEach(function (tr) {
          poser(tr, toutes.checked);
        });
        refleter(panneau);
      });
    }

    document.addEventListener("keydown", function (evt) {
      if (evt.key !== "Escape") return;
      if (document.querySelector("dialog[open]")) return; // Échap ferme la boîte d'abord
      if (selectionnees(panneau).length === 0) return;
      viderLaSelection(panneau);
      refleter(panneau);
    });

    activerLaBarre(panneau);
    refleter(panneau);
  }

  function activerLaBarre(panneau) {
    var modifier = panneau.querySelector("[data-action='modifier']");
    if (modifier) {
      modifier.addEventListener("click", function () {
        if (modifier.dataset.cible) window.location.href = modifier.dataset.cible;
      });
    }

    var supprimer = panneau.querySelector("[data-action='supprimer']");
    if (supprimer) {
      supprimer.addEventListener("click", function () {
        preparerLaSuppression(panneau);
      });
    }
  }

  // --- Boîtes de dialogue ---------------------------------------------------
  // Câblées globalement : les filtres, l'aide et les formulaires de création
  // vivent dans des boîtes qui n'appartiennent à aucun tableau.
  function equiperLesBoites() {
    document.querySelectorAll("[data-ouvre]").forEach(function (bouton) {
      bouton.addEventListener("click", function () {
        var boite = document.getElementById(bouton.dataset.ouvre);
        if (!boite) return;
        boite.showModal();
        var premier = boite.querySelector(
          "input:not([type=hidden]):not([disabled]), select, textarea"
        );
        if (premier) premier.focus();
      });
    });

    document.querySelectorAll("dialog [data-ferme]").forEach(function (bouton) {
      bouton.addEventListener("click", function () {
        bouton.closest("dialog").close();
      });
    });

    // Cliquer sur le fond ferme : c'est le geste attendu, et `<dialog>` ne le
    // fait pas seul. On compare la cible au dialogue lui-même — le fond *est*
    // le dialogue, du point de vue des événements.
    document.querySelectorAll("dialog.modale").forEach(function (boite) {
      boite.addEventListener("click", function (evt) {
        if (evt.target === boite) boite.close();
      });
    });
  }

  function demarrer() {
    document.querySelectorAll("[data-tableau]").forEach(equiper);
    equiperLesBoites();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", demarrer);
  } else {
    demarrer();
  }
})();
