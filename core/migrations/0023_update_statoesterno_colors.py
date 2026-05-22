from django.db import migrations


APPROVED_COLOR = "#00B050"
COMMENTED_COLOR = "#D61D09"


def update_statoesterno_colors(apps, schema_editor):
    """Normalize external status colors for approved and commented responses."""
    StatoEsterno = apps.get_model("core", "StatoEsterno")

    for stato in StatoEsterno.objects.all():
        nome = (stato.nome or "").strip().lower()
        if nome.startswith("approved"):
            stato.colore = APPROVED_COLOR
            stato.save(update_fields=["colore"])
        elif nome.startswith("commented"):
            stato.colore = COMMENTED_COLOR
            stato.save(update_fields=["colore"])


def revert_statoesterno_colors(apps, schema_editor):
    """Keep migration reversible without guessing previous colors."""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_rimuovi_creato_da_ticket"),
    ]

    operations = [
        migrations.RunPython(update_statoesterno_colors, revert_statoesterno_colors),
    ]
