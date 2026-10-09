"""Confiance et lutte contre la fraude (docs/23, ADR-013).

Placée **au-dessus** des commandes et des paiements dans le graphe des dépendances, parce qu'elle
lit tout — boutiques, vérifications, livraisons, litiges, versements — pour en tirer deux choses :

* le **palier de confiance** de chaque boutique, écrit dans `Boutique.palier_confiance`, que les
  paiements lisent sans jamais importer ce module ;
* les **signaux de risque**, présentés dans la console pour qu'un humain décide.

Elle ne décide jamais seule de suspendre une boutique : un signal est un indice, pas une preuve.
"""
