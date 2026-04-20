# Query SQL verso Business Central (database BREMBANA_PROD su SQL Server).
# Ogni costante è una stringa parametrizzata con ? come placeholder (stile pyodbc).

# ── Query 1: dati anagrafici della commessa ────────────────────────────────────
# Tabella: BREMBANA$Job$437dbf0e-84ff-417a-965d-ed2bb9650972
# È la tabella Job standard di Business Central (prima estensione).
#
# Campi restituiti:
#   commessa   → numero commessa BC          → Testata.job
#   descrizione→ titolo/oggetto della commessa → Testata.job_detail
#   cliente    → nome del cliente fatturato  → Testata.client
COMMESSA_ANAGRAFICA = """
    SELECT
        CAST(No_            AS NVARCHAR(MAX)) AS commessa,
        CAST(Description    AS NVARCHAR(MAX)) AS descrizione,
        CAST([Bill-to Name] AS NVARCHAR(MAX)) AS cliente
    FROM [BREMBANA$Job$437dbf0e-84ff-417a-965d-ed2bb9650972]
    WHERE No_ = ?
"""

# ── Query 2: dati commerciali della commessa ───────────────────────────────────
# Tabella: BREMBANA$Job$d71d761a-a85c-4b10-8459-d30c64b4a709
# È la tabella Job con estensioni custom NBT_BRL (campi aggiuntivi Brembana).
#
# Campi restituiti:
#   commessa      → numero commessa BC (chiave di join con COMMESSA_ANAGRAFICA)
#   po_cliente    → riferimento ordine acquisto del cliente → Testata.po_no
#   data_consegna → data di consegna concordata            → Testata.delivery_date
COMMESSA_COMMERCIALE = """
    SELECT
        CAST(No_                           AS NVARCHAR(MAX)) AS commessa,
        CAST([NBT_BRL Ref_ Customer Order] AS NVARCHAR(MAX)) AS po_cliente,
        FORMAT([NBT_BRL Consignment Date], 'yyyy-MM-dd')     AS data_consegna
    FROM [BREMBANA$Job$d71d761a-a85c-4b10-8459-d30c64b4a709]
    WHERE No_ = ?
"""
