from django.db import migrations


def clear_transmittal(apps, schema_editor):
    Transmittal = apps.get_model("core", "Transmittal")
    Transmittal.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0038_user_stabilimento"),
    ]

    operations = [
        migrations.RunPython(clear_transmittal, migrations.RunPython.noop),
    ]
