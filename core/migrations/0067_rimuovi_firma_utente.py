"""Toglie l'immagine di firma dell'utente: i file e poi la colonna.

Dalla presa visione del trasmittal interno (`0062`) nessuna funzione usa più
l'immagine: il PDF riporta nome, data e ora di chi ha preso visione.
"""

import logging

from django.core.files.storage import default_storage
from django.db import migrations

logger = logging.getLogger(__name__)


def elimina_i_file_delle_firme(apps, schema_editor):
    """Cancella dallo storage i file ancora referenziati dalla colonna.

    Va prima della rimozione della colonna, l'unico posto da cui si sa quali
    file sono in uso. Un file che non si riesce a cancellare resta orfano
    (non fa danni) e finisce nel log: la migrazione non deve fallire perché
    lo storage non risponde.
    """
    User = apps.get_model("core", "User")
    for nome in User.objects.exclude(firma="").exclude(firma=None).values_list("firma", flat=True):
        try:
            default_storage.delete(nome)
        except Exception:  # noqa: BLE001 — qualsiasi errore dello storage
            logger.warning("File %s non cancellato dallo storage.", nome, exc_info=True)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0066_presa_visione_automatica"),
    ]

    operations = [
        migrations.RunPython(elimina_i_file_delle_firme, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="user",
            name="firma",
        ),
    ]
