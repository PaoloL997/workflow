from django.db import migrations

# Match per nome: gli id degli stabilimenti in produzione sono diversi da
# quelli di sviluppo, e codice_bc non è la primary key.
SIGLE_E_CODICI = {
    "Valbrembo": ("BG", 1),
    "Albignasego": ("PD", 2),
    "Marghera": ("VE", 3),
    "Ricengo": ("CR", 4),
    "Schio": ("VI", 5),
    # Milano resta senza sigla né codice: non è un sito costruttivo.
}


def popola(apps, schema_editor):
    Stabilimento = apps.get_model("core", "Stabilimento")
    for nome, (sigla, codice_bc) in SIGLE_E_CODICI.items():
        Stabilimento.objects.filter(nome=nome).update(sigla=sigla, codice_bc=codice_bc)


def svuota(apps, schema_editor):
    Stabilimento = apps.get_model("core", "Stabilimento")
    Stabilimento.objects.filter(nome__in=SIGLE_E_CODICI).update(sigla=None, codice_bc=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0044_anagrafiche_trasmittal_interno"),
    ]

    operations = [
        migrations.RunPython(popola, svuota),
    ]
