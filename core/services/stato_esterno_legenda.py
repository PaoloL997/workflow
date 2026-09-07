"""Legenda STATUS dell'header PDF, costruita sulle risposte del cliente.

L'admin configura lettera, nome e colore di ogni risposta del cliente
(``StatoEsterno``): la legenda stampata nell'header del PDF deve seguire quelle
scelte, senza colori fissi nel codice, così resta uniforme alle celle colorate
delle viste situazione documenti.

Se non c'è nessuna risposta configurata (o il database non è raggiungibile) si
ricade sulla legenda canonica di ``stato_esterno_codes``.
"""

from django.db import DatabaseError

from ..models import StatoEsterno
from .stato_esterno_codes import (
    DEFAULT_STATUS_COLORS,
    DEFAULT_STATUS_LEGEND,
    letter_for_status_name,
)


def _voce(lettera: str, nome: str, colore: str) -> dict:
    return {"lettera": lettera, "nome": nome, "colore": colore}


def legenda_default() -> list:
    """Legenda canonica: le otto risposte storiche con i colori di default."""
    return [_voce(lettera, nome, colore) for lettera, nome, colore in DEFAULT_STATUS_LEGEND]


def legenda_stati_esterni() -> list:
    """Voci della legenda STATUS: ``[{"lettera", "nome", "colore"}, ...]``.

    Le voci arrivano dalle risposte del cliente messe a sistema dall'admin,
    ordinate per lettera. La lettera mancante viene dedotta dal nome, il colore
    mancante ricade sul default della lettera. Le risposte senza lettera non
    entrano in legenda: nelle celle del PDF sono identificate proprio da quella.
    """
    try:
        stati = list(StatoEsterno.objects.all())
    except DatabaseError:
        stati = []

    voci = {}
    for stato in stati:
        lettera = (stato.lettera or "").strip().upper()
        if not lettera:
            lettera = letter_for_status_name(stato.nome)
        nome = (stato.nome or "").strip()
        if not lettera or not nome or lettera in voci:
            continue
        colore = (stato.colore or "").strip() or DEFAULT_STATUS_COLORS.get(lettera, "")
        voci[lettera] = _voce(lettera, nome, colore)

    if not voci:
        return legenda_default()
    return [voci[lettera] for lettera in sorted(voci)]


