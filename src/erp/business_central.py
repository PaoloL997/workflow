"""Connector for Business Central ERP. """
import os
import pyodbc
import pandas as pd
from dotenv import load_dotenv
from src.erp.queries import COMMESSA_ANAGRAFICA, COMMESSA_COMMERCIALE


load_dotenv()

class BusinessCentral:
    """Business Central connector class. Provides methods to connect and query the Business Central database."""
    def __init__(self):
        self.conn = self._connect(
            server=os.getenv('BUSINESS_CENTRAL_SERVER'),
            database=os.getenv('BUSINESS_CENTRAL_DATABASE'),
            uid=os.getenv('BUSINESS_CENTRAL_UID'),
            psw=os.getenv('BUSINESS_CENTRAL_PSW'),
        )

    @staticmethod
    def _connect(
        server: str,
        database: str,
        uid: str,
        psw: str,
        ):
        try:
            connection_string = (
                    f"Driver={{SQL Server}};"
                    f"Server={server};"
                    f"Database={database};"
                    f"UID={uid};"
                    f"PWD={psw}"
                )
            conn = pyodbc.connect(connection_string)
            return conn
        except pyodbc.Error as e:
            print(f"Error connecting to Business Central: {e}")
            return None
    
    def fetch(self, query: str, params=None) -> pd.DataFrame | None:
        """Fetch data from Business Central using a SQL query. Returns a pandas DataFrame."""
        df = pd.read_sql(query, self.conn, params=params)
        return df
    
    def get_commessa_anagrafica(self, numero_commessa: str) -> pd.DataFrame | None:
        """Dati anagrafici della commessa: numero, descrizione, cliente."""
        return self.fetch(COMMESSA_ANAGRAFICA, params=(numero_commessa,))

    def get_commessa_commerciale(self, numero_commessa: str) -> pd.DataFrame | None:
        """Dati commerciali della commessa: PO cliente e data consegna."""
        return self.fetch(COMMESSA_COMMERCIALE, params=(numero_commessa,))

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None