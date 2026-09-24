"""Nuova configurazione delle risposte del cliente (StatoEsterno).

Colori e flag «Crea nuova revisione» arrivano dall'elenco fornito dall'ufficio:
i colori sostituiscono quelli creati all'import da Access, mentre «Final - As
Built» e «For Information» chiudono il giro e non generano più una revisione
nuova alla ricezione. Le righe si riconoscono dal nome, che è unico.
"""

from django.db import migrations

# nome (minuscolo) → (colore, crea_nuova_rev)
RISPOSTE = {
    "approved": ("#4AF536", True),
    "commented - to be issued as final": ("#E32400", True),
    "commented - to be resubmitted - work can proceed": ("#E32400", True),
    "final - as built": ("#1649F0", False),
    "for information": ("#4AF536", False),
    "old": ("#131314", True),
    "rejected - work can not proceed": ("#000000", True),
    "superseeded": ("#1649F0", True),
}


def applica_risposte(apps, schema_editor):
    """Apply color and «crea nuova revisione» to every known client response."""
    StatoEsterno = apps.get_model("core", "StatoEsterno")
    for stato in StatoEsterno.objects.all():
        valori = RISPOSTE.get((stato.nome or "").strip().lower())
        if not valori:
            continue
        colore, crea_nuova_rev = valori
        campi = []
        if stato.colore != colore:
            stato.colore = colore
            campi.append("colore")
        if stato.crea_nuova_rev != crea_nuova_rev:
            stato.crea_nuova_rev = crea_nuova_rev
            campi.append("crea_nuova_rev")
        if campi:
            stato.save(update_fields=campi)


def revert_risposte(apps, schema_editor):
    """Keep migration reversible without restoring the previous configuration."""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0044_notifica_autore"),
    ]

    operations = [
        migrations.RunPython(applica_risposte, revert_risposte),
    ]
