# Query SQL verso Business Central (database BREMBANA_PROD su SQL Server).
# Ogni costante è una stringa parametrizzata con ? come placeholder (stile pyodbc).
#
# Due GUID ricorrono nei nomi degli oggetti BC:
#   437dbf0e-… identifica le tabelle standard (Job, Location) e la loro estensione
#   d71d761a-… identifica l'app custom NBT_BRL. Attenzione: per i campi aggiuntivi
#              sulla commessa questo GUID sta nel nome della COLONNA, non della
#              tabella — le colonne vivono su [BREMBANA$Job$437dbf0e-…$ext].
#              Per le tabelle proprie di NBT_BRL invece è il suffisso della tabella.

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
# È la tabella di estensione della Job: i campi custom NBT_BRL stanno qui, con il
# GUID dell'app dentro il NOME DELLA COLONNA.
#
# La versione precedente leggeva da [BREMBANA$Job$d71d761a-…], che non esiste:
# fetch() inghiotte l'errore e restituisce None, quindi po_no e data consegna non
# sono mai arrivati da BC e il controllo giornaliero non li ha mai allineati.
#
# Campi restituiti:
#   commessa      → numero commessa BC (chiave di join con COMMESSA_ANAGRAFICA)
#   po_cliente    → riferimento ordine acquisto del cliente → Testata.po_no
#   data_consegna → data di consegna concordata            → Testata.delivery_date
COMMESSA_COMMERCIALE = """
    SELECT
        CAST(No_ AS NVARCHAR(MAX)) AS commessa,
        CAST([NBT_BRL Ref_ Customer Order$d71d761a-a85c-4b10-8459-d30c64b4a709]
             AS NVARCHAR(MAX)) AS po_cliente,
        FORMAT([NBT_BRL Consignment Date$d71d761a-a85c-4b10-8459-d30c64b4a709],
               'yyyy-MM-dd') AS data_consegna
    FROM [BREMBANA$Job$437dbf0e-84ff-417a-965d-ed2bb9650972$ext]
    WHERE No_ = ?
"""

# ── Query 3: testata del Quality Control Plan ──────────────────────────────────
# Tabelle: Job (standard) + Job$ext (campi NBT_BRL) + Location (per il nome dello
# stabilimento, che sulla Job è solo un codice).
#
# Campi restituiti:
#   progetto   → nome del progetto        → QualityControlPlan.project
#   location   → stabilimento produttivo  → QualityControlPlan.location
#   owner      → destinatario finale della fornitura → QualityControlPlan.owner
#   purchaser  → cliente fatturato        → QualityControlPlan.purchaser
#   po_cliente → riferimento ordine       → QualityControlPlan.po_no
#
# Owner e purchaser sono davvero due cose diverse: su tutte le commesse BC
# Bill-to e Sell-to coincidono, mentre "Customer Dest_ Name" porta il committente
# finale (es. purchaser THYSSENKRUPP UHDE, owner QATAR FERTILIZERS).
QCP_TESTATA = """
    SELECT
        CAST(e.[NBT_BRL Project$d71d761a-a85c-4b10-8459-d30c64b4a709]
             AS NVARCHAR(MAX)) AS progetto,
        CAST(l.Name AS NVARCHAR(MAX)) AS location,
        CAST(e.[NBT_BRL Customer Dest_ Name$d71d761a-a85c-4b10-8459-d30c64b4a709]
             AS NVARCHAR(MAX)) AS owner,
        CAST(j.[Bill-to Name] AS NVARCHAR(MAX)) AS purchaser,
        CAST(e.[NBT_BRL Ref_ Customer Order$d71d761a-a85c-4b10-8459-d30c64b4a709]
             AS NVARCHAR(MAX)) AS po_cliente
    FROM [BREMBANA$Job$437dbf0e-84ff-417a-965d-ed2bb9650972] j
    LEFT JOIN [BREMBANA$Job$437dbf0e-84ff-417a-965d-ed2bb9650972$ext] e
           ON e.No_ = j.No_
    LEFT JOIN [BREMBANA$Location$437dbf0e-84ff-417a-965d-ed2bb9650972] l
           ON l.Code = j.[Location Code]
    WHERE j.No_ = ?
"""

# ── Query 4: item della commessa (scope of supply) ─────────────────────────────
# Tabella: BREMBANA$NBT_BRL Scope of supply$d71d761a-a85c-4b10-8459-d30c64b4a709
# È la distinta di fornitura: la fonte autorevole degli item di una commessa.
#
# Campi restituiti:
#   item        → codice item      → QualityControlPlanItem.item_no
#   descrizione → descrizione item → QualityControlPlanItem.descrizione
#   quantita    → numero di unità coperte dalla riga
#
# Avvertenza: [Item No_] è un nvarchar(20) e i codici più lunghi arrivano troncati
# a metà (es. "ITEM 1E/2E-1421/1E/2"). Il valore va mostrato così com'è e lasciato
# correggibile a mano: non spetta a noi indovinare il codice completo.
QCP_ITEMS = """
    SELECT
        CAST(s.[Item No_]     AS NVARCHAR(MAX)) AS item,
        CAST(s.[Description]  AS NVARCHAR(MAX)) AS descrizione,
        s.N                                     AS quantita
    FROM [BREMBANA$NBT_BRL Scope of supply$d71d761a-a85c-4b10-8459-d30c64b4a709] s
    WHERE s.[Job No_] = ?
    ORDER BY s.[Line No_]
"""
