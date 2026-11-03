"""Unisce gli indirizzi "sempre in copia" agli indirizzi A/CC dello stabilimento.

``IndirizzoDefaultTrasmittalInterno`` è legato allo stabilimento dalla 0058 e
da allora ha gli stessi campi di ``IndirizzoStabilimento`` (stabilimento,
email, tipo, attivo): due tabelle per la stessa cosa. Ogni indirizzo default
diventa un indirizzo dello stesso stabilimento con lo stesso tipo. Se
l'indirizzo c'è già, resta uno solo, attivo se lo era almeno uno dei due:
prima finiva comunque in lettera.

All'indietro la tabella torna vuota: gli indirizzi restano tra quelli dello
stabilimento e continuano a finire in lettera.
"""

from django.db import migrations


def unisci_indirizzi_default(apps, schema_editor):
    IndirizzoDefault = apps.get_model("core", "IndirizzoDefaultTrasmittalInterno")
    IndirizzoStabilimento = apps.get_model("core", "IndirizzoStabilimento")
    for default in IndirizzoDefault.objects.all():
        indirizzo, creato = IndirizzoStabilimento.objects.get_or_create(
            stabilimento_id=default.stabilimento_id,
            email=default.email,
            tipo=default.tipo,
            defaults={"attivo": default.attivo},
        )
        if not creato and default.attivo and not indirizzo.attivo:
            indirizzo.attivo = True
            indirizzo.save(update_fields=["attivo"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0063_revisionefilelink_tipo"),
    ]

    operations = [
        migrations.RunPython(unisci_indirizzi_default, migrations.RunPython.noop),
        migrations.DeleteModel(name="IndirizzoDefaultTrasmittalInterno"),
    ]
