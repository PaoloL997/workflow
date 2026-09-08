"""Etichetta di una revisione: lettera oppure numero, secondo l'archivio.

Il flag ``RevLetFlag`` della testata (Informazioni archivio → «Revisioni con
lettera») decide da solo come la revisione viene mostrata ovunque — schermo,
Excel, PDF: se è attivo si vede sempre la lettera (A, B, C…), se non lo è si
vede sempre il numero (0, 1, 2…), a prescindere da cosa è memorizzato sulla
singola revisione. Lettera e numero sono due modi di scrivere lo stesso dato,
quindi quando manca il valore richiesto viene convertito l'altro
(0 ↔ A, 1 ↔ B, … 25 ↔ Z, 26 ↔ AA).

Modulo senza import Django: è usato anche dalla generazione dei PDF.
"""

_ALFABETO = 26
_A = ord("A")


def numero_a_lettera(rev_no) -> str:
    """0 → ``A``, 1 → ``B``, … 25 → ``Z``, 26 → ``AA``. Vuoto se non convertibile."""
    numero = _as_int(rev_no)
    if numero is None or numero < 0:
        return ""
    label = ""
    numero += 1
    while numero > 0:
        numero, resto = divmod(numero - 1, _ALFABETO)
        label = chr(_A + resto) + label
    return label


def lettera_a_numero(rev_let) -> int | None:
    """``A`` → 0, ``B`` → 1, … ``Z`` → 25, ``AA`` → 26. ``None`` se non è una sigla."""
    sigla = str(rev_let or "").strip().upper()
    if not sigla or not sigla.isascii() or not sigla.isalpha():
        return None
    numero = 0
    for ch in sigla:
        numero = numero * _ALFABETO + (ord(ch) - _A + 1)
    return numero - 1


def format_revisione_label(rev_no, rev_let, rev_let_flag) -> str:
    """Etichetta da mostrare per la revisione.

    Args:
        rev_no: Numero della revisione (``RevNo``), può essere ``None``.
        rev_let: Lettera della revisione (``RevLet``), può essere vuota.
        rev_let_flag: Flag «Revisioni con lettera» della testata.

    Returns:
        La lettera se il flag è attivo, altrimenti il numero; stringa vuota
        quando la revisione non ha né numero né lettera.
    """
    lettera = str(rev_let or "").strip()
    if rev_let_flag:
        if lettera and lettera_a_numero(lettera) is not None:
            return lettera.upper()
        # Lettera assente (o scritta come numero): si ricava dal numero.
        return numero_a_lettera(_as_int(lettera) if lettera else rev_no)
    numero = _as_int(rev_no)
    if numero is None:
        numero = lettera_a_numero(lettera)
        if numero is None:
            numero = _as_int(lettera)
    return "" if numero is None else str(numero)


def _as_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
