import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0065_indirizzi_tipo_documento"),
    ]

    operations = [
        migrations.AddField(
            model_name="presavisionetransmittalinterno",
            name="automatica",
            field=models.BooleanField(
                default=False,
                help_text="Registrata dall'applicazione all'emissione («in automatico»), senza utente.",
            ),
        ),
        migrations.AlterField(
            model_name="presavisionetransmittalinterno",
            name="utente",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="prese_visione_trasmittal_interno",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
