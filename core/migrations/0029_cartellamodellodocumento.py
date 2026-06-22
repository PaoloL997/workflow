from django.db import migrations, models
import django.db.models.deletion


def assign_default_cartella(apps, schema_editor):
    Cartella = apps.get_model("core", "CartellaModelloDocumento")
    Modello = apps.get_model("core", "ModelloDocumento")
    if not Modello.objects.exists():
        return
    cartella, _ = Cartella.objects.get_or_create(
        nome="Predefinita",
        defaults={"descrizione": "Modelli migrati dalla configurazione precedente."},
    )
    Modello.objects.filter(cartella__isnull=True).update(cartella=cartella)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0028_statoesterno_crea_nuova_rev"),
    ]

    operations = [
        migrations.CreateModel(
            name="CartellaModelloDocumento",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "nome",
                    models.CharField(
                        db_column="Nome",
                        max_length=200,
                        verbose_name="Nome cartella",
                    ),
                ),
                (
                    "descrizione",
                    models.TextField(
                        blank=True,
                        db_column="Descrizione",
                        default="",
                        verbose_name="Descrizione",
                    ),
                ),
            ],
            options={
                "verbose_name": "Cartella modelli documento",
                "verbose_name_plural": "Cartelle modelli documento",
                "db_table": "cartelle_modelli_documento",
                "ordering": ["nome"],
                "managed": True,
            },
        ),
        migrations.AddField(
            model_name="modellodocumento",
            name="cartella",
            field=models.ForeignKey(
                blank=True,
                db_column="CartellaId",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="modelli",
                to="core.cartellamodellodocumento",
                verbose_name="Cartella",
            ),
        ),
        migrations.RunPython(assign_default_cartella, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="modellodocumento",
            name="cartella",
            field=models.ForeignKey(
                db_column="CartellaId",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="modelli",
                to="core.cartellamodellodocumento",
                verbose_name="Cartella",
            ),
        ),
    ]
