from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0031_user_permesso"),
    ]

    operations = [
        migrations.AddField(
            model_name="revisione",
            name="ignora_anomalie",
            field=models.BooleanField(
                db_column="IgnoraAnomalie",
                default=False,
                help_text="Se attivo, le incongruenze su questa revisione non vengono segnalate.",
            ),
        ),
    ]
