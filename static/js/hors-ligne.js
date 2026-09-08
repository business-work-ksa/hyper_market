/**
 * File d'attente des ventes hors ligne.
 *
 * Le serveur est idempotent : chaque encaissement porte une clé générée côté
 * client, et une opération déjà appliquée renvoie son résultat précédent plutôt
 * que d'en créer un second (ADR-004). C'est ce qui rend le rejeu sûr, et donc
 * cette file possible.
 *
 * Règles de la file, chacune payée par une expérience de terrain :
 *
 *   1. Une vente encaissée n'est jamais perdue. Elle part au réseau, ou elle
 *      attend. Jamais elle ne disparaît.
 *   2. Le rejeu est **séquentiel** : la numérotation des tickets doit rester
 *      déterministe, et deux ventes envoyées en parallèle se disputeraient le
 *      même numéro.
 *   3. Une erreur métier (4xx) **sort** de la file. Réessayer indéfiniment une
 *      vente que le serveur refuse ne la fera jamais passer, et bloquerait
 *      toutes les suivantes derrière elle.
 *   4. Une erreur réseau **reste** dans la file. C'est exactement le cas pour
 *      lequel elle existe.
 *
 * Le stockage est `localStorage` : synchrone, disponible partout, et suffisant
 * pour quelques dizaines de tickets. IndexedDB deviendra nécessaire le jour où
 * l'on mettra aussi les mouvements de stock en attente.
 */
(function (global) {
  "use strict";

  var CLE = "hm-file-ventes";
  var ecouteurs = [];

  function lire() {
    try {
      return JSON.parse(localStorage.getItem(CLE) || "[]");
    } catch (e) {
      return [];
    }
  }

  function ecrire(file) {
    try {
      localStorage.setItem(CLE, JSON.stringify(file));
    } catch (e) {
      // Quota plein ou stockage refusé : on ne peut plus garantir la règle 1.
      // Mieux vaut le dire que de faire semblant.
      console.error("File de ventes non persistable", e);
    }
    ecouteurs.forEach(function (f) {
      f(file.length);
    });
  }

  function jetonCsrf() {
    var champ = document.querySelector("[name=csrfmiddlewaretoken]");
    if (champ) return champ.value;
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function envoyer(charge) {
    return fetch("/caisse/encaisser/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": jetonCsrf() },
      body: JSON.stringify(charge),
    });
  }

  var vidageEnCours = false;

  /**
   * Rejoue la file, une vente à la fois.
   * Résout avec {envoyees, restantes, refusees}.
   */
  function vider() {
    if (vidageEnCours) return Promise.resolve(null);
    var file = lire();
    if (file.length === 0) return Promise.resolve({ envoyees: 0, restantes: 0, refusees: [] });

    vidageEnCours = true;
    var envoyees = 0;
    var refusees = [];

    function suivante() {
      var restante = lire();
      if (restante.length === 0) return Promise.resolve();

      var charge = restante[0];
      return envoyer(charge)
        .then(function (reponse) {
          if (reponse.ok) {
            envoyees += 1;
            ecrire(lire().slice(1));
            return suivante();
          }
          if (reponse.status >= 400 && reponse.status < 500) {
            // Règle 3 : le serveur refuse cette vente, pas le réseau.
            return reponse
              .json()
              .catch(function () {
                return {};
              })
              .then(function (corps) {
                refusees.push({ charge: charge, erreur: corps.erreur || "Vente refusée." });
                ecrire(lire().slice(1));
                return suivante();
              });
          }
          // 5xx : le serveur est en difficulté, on réessaiera plus tard.
          throw new Error("serveur indisponible");
        })
        .catch(function () {
          // Règle 4 : on s'arrête là et on garde le reste pour la prochaine fois.
        });
    }

    return suivante()
      .then(function () {
        return { envoyees: envoyees, restantes: lire().length, refusees: refusees };
      })
      .finally(function () {
        vidageEnCours = false;
      });
  }

  var FileVentes = {
    /** Nombre de ventes en attente d'envoi. */
    enAttente: function () {
      return lire().length;
    },

    /** Met une vente en attente. Retourne le nouveau nombre d'éléments. */
    ajouter: function (charge) {
      var file = lire();
      file.push(charge);
      ecrire(file);
      return file.length;
    },

    /**
     * Encaisse : tente l'envoi immédiat, met en file si le réseau manque.
     * Résout avec {etat: "envoyee"|"en_attente"|"refusee", ...}.
     */
    encaisser: function (charge) {
      if (!navigator.onLine) {
        var n = FileVentes.ajouter(charge);
        return Promise.resolve({ etat: "en_attente", enAttente: n });
      }
      return envoyer(charge)
        .then(function (reponse) {
          return reponse
            .json()
            .catch(function () {
              return {};
            })
            .then(function (corps) {
              if (reponse.ok && corps.ok) {
                return { etat: "envoyee", corps: corps };
              }
              if (reponse.status >= 400 && reponse.status < 500) {
                return { etat: "refusee", erreur: corps.erreur || "Vente refusée." };
              }
              throw new Error("serveur indisponible");
            });
        })
        .catch(function () {
          var n = FileVentes.ajouter(charge);
          return { etat: "en_attente", enAttente: n };
        });
    },

    vider: vider,

    /** S'abonne aux changements de taille de la file. */
    surChangement: function (rappel) {
      ecouteurs.push(rappel);
      rappel(lire().length);
    },
  };

  // Rejeu automatique : au retour du réseau, et à l'ouverture d'une page.
  global.addEventListener("online", function () {
    FileVentes.vider();
  });
  if (navigator.onLine) {
    global.addEventListener("load", function () {
      FileVentes.vider();
    });
  }

  global.FileVentes = FileVentes;
})(window);
