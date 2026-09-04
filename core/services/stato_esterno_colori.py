"""Colori delle celle legate alle risposte del cliente (StatoEsterno).

Le viste situazione documenti (verticale e orizzontale) colorano le celle con il
colore configurato sullo stato esterno, tenuto praticamente inalterato per
restare uniforme alla legenda. Il testo diventa bianco o nero a seconda di quale
dei due si legge meglio sul colore, così restano leggibili anche gli stati
bianchi, gialli, neri o grigi.
"""

# Testo delle celle colorate: bianco sui colori scuri, quasi nero sui chiari.
TEXT_LIGHT = "#FFFFFF"
TEXT_DARK = "#111111"

# Usato quando lo stato esterno non ha un colore (o ne ha uno non valido).
FALLBACK_BG = "#9E9E9E"

# Contrasto minimo WCAG AA per testo normale.
MIN_CONTRAST = 4.5

# Se nessuno dei due testi arriva a MIN_CONTRAST (succede solo con i mezzi toni)
# il fondo viene spostato a piccoli passi verso bianco/nero: bastano pochi punti
# percentuali, così la cella resta riconoscibile accanto alla legenda.
_ADJUST_STEP = 0.04
_MAX_ADJUST = 0.32

_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)


def hex_to_rgb(colore):
    """Return ``(r, g, b)`` for ``#RRGGBB`` / ``#RGB``, or None if invalid."""
    h = str(colore or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def rgb_to_hex(rgb) -> str:
    """Return the ``#RRGGBB`` form of an ``(r, g, b)`` triple."""
    return "#" + "".join(f"{max(0, min(255, int(round(c)))):02X}" for c in rgb[:3])


def _as_rgb(colore):
    """Accept both ``#RRGGBB`` strings and ``(r, g, b)`` triples."""
    if isinstance(colore, (tuple, list)):
        if len(colore) < 3:
            return None
        return tuple(max(0, min(255, int(c))) for c in colore[:3])
    return hex_to_rgb(colore)


def _channel_luminance(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(colore) -> float:
    """WCAG relative luminance (0 = nero, 1 = bianco)."""
    r, g, b = _as_rgb(colore) or _BLACK
    return (
        0.2126 * _channel_luminance(r)
        + 0.7152 * _channel_luminance(g)
        + 0.0722 * _channel_luminance(b)
    )


def contrast_ratio(colore_a, colore_b) -> float:
    """WCAG contrast ratio between two colors (1 = identici, 21 = max)."""
    la = relative_luminance(colore_a)
    lb = relative_luminance(colore_b)
    chiaro, scuro = max(la, lb), min(la, lb)
    return (chiaro + 0.05) / (scuro + 0.05)


def readable_text_color(sfondo) -> str:
    """Return TEXT_DARK or TEXT_LIGHT, whichever reads better on ``sfondo``."""
    rgb = _as_rgb(sfondo) or hex_to_rgb(FALLBACK_BG)
    if contrast_ratio(rgb, TEXT_DARK) >= contrast_ratio(rgb, TEXT_LIGHT):
        return TEXT_DARK
    return TEXT_LIGHT


def _blend(rgb, target, amount):
    return tuple(round(c + (t - c) * amount) for c, t in zip(rgb, target))


def cell_colors(colore) -> dict:
    """Return ``{"bg", "fg"}`` for a cell tied to a client response color.

    ``bg`` è il colore configurato (spostato di pochissimo solo se nessun testo
    ci si leggerebbe sopra), ``fg`` è il bianco o il nero che ci si legge meglio.
    """
    rgb = _as_rgb(colore) or hex_to_rgb(FALLBACK_BG)
    testo = readable_text_color(rgb)
    # Allontanando il fondo dal testo il contrasto può solo salire.
    target = _WHITE if testo == TEXT_DARK else _BLACK
    fondo = rgb
    amount = 0.0
    while contrast_ratio(fondo, testo) < MIN_CONTRAST and amount < _MAX_ADJUST:
        amount = min(amount + _ADJUST_STEP, _MAX_ADJUST)
        fondo = _blend(rgb, target, amount)
    return {"bg": rgb_to_hex(fondo), "fg": testo}
