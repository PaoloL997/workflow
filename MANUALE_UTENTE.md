# Manuale utente — Workflow (Gestione Commesse)

Applicazione web per la gestione di commesse, documenti e revisioni in ambito industriale (Brembana&Rolle).

Questo documento descrive **tutte le operazioni disponibili** nell'interfaccia utente, passo per passo.

---

## Indice

1. [Panoramica](#1-panoramica)
2. [Accesso e account](#2-accesso-e-account)
3. [Navigazione generale](#3-navigazione-generale)
4. [Home e gestione commesse](#4-home-e-gestione-commesse)
5. [Pagina commessa (dashboard)](#5-pagina-commessa-dashboard)
6. [Informazioni archivio](#6-informazioni-archivio)
7. [Elenco documenti](#7-elenco-documenti)
8. [Revisioni e file collegati](#8-revisioni-e-file-collegati)
9. [Gestione emissione](#9-gestione-emissione)
10. [Gestione ricezione](#10-gestione-ricezione)
11. [Situazione documenti](#11-situazione-documenti)
12. [Pannello amministrazione](#12-pannello-amministrazione)
13. [Flusso di lavoro completo](#13-flusso-di-lavoro-completo)
14. [Glossario](#14-glossario)
15. [Scorciatoie da tastiera](#15-scorciatoie-da-tastiera)
16. [Domande frequenti](#16-domande-frequenti)

---

## 1. Panoramica

Workflow consente di:

- Creare e consultare **commesse** (job) con dati cliente, PO, date di consegna
- Gestire l'**elenco documenti** di ogni commessa
- Tracciare le **revisioni** di ogni documento con stati interni ed esterni
- **Emettere** documenti al cliente (con generazione PDF trasmittal)
- **Registrare la ricezione** delle risposte del cliente
- Visualizzare la **situazione** complessiva dei documenti
- Collegare e aprire i **file** sul fileserver di rete (cartelle JOBS)

### Concetti principali

| Concetto | Descrizione |
|----------|-------------|
| **Commessa (Job)** | Identificativo univoco del progetto (es. `25056`) |
| **Documento** | Singolo documento tecnico/commerciale della commessa |
| **Revisione** | Iterazione di un documento (Rev. 0, 1, 2… oppure con lettera A, B, C…) |
| **Stato interno** | Fase di lavorazione interna (da iniziare → inviato al cliente → ricevuto) |
| **Risposta cliente** | Esito della revisione da parte del cliente (Approved, Commented, ecc.) |
| **Trasmittal** | Lettera di accompagnamento PDF inviata al cliente con i documenti |

---

## 2. Accesso e account

### 2.1 Accedere all'applicazione

1. Apri l'indirizzo dell'applicazione nel browser (es. `http://server:8000/`).
2. Se non sei autenticato, verrai reindirizzato alla pagina **Accedi**.
3. Inserisci **username** e **password**.
4. Clicca **Accedi**.

In caso di credenziali errate compare il messaggio: *"Credenziali non valide. Riprova."*

### 2.2 Registrarsi

1. Dalla pagina di login, vai su **Registrati**.
2. Compila i campi obbligatori:
   - **Username**
   - **Email**
   - **Password** (minimo 8 caratteri)
   - **Conferma password**
3. Opzionalmente inserisci nome e cognome.
4. Clicca **Registrati**.

Dopo la registrazione vieni automaticamente loggato e portato alla Home.

### 2.3 Profilo utente

Clicca sull'**avatar** in alto a destra per aprire la pagina **Profilo**.

#### Modificare i dati personali

1. Aggiorna nome, cognome, email, ruolo e reparto.
2. Per cambiare l'avatar, clicca sull'immagine circolare e seleziona un file.
3. Clicca **Salva modifiche**.

#### Cambiare password

1. Nella sezione **Cambia password**, inserisci la password attuale.
2. Inserisci la nuova password e la conferma (minimo 8 caratteri).
3. Clicca **Aggiorna password**.

#### Uscire dall'account

Dalla pagina Profilo, clicca **Esci** (in basso nella colonna sinistra).

---

## 3. Navigazione generale

### 3.1 Barra di navigazione

Su ogni pagina trovi una barra centrale con:

| Voce | Funzione |
|------|----------|
| **Home** | Torna alla pagina principale con le commesse recenti |
| **Cerca** | Apre la ricerca rapida (Spotlight) |
| **Scarica** | Scarica i dati grezzi di una commessa in Excel (`/scarica/`) |
| **Impostazioni** | Apre il pannello amministrazione Django (`/admin/`) |

### 3.2 Ricerca commesse (Spotlight)

La ricerca è disponibile ovunque:

- Clicca **Cerca** nella navbar, oppure
- Clicca **Cerca Commessa** dalla Home, oppure
- Premi **Ctrl+K** (Windows) / **Cmd+K** (Mac)

**Come usarla:**

1. Digita il numero job o il nome cliente.
2. I risultati appaiono in tempo reale (max 8 risultati).
3. Clicca su una commessa per aprirla, oppure premi **Invio**.
4. Premi **Esc** per chiudere.

### 3.3 Tema chiaro/scuro

In basso a destra trovi il pulsante circolare per cambiare tema. La preferenza viene salvata nel browser.

### 3.4 Brand e navigazione indietro

In alto a sinistra compare sempre **Brembana&Rolle / Gestione di commessa**. Nelle pagine interne alla commessa è presente un pulsante per tornare alla dashboard della commessa o alla Home.

### 3.5 Notifiche

In alto a destra, subito a sinistra dell'icona del tuo profilo, c'è una **campanella**. Un pallino rosso con il numero indica quante notifiche non hai ancora letto.

**Quando arriva una notifica:**

- Quando un collega propone una nuova feature — *"Mario Rossi ha proposto una nuova feature"*
- Quando un collega segnala un problema — *"Mario Rossi ha evidenziato un problema"*

La notifica viene inviata a tutti gli utenti attivi tranne a chi ha creato la segnalazione.

**Come si usano:**

1. Clicca la campanella: si apre l'elenco delle notifiche non lette, dalla più recente.
2. Clicca una notifica per aprire la pagina **Proposte e segnalazioni** (`/segnalazioni/`).
3. Una volta aperto l'elenco le notifiche risultano lette: il contatore si azzera e alla prossima apertura non compaiono più.
4. Clicca fuori dal riquadro o premi **Esc** per chiudere.

Il contatore si aggiorna automaticamente ogni minuto, senza ricaricare la pagina.

### 3.6 Scarica dati grezzi

La voce **Scarica** della navbar (`/scarica/`) permette di esportare in Excel i dati di una commessa così come sono salvati sul database, senza elaborazioni né formattazioni.

**Come si usa:**

1. Nel campo **Commessa** digita job o cliente e scegli la commessa dai risultati (usa **Cambia** per sceglierne un'altra).
2. Spunta le **tabelle** da esportare, oppure usa **Seleziona tutte**.
3. Clicca **Scarica**: il browser scarica un file `{job}_dati_grezzi_{gg_mm_aaaa}.xlsx`.

Il file contiene **un foglio per ogni tabella selezionata**; la prima riga riporta i nomi delle colonne in grassetto, le righe successive i dati grezzi.

| Tabella | Contenuto |
|---------|-----------|
| **Commessa** | La riga di testata della commessa |
| **Indirizzi spedizione** | Gli indirizzi di spedizione collegati |
| **Documenti** | Tutti i documenti della commessa |
| **Revisioni** | Tutte le revisioni dei documenti della commessa |

Il foglio **Revisioni** riporta, prima dei dati della revisione, gli identificativi del documento a cui appartiene (**Client Doc N°**, **Client Doc Class**, **Contractor Doc N°**, **B&R Doc**, **Item**) e chiude con la **lettera** della risposta del cliente (es. `A`, `C`).

Il pulsante **Scarica** resta disabilitato finché non hai scelto sia la commessa sia almeno una tabella.

---

## 4. Home e gestione commesse

La **Home** mostra le commesse più recenti (fino a 8) in una griglia di card. Ogni card mostra job, cliente, descrizione e data di consegna.

### 4.1 Visualizzare tutte le commesse

Clicca **Visualizza tutte** sotto i pulsanti principali per aprire l'elenco completo (`/commesse/`).

### 4.2 Creare una nuova commessa

1. Clicca **Apri Commessa** → **Nuova commessa**.
2. Compila il modulo:
   - **Job** * (obbligatorio) — numero commessa
   - **Cliente** * (obbligatorio)
   - **PO No.** — numero ordine cliente
   - **Bid No.** — numero offerta
   - **Descrizione** — dettaglio commessa
   - **Data consegna**
   - **Termini consegna** — es. DDP, FCA
3. Clicca **Crea commessa**.

> **Suggerimento ERP:** quando digiti il Job (almeno 3 caratteri), l'app interroga automaticamente Business Central e, se trova la commessa, compila i campi Cliente, PO, Descrizione e Data consegna. Compare l'indicatore ✓ *Trovata* o *Non trovata in ERP*. Se in seguito quei dati cambiano in Business Central, il controllo giornaliero riallinea la commessa (vedi [6.3](#63-aggiornamenti-da-business-central)).

### 4.3 Importare una commessa dal vecchio sistema (Report/Access)

Per migrare dati dal database Access legacy:

1. Clicca **Apri Commessa** → **Importa da Report**.
2. Inserisci il **numero commessa**.
3. Clicca **Importa**.

L'importazione recupera testata, documenti, revisioni, indirizzi e stati direttamente dal database Access configurato in `.env` (`ACCESS_MDB_PATH`). Le revisioni orfane vengono escluse automaticamente. Se la commessa esiste già, l'operazione viene rifiutata.

È disponibile anche la pagina dedicata `/import-from-old/` con la stessa funzione.

### 4.4 Aprire una commessa esistente

- Clicca su una card dalla Home
- Usa la ricerca Spotlight
- Vai all'elenco completo commesse

---

## 5. Pagina commessa (dashboard)

URL: `/commesse/<job>/`

La dashboard della commessa è il punto centrale per tutte le attività. Mostra:

- **Intestazione** con job, cliente e descrizione
- **Gauge** con avanzamento complessivo
- **5 sezioni** principali (card cliccabili)

### 5.1 Sezioni disponibili

| Sezione | Contenuto |
|---------|-----------|
| **Informazioni archivio** | Tempi di revisione, indirizzi di consegna |
| **Elenco documenti** | Lista e gestione documenti |
| **Gestisci emissione** | Invio documenti al cliente |
| **Gestisci ricezione** | Registrazione risposte cliente |
| **Situazione documenti** | Vista tabellare completa |

> **Nota:** le sezioni Emissione, Ricezione e Situazione sono **pienamente attive** solo quando l'archivio è completo, cioè quando sono stati impostati sia i **giorni revisione cliente** sia i **giorni revisione B&R** in Informazioni archivio. Se mancano, le card appaiono attenuate con il messaggio *"Clicca per compilare"*.

### 5.2 Anteprime nella dashboard

Ogni sezione mostra un'anteprima:

- **Emissione:** documenti da emettere con scadenze (rosso = scaduto, arancio = urgente)
- **Ricezione:** documenti inviati in attesa di risposta
- **Situazione:** conteggio totale / emessi / ricevuti
- **Documenti:** prime 7 card con titolo e stato

### 5.3 Eliminare una commessa

1. Sotto il titolo della commessa, clicca **Elimina commessa**.
2. Conferma nel modale di avviso.

> **Attenzione:** l'eliminazione è irreversibile e cancella anche tutti i documenti, revisioni e indirizzi collegati.

---

## 6. Informazioni archivio

URL: `/commesse/<job>/archivio/`

Questa sezione configura i parametri che governano il calcolo automatico delle date nelle fasi di emissione e ricezione.

### 6.1 Tempi di revisione

| Campo | Significato | Effetto |
|-------|-------------|---------|
| **Revisione cliente** | Giorni concessi al cliente per rispondere | All'emissione: `Data ricezione prevista = Data emissione + giorni cliente` |
| **Revisione interna** | Giorni a disposizione di B&R per emettere la revisione successiva | Alla ricezione con nuova rev.: `Data invio prevista = Data ricezione + giorni interni` |
| **Revisioni con lettera** | Usa lettere alfabetiche (A, B, C…) invece del solo numero | Decide come si legge la revisione in tutta l'applicazione |

**Procedura:**

1. Inserisci i valori nei campi numerici.
2. Attiva/disattiva il toggle **Revisioni con lettera** se necessario.
3. Clicca **Salva modifiche**.

#### Come viene mostrata la revisione

Questo toggle è l'unica cosa che decide come si legge la revisione: con il flag **attivo** si vede sempre la lettera (A, B, C…), con il flag **spento** si vede sempre il numero (0, 1, 2…). Vale per ogni schermata (elenco documenti, situazione documenti in entrambe le viste comprese le intestazioni di colonna, emissione, ricezione, sblocco e anomalie revisioni) e per ogni stampa o export (Excel, PDF, trasmittal).

Numero e lettera sono due modi di scrivere lo stesso dato (`0 = A`, `1 = B`, … `25 = Z`, `26 = AA`): se sulla revisione manca il valore richiesto, viene ricavato dall'altro. Cambiare il toggle non modifica quindi i dati, solo la loro lettura.

### 6.2 Indirizzi di consegna

Gli indirizzi vengono usati nella generazione del PDF trasmittal.

#### Aggiungere un indirizzo

1. Clicca **+ Aggiungi indirizzo**.
2. Compila i campi:
   - Consignee (destinatario)
   - Indirizzo
   - CAP, Città, Paese
   - Attn (persona di riferimento)
   - Telefono
3. Clicca **Salva**.

#### Modificare o eliminare un indirizzo

- Clicca **Modifica** sulla riga dell'indirizzo, aggiorna i campi e salva.
- Clicca **Elimina** per rimuoverlo (con conferma implicita).

### 6.3 Aggiornamenti da Business Central

Ogni giorno alle **17:00** il sistema riconfronta con **Business Central** i dati che l'ERP aveva precompilato alla creazione della commessa — **Cliente**, **PO cliente**, **Descrizione** e **Data consegna** — e aggiorna la commessa se in BC sono cambiati.

La sezione elenca le ultime dieci modifiche applicate, con data, campo e valore precedente → nuovo. Se non compare nulla, i dati della commessa sono allineati a BC.

Regole del controllo:

- vengono controllate le commesse **aperte** (senza data consegna effettiva);
- un valore **vuoto** in Business Central non sovrascrive mai un dato già inserito nel sistema;
- gli altri campi (tempi di revisione, indirizzi, documenti…) non vengono toccati;
- una commessa non presente in BC viene semplicemente saltata;
- se il server era spento alle 17:00, il controllo viene recuperato alla prima riaccensione;
- se Business Central non risponde, l'errore viene registrato e si ritenta il giorno successivo.

Lo storico completo è consultabile nel pannello **admin** alla voce *Aggiornamenti da Business Central*; data ed esito dell'ultima esecuzione sono sotto *Esecuzioni schedulate*.

---

## 7. Elenco documenti

URL: `/commesse/<job>/documenti/`

Pagina principale per la gestione dell'elenco documenti della commessa.

### 7.1 Visualizzare i documenti

La tabella mostra per ogni documento:

- Item, B&R Doc, Client Doc N°, Client Doc Class
- Titolo, Reparto
- Flag Penale, Pagamento, Rev. Generale
- **Chip revisioni** (Rev. 0, Rev. 1, …) — cliccabili per aprire il file

Usa la **barra di ricerca** per filtrare per titolo, item o numero documento.

> Le revisioni nella lista sono in **sola lettura** (non modificabili direttamente da questa pagina). Lo stato interno viene aggiornato automaticamente tramite Emissione e Ricezione.

### 7.2 Aggiungere un documento manualmente

1. Clicca **Aggiungi** → **Inserimento manuale**.
2. Compila il modulo:
   - **Item** — numero progressivo
   - **B&R Doc** — numero documento interno (es. `25056-QMDBI`)
   - **Client Doc N°** e **Client Doc Class**
   - **Titolo**
   - **Reparto** — seleziona dalla lista (deve esistere nel sistema)
   - **Data invio prevista (Rev. 0)** — data pianificata prima emissione
   - **Penale**, **Pagamento**, **Rev. Generale** — toggle on/off
   - **Note**
3. Clicca **Salva**.

Alla creazione viene automaticamente generata la **Revisione 0**.

### 7.3 Importare documenti da Excel

1. Clicca **Aggiungi** → **Importa da Excel**.
2. Prepara un file `.xlsx` o `.xls` con la **prima riga come intestazione**.
3. Trascina il file nell'area indicata oppure clicca per selezionarlo.
4. Clicca **Importa**.

**Colonne riconosciute** (non sensibili a maiuscole):

| Colonna Excel | Campo |
|---------------|-------|
| Item | Numero item |
| B&R Doc / Vendor Doc | Numero doc. B&R |
| Client Doc N° | Numero doc. cliente |
| Client Doc Class | Classe doc. cliente |
| Titolo / Titolo documento / Doc Title | Titolo |
| Reparto | Nome reparto (deve esistere) |
| Penale / Pagamento / Rev. Generale | `Sì`, `Si`, `Yes`, `1`, `X` per attivo |
| Note / Remarks | Note libere |

Per ogni riga importata viene creata una Revisione 0. Eventuali errori (es. reparto non trovato) vengono segnalati nel riepilogo.

### 7.4 Generare documenti da modello

1. Clicca **Aggiungi** → **Genera da modello**.
2. L'app crea automaticamente un documento per ogni **Modello documento** configurato nell'admin.
3. Il numero B&R Doc viene calcolato come `{job}-{codice_fisso}` (es. `25056-QMDBI`).
4. I modelli il cui documento esiste già nella commessa vengono saltati.

> I modelli documento si gestiscono dal pannello admin (sezione *Modelli documento*).

### 7.5 Modificare un documento

1. Clicca i tre puntini **···** sulla riga del documento.
2. Seleziona **Modifica**.
3. Aggiorna i campi nel modale.
4. Clicca **Salva**.

### 7.6 Eliminare un documento

1. Clicca **···** → **Elimina**.
2. Conferma l'operazione.

> L'eliminazione rimuove anche tutte le revisioni collegate.

### 7.7 Esportare l'elenco documenti

Clicca **Esporta** per scaricare un file Excel (`<job>_document_list.xlsx`) con tutti i documenti della commessa.

---

## 8. Revisioni e file collegati

### 8.1 Struttura cartelle sul fileserver

I file dei documenti risiedono nella share di rete JOBS, con questa struttura:

```
JOBS/
└── <numero_commessa>/
    └── PROGETTO/
        └── <acronimo_reparto>/     ← es. QMD, PM, UT
            ├── (file emessi)       ← documenti inviati al cliente
            └── RICEVUTI/
                └── <YYYY-MM-DD>/   ← documenti ricevuti dal cliente
```

L'acronimo reparto si configura nell'admin (es. Quality Control → `QC`).

### 8.2 Apertura automatica dei file

Clicca su un **chip revisione** (es. `Rev. 0`, `Rev. 1A`) nella lista documenti o nella situazione:

1. L'app cerca il file nella cartella corretta:
   - Se la revisione ha **data ricezione effettiva** → cerca in `RICEVUTI/<data>/`
   - Se ha solo **data emissione effettiva** → cerca nella cartella base del reparto
   - Il nome file deve **contenere** il B&R Doc (ricerca case-insensitive)
2. Se trova **un solo file** → lo apre direttamente.
3. Se trova **più file** → mostra un elenco per scegliere quale aprire.
4. Se **non trova nulla** → apre il browser file per collegamento manuale.

**Comportamento per tipo file:**

| Tipo | Apertura |
|------|----------|
| Word (.doc, .docx) | Direttamente in Microsoft Word |
| Excel (.xls, .xlsx) | Direttamente in Microsoft Excel |
| PDF e altri | Download tramite browser, poi apertura con app predefinita |

### 8.3 Collegamento manuale di un file

Se il file non viene trovato automaticamente:

1. Si apre il modale **Collega un file alla revisione**.
2. Naviga le cartelle del fileserver (partendo dalla cartella commessa).
3. Clicca su una cartella per entrarci, oppure su un file per selezionarlo.
4. Clicca **Salva collegamento**.

Il collegamento viene memorizzato e avrà priorità nelle ricerche future.

---

## 9. Gestione emissione

URL: `/commesse/<job>/emissione/`

Questa sezione gestisce l'invio dei documenti al cliente.

### 9.1 Quali documenti compaiono

Vengono elencati i documenti la cui revisione corrente **non** è ancora in stato *Inviato al Cliente* o *Ricevuto*.

### 9.2 Procedura di emissione

1. **Imposta la data** di emissione nella barra superiore (default: oggi).
2. **Seleziona i destinatari** cliccando il pulsante destinatari e spuntando gli indirizzi di consegna configurati in archivio.
3. **Seleziona i documenti** da emettere spuntando le checkbox (o usa *Seleziona tutti*).
4. Scegli l'azione:
   - **Stampa** — genera solo il PDF trasmittal senza registrare l'emissione
   - **Emetti e scarica** — genera il PDF e registra l'emissione

### 9.3 Opzioni trasmittal (PDF)

Prima di generare il PDF, compila:

| Campo | Descrizione |
|-------|-------------|
| **Our Ref.** | Numero trasmittal (es. `18022-BRRO-T-ETCE-0005`) |
| **Stabilimento (città)** | Sede di emissione, scelta dall'elenco stabilimenti |
| **Modalità spedizione** | In allegato / Per pacco postale / Per Corriere / Brevi manu |
| **Nome** (solo Brevi manu) | Nome della persona che consegna |

Clicca **Procedi** per continuare.

### 9.4 Conferma emissione

1. Verifica il riepilogo nel modale di conferma.
2. Clicca **Conferma ed emetti**.

**Cosa succede automaticamente:**

- Per ogni documento selezionato, sulla revisione corrente:
  - `Data invio effettivo` = data scelta
  - `Stato interno` = **Inviato al Cliente**
  - `Data ricezione prevista` = data emissione + giorni revisione cliente
- Viene scaricato il PDF trasmittal

---

## 10. Gestione ricezione

URL: `/commesse/<job>/ricezione/`

Questa sezione registra le risposte del cliente sui documenti già inviati.

### 10.1 Quali documenti compaiono

Solo i documenti in stato **Inviato al Cliente** (in attesa di risposta).

I documenti sono ordinati per urgenza: prima quelli con data ricezione prevista scaduta (riga rossa), poi quelli in scadenza entro 7 giorni (riga arancione).

### 10.2 Procedura di ricezione

Per ogni documento da registrare:

1. **Stato esterno** — seleziona la risposta del cliente dal menu a tendina (es. Approved, Commented, Rejected…).
2. **Data ricezione** — inserisci la data in formato `gg/mm/aaaa` oppure usa il calendario.
3. **Nuova rev.** — toggle che indica se creare automaticamente la revisione successiva.

> Quando selezioni uno stato esterno, il toggle **Nuova rev.** si imposta automaticamente in base alla configurazione dello stato (campo *Crea nuova revisione* nell'admin).

### 10.3 Registrare le ricezioni

1. Compila almeno un documento (stato + data).
2. Clicca **Registra ricezioni**.
3. Conferma nel modale.

**Cosa succede automaticamente:**

- Sulla revisione corrente:
  - `Data ricezione effettiva` = data inserita
  - `Risposta cliente` = stato selezionato
  - `Stato interno` = **Ricevuto**
- Se il toggle **Nuova rev.** è attivo:
  - Viene creata una nuova revisione con numero incrementato
  - `Data invio prevista` = data ricezione + giorni revisione interna B&R

### 10.4 Risposte del cliente disponibili

Gli stati esterni predefiniti (importati dal vecchio sistema) includono:

| Stato | Colore tipico |
|-------|---------------|
| Approved | Verde |
| Commented - To be issued as Final | Rosso |
| Commented - To be resubmitted - Work can proceed | Rosso |
| Final - As Built | Giallo |
| For Information | Giallo |
| Rejected - Work can not proceed | Rosso |
| Superseeded | Grigio |
| Old | Rosso |

Nuovi stati possono essere aggiunti dall'admin o dall'API.

---

## 11. Situazione documenti

URL: `/commesse/<job>/situazione/`

Vista tabellare completa dello stato di tutti i documenti e revisioni.

### 11.1 Tipi di visualizzazione

| Vista | Descrizione |
|-------|-------------|
| **Verticale** (default) | Una riga per ogni combinazione documento × revisione, con tutte le colonne di stato |
| **Orizzontale** | Una riga per documento, con colonne raggruppate per revisione (Inv. prev., Inv. eff., Ric. prev., Ric. eff.) |

Usa i pulsanti **Verticale** / **Orizzontale** nella toolbar.

### 11.2 Colonne (vista verticale)

- Item, B&R Doc, Client Doc No, Client Doc Class
- Titolo, Reparto
- Penale, Pagamento
- Rev. (numero/lettera)
- Inv. previsto / Inv. effettivo
- Ric. previsto / Ric. effettivo
- **Stato interno** (badge colorato)
- **Risposta cliente** (badge con colore configurato)

### 11.3 Colori delle risposte del cliente

Le celle legate alla risposta del cliente usano il colore configurato sullo stato esterno, pieno e identico a quello della legenda:

| Vista | Dove compare il colore |
|-------|------------------------|
| **Verticale** | Badge **Risposta cliente**; la riga resta tinta più tenue con il bordo sinistro del colore dello stato |
| **Orizzontale** | Colonna **B&R Doc** (ultima risposta ricevuta) e cella **Status** di ogni revisione, con la lettera dello stato |

Il testo dentro alle celle diventa automaticamente bianco o nero, quello dei due che si legge meglio sul colore: gli stati bianchi o gialli hanno testo nero, quelli neri, grigi scuri o molto saturi hanno testo bianco. Se un colore è così a metà strada da non reggere nessuno dei due, il fondo viene schiarito (o scurito) di pochi punti, quanto basta a leggere il testo restando lo stesso colore a vista.

La legenda in alto nella vista orizzontale ripete la stessa coppia colore/lettera delle celle.

Anche la legenda **STATUS** nell'header del PDF (viste orizzontale e verticale) è costruita sulle risposte del cliente messe a sistema: lettera, nome e colore del quadratino sono quelli configurati nell'admin, quindi cambiando un colore là il PDF successivo esce già aggiornato. Se una risposta non ha il colore si usa quello storico della sua lettera; se una risposta non ha la lettera, questa viene dedotta dal nome e, se il nome non è riconosciuto, la risposta resta fuori dalla legenda (nelle celle del PDF gli stati sono identificati proprio dalla lettera). Nel riquadro ci stanno al massimo dieci righe: oltre quel numero entrano le prime in ordine di lettera. Se nell'admin non c'è nessuna risposta del cliente, il PDF stampa la legenda storica delle otto risposte standard.

### 11.4 Ordinamento

Clicca sull'intestazione di una colonna per ordinare i dati.

### 11.5 Apertura file

Clicca su una riga o su una data di ricezione effettiva per aprire il file collegato alla revisione (stessa logica descritta al §8).

### 11.6 Esportazione Excel e PDF

1. Clicca il pulsante **Esporta** (icona download).
2. Scegli il formato:
   - **Excel** (senza header): viene scaricato `situazione_documenti_<vista>_<job>.xlsx` con la vista corrente.
   - **PDF** (con header Document Status): viene scaricato il PDF della vista corrente.

Entrambe le viste, verticale e orizzontale, offrono i due formati. L'Excel della vista orizzontale riproduce la tabella a schermo: una riga per documento, il gruppo **Planning** (Submission date, Receipt date) e un gruppo per ogni revisione (Dispatch, Received, Status). La colonna **B&R Doc** e le celle **Status** hanno gli stessi colori della risposta del cliente visti a schermo. L'Excel della vista verticale ha una riga per ogni revisione, senza colori.

### 11.7 Schermo intero

Clicca l'icona schermo intero per espandere la tabella a tutto lo schermo. Clicca di nuovo per uscire.

---

## 12. Pannello amministrazione

URL: `/admin/` — accessibile dalla navbar tramite **Impostazioni**.

Richiede un account con privilegi di staff. Qui si gestiscono le entità di configurazione:

| Sezione | Cosa si configura |
|---------|-------------------|
| **Utenti** | Account, ruolo, reparto, permessi staff |
| **Reparti** | Nome e acronimo (usato per le cartelle fileserver) |
| **Stabilimenti** | Sedi per il trasmittal PDF |
| **Risposte del cliente** | Stati esterni, colore, flag *Crea nuova revisione* |
| **Modelli documento** | Template per generazione automatica documenti |
| **Archivi commessa** | Accesso diretto alle testate |
| **Documenti / Revisioni** | Consultazione e modifica avanzata |
| **Link file revisione** | Collegamenti manuali ai file |
| **Aggiornamenti da Business Central** | Storico (sola lettura) dei campi riallineati all'ERP |
| **Esecuzioni schedulate** | Data ed esito dell'ultimo controllo automatico con l'ERP (sola lettura) |

### 12.1 Configurare un modello documento

1. Vai su **Modelli documento** → **Aggiungi**.
2. Compila:
   - **Titolo documento**
   - **Item** (opzionale)
   - **Codice fisso** — parte fissa del B&R Doc (es. `QMDBI` → `25056-QMDBI`)
   - **Reparto**
3. Salva.

### 12.2 Configurare una risposta del cliente

1. Vai su **Risposte del cliente** → **Aggiungi** (o modifica esistente).
2. Imposta:
   - **Nome** — etichetta visibile (es. `Approved`)
   - **Colore** — esadecimale (es. `#00B050`)
   - **Crea nuova revisione** — se attivo, alla ricezione con questa risposta viene proposta automaticamente la creazione della revisione successiva

---

## 13. Flusso di lavoro completo

Questo è il ciclo tipico di vita di un documento:

```
┌─────────────────┐
│  Crea commessa  │
└────────┬────────┘
         ▼
┌─────────────────────────┐
│ Configura archivio      │
│ (giorni rev. + indirizzi)│
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ Aggiungi documenti      │
│ (manuale / Excel /      │
│  modello)               │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ Revisione 0 creata      │
│ Stato: (vuoto)          │
│ Imposta data invio      │
│ prevista (Rev. 0)       │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ EMISSIONE               │
│ → Stato: Inviato al     │
│   Cliente               │
│ → Calcola data ric.     │
│   prevista              │
│ → PDF trasmittal        │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ RICEZIONE               │
│ → Stato: Ricevuto       │
│ → Registra risposta     │
│   cliente               │
│ → (Opz.) Nuova rev.     │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ Nuova revisione creata  │
│ → Data invio prevista   │
│   calcolata             │
│ → Torna a EMISSIONE     │
└─────────────────────────┘
```

### Esempio pratico

1. Crei la commessa `25056` con cliente "ACME Corp".
2. In archivio imposti: 14 giorni revisione cliente, 7 giorni revisione interna.
3. Aggiungi il documento `25056-QMDBI` con data invio prevista 15/06/2026.
4. Il 15/06 emetti il documento → stato *Inviato al Cliente*, ricezione prevista 29/06.
5. Il 25/06 registri ricezione con stato *Commented* e nuova revisione → stato *Ricevuto*, creata Rev. 1 con invio previsto 02/07.
6. Il 02/07 emetti la Rev. 1 → ciclo continua.

---

## 14. Glossario

### Stati interni

| Codice | Etichetta | Significato |
|--------|-----------|-------------|
| `da_iniziare` | Da iniziare | Documento non ancora avviato |
| `in_lavorazione` | In lavorazione | In preparazione |
| `in_revisione` | In revisione | In revisione interna |
| `in_approvazione` | In approvazione | In attesa approvazione interna |
| `da_emettere` | Da emettere | Pronto per l'invio |
| `inviato_al_cliente` | Inviato al Cliente | Emesso, in attesa risposta |
| `ricevuto` | Ricevuto | Risposta cliente registrata |

> Nell'interfaccia attuale, gli stati vengono impostati principalmente tramite **Emissione** (*Inviato al Cliente*) e **Ricezione** (*Ricevuto*). Gli altri stati sono disponibili per consultazione e modifica avanzata via admin/API.

### Campi documento

| Campo | Descrizione |
|-------|-------------|
| **Item** | Numero progressivo nella lista documenti del cliente |
| **B&R Doc** | Numero documento interno Brembana&Rolle |
| **Client Doc N°** | Numero documento del cliente |
| **Client Doc Class** | Classe/categoria documento cliente |
| **Penale** | Documento soggetto a penale contrattuale |
| **Pagamento** | Documento collegato a milestone di pagamento |
| **Rev. Generale** | Documento di revisione generale |

### Campi revisione

| Campo | Descrizione |
|-------|-------------|
| **Rev. No** | Numero revisione (0, 1, 2…) |
| **Rev. Let** | Lettera revisione (A, B, C…) |
| | Quale dei due si vede a schermo e nelle stampe dipende solo dal flag **Revisioni con lettera** in archivio (§6.1); se il valore manca viene ricavato dall'altro |
| **Inv. previsto** | Data pianificata di invio al cliente |
| **Inv. effettivo** | Data effettiva di invio |
| **Ric. previsto** | Data entro cui ci si aspetta la risposta |
| **Ric. effettivo** | Data effettiva di ricezione risposta |

---

## 15. Scorciatoie da tastiera

| Scorciatoia | Azione |
|-------------|--------|
| **Ctrl+K** / **Cmd+K** | Apri ricerca commesse (Spotlight) |
| **Esc** | Chiudi modale / ricerca / menu |
| **Invio** | Conferma modale / avvia ricerca |

---

## 16. Domande frequenti

### Perché non vedo documenti in Emissione/Ricezione?

Verifica di aver compilato **entrambi** i campi giorni revisione in **Informazioni archivio**. Senza questi valori l'archivio è considerato incompleto.

### Perché un documento non compare in Ricezione?

Solo i documenti con stato **Inviato al Cliente** sono in attesa di risposta. Se hai già registrato la ricezione, il documento non compare più (a meno che non sia stata creata una nuova revisione ancora da emettere).

### Perché non si apre il file di una revisione?

Possibili cause:
- Il documento non ha un **reparto** con acronimo configurato
- Il file non esiste nella cartella prevista sul fileserver
- Il nome file non contiene il B&R Doc
- La share JOBS non è montata o accessibile dal server

Soluzione: usa il **collegamento manuale** tramite il browser file.

### Posso modificare lo stato interno di una revisione?

Non dall'interfaccia lista documenti (sola lettura). Puoi farlo dal pannello **admin** oppure tramite le operazioni di Emissione e Ricezione che aggiornano automaticamente gli stati.

### Come funziona l'integrazione ERP?

Quando crei una nuova commessa e digiti il Job, l'app interroga **Business Central** per recuperare automaticamente cliente, PO, descrizione e data consegna. Richiede che il server abbia accesso al database SQL Server configurato in `.env`.

### I dati presi da Business Central restano aggiornati?

Sì: ogni giorno alle 17:00 il sistema riconfronta cliente, PO, descrizione e data consegna delle commesse aperte con Business Central e le riallinea se in BC sono cambiate. Le modifiche applicate sono elencate in **Informazioni archivio → Aggiornamenti da Business Central** (vedi [6.3](#63-aggiornamenti-da-business-central)). Un valore vuoto in BC non cancella mai quello inserito nel sistema.

### Come importo dati dal vecchio database Access?

Usa **Apri Commessa → Importa da Report** dalla Home, oppure la pagina `/import-from-old/`. Il server deve avere accesso al database Access indicato in `ACCESS_MDB_PATH` nel file `.env`.

---

*Ultimo aggiornamento: giugno 2026*
