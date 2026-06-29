"""Read commessa data from the legacy Access MDB via ODBC."""

import logging
from pathlib import Path

import pandas as pd
import pyodbc
from django.conf import settings

logger = logging.getLogger(__name__)

_QUERIES = {
    "testata": "SELECT * FROM [Testata] WHERE [Job] = ?",
    "indirsped": "SELECT * FROM [IndirSped] WHERE [Job] = ?",
    "dettaglio": "SELECT * FROM [Dettaglio] WHERE [Job] = ?",
    "revisioni": "SELECT * FROM [Revisioni] WHERE [Job] = ?",
}


def _connection_string() -> str:
    return f"Driver={{{settings.ACCESS_ODBC_DRIVER}}};DBQ={settings.ACCESS_MDB_PATH};ReadOnly=1;"


def get_access_connection() -> pyodbc.Connection:
    """Open a read-only ODBC connection to the configured Access database."""
    mdb_path = Path(settings.ACCESS_MDB_PATH)
    if not mdb_path.is_file():
        raise FileNotFoundError(f'Database Access non trovato: "{settings.ACCESS_MDB_PATH}"')

    try:
        conn = pyodbc.connect(_connection_string(), timeout=30)
        logger.info("Connessione Access riuscita (path=%s)", settings.ACCESS_MDB_PATH)
        return conn
    except pyodbc.InterfaceError as exc:
        raise RuntimeError(
            f"Driver ODBC Access non disponibile ({settings.ACCESS_ODBC_DRIVER}): {exc}"
        ) from exc
    except pyodbc.Error as exc:
        raise RuntimeError(
            f'Impossibile aprire il database Access "{settings.ACCESS_MDB_PATH}": {exc}'
        ) from exc


def fetch_commessa_frames(job: str) -> dict[str, pd.DataFrame]:
    """Fetch testata, indirizzo, documenti and revisioni for a single job."""
    conn = get_access_connection()
    try:
        return {key: pd.read_sql(query, conn, params=[job]) for key, query in _QUERIES.items()}
    finally:
        conn.close()
