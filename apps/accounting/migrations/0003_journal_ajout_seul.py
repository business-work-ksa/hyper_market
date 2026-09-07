"""Trigger PostgreSQL : le journal comptable est en ajout seul.

Troisième protection de l'immuabilité des écritures (ADR-003). Les deux premières vivent dans le
code Python — `EcritureComptable.save()` et `delete()`. Celle-ci vit dans la base : elle rejette
un `UPDATE` ou un `DELETE` même émis en SQL brut, depuis un script, un client psql ou un ORM tiers.

C'est la seule qui tienne face à un développeur pressé.

Deux dérogations volontaires :

* `contrepassee_par` reste modifiable : c'est un champ de suivi, sans effet sur les montants ;
* `modifie_le` accompagne cette mise à jour.

Sur SQLite (tests hors infrastructure), la migration est un no-op : seules les protections Python
s'appliquent alors, ce qui suffit pour les tests unitaires mais **jamais pour la production**.
"""

from django.db import migrations

SQL_INSTALLATION = """
CREATE OR REPLACE FUNCTION hm_ecriture_ajout_seul() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.validee THEN
            RAISE EXCEPTION
                'Ecriture % validee : suppression interdite. Utilisez une contre-passation.',
                OLD.piece;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.validee THEN
        -- Seuls le rattachement de contre-passation et son horodatage restent modifiables.
        IF NEW.journal_id      IS DISTINCT FROM OLD.journal_id
           OR NEW.exercice_id  IS DISTINCT FROM OLD.exercice_id
           OR NEW.boutique_id  IS DISTINCT FROM OLD.boutique_id
           OR NEW.date_ecriture IS DISTINCT FROM OLD.date_ecriture
           OR NEW.piece        IS DISTINCT FROM OLD.piece
           OR NEW.libelle      IS DISTINCT FROM OLD.libelle
           OR NEW.validee      IS DISTINCT FROM OLD.validee
           OR NEW.origine_type IS DISTINCT FROM OLD.origine_type
           OR NEW.origine_id   IS DISTINCT FROM OLD.origine_id
        THEN
            RAISE EXCEPTION
                'Ecriture % validee : modification interdite. Utilisez une contre-passation.',
                OLD.piece;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hm_ecriture_ajout_seul_trg
    BEFORE UPDATE OR DELETE ON accounting_ecriturecomptable
    FOR EACH ROW EXECUTE FUNCTION hm_ecriture_ajout_seul();

-- Une ligne appartenant a une ecriture validee est figee, sans exception.
CREATE OR REPLACE FUNCTION hm_ligne_ecriture_ajout_seul() RETURNS trigger AS $$
DECLARE
    ecriture_validee boolean;
    ligne record;
BEGIN
    ligne := COALESCE(NEW, OLD);
    SELECT validee INTO ecriture_validee
        FROM accounting_ecriturecomptable WHERE id = ligne.ecriture_id;

    IF ecriture_validee THEN
        RAISE EXCEPTION
            'Ligne rattachee a une ecriture validee : modification interdite.';
    END IF;

    RETURN ligne;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hm_ligne_ecriture_ajout_seul_trg
    BEFORE UPDATE OR DELETE ON accounting_ligneecriture
    FOR EACH ROW EXECUTE FUNCTION hm_ligne_ecriture_ajout_seul();
"""

SQL_DESINSTALLATION = """
DROP TRIGGER IF EXISTS hm_ligne_ecriture_ajout_seul_trg ON accounting_ligneecriture;
DROP FUNCTION IF EXISTS hm_ligne_ecriture_ajout_seul();
DROP TRIGGER IF EXISTS hm_ecriture_ajout_seul_trg ON accounting_ecriturecomptable;
DROP FUNCTION IF EXISTS hm_ecriture_ajout_seul();
"""


def installer(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    # params=None : sans cela, psycopg interprète les « % » des messages RAISE comme des
    # marqueurs de paramètre.
    schema_editor.execute(SQL_INSTALLATION, params=None)


def desinstaller(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(SQL_DESINSTALLATION, params=None)


class Migration(migrations.Migration):
    dependencies = [("accounting", "0002_initial")]

    operations = [migrations.RunPython(installer, desinstaller)]
