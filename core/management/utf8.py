"""Output UTF-8 per i comandi di gestione, anche sulla console cp1252 di Windows."""


def forza_utf8(wrapper):
    """Porta lo stream di un comando (``self.stdout``/``self.stderr``) su UTF-8.

    Su Windows la console è cp1252 e caratteri come la freccia dei report (→)
    fanno abortire il comando con ``UnicodeEncodeError``, sia a video sia
    quando lo scheduler redirige l'output su file.
    """
    stream = getattr(wrapper, "_out", wrapper)
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass
