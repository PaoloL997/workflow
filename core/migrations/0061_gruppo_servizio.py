from django.db import migrations

# Il nome è quello di core.permissions.GRUPPO_SERVIZIO, copiato e non importato:
# una migration non deve cambiare se un domani cambia il codice.
GRUPPO_SERVIZIO = "Servizio"


def crea_gruppo(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=GRUPPO_SERVIZIO)


def elimina_gruppo(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GRUPPO_SERVIZIO).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("core", "0060_api_token_senza_scadenza"),
    ]

    operations = [
        migrations.RunPython(crea_gruppo, elimina_gruppo),
    ]
