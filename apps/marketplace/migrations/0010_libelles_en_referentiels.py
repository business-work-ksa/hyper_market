"""Les libellés anglais des référentiels livrés avec la plateforme : rayons et offres.

Ne remplit que les champs vides : un libellé anglais déjà corrigé par l'exploitant est gardé.
Copie figée des valeurs de `initialiser_referentiels` au jour de la migration.
"""

from django.db import migrations

RAYONS_EN = {
    "cosmetique-beaute": "Cosmetics & beauty",
    "mode-accessoires": "Fashion & accessories",
    "quincaillerie": "Hardware & DIY",
    "pieces-detachees": "Spare parts",
    "maison-decoration": "Home & decor",
    "petit-electronique": "Small electronics",
    "electromenager": "Home appliances",
    "alimentaire": "Food",
}
OFFRES_EN = {"ETAL": "Stall", "BOUTIQUE": "Shop", "GRANDE_SURFACE": "Superstore"}


def remplir(apps, schema_editor):
    Rayon = apps.get_model("marketplace", "Rayon")
    TypeEmplacement = apps.get_model("marketplace", "TypeEmplacement")
    for code, libelle_en in RAYONS_EN.items():
        Rayon.objects.filter(code=code, libelle_en="").update(libelle_en=libelle_en)
    for code, libelle_en in OFFRES_EN.items():
        TypeEmplacement.objects.filter(code=code, libelle_en="").update(libelle_en=libelle_en)


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0009_libelles_en")]
    operations = [migrations.RunPython(remplir, migrations.RunPython.noop)]
