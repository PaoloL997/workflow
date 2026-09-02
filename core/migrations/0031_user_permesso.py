from django.db import migrations, models


def migrate_permessi(apps, schema_editor):
    User = apps.get_model("core", "User")
    for user in User.objects.all():
        if user.is_superuser or user.is_staff:
            user.permesso = "admin"
        else:
            user.permesso = "writing"
        user.is_staff = user.permesso in ("admin", "writing")
        user.save(update_fields=["permesso", "is_staff"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0030_testata_actual_delivery_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="permesso",
            field=models.CharField(
                choices=[
                    ("admin", "Admin"),
                    ("writing", "Scrittura"),
                    ("reading", "Lettura"),
                ],
                db_column="Permesso",
                default="reading",
                max_length=20,
            ),
        ),
        migrations.RunPython(migrate_permessi, migrations.RunPython.noop),
    ]
