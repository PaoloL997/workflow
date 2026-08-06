from django.db import migrations, models


def populate_lettera(apps, schema_editor):
    StatoEsterno = apps.get_model("core", "StatoEsterno")
    from core.services.stato_esterno_codes import letter_for_status_name

    for stato in StatoEsterno.objects.all():
        letter = letter_for_status_name(stato.nome)
        if letter and stato.lettera != letter:
            stato.lettera = letter
            stato.save(update_fields=["lettera"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_commissapin"),
    ]

    operations = [
        migrations.AddField(
            model_name="statoesterno",
            name="lettera",
            field=models.CharField(
                blank=True,
                db_column="Lettera",
                default="",
                help_text="Codice lettera mostrato in situazione documenti (es. A = Approved).",
                max_length=2,
                verbose_name="Lettera",
            ),
        ),
        migrations.RunPython(populate_lettera, noop_reverse),
    ]
