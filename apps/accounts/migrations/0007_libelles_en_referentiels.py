"""Les libellés anglais des référentiels livrés avec la plateforme.

Ne remplit que les champs vides : un libellé anglais déjà corrigé par l'exploitant est gardé.
Copie figée des valeurs de `initialiser_referentiels` au jour de la migration.
"""

from django.db import migrations

ROLES_EN = {
    "GERANT": "Shop manager",
    "VENDEUR": "Salesperson",
    "CAISSIER": "Cashier",
    "MAGASINIER": "Storekeeper",
    "COMPTABLE": "Accountant",
    "RH": "HR manager",
    "RESP_RAYON": "Aisle manager",
    "ADMIN_MARCHE": "Market manager",
    "CABINET": "Partner accounting firm",
}


def remplir(apps, schema_editor):
    Modele = apps.get_model("accounts", "Role")
    for code, libelle_en in ROLES_EN.items():
        Modele.objects.filter(code=code, libelle_en="").update(libelle_en=libelle_en)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_libelles_en")]
    operations = [migrations.RunPython(remplir, migrations.RunPython.noop)]
