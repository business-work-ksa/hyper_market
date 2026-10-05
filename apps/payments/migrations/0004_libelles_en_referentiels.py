"""Les libellés anglais des référentiels livrés avec la plateforme.

Ne remplit que les champs vides : un libellé anglais déjà corrigé par l'exploitant est gardé.
Copie figée des valeurs de `initialiser_referentiels` au jour de la migration.
"""

from django.db import migrations

PRESTATAIRES_EN = {
    "MTN_MOMO": "MTN Mobile Money",
    "ORANGE_MONEY": "Orange Money",
    "CAMTEL": "Camtel Blue Mobile Money",
    "CARTE": "Bank card",
    "COD": "Cash on delivery",
    "FAUX": "Simulated payment (demo)",
}


def remplir(apps, schema_editor):
    Modele = apps.get_model("payments", "Prestataire")
    for code, libelle_en in PRESTATAIRES_EN.items():
        Modele.objects.filter(code=code, libelle_en="").update(libelle_en=libelle_en)


class Migration(migrations.Migration):
    dependencies = [("payments", "0003_libelles_en")]
    operations = [migrations.RunPython(remplir, migrations.RunPython.noop)]
