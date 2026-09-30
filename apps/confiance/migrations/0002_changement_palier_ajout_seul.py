"""Trigger PostgreSQL : le journal des changements de palier est en ajout seul.

Même motif que le journal des accès (`core/0011`) et le journal comptable (ADR-003). Un marchand
rétrogradé demandera pourquoi, et peut-être devant un juge : la réponse doit être la ligne écrite
le jour de la décision, pas une ligne réécrite depuis. Les protections Python
(`ChangementPalier.save()`, `.delete()`) donnent un message clair au développeur ; celle-ci tient
face au SQL brut.

Sur une autre base que PostgreSQL, la migration est un no-op.
"""

from django.db import migrations

SQL_INSTALLATION = """
CREATE OR REPLACE FUNCTION hm_changement_palier_ajout_seul() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'Journal des changements de palier : ajout seul. Ni modification ni suppression (ADR-013).';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hm_changement_palier_ajout_seul_trg
    BEFORE UPDATE OR DELETE ON confiance_changementpalier
    FOR EACH ROW EXECUTE FUNCTION hm_changement_palier_ajout_seul();
"""

SQL_DESINSTALLATION = """
DROP TRIGGER IF EXISTS hm_changement_palier_ajout_seul_trg ON confiance_changementpalier;
DROP FUNCTION IF EXISTS hm_changement_palier_ajout_seul();
"""


def installer(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(SQL_INSTALLATION, params=None)


def desinstaller(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(SQL_DESINSTALLATION, params=None)


class Migration(migrations.Migration):
    dependencies = [("confiance", "0001_initial")]

    operations = [migrations.RunPython(installer, desinstaller)]
