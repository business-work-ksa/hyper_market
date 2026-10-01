"""Génération d'UUIDv7.

Les identifiants métier sont générés côté client (voir ADR-004, docs/09-architecture-technique.md) :
une vente saisie hors ligne possède son identifiant définitif avant même d'atteindre le serveur.
L'UUIDv7 est retenu parce qu'il est ordonné dans le temps, donc indexable efficacement — contrairement
à l'UUIDv4, qui fragmente les index B-tree sur des tables de plusieurs dizaines de millions de lignes.

Format (RFC 9562) :
    48 bits  horodatage Unix en millisecondes
     4 bits  version (7)
    12 bits  sous-milliseconde / aléatoire
     2 bits  variante
    62 bits  aléatoire
"""

import os
import time
import uuid

__all__ = ["uuid7"]


def uuid7(horodatage_ms: int | None = None) -> uuid.UUID:
    """Retourne un UUIDv7. `horodatage_ms` n'est fourni que par les tests."""
    if horodatage_ms is None:
        horodatage_ms = time.time_ns() // 1_000_000

    alea = int.from_bytes(os.urandom(10), "big")

    valeur = (horodatage_ms & 0xFFFFFFFFFFFF) << 80
    valeur |= 0x7 << 76  # version 7
    valeur |= ((alea >> 62) & 0xFFF) << 64  # 12 bits de sous-milliseconde
    valeur |= 0b10 << 62  # variante RFC 4122
    valeur |= alea & 0x3FFFFFFFFFFFFFFF  # 62 bits aléatoires

    return uuid.UUID(int=valeur)
