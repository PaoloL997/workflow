from django.db import migrations


SENT_TO_CLIENT_COLOR = "#FFC000"
SENT_STATUS_NAMES = {
    "final - as built",
    "for information",
}


def update_sent_status_colors(apps, schema_editor):
    """Apply a yellow color to external statuses used for sent documents."""
    StatoEsterno = apps.get_model("core", "StatoEsterno")
    for stato in StatoEsterno.objects.all():
        nome = (stato.nome or "").strip().lower()
        if nome in SENT_STATUS_NAMES:
            stato.colore = SENT_TO_CLIENT_COLOR
            stato.save(update_fields=["colore"])


def revert_sent_status_colors(apps, schema_editor):
    """Keep migration reversible without restoring previous guessed colors."""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0023_update_statoesterno_colors"),
    ]

    operations = [
        migrations.RunPython(update_sent_status_colors, revert_sent_status_colors),
    ]
