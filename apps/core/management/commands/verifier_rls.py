"""Contrôle d'exploitation : la barrière 3 est-elle réellement en place ?

À lancer après tout déploiement et après toute restauration de sauvegarde. Une
table scopée sans politique est une fuite qui ne se voit nulle part ailleurs :
l'application continue de fonctionner, les tests passent, et les données de
deux commerçants se mélangent au premier `objects_all_tenants` mal filtré.

Sortie non nulle si une table manque à l'appel : la commande est faite pour
être branchée dans un contrôle automatique.
"""

from django.core.management.base import BaseCommand
from django.db import connection

from apps.core.rls import (
    TABLES_SCOPEES,
    etat_des_tables,
    role_contourne_la_securite,
    tables_des_modeles_scopes,
)


class Command(BaseCommand):
    help = "Vérifie que toutes les tables scopées portent la politique de sécurité au niveau ligne."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stderr.write(
                self.style.ERROR(
                    "Base non PostgreSQL : la barrière 3 n'existe pas ici. "
                    "Acceptable pour les tests, jamais pour la production."
                )
            )
            return

        if role_contourne_la_securite(connection):
            self.stderr.write(
                self.style.ERROR(
                    "Le rôle applicatif est SUPERUSER ou BYPASSRLS : les politiques sont "
                    "ignorées et la barrière 3 ne protège rien. "
                    "Corrigez par : ALTER ROLE <role> NOSUPERUSER NOBYPASSRLS;"
                )
            )
            raise SystemExit(1)

        attendues = set(tables_des_modeles_scopes())
        oubliees = attendues - set(TABLES_SCOPEES)
        if oubliees:
            self.stderr.write(
                self.style.ERROR(
                    "Modèles scopés absents de `TABLES_SCOPEES` (migration à écrire) : "
                    + ", ".join(sorted(oubliees))
                )
            )

        etat = etat_des_tables(connection)
        defaillantes = []
        for table in sorted(attendues | set(TABLES_SCOPEES)):
            ligne = etat.get(table)
            if ligne is None:
                defaillantes.append((table, "table absente"))
            elif not ligne["activee"]:
                defaillantes.append((table, "RLS désactivée"))
            elif not ligne["forcee"]:
                defaillantes.append((table, "FORCE manquant — le propriétaire contourne tout"))
            elif not ligne["politique"]:
                defaillantes.append((table, "politique absente"))

        if defaillantes or oubliees:
            for table, motif in defaillantes:
                self.stderr.write(self.style.ERROR(f"  {table} : {motif}"))
            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(f"{len(attendues)} tables scopées, toutes protégées.")
        )
