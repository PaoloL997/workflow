"""Connector for Business Central ERP."""

import logging
import os

import pandas as pd
import pyodbc
from dotenv import load_dotenv

from src.erp.queries import (
    COMMESSA_ANAGRAFICA,
    COMMESSA_COMMERCIALE,
    QCP_ITEMS,
    QCP_TESTATA,
)

load_dotenv()

logger = logging.getLogger(__name__)


class BusinessCentral:
    """Business Central connector class. Provides methods to connect and query the Business Central database."""

    def __init__(self):
        server = os.getenv("BUSINESS_CENTRAL_SERVER")
        database = os.getenv("BUSINESS_CENTRAL_DATABASE")
        uid = os.getenv("BUSINESS_CENTRAL_UID")
        psw = os.getenv("BUSINESS_CENTRAL_PSW")

        missing = [
            k
            for k, v in {
                "BUSINESS_CENTRAL_SERVER": server,
                "BUSINESS_CENTRAL_DATABASE": database,
                "BUSINESS_CENTRAL_UID": uid,
                "BUSINESS_CENTRAL_PSW": psw,
            }.items()
            if not v
        ]
        if missing:
            logger.error("Variabili .env mancanti: %s", ", ".join(missing))

        self.conn = self._connect(server=server, database=database, uid=uid, psw=psw)

    @staticmethod
    def _connect(server: str, database: str, uid: str, psw: str):
        driver = os.getenv("BUSINESS_CENTRAL_DRIVER", "ODBC Driver 18 for SQL Server")
        trust = os.getenv("BUSINESS_CENTRAL_TRUST_SERVER_CERTIFICATE", "yes")
        logger.debug(
            "Tentativo di connessione a Business Central — server=%s  database=%s  uid=%s  driver=%s",
            server,
            database,
            uid,
            driver,
        )
        try:
            connection_string = (
                f"Driver={{{driver}}};"
                f"Server={server};"
                f"Database={database};"
                f"UID={uid};"
                f"PWD={psw};"
                f"TrustServerCertificate={trust}"
            )
            conn = pyodbc.connect(connection_string, timeout=10)
            logger.info(
                "Connessione a Business Central riuscita (server=%s, database=%s)", server, database
            )
            return conn
        except pyodbc.InterfaceError as e:
            logger.error("Driver ODBC non trovato o non configurato: %s", e)
        except pyodbc.OperationalError as e:
            logger.error('Impossibile raggiungere il server "%s": %s', server, e)
        except pyodbc.DatabaseError as e:
            logger.error('Errore database "%s": %s', database, e)
        except pyodbc.Error as e:
            sqlstate = e.args[0] if e.args else "sconosciuto"
            logger.error("Errore ODBC (SQLSTATE %s): %s", sqlstate, e)
        return None

    def fetch(self, query: str, params=None) -> pd.DataFrame | None:
        """Fetch data from Business Central using a SQL query. Returns a pandas DataFrame."""
        if self.conn is None:
            logger.error("fetch() chiamato ma la connessione a Business Central non è disponibile")
            return None
        try:
            logger.debug("Esecuzione query ERP (params=%s)", params)
            df = pd.read_sql(query, self.conn, params=params)
            logger.debug("Query completata — %d righe restituite", len(df))
            return df
        except Exception as e:
            logger.error("Errore durante l'esecuzione della query ERP: %s", e)
            return None

    def get_commessa_anagrafica(self, numero_commessa: str) -> pd.DataFrame | None:
        """Dati anagrafici della commessa: numero, descrizione, cliente."""
        logger.debug("get_commessa_anagrafica(%s)", numero_commessa)
        return self.fetch(COMMESSA_ANAGRAFICA, params=(numero_commessa,))

    def get_commessa_commerciale(self, numero_commessa: str) -> pd.DataFrame | None:
        """Dati commerciali della commessa: PO cliente e data consegna."""
        logger.debug("get_commessa_commerciale(%s)", numero_commessa)
        return self.fetch(COMMESSA_COMMERCIALE, params=(numero_commessa,))

    def get_qcp_testata(self, numero_commessa: str) -> pd.DataFrame | None:
        """Dati di testata per il Quality Control Plan: progetto, stabilimento, owner."""
        logger.debug("get_qcp_testata(%s)", numero_commessa)
        return self.fetch(QCP_TESTATA, params=(numero_commessa,))

    def get_qcp_items(self, numero_commessa: str) -> pd.DataFrame | None:
        """Item della commessa dalla distinta di fornitura (scope of supply)."""
        logger.debug("get_qcp_items(%s)", numero_commessa)
        return self.fetch(QCP_ITEMS, params=(numero_commessa,))

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.debug("Connessione a Business Central chiusa")
