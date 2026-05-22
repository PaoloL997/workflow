from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_remove_ticket_stato"),
    ]

    operations = [
        migrations.CreateModel(
            name="ModelloDocumento",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "doc_title",
                    models.CharField(
                        db_column="DocTitle", max_length=300, verbose_name="Titolo documento"
                    ),
                ),
                (
                    "item_no",
                    models.CharField(
                        blank=True,
                        db_column="ItemNo",
                        default="",
                        max_length=100,
                        verbose_name="Item",
                    ),
                ),
                (
                    "codice_fisso",
                    models.CharField(
                        db_column="CodiceFisso",
                        max_length=100,
                        verbose_name="Codice fisso",
                        help_text='Parte fissa del numero documento interno B&R. Il numero finale sarà "{numero_commessa}-{codice_fisso}".',
                    ),
                ),
            ],
            options={
                "verbose_name": "Modello documento",
                "verbose_name_plural": "Modelli documento",
                "db_table": "modelli_documento",
                "ordering": ["doc_title"],
                "managed": True,
            },
        ),
    ]
