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
# Tabella: BREMBANA$Job$437dbf0e-84ff-417a-965d-ed2bb9650972$ext
# Campi custom NBT_BRL della tabella Job (estensione "BRL_Main" di NBT).
#
# Fino al 16/07/2026 questi campi vivevano in una tabella dedicata all'estensione
# (BREMBANA$Job$d71d761a-a85c-4b10-8459-d30c64b4a709, l'App ID di BRL_Main). Un
# aggiornamento tecnico di Business Central quel giorno ha consolidato i campi
# extension nella tabella "$ext" della tabella base (Job), condivisa da tutte le
# estensioni che la toccano: la vecchia tabella non esiste più, la query è stata
# aggiornata di conseguenza. Le colonne mantengono il suffisso "$d71d761a-..."
# (l'App ID di BRL_Main) per tracciare quale estensione le possiede.
#
# Campi restituiti:
#   commessa      → numero commessa BC (chiave di join con COMMESSA_ANAGRAFICA)
#   po_cliente    → riferimento ordine acquisto del cliente → Testata.po_no
#   data_consegna → data di consegna concordata            → Testata.delivery_date
#   codice_sito   → NBT_BRL Location Code, sito costruttivo → Stabilimento.codice_bc
COMMESSA_COMMERCIALE = """
    SELECT
        CAST(No_ AS NVARCHAR(MAX)) AS commessa,
        CAST([NBT_BRL Ref_ Customer Order$d71d761a-a85c-4b10-8459-d30c64b4a709]
            AS NVARCHAR(MAX)) AS po_cliente,
        FORMAT([NBT_BRL Consignment Date$d71d761a-a85c-4b10-8459-d30c64b4a709],
            'yyyy-MM-dd') AS data_consegna,
        CAST([NBT_BRL Location Code$d71d761a-a85c-4b10-8459-d30c64b4a709]
            AS NVARCHAR(MAX)) AS codice_sito
    FROM [BREMBANA$Job$437dbf0e-84ff-417a-965d-ed2bb9650972$ext]
    WHERE No_ = ?
"""
