/**
 * Impression directe sur imprimante thermique Bluetooth (ESC/POS).
 *
 * Pourquoi ce fichier existe : `window.print()` ouvre la boîte de dialogue du
 * navigateur, qui ne sait pas parler à une bobine 58 mm posée sur le comptoir.
 * Sur Android, Chrome expose le Bluetooth basse consommation aux pages web ; les
 * imprimantes de caisse vendues au marché exposent presque toutes un service
 * série sur lequel on écrit des octets ESC/POS. Cela suffit à imprimer un ticket
 * sans application native.
 *
 * Ce que cela couvre, et ce que cela ne couvre pas — autant le dire ici :
 *
 *   — couvert : imprimante **Bluetooth LE**, navigateur Chromium sur Android ou
 *     bureau, page servie en **HTTPS** (ou localhost). Web Bluetooth exige un
 *     contexte sécurisé et un geste de l'utilisateur : le bouton, pas le
 *     chargement de la page ;
 *   — non couvert : iOS (aucun navigateur n'expose Web Bluetooth), les
 *     imprimantes USB ou Wi-Fi, et le Bluetooth « classique » (SPP) des modèles
 *     les plus anciens. Là, l'impression navigateur et le partage WhatsApp
 *     restent les chemins, et une application native reste nécessaire pour
 *     piloter la bobine sans intervention.
 *
 * L'appareil n'est pas mémorisé d'une session à l'autre : le navigateur redemande
 * l'autorisation à chaque page. C'est une contrainte de la plateforme, pas un
 * oubli.
 */
(function (global) {
  "use strict";

  // Traduction : le catalogue de Django (`/jsi18n/`) n'est chargé qu'en anglais.
  var gettext = window.gettext || function (s) { return s; };

  // Service « série » des imprimantes ESC/POS courantes, et deux variantes
  // rencontrées sur les modèles bon marché.
  var SERVICES = [
    0x18f0,
    "000018f0-0000-1000-8000-00805f9b34fb",
    "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
    "49535343-fe7d-4ae5-8fa9-9fafd205e455",
  ];

  var MORCEAU = 100; // octets par écriture : les tampons embarqués sont petits
  var PAUSE = 30; // ms entre deux écritures, sinon la bobine décroche

  var appareil = null;
  var caracteristique = null;

  // --- Texte ---------------------------------------------------------------
  var ACCENTS = {
    à: "a", â: "a", ä: "a", á: "a", ã: "a", å: "a",
    è: "e", é: "e", ê: "e", ë: "e",
    ì: "i", í: "i", î: "i", ï: "i",
    ò: "o", ó: "o", ô: "o", ö: "o", õ: "o",
    ù: "u", ú: "u", û: "u", ü: "u",
    ç: "c", ñ: "n", ý: "y", ÿ: "y",
    œ: "oe", æ: "ae",
    " ": " ", " ": " ", "’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-",
  };

  /**
   * Réduit le texte à l'ASCII imprimable.
   *
   * Les imprimantes bon marché démarrent sur une table de caractères CP437 et
   * ignorent la commande qui en change. Un « é » y sort en caractère grec. Un
   * ticket sans accents reste lisible ; un ticket en charabia, non.
   */
  function sansAccents(texte) {
    var sortie = "";
    var chaine = String(texte === null || texte === undefined ? "" : texte);
    for (var i = 0; i < chaine.length; i += 1) {
      var c = chaine[i];
      var bas = c.toLowerCase();
      if (ACCENTS[bas]) {
        var remplacement = ACCENTS[bas];
        sortie += c === bas ? remplacement : remplacement.toUpperCase();
      } else if (chaine.charCodeAt(i) < 128) {
        sortie += c;
      } else {
        sortie += "?";
      }
    }
    return sortie;
  }

  // --- Construction du ruban ESC/POS ---------------------------------------
  function Ruban(largeur) {
    this.largeur = largeur || 32;
    this.octets = [];
  }

  Ruban.prototype.commande = function () {
    for (var i = 0; i < arguments.length; i += 1) this.octets.push(arguments[i]);
    return this;
  };

  Ruban.prototype.texte = function (chaine) {
    var propre = sansAccents(chaine);
    for (var i = 0; i < propre.length; i += 1) this.octets.push(propre.charCodeAt(i) & 0xff);
    return this;
  };

  Ruban.prototype.ligne = function (chaine) {
    return this.texte(chaine === undefined ? "" : chaine).commande(0x0a);
  };

  Ruban.prototype.initialiser = function () {
    return this.commande(0x1b, 0x40);
  };
  Ruban.prototype.gauche = function () {
    return this.commande(0x1b, 0x61, 0x00);
  };
  Ruban.prototype.centre = function () {
    return this.commande(0x1b, 0x61, 0x01);
  };
  Ruban.prototype.gras = function (actif) {
    return this.commande(0x1b, 0x45, actif ? 0x01 : 0x00);
  };
  Ruban.prototype.grand = function (actif) {
    return this.commande(0x1d, 0x21, actif ? 0x11 : 0x00);
  };
  Ruban.prototype.separateur = function () {
    return this.ligne(new Array(this.largeur + 1).join("-"));
  };

  /** Deux colonnes justifiées aux bords, la droite jamais tronquée. */
  Ruban.prototype.duo = function (gauche, droite) {
    var g = sansAccents(gauche);
    var d = sansAccents(droite);
    var place = this.largeur - d.length;
    if (place < 1) return this.ligne(d);
    if (g.length > place - 1) g = g.slice(0, place - 1);
    var espaces = new Array(this.largeur - g.length - d.length + 1).join(" ");
    return this.ligne(g + espaces + d);
  };

  Ruban.prototype.couper = function () {
    // Trois sauts avant la coupe : sans eux, la lame tranche dans le texte.
    return this.commande(0x0a, 0x0a, 0x0a).commande(0x1d, 0x56, 0x00);
  };

  Ruban.prototype.terminer = function () {
    return new Uint8Array(this.octets);
  };

  // --- Mise en page du ticket ----------------------------------------------
  function fcfa(nombre) {
    return Math.round(nombre)
      .toString()
      .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  function composer(ticket, largeur) {
    var ruban = new Ruban(largeur);

    ruban.initialiser().centre().grand(true).ligne(ticket.enseigne).grand(false);
    ruban.ligne(ticket.raison_sociale);
    if (ticket.rccm) ruban.ligne("RCCM " + ticket.rccm);
    if (ticket.niu) ruban.ligne("NIU " + ticket.niu);
    ruban.ligne(ticket.ville + (ticket.telephone ? " - " + ticket.telephone : ""));

    ruban.gauche().separateur();
    ruban.duo("Ticket", ticket.numero);
    ruban.duo("Date", ticket.date);
    ruban.duo("Caissier", ticket.caissier);
    if (ticket.client) ruban.duo("Client", ticket.client);
    ruban.separateur();

    ticket.lignes.forEach(function (ligne) {
      ruban.ligne(ligne.libelle);
      ruban.duo("  " + ligne.quantite + " x " + fcfa(ligne.pu), fcfa(ligne.total));
      if (ligne.remise) ruban.duo("  Remise", "-" + fcfa(ligne.remise));
    });

    ruban.separateur();
    if (ticket.assujetti_tva) {
      ruban.duo(gettext("Total hors taxes"), fcfa(ticket.total_ht));
      ruban.duo(gettext("TVA 19,25 %"), fcfa(ticket.total_tva));
    }
    ruban.gras(true).duo("TOTAL", fcfa(ticket.total_ttc) + " FCFA").gras(false);
    ruban.separateur();

    ticket.reglements.forEach(function (reglement) {
      ruban.duo(reglement.moyen, fcfa(reglement.montant));
    });

    ruban.centre().ligne("");
    if (!ticket.assujetti_tva) {
      ruban.ligne(gettext("TVA non applicable"));
      ruban.ligne(gettext("Impot general synthetique"));
    }
    ruban.ligne(gettext("Merci de votre visite."));
    ruban.ligne(gettext("Conservez ce ticket."));

    return ruban.couper().terminer();
  }

  // --- Liaison Bluetooth ----------------------------------------------------
  function trouverCaracteristique(serveur) {
    return serveur.getPrimaryServices().then(function (services) {
      var suite = Promise.resolve(null);
      services.forEach(function (service) {
        suite = suite.then(function (trouvee) {
          if (trouvee) return trouvee;
          return service.getCharacteristics().then(function (caracteristiques) {
            for (var i = 0; i < caracteristiques.length; i += 1) {
              var c = caracteristiques[i];
              if (c.properties.write || c.properties.writeWithoutResponse) return c;
            }
            return null;
          });
        });
      });
      return suite;
    });
  }

  function connecter() {
    if (caracteristique && appareil && appareil.gatt.connected) {
      return Promise.resolve(caracteristique);
    }
    if (!global.navigator || !navigator.bluetooth) {
      return Promise.reject(new Error(gettext("Ce navigateur ne sait pas parler Bluetooth.")));
    }

    return navigator.bluetooth
      .requestDevice({ acceptAllDevices: true, optionalServices: SERVICES })
      .then(function (trouve) {
        appareil = trouve;
        appareil.addEventListener("gattserverdisconnected", function () {
          caracteristique = null;
        });
        return appareil.gatt.connect();
      })
      .then(trouverCaracteristique)
      .then(function (trouvee) {
        if (!trouvee) throw new Error(gettext("Aucune voie d'écriture sur cette imprimante."));
        caracteristique = trouvee;
        return caracteristique;
      });
  }

  function ecrire(cible, donnees) {
    var position = 0;

    function suivant() {
      if (position >= donnees.length) return Promise.resolve();
      var tranche = donnees.slice(position, position + MORCEAU);
      position += MORCEAU;
      var envoi = cible.properties.writeWithoutResponse
        ? cible.writeValueWithoutResponse(tranche)
        : cible.writeValue(tranche);
      return envoi.then(function () {
        return new Promise(function (resoudre) {
          setTimeout(resoudre, PAUSE);
        });
      }).then(suivant);
    }

    return suivant();
  }

  global.Imprimante = {
    /** Le navigateur sait-il piloter une imprimante Bluetooth ? */
    disponible: function () {
      return !!(global.navigator && navigator.bluetooth);
    },

    /** Nom de l'appareil connecté, ou null. */
    appareil: function () {
      return appareil && appareil.gatt.connected ? appareil.name || "imprimante" : null;
    },

    composer: composer,
    sansAccents: sansAccents,

    /** Imprime un ticket. Résout quand tout est parti sur la bobine. */
    imprimer: function (ticket, largeur) {
      var donnees = composer(ticket, largeur);
      return connecter().then(function (cible) {
        return ecrire(cible, donnees);
      });
    },
  };
})(window);
