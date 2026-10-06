"""Etichetta di una revisione: numero, lettera o sequenza personalizzata.

Il dato vero di una revisione è il suo numero progressivo (``RevNo``, da 0).
Come viene *mostrato* lo decide l'archivio (Informazioni archivio →
«Revisioni»), ovunque — schermo, Excel, PDF — a prescindere da cosa è
memorizzato sulla singola revisione:

- **Numero**: 0, 1, 2…
- **Lettera** (flag ``RevLetFlag``): A, B, C… Lettera e numero sono due modi
  di scrivere lo stesso dato, quindi quando manca il valore richiesto viene
  convertito l'altro (0 ↔ A, 1 ↔ B, … 25 ↔ Z, 26 ↔ AA).
- **Personalizzata** (``Testata.rev_sequenza`` non vuota, vince sul flag): la
  revisione N mostra l'N-esima etichetta della sequenza, es. ``1,2,3,D,E,F``.
  Oltre la fine la sequenza prosegue dall'ultima etichetta (6 → 7, F → G).

Lo stesso calcolo è replicato in JS in ``core/templates/core/base.html``
(``formatRevLabel``): le due versioni vanno tenute allineate.

Modulo senza import Django: è usato anche dalla generazione dei PDF.
"""

import re

_ALFABETO = 26
_A = ord("A")

# RevLet e la revisione delle righe del trasmittal interno sono CharField(10).
MAX_LUNGHEZZA_ETICHETTA = 10

# [0-9] e non \d: \d accetta anche cifre Unicode, che il JS non riconosce.
_FINALE_NUMERICO = re.compile(r"(.*?)([0-9]+)")
_FINALE_LETTERE = re.compile(r"(.*?)([A-Za-z]+)")


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


def sequenza_revisioni(valore) -> list[str]:
    """Sequenza personalizzata così come memorizzata; ``[]`` se assente o illeggibile."""
    if not isinstance(valore, list | tuple):
        return []
    return [str(voce).strip() for voce in valore if str(voce).strip()]


def valida_sequenza_revisioni(valore) -> list[str]:
    """Normalizza la sequenza personalizzata inserita dall'utente.

    Args:
        valore: Elenco di etichette oppure stringa separata da virgole
            (``"1,2,3,D"``). ``None`` o vuoto significa nessuna sequenza.

    Returns:
        Le etichette senza spazi ai lati, maiuscole/minuscole come scritte.

    Raises:
        ValueError: Con il messaggio da mostrare all'utente.
    """
    if valore is None or (isinstance(valore, str) and not valore.strip()):
        return []
    if isinstance(valore, str):
        valore = valore.split(",")
    if not isinstance(valore, list | tuple):
        raise ValueError("La sequenza deve essere un elenco di etichette.")
    etichette = []
    viste = set()
    for posizione, voce in enumerate(valore, start=1):
        if isinstance(voce, bool) or not isinstance(voce, str | int):
            raise ValueError(f"Etichetta non valida in posizione {posizione}.")
        etichetta = str(voce).strip()
        if not etichetta:
            raise ValueError(f"Etichetta vuota in posizione {posizione}.")
        if "," in etichetta:
            raise ValueError(f"L'etichetta «{etichetta}» non può contenere virgole.")
        if len(etichetta) > MAX_LUNGHEZZA_ETICHETTA:
            raise ValueError(
                f"L'etichetta «{etichetta}» supera i {MAX_LUNGHEZZA_ETICHETTA} caratteri."
            )
        if etichetta.upper() in viste:
            raise ValueError(f"L'etichetta «{etichetta}» è ripetuta.")
        viste.add(etichetta.upper())
        etichette.append(etichetta)
    return etichette


def etichetta_da_sequenza(numero: int, sequenza: list[str]) -> str:
    """Etichetta della revisione ``numero`` (≥ 0) in una sequenza non vuota."""
    if numero < len(sequenza):
        return sequenza[numero]
    oltre = _etichetta_oltre_sequenza(sequenza[-1], numero - len(sequenza) + 1)
    return oltre if oltre is not None else str(numero)


def _etichetta_oltre_sequenza(ultima: str, passi: int) -> str | None:
    """Prosegue la sequenza oltre la fine, partendo dall'ultima etichetta.

    Se finisce con un numero lo incrementa (``6`` → ``7``, ``R09`` → ``R10``),
    se finisce con lettere le incrementa (``F`` → ``G``, ``Z`` → ``AA``,
    ``1A`` → ``1B``). ``None`` quando non si può proseguire (es. ``A-``).
    """
    m = _FINALE_NUMERICO.fullmatch(ultima)
    if m:
        prefisso, cifre = m.groups()
        return prefisso + str(int(cifre) + passi).zfill(len(cifre))
    m = _FINALE_LETTERE.fullmatch(ultima)
    if m:
        prefisso, lettere = m.groups()
        seguito = numero_a_lettera(lettera_a_numero(lettere) + passi)
        return prefisso + (seguito.lower() if lettere.islower() else seguito)
    return None


def _indice_in_sequenza(etichetta, sequenza: list[str]) -> int | None:
    chiave = str(etichetta or "").strip().upper()
    if not chiave:
        return None
    for indice, voce in enumerate(sequenza):
        if voce.upper() == chiave:
            return indice
    return None


def numero_revisione(rev_no, rev_let, rev_let_flag, rev_sequenza=None) -> int | None:
    """Numero progressivo della revisione mostrato dall'etichetta.

    Coincide con ``rev_no`` tranne quando questo manca, o quando con le
    lettere attive la lettera memorizzata ha la precedenza sul numero.
    """
    lettera = str(rev_let or "").strip()
    sequenza = sequenza_revisioni(rev_sequenza)
    if sequenza:
        numero = _as_int(rev_no)
        return numero if numero is not None else _indice_in_sequenza(lettera, sequenza)
    if rev_let_flag:
        if not lettera:
            return _as_int(rev_no)
        numero = lettera_a_numero(lettera)
        # Lettera scritta come numero: viene comunque convertita.
        return numero if numero is not None else _as_int(lettera)
    numero = _as_int(rev_no)
    if numero is None:
        numero = lettera_a_numero(lettera)
    if numero is None:
        numero = _as_int(lettera)
    return numero


def etichetta_revisione(numero, rev_let_flag, rev_sequenza=None) -> str:
    """Etichetta del numero progressivo ``numero`` secondo l'archivio."""
    numero = _as_int(numero)
    if numero is None:
        return ""
    sequenza = sequenza_revisioni(rev_sequenza)
    if sequenza:
        return etichetta_da_sequenza(numero, sequenza) if numero >= 0 else ""
    if rev_let_flag:
        return numero_a_lettera(numero)
    return str(numero)


def format_revisione_label(rev_no, rev_let, rev_let_flag, rev_sequenza=None) -> str:
    """Etichetta da mostrare per la revisione.

    Args:
        rev_no: Numero della revisione (``RevNo``), può essere ``None``.
        rev_let: Lettera della revisione (``RevLet``), può essere vuota.
        rev_let_flag: Flag «Revisioni con lettera» della testata.
        rev_sequenza: Sequenza personalizzata della testata; se non è vuota
            vince sul flag.

    Returns:
        L'etichetta della sequenza personalizzata, altrimenti la lettera se il
        flag è attivo, altrimenti il numero; stringa vuota quando la revisione
        non ha né numero né lettera.
    """
    numero = numero_revisione(rev_no, rev_let, rev_let_flag, rev_sequenza)
    if numero is None:
        # Senza numero e con un'etichetta fuori sequenza: la si mostra com'è.
        return str(rev_let or "").strip() if sequenza_revisioni(rev_sequenza) else ""
    return etichetta_revisione(numero, rev_let_flag, rev_sequenza)


def _as_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
