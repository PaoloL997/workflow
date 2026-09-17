from django.db import migrations, models


def popola_tpi_strutturato(apps, schema_editor):
    """Testo libero -> (tpi bool, tpi_destinatario): non vuoto = SÌ + il testo com'era."""
    RigaTransmittalInterno = apps.get_model("core", "RigaTransmittalInterno")
    for riga in RigaTransmittalInterno.objects.all():
        testo = (riga.tpi_testo or "").strip()
        riga.tpi_destinatario = testo
        riga.tpi_bool = bool(testo)
        riga.save(update_fields=["tpi_destinatario", "tpi_bool"])


def ripristina_tpi_testo(apps, schema_editor):
    RigaTransmittalInterno = apps.get_model("core", "RigaTransmittalInterno")
    for riga in RigaTransmittalInterno.objects.all():
        riga.tpi_testo = riga.tpi_destinatario if riga.tpi_bool else ""
        riga.save(update_fields=["tpi_testo"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0050_origine_destinatario_manuale"),
    ]

    operations = [
        # Il vecchio campo testuale libero non può diventare direttamente un
        # BooleanField (il contenuto non è un booleano serializzato): si
        # rinomina da parte, si popolano i due nuovi campi via RunPython, poi
        # si rimuove e si rinomina il campo booleano temporaneo al suo posto.
        migrations.RenameField(
            model_name="rigatransmittalinterno",
            old_name="tpi",
            new_name="tpi_testo",
        ),
        migrations.AddField(
            model_name="rigatransmittalinterno",
            name="tpi_destinatario",
            field=models.CharField(
                blank=True,
                max_length=50,
                help_text='Chi, se tpi è attivo (es. "No.Bo.", "AI", o un altro destinatario).',
            ),
        ),
        migrations.AddField(
            model_name="rigatransmittalinterno",
            name="tpi_bool",
            field=models.BooleanField(
                default=False,
                help_text="Il documento va trasmesso a un ispettore terzo (TPI).",
            ),
        ),
        migrations.RunPython(popola_tpi_strutturato, ripristina_tpi_testo),
        migrations.RemoveField(
            model_name="rigatransmittalinterno",
            name="tpi_testo",
        ),
        migrations.RenameField(
            model_name="rigatransmittalinterno",
            old_name="tpi_bool",
            new_name="tpi",
        ),
    ]
