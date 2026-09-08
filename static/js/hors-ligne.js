/**
 * File d'attente hors ligne, et catalogue de secours.
 *
 * Le serveur est idempotent : chaque opération issue du terrain porte une clé
 * générée côté client, et une opération déjà appliquée renvoie son résultat
 * précédent plutôt que d'en créer un second (ADR-004). C'est ce qui rend le
 * rejeu sûr, et donc cette file possible.
 *
 * Règles de la file, chacune payée par une expérience de terrain :
 *
 *   1. Une opération enregistrée n'est jamais perdue. Elle part au réseau, ou
 *      elle attend. Jamais elle ne disparaît.
 *   2. Le rejeu est **séquentiel** : la numérotation des tickets doit rester
 *      déterministe, et deux ventes envoyées en parallèle se disputeraient le
 *      même numéro.
 *   3. Une erreur métier (4xx) **sort** de la file. Réessayer indéfiniment une
 *      opération que le serveur refuse ne la fera jamais passer, et bloquerait
 *      toutes les suivantes derrière elle.
 *   4. Une erreur réseau **reste** dans la file. C'est exactement le cas pour
 *      lequel elle existe.
 *
 * Deux choses ont changé depuis la première version :
 *
 *   — la file ne porte plus seulement des ventes. Une réception de marchandise
 *     saisie pendant une coupure était perdue, et le camion reparti : le stock
 *     était en réserve et absent du système. Chaque entrée porte donc son URL,
 *     et le vidage ne connaît rien du métier qu'il transporte ;
 *   — le stockage est **IndexedDB**. `localStorage` est synchrone, plafonné à
 *     quelques mégaoctets et partagé avec tout le reste ; il tenait pour trente
 *     tickets, pas pour un catalogue complet. Un repli sur `localStorage`
 *     subsiste pour les navigateurs qui refusent IndexedDB (navigation privée
 *     de certains WebView Android) : mieux vaut une file dégradée qu'aucune.
 */
(function (global) {
  "use strict";

  var NOM_BASE = "hypermarche";
  var VERSION_BASE = 1;
  var FILE = "operations";
  var CATALOGUE = "catalogue";

  var ecouteurs = [];
  var compte = 0; // miroir synchrone, pour l'indicateur de l'en-tête

  function notifier() {
    ecouteurs.forEach(function (f) {
      f(compte);
    });
  }

  // -------------------------------------------------------------------------
  // Magasin — deux implémentations, une seule interface asynchrone :
  //   empiler(entree) · lister() · retirer(rang) · rangerCatalogue(x) · lireCatalogue()
  // -------------------------------------------------------------------------
  function ouvrirIndexedDB() {
    return new Promise(function (resoudre) {
      if (!global.indexedDB) return resoudre(null);
      var requete;
      try {
        requete = indexedDB.open(NOM_BASE, VERSION_BASE);
      } catch (e) {
        return resoudre(null);
      }
      requete.onupgradeneeded = function () {
        var db = requete.result;
        if (!db.objectStoreNames.contains(FILE)) {
          // Clé auto-incrémentée : l'ordre des clés est l'ordre d'insertion, et
          // c'est lui qui garantit le rejeu séquentiel (règle 2). Un UUID en clé
          // primaire aurait donné un ordre aléatoire.
          var file = db.createObjectStore(FILE, { keyPath: "rang", autoIncrement: true });
          // Unique : une opération remise en file deux fois n'y figure qu'une.
          file.createIndex("operation_id", "operation_id", { unique: true });
        }
        if (!db.objectStoreNames.contains(CATALOGUE)) {
          db.createObjectStore(CATALOGUE, { keyPath: "cle" });
        }
      };
      requete.onsuccess = function () {
        resoudre(requete.result);
      };
      requete.onerror = function () {
        resoudre(null);
      };
      requete.onblocked = function () {
        resoudre(null);
      };
    });
  }

  function magasinIndexedDB(db) {
    function ecrire(nom, action) {
      return new Promise(function (resoudre, rejeter) {
        var tx = db.transaction(nom, "readwrite");
        tx.oncomplete = resoudre;
        tx.onerror = function () {
          rejeter(tx.error);
        };
        tx.onabort = function () {
          rejeter(tx.error);
        };
        action(tx.objectStore(nom), tx);
      });
    }

    function lire(nom, action) {
      return new Promise(function (resoudre, rejeter) {
        var tx = db.transaction(nom, "readonly");
        var requete = action(tx.objectStore(nom));
        requete.onsuccess = function () {
          resoudre(requete.result);
        };
        requete.onerror = function () {
          rejeter(requete.error);
        };
      });
    }

    return {
      empiler: function (entree) {
        return ecrire(FILE, function (magasin) {
          var requete = magasin.add(entree);
          // Doublon d'`operation_id` : l'opération est déjà en file, tant mieux.
          // Sans ce `preventDefault`, l'erreur d'unicité avorterait toute la
          // transaction — et une file qui refuse d'écrire perd la règle 1.
          requete.onerror = function (evenement) {
            evenement.preventDefault();
            evenement.stopPropagation();
          };
        });
      },
      lister: function () {
        return lire(FILE, function (magasin) {
          return magasin.getAll();
        });
      },
      retirer: function (rang) {
        return ecrire(FILE, function (magasin) {
          magasin.delete(rang);
        });
      },
      rangerCatalogue: function (enregistrement) {
        return ecrire(CATALOGUE, function (magasin) {
          magasin.put(enregistrement);
        });
      },
      lireCatalogue: function () {
        return lire(CATALOGUE, function (magasin) {
          return magasin.get("articles");
        });
      },
    };
  }

  /**
   * Repli `localStorage`, pour les navigateurs qui refusent IndexedDB. Même
   * interface, sans transaction ni quota confortable : on n'y range que la file,
   * et un catalogue tronqué à ce que le stockage accepte.
   */
  function magasinLocal() {
    function charger(cle) {
      try {
        return JSON.parse(localStorage.getItem(cle) || "[]");
      } catch (e) {
        return [];
      }
    }
    function sauver(cle, valeur) {
      try {
        localStorage.setItem(cle, JSON.stringify(valeur));
      } catch (e) {
        // Quota plein ou stockage refusé : on ne peut plus garantir la règle 1.
        // Mieux vaut le dire que de faire semblant.
        console.error("File hors ligne non persistable", e);
      }
    }

    return {
      empiler: function (entree) {
        var lignes = charger("hm-file-operations");
        var deja = lignes.some(function (l) {
          return l.operation_id === entree.operation_id;
        });
        if (!deja) {
          entree.rang = lignes.length ? lignes[lignes.length - 1].rang + 1 : 1;
          lignes.push(entree);
          sauver("hm-file-operations", lignes);
        }
        return Promise.resolve();
      },
      lister: function () {
        return Promise.resolve(charger("hm-file-operations"));
      },
      retirer: function (rang) {
        sauver(
          "hm-file-operations",
          charger("hm-file-operations").filter(function (l) {
            return l.rang !== rang;
          })
        );
        return Promise.resolve();
      },
      rangerCatalogue: function (enregistrement) {
        sauver("hm-catalogue", [enregistrement]);
        return Promise.resolve();
      },
      lireCatalogue: function () {
        return Promise.resolve(charger("hm-catalogue")[0]);
      },
    };
  }

  var promesseMagasin = null;
  function magasin() {
    if (!promesseMagasin) {
      promesseMagasin = ouvrirIndexedDB().then(function (db) {
        return db ? magasinIndexedDB(db) : magasinLocal();
      });
    }
    return promesseMagasin;
  }

  // -------------------------------------------------------------------------
  // File
  // -------------------------------------------------------------------------
  function lireFile() {
    return magasin()
      .then(function (m) {
        return m.lister();
      })
      .then(function (lignes) {
        return (lignes || []).slice().sort(function (a, b) {
          return a.rang - b.rang;
        });
      })
      .catch(function () {
        return [];
      });
  }

  function rafraichirCompte() {
    return lireFile().then(function (lignes) {
      compte = lignes.length;
      notifier();
      return compte;
    });
  }

  function empiler(entree) {
    return magasin()
      .then(function (m) {
        return m.empiler(entree);
      })
      .catch(function () {})
      .then(rafraichirCompte);
  }

  function retirer(rang) {
    return magasin()
      .then(function (m) {
        return m.retirer(rang);
      })
      .catch(function () {});
  }

  // -------------------------------------------------------------------------
  // Transport
  // -------------------------------------------------------------------------
  function jetonCsrf() {
    var champ = document.querySelector("[name=csrfmiddlewaretoken]");
    if (champ) return champ.value;
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function envoyer(entree) {
    return fetch(entree.url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": jetonCsrf() },
      body: JSON.stringify(entree.charge),
    });
  }

  var vidageEnCours = false;

  /** Rejoue la file, une opération à la fois. Résout {envoyees, restantes, refusees}. */
  function vider() {
    if (vidageEnCours) return Promise.resolve(null);
    vidageEnCours = true;

    var envoyees = 0;
    var refusees = [];

    function suivante() {
      return lireFile().then(function (lignes) {
        if (lignes.length === 0) return null;
        var entree = lignes[0];

        return envoyer(entree)
          .then(function (reponse) {
            if (reponse.ok) {
              envoyees += 1;
              return retirer(entree.rang).then(suivante);
            }
            if (reponse.status >= 400 && reponse.status < 500) {
              // Règle 3 : le serveur refuse cette opération, pas le réseau.
              return reponse
                .json()
                .catch(function () {
                  return {};
                })
                .then(function (corps) {
                  refusees.push({ entree: entree, erreur: corps.erreur || "Opération refusée." });
                  return retirer(entree.rang).then(suivante);
                });
            }
            // 5xx : le serveur est en difficulté, on réessaiera plus tard.
            throw new Error("serveur indisponible");
          })
          .catch(function () {
            // Règle 4 : on s'arrête là et on garde le reste pour la prochaine fois.
            return null;
          });
      });
    }

    return suivante()
      .then(rafraichirCompte)
      .then(function (restantes) {
        return { envoyees: envoyees, restantes: restantes, refusees: refusees };
      })
      .finally(function () {
        vidageEnCours = false;
      });
  }

  /**
   * Soumet une opération : tente l'envoi immédiat, met en file si le réseau manque.
   * Résout {etat: "envoyee"|"en_attente"|"refusee", ...}.
   */
  function soumettre(entree) {
    if (!navigator.onLine) {
      return empiler(entree).then(function (n) {
        return { etat: "en_attente", enAttente: n };
      });
    }
    return envoyer(entree)
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
              return { etat: "refusee", erreur: corps.erreur || "Opération refusée." };
            }
            throw new Error("serveur indisponible");
          });
      })
      .catch(function () {
        return empiler(entree).then(function (n) {
          return { etat: "en_attente", enAttente: n };
        });
      });
  }

  // -------------------------------------------------------------------------
  // Catalogue de secours
  // -------------------------------------------------------------------------
  var Catalogue = {
    /** Range le catalogue rapporté du serveur, pour la prochaine coupure. */
    enregistrer: function (articles, meta) {
      return magasin()
        .then(function (m) {
          return m.rangerCatalogue({
            cle: "articles",
            articles: articles,
            genere_le: (meta && meta.genere_le) || null,
            depot: (meta && meta.depot) || null,
            range_le: new Date().toISOString(),
          });
        })
        .catch(function () {});
    },

    /** Dernier catalogue connu, ou null. */
    lire: function () {
      return magasin()
        .then(function (m) {
          return m.lireCatalogue();
        })
        .then(function (enregistrement) {
          return enregistrement || null;
        })
        .catch(function () {
          return null;
        });
    },
  };

  // -------------------------------------------------------------------------
  // Surface publique
  // -------------------------------------------------------------------------
  var HorsLigne = {
    /** Nombre d'opérations en attente d'envoi (miroir synchrone). */
    enAttente: function () {
      return compte;
    },

    /** Contenu de la file, dans l'ordre de rejeu. */
    file: lireFile,

    /** Met une opération en attente sans tenter l'envoi. */
    ajouter: empiler,

    soumettre: soumettre,
    vider: vider,
    catalogue: Catalogue,

    /** S'abonne aux changements de taille de la file. */
    surChangement: function (rappel) {
      ecouteurs.push(rappel);
      rappel(compte);
    },
  };

  /**
   * Surface héritée, conservée parce qu'elle nomme exactement ce que fait la
   * caisse. Elle délègue à la file générique.
   */
  function entreeVente(charge) {
    return {
      operation_id: charge.operation_id,
      type: "vente",
      url: "/caisse/encaisser/",
      charge: charge,
    };
  }

  global.HorsLigne = HorsLigne;
  global.FileVentes = {
    enAttente: HorsLigne.enAttente,
    surChangement: HorsLigne.surChangement,
    vider: vider,
    ajouter: function (charge) {
      return empiler(entreeVente(charge));
    },
    encaisser: function (charge) {
      return soumettre(entreeVente(charge));
    },
  };

  // Rejeu automatique : au retour du réseau, et à l'ouverture d'une page.
  global.addEventListener("online", function () {
    vider();
  });
  global.addEventListener("load", function () {
    rafraichirCompte().then(function (n) {
      if (n > 0 && navigator.onLine) vider();
    });
  });

  rafraichirCompte();
})(window);
