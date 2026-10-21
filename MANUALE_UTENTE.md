# Manuale utente — Workflow (Gestione Documentale)

Applicazione web per la gestione di commesse, documenti e revisioni in ambito industriale (Brembana&Rolle).

Questo documento descrive **tutte le operazioni disponibili** nell'interfaccia utente, passo per passo.

---

## 1. Panoramica

Workflow consente di:

- Creare e consultare **commesse** (job) con dati cliente, PO, date di consegna
- Gestire l'**elenco documenti** di ogni commessa
- Tracciare le **revisioni** di ogni documento con stati interni ed esterni
- **Emettere** documenti al cliente (con generazione PDF trasmittal)
- **Distribuire** internamente i documenti UT agli stabilimenti con il **trasmittal interno** (modulo MQ 7.5-04)
- **Registrare la ricezione** delle risposte del cliente
- Visualizzare la **situazione** complessiva dei documenti
- Collegare e aprire i **file** sul fileserver di rete (cartelle JOBS)

### Concetti principali

| Concetto | Descrizione |
|----------|-------------|
| **Commessa (Job)** | Identificativo univoco del progetto (es. `25056`) |
| **Documento** | Singolo documento tecnico/commerciale della commessa |
| **Revisione** | Iterazione di un documento (Rev. 0, 1, 2…, con lettera A, B, C… oppure con una sequenza personalizzata dell'archivio) |
| **Stato interno** | Fase di lavorazione interna (da iniziare → inviato al cliente → ricevuto) |
| **Risposta cliente** | Esito della revisione da parte del cliente (Approved, Commented, ecc.) |
| **Trasmittal** | Lettera di accompagnamento PDF inviata al cliente con i documenti |
| **Trasmittal interno** | Lettera (modulo MQ 7.5-04) con cui i documenti UT vengono distribuiti agli stabilimenti e preparati per il DCC, prima dell'invio al cliente |
| **Sito costruttivo** | Stabilimento che costruisce la commessa; serve per il trasmittal interno |

---

## 2. Accesso e account

Questo capitolo spiega come accedere all'applicazione, registrarsi e gestire il proprio profilo.

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

1. Nella pagina **Profilo**, aggiorna nome, cognome, email, ruolo e reparto.
2. Per cambiare l'avatar, clicca sull'immagine circolare e seleziona un file.
3. Nel riquadro **Firma**, carica (o sostituisci) l'immagine della tua firma: viene stampata nel PDF del trasmittal interno se sei registrato come firmatario di uno stabilimento (vedi **12.8 Il PDF della lettera**).
4. Clicca **Salva modifiche**.

#### Cambiare password

1. Nella pagina **Profilo**, sezione **Cambia password**, inserisci la password attuale.
2. Inserisci la nuova password e la conferma (minimo 8 caratteri).
3. Clicca **Aggiorna password**.

#### Uscire dall'account

Dalla pagina Profilo, clicca **Esci** (in basso nella colonna sinistra).

---

## 3. Navigazione generale

Questo capitolo descrive gli elementi comuni a tutte le pagine: barra di navigazione, ricerca, tema, notifiche e download dei dati grezzi.

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

> **Suggerimento ERP:** quando digiti il Job (almeno 3 caratteri), l'app interroga automaticamente Business Central e, se trova la commessa, compila i campi Cliente, PO, Descrizione e Data consegna. Compare l'indicatore ✓ *Trovata* o *Non trovata in ERP*. Se in seguito quei dati cambiano in Business Central, il controllo giornaliero riallinea la commessa (vedi [6.4 Aggiornamenti da Business Central](#64-aggiornamenti-da-business-central)).

### 4.3 Importare una commessa dal vecchio sistema (Report/Access)

Per migrare dati dal database Access legacy:

1. Clicca **Apri Commessa** → **Importa da Report**.
2. Inserisci il **numero commessa**.
3. Clicca **Importa**.

L'importazione recupera testata, documenti, revisioni, indirizzi e stati direttamente dal database Access configurato in `.env` (`ACCESS_MDB_PATH`). Le revisioni orfane vengono escluse automaticamente. Se la commessa esiste già, l'operazione viene rifiutata.

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
| **Trasmittal interno** | Distribuzione interna dei documenti UT agli stabilimenti (capitolo **12. Trasmittal interno**) |

> **Nota:** le sezioni Emissione, Ricezione e Situazione sono **pienamente attive** solo quando l'archivio è completo, cioè quando sono stati impostati sia i **giorni revisione cliente** sia i **giorni revisione B&R** in **6.1 Tempi di revisione**. Se mancano, le card appaiono attenuate con il messaggio *"Clicca per compilare"*. La card **Trasmittal interno** si sblocca invece quando è impostato il **Sito costruttivo** della commessa.

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

**Procedura:**

1. Inserisci i valori nei campi numerici.
2. Clicca **Salva modifiche**.

Nello stesso riquadro c'è il campo **Sito costruttivo**: lo stabilimento che costruisce la commessa, scelto tra quelli con un codice sito Business Central. Serve a sbloccare il **Trasmittal interno** (capitolo **12. Trasmittal interno**). Se è vuoto, il controllo giornaliero con Business Central prova a impostarlo da solo; si può comunque scegliere a mano e salvare con **Salva modifiche**.

Come vengono indicate le revisioni (numero, lettera o sequenza personalizzata) si sceglie nella sezione **6.3 Revisioni**.

### 6.2 Indirizzi di consegna

Gli indirizzi vengono usati nella generazione del PDF trasmittal.

#### Aggiungere un indirizzo

1. In **Informazioni archivio**, sezione **Indirizzi di consegna**, clicca **+ Aggiungi indirizzo**.
2. Compila i campi:
   - Consignee (destinatario)
   - Indirizzo
   - CAP, Città, Paese
   - Attn (persona di riferimento)
   - Telefono
3. Clicca **Salva**.

#### Modificare o eliminare un indirizzo

In **Informazioni archivio**, sezione **Indirizzi di consegna**:

- Clicca **Modifica** sulla riga dell'indirizzo, aggiorna i campi e salva.
- Clicca **Elimina** per rimuoverlo (con conferma implicita).

### 6.3 Revisioni

La sezione, sotto gli indirizzi di consegna, decide come si legge la revisione in tutta l'applicazione. Le scelte sono tre:

| Scelta | Revisioni | Esempio |
|--------|-----------|---------|
| **Numero** | Sempre il numero, partendo da 0 | 0, 1, 2, 3… |
| **Lettera** | Sempre la lettera, partendo da A | A, B, C, D… |
| **Personalizzata** | Le etichette scritte nel campo **Sequenza**, nell'ordine dato | 1, 2, 3, D, E, F, 4, 5, 6 |

**Procedura:**

1. Scegli **Numero**, **Lettera** o **Personalizzata**.
2. Con **Personalizzata**, scrivi nel campo **Sequenza** le etichette separate da virgole (es. `1,2,3,D,E,F,4,5,6`). Sotto compare l'anteprima delle revisioni.
3. Clicca **Salva revisioni**.

Regole della sequenza personalizzata:

- la **prima** etichetta è la prima revisione del documento (quella che con i numeri sarebbe la Rev. 0), la seconda la successiva e così via;
- oltre l'ultima etichetta la sequenza **prosegue da sola** partendo dall'ultima: se finisce con un numero continua con i numeri (`…, 5, 6` → 7, 8…), se finisce con una lettera continua con le lettere (`…, E, F` → G, H…);
- ogni etichetta è lunga al massimo 10 caratteri, non può essere vuota né ripetuta (maiuscole e minuscole contano come uguali).

Scegliendo **Numero** o **Lettera** e salvando, la sequenza personalizzata viene cancellata.

#### Come viene mostrata la revisione

La scelta fatta nella sezione **6.3 Revisioni** (Numero, Lettera o Personalizzata) è l'unica cosa che decide come si legge la revisione. Vale per ogni schermata (elenco documenti, situazione documenti in entrambe le viste comprese le intestazioni di colonna, emissione, ricezione, trasmittal interno, sblocco e anomalie revisioni) e per ogni stampa o export (Excel, PDF, trasmittal).

Sotto, ogni revisione resta un numero progressivo. Numero e lettera sono due modi di scrivere lo stesso dato (`0 = A`, `1 = B`, … `25 = Z`, `26 = AA`): se sulla revisione manca il valore richiesto, viene ricavato dall'altro. Con la sequenza personalizzata conta solo il numero progressivo, e la lettera eventualmente salvata sulla revisione viene ignorata. Cambiare la scelta non modifica quindi i dati, solo la loro lettura: i PDF già emessi e le lettere di trasmittal interno già create mantengono la revisione con cui sono state prodotte.

### 6.4 Aggiornamenti da Business Central

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

> I modelli documento si gestiscono dal pannello admin (sezione *Modelli documento*, vedi **13.1 Configurare un modello documento**).

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

Questo capitolo spiega dove stanno i file delle revisioni sul fileserver e come l'applicazione li apre o li collega.

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
2. **Seleziona i destinatari** cliccando il pulsante destinatari e spuntando gli indirizzi di consegna configurati in **6.2 Indirizzi di consegna**.
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

> Quando selezioni uno stato esterno, il toggle **Nuova rev.** si imposta automaticamente in base alla configurazione dello stato (campo *Crea nuova revisione* nell'admin, vedi **12.2 Configurare una risposta del cliente**).

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
- Rev. (numero, lettera o sequenza personalizzata)
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

Clicca su una riga o su una data di ricezione effettiva per aprire il file collegato alla revisione (stessa logica descritta in **8.2 Apertura automatica dei file**).

### 11.6 Esportazione Excel e PDF

1. Clicca il pulsante **Esporta** (icona download).
2. Scegli il formato:
   - **Excel** (senza header): viene scaricato `situazione_documenti_<vista>_<job>.xlsx` con la vista corrente.
   - **PDF** (con header Document Status): viene scaricato il PDF della vista corrente.

Entrambe le viste, verticale e orizzontale, offrono i due formati. L'Excel della vista orizzontale riproduce la tabella a schermo: una riga per documento, il gruppo **Planning** (Submission date, Receipt date) e un gruppo per ogni revisione (Dispatch, Received, Status). La colonna **B&R Doc** e le celle **Status** hanno gli stessi colori della risposta del cliente visti a schermo. L'Excel della vista verticale ha una riga per ogni revisione, senza colori.

### 11.7 Schermo intero

Clicca l'icona schermo intero per espandere la tabella a tutto lo schermo. Clicca di nuovo per uscire.

---

## 12. Trasmittal interno

URL: `/commesse/<job>/trasmittal-interno/`

Il trasmittal interno è la lettera (modulo qualità **MQ 7.5-04**) con cui l'Ufficio Tecnico distribuisce agli **stabilimenti** le copie dei documenti UT e segnala quali vanno preparati per il cliente. È un'operazione separata da **Gestisci emissione** (capitolo **9. Gestione emissione**): emettere una lettera di trasmittal interno **non cambia lo stato di nessuna revisione**.

A ogni emissione l'applicazione crea la lettera, salva il PDF sul fileserver, prepara una cartella per il DCC con i PDF dei documenti destinati al cliente e invia un'email ai destinatari.

### 12.1 Prerequisiti

| Requisito | Dove si imposta |
|-----------|-----------------|
| **Sito costruttivo** della commessa | **Informazioni archivio** (campo *Sito costruttivo*, vedi **6.1 Tempi di revisione**). Se manca, la card *Trasmittal interno* nella pagina commessa è bloccata con il messaggio *"Completa prima il sito costruttivo della commessa"*. Il controllo giornaliero con Business Central prova a impostarlo da solo |
| Documenti del reparto **UT** | Nella lettera entrano solo i documenti il cui reparto ha acronimo `UT`. I documenti degli altri reparti non compaiono |
| Permesso **Può scrivere sul trasmittal interno** | Pannello admin, scheda *Utenti* → *Permessi app*. È indipendente dal permesso generale di scrittura: chi non lo ha vede la sezione ma non può modificare destinazioni, emettere, annullare o ritentare un passo |
| **Stabilimenti** con sigla, codice sito Business Central e indirizzi email | Pannello admin, *Stabilimenti*: per ogni sito gli indirizzi **TO/CC** e gli indirizzi **default** sempre in copia |
| **Persone commessa** (PM, PE, QCI) | Pannello admin, *Archivi commessa* → riquadro *Persone commessa*. Servono per i destinatari automatici dell'email |
| **Firmatari stabilimento** | Pannello admin, *Firmatari stabilimento*: chi firma per Produzione e Qualità nel PDF (vedi **12.8 Il PDF della lettera**) |

### 12.2 La schermata

La pagina mostra lo **storico delle lettere emesse** per la commessa, le più recenti in cima. Ogni lettera ha un nome del tipo `<job>_<aaaa-mm-gg>_E<n>` (es. `25056_2026-10-21_E1`): il progressivo `E<n>` riparte da 1 ogni giorno per ogni commessa.

Per ogni lettera:

- la **data** è un link che apre il PDF salvato sul fileserver. Se il PDF non è più nella cartella, la data è grigia con l'indicazione *"PDF non trovato sul fileserver"*;
- il pulsante **Annulla** compare solo sull'ultima lettera emessa in quel giorno (vedi **12.9 Annullare una lettera**).

In alto a destra ci sono i due pulsanti **Destinazioni** e **Nuova Lettera**. L'icona informativa accanto al titolo spiega come compaiono le firme nel PDF.

### 12.3 Destinazioni (siti coinvolti)

**Destinazioni** apre l'elenco di tutti i documenti UT della commessa con i siti a cui va la copia cartacea di ciascuno. Sono le destinazioni che la lettera riporta nella colonna *INVOLVED SITES* e che decidono quali stabilimenti ricevono l'email.

Colonne: **Documento**, **Titolo**, **Ultima modifica** (data del file in `PROGETTO\UT`, in grigio) e **Siti coinvolti**. Si ordinano cliccando l'intestazione e si filtrano con l'imbuto, come in Gestisci emissione. Di default i documenti modificati più di recente sono in cima, quelli senza file in coda.

Per impostare i siti:

- **Un documento alla volta:** clicca la cella **Siti coinvolti** del documento e spunta gli stabilimenti nel menu a tendina. Il salvataggio è immediato.
- **Più documenti insieme:** spunta i documenti (o **Seleziona tutti**), scegli lo stabilimento in *Assegna sito ai documenti selezionati* e clicca **Aggiungi** oppure **Rimuovi**. Con un filtro attivo, *Seleziona tutti* seleziona solo i documenti visibili.

Le destinazioni dei documenti che non ne hanno ancora nessuna vengono **precompilate automaticamente** ogni giorno, insieme al controllo con Business Central, dal vecchio file `<job>-RecipientsData.txt` sul fileserver, se esiste. Una destinazione impostata (a mano o dall'import) non viene più toccata dall'import.

### 12.4 Nuova lettera: scegliere i documenti

**Nuova Lettera** apre l'elenco dei documenti UT con le stesse colonne, ordinamenti e filtri di **Destinazioni**, più la casella **Cerca documento**. Il caricamento può richiedere qualche secondo perché l'applicazione verifica i file sul fileserver.

Un documento si può selezionare solo se:

1. ha almeno una revisione registrata;
2. la sua **ultima revisione è ancora da emettere** al cliente, cioè lo stato interno non è né *Inviato al Cliente* né *Ricevuto* (lo stesso criterio di Gestisci emissione);
3. nella cartella `PROGETTO\UT` c'è **un solo file** che corrisponde al B&R Doc.

Gli altri documenti compaiono in grigio con il motivo (*"Nessuna revisione registrata"*, *"Rev 1 già inviata al cliente"*, *"Nessun file trovato sul fileserver"*, *"Più file corrispondenti sul fileserver"*) e non si possono spuntare.

Spunta i documenti e clicca **Emetti trasmittal interno** per passare alla compilazione.

### 12.5 Cosa stai trasmettendo: compilare la lettera

Il pannello **Cosa stai trasmettendo** mostra in alto le sigle dei siti coinvolti e una riga per ogni documento scelto:

| Colonna | Cosa indica |
|---------|-------------|
| **Documento** | B&R Doc e titolo |
| **Revisione** | Revisione trasmessa. Lo stepper ± sceglie solo tra le revisioni ammesse del documento: oggi è l'ultima, quindi un solo valore |
| **Siti** | Siti coinvolti della riga. Si possono modificare qui, cliccando la cella: il cambio aggiorna anche le destinazioni del documento |
| **Copie** | Numero di copie cartacee (facoltativo) |
| **Cliente** | Spuntato (default): il documento va al cliente e il suo PDF viene copiato nella cartella DCC. Deselezionalo per un documento solo interno |
| **TPI** | Spunta se il documento va a un ispettore terzo e scrivi a chi (suggerimenti: `No.Bo.`, `AI`) |
| **Nota** | Richiama una o più delle note libere della lettera: nel PDF la riga riporta il numero della nota |

Sotto la tabella, **Note libere della lettera** (tre righe, si aggiungono con **+ Aggiungi nota**) finiscono nella sezione *NOTES* del PDF; le righe vuote vengono ignorate.

Clicca **Emetti** per passare ai destinatari.

### 12.6 A chi va: destinatari e invio

Il pannello **A chi va** riepiloga cosa succederà all'invio (nome della lettera, percorso del PDF, cartella DCC o l'avviso che nessun documento è marcato *Cliente*, email) e propone i destinatari calcolati automaticamente, divisi in **A (TO)** e **CC** e raggruppati per origine:

| Gruppo | Chi | Colonna |
|--------|-----|---------|
| **Stabilimenti** | Indirizzi TO/CC e indirizzi default dei siti coinvolti (tra parentesi la sigla del sito) | TO o CC come da anagrafica |
| **PM** | Project manager della commessa | TO |
| **PE** / **QCI** | Project engineer e ispettore qualità della commessa | CC |
| **Export** | `export@brembanarolle.com`, solo se nella lettera c'è almeno un documento SHn (B&R Doc del tipo `xxxxx-xx-ESH…`) | CC |
| **Manuale** | Indirizzi aggiunti a mano | dove li hai inseriti |

Se sulla commessa manca una persona per un ruolo (PM, PE o QCI), un avviso lo segnala: per quel ruolo non viene aggiunto nessun destinatario. Il ruolo WE non ha una lista di distribuzione e non genera destinatari.

Prima di inviare puoi:

- togliere un destinatario con la **×** sulla sua etichetta;
- aggiungerne uno scrivendolo nel campo **Aggiungi email…** della colonna giusta e premendo **+** o **Invio**. Mentre scrivi compaiono gli indirizzi già noti all'applicazione (utenti attivi, indirizzi degli stabilimenti, destinatari delle lettere precedenti). Un indirizzo già presente nella stessa colonna non viene duplicato;
- scrivere un **Messaggio nell'email** (facoltativo, massimo 2000 caratteri): compare nell'email sopra la tabella dei documenti, non nel PDF;
- scaricare un'**Anteprima PDF** della lettera così com'è: non crea nulla e non occupa un progressivo.

Clicca **Invia a N destinatari** per emettere la lettera.

### 12.7 Cosa succede all'invio

L'emissione è una sequenza di passi. Il primo è l'unico che può bloccare tutto: se la selezione o un destinatario non sono validi, non viene creata nessuna lettera. Gli altri sono indipendenti: un passo che fallisce non annulla la lettera e non blocca i successivi.

| Passo | Cosa fa |
|-------|---------|
| **Archivio** | Crea la lettera con il progressivo del giorno, le righe e i destinatari. I siti di ogni riga sono una fotografia delle destinazioni in quel momento: cambiarle dopo non modifica la lettera |
| **PDF** | Salva il PDF in `Z:\JOBS\<job>\Progetto\UT\Transmittal\<nome>.pdf` |
| **DCC** | Copia il PDF di ogni documento con **Cliente** spuntato nella cartella `Z:\JOBS\<job>\PROGETTO\DCC\DA SPEDIRE\<nome>`. Un documento di cui non si trova il file viene segnalato come mancante, gli altri vengono copiati comunque. Senza documenti per il cliente la cartella non viene creata |
| **Email** | Invia l'email ai destinatari confermati |

Al termine il pannello mostra l'esito di ogni passo con ✓ o ✗. Su un passo fallito compare **Riprova**, che ripete solo quel passo (ad esempio il PDF se lo storage delle firme non rispondeva, o l'email se il server di posta era fermo).

L'email:

- parte dalla **casella dell'applicazione**; chi ha emesso la lettera è scritto nella prima riga del testo (*emesso da Nome Cognome (email)*), riceve le risposte e una copia. Vale anche se **Riprova** sull'email lo preme un'altra persona;
- ha come oggetto `DOCUMENT TRANSMITTAL [Form MQ 7.5-04 Rev.0]: <nome lettera>`;
- riporta nel corpo il messaggio facoltativo, la tabella dei documenti con le stesse colonne del PDF e il percorso in cui il PDF è salvato sul fileserver. Il PDF non è allegato: si apre dal percorso indicato.

### 12.8 Il PDF della lettera

Il PDF riproduce il modulo **MQ 7.5-04**, dall'alto in basso:

1. **Intestazione** con logo, titolo del modulo e numero di commessa.
2. **Tabella dei documenti**: *B&R DOC. No.*, *REV.*, *INVOLVED SITES (a)*, *No. OF COPIES*, *CLIENT (b)*, *TPI (b)(c)*, *NOTES*.
3. **REMARKS LEGENDA**: la legenda delle sigle dei siti (a), il significato di CLIENT/TPI (b) e dei destinatari TPI (c).
4. **NOTES**: le note libere della lettera, numerate.
5. **PAPER COPIES DISTRIBUTION**: una riga **PRODUCTION** e una **QUALITY** con firma e data. La data è il giorno lavorativo successivo all'emissione (il venerdì diventa lunedì): è il termine entro cui distribuire le copie cartacee, non la data della firma.
6. I riferimenti fissi del modulo.

La revisione è scritta come indicato in **6.3 Revisioni** al momento dell'emissione; una lettera già emessa non cambia se la scelta cambia dopo.

**Firme di Produzione e Qualità.** Per ogni sito coinvolto, la firma compare in automatico solo se valgono entrambe le condizioni:

1. la persona ha caricato la propria firma nella pagina **Profilo** (vedi **2.3 Profilo utente**);
2. è registrata come **Firmatario stabilimento** per quel sito e quel ruolo (pannello admin).

Chi è firmatario ma non ha caricato la firma ha nel PDF un riquadro vuoto da firmare a mano. Se per un ruolo non c'è nessun firmatario, per quel ruolo non compare nulla. Se lo storage delle firme non risponde, il passo PDF fallisce e va ripetuto con **Riprova**: la lettera non viene emessa senza firme.

### 12.9 Annullare una lettera

**Annulla** è disponibile solo sull'**ultima lettera emessa in quel giorno** per la commessa, così il progressivo liberato è davvero l'ultimo. Dopo la conferma:

- la lettera e le sue righe vengono eliminate dall'archivio;
- il PDF viene rimosso dal fileserver;
- i file copiati nella cartella DCC vengono rimossi, e la cartella viene eliminata se resta vuota;
- l'email, se era già partita, **non può essere richiamata**: avvisa tu i destinatari.

Una lettera che non è l'ultima del suo giorno può essere eliminata solo da un superuser dal pannello admin (*Trasmittal interni*). Quell'eliminazione non tocca il PDF, la cartella DCC né l'email: per l'uso normale usa **Annulla**.

---

## 13. Pannello amministrazione

URL: `/admin/` — accessibile dalla navbar tramite **Impostazioni**.

Richiede un account con privilegi di staff. Qui si gestiscono le entità di configurazione:

| Sezione | Cosa si configura |
|---------|-------------------|
| **Utenti** | Account, ruolo, reparto, permessi staff, flag *Può scrivere sul trasmittal interno* |
| **Reparti** | Nome e acronimo (usato per le cartelle fileserver) |
| **Stabilimenti** | Sedi per il trasmittal PDF; per il trasmittal interno anche sigla, codice sito Business Central, indirizzi email TO/CC e indirizzi default sempre in copia |
| **Firmatari stabilimento** | Chi firma per Produzione e Qualità nel PDF del trasmittal interno |
| **Trasmittal interni** | Lettere di trasmittal interno emesse; un superuser può eliminarle |
| **Risposte del cliente** | Stati esterni, colore, flag *Crea nuova revisione* |
| **Modelli documento** | Template per generazione automatica documenti |
| **Archivi commessa** | Accesso diretto alle testate; riquadro *Persone commessa* (PM, PE, QCI) per i destinatari del trasmittal interno |
| **Documenti / Revisioni** | Consultazione e modifica avanzata |
| **Link file revisione** | Collegamenti manuali ai file |
| **Aggiornamenti da Business Central** | Storico (sola lettura) dei campi riallineati all'ERP |
| **Esecuzioni schedulate** | Data ed esito dell'ultimo controllo automatico con l'ERP (sola lettura) |

### 13.1 Configurare un modello documento

1. Vai su **Modelli documento** → **Aggiungi**.
2. Compila:
   - **Titolo documento**
   - **Item** (opzionale)
   - **Codice fisso** — parte fissa del B&R Doc (es. `QMDBI` → `25056-QMDBI`)
   - **Reparto**
3. Salva.

### 13.2 Configurare una risposta del cliente

1. Vai su **Risposte del cliente** → **Aggiungi** (o modifica esistente).
2. Imposta:
   - **Nome** — etichetta visibile (es. `Approved`)
   - **Colore** — esadecimale (es. `#00B050`)
   - **Crea nuova revisione** — se attivo, alla ricezione con questa risposta viene proposta automaticamente la creazione della revisione successiva

---

## 14. Flusso di lavoro completo

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

Un esempio del ciclo descritto nel capitolo **14. Flusso di lavoro completo**:

1. Crei la commessa `25056` con cliente "ACME Corp".
2. In archivio imposti: 14 giorni revisione cliente, 7 giorni revisione interna.
3. Aggiungi il documento `25056-QMDBI` con data invio prevista 15/06/2026.
4. Il 15/06 emetti il documento → stato *Inviato al Cliente*, ricezione prevista 29/06.
5. Il 25/06 registri ricezione con stato *Commented* e nuova revisione → stato *Ricevuto*, creata Rev. 1 con invio previsto 02/07.
6. Il 02/07 emetti la Rev. 1 → ciclo continua.

---

## 15. Glossario

Questo capitolo raccoglie il significato degli stati interni e dei campi di documenti e revisioni.

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
| | Come si vede la revisione a schermo e nelle stampe dipende solo dalla sezione **6.3 Revisioni** in Informazioni archivio: numero, lettera o sequenza personalizzata; se il valore manca viene ricavato dall'altro |
| **Inv. previsto** | Data pianificata di invio al cliente |
| **Inv. effettivo** | Data effettiva di invio |
| **Ric. previsto** | Data entro cui ci si aspetta la risposta |
| **Ric. effettivo** | Data effettiva di ricezione risposta |

---

## 16. Scorciatoie da tastiera

| Scorciatoia | Azione |
|-------------|--------|
| **Ctrl+K** / **Cmd+K** | Apri ricerca commesse (Spotlight) |
| **Esc** | Chiudi modale / ricerca / menu |
| **Invio** | Conferma modale / avvia ricerca |

---

## 17. Domande frequenti

Questo capitolo risponde ai dubbi più comuni su emissione, ricezione, file e integrazioni.

### Perché non vedo documenti in Emissione/Ricezione?

Verifica di aver compilato **entrambi** i campi giorni revisione in **Informazioni archivio → 6.1 Tempi di revisione**. Senza questi valori l'archivio è considerato incompleto.

### Perché un documento non compare in Ricezione?

Solo i documenti con stato **Inviato al Cliente** sono in attesa di risposta. Se hai già registrato la ricezione, il documento non compare più (a meno che non sia stata creata una nuova revisione ancora da emettere).

### Perché non si apre il file di una revisione?

Possibili cause:
- Il documento non ha un **reparto** con acronimo configurato
- Il file non esiste nella cartella prevista sul fileserver
- Il nome file non contiene il B&R Doc
- La share JOBS non è montata o accessibile dal server

Soluzione: usa il **collegamento manuale** tramite il browser file (vedi **8.3 Collegamento manuale di un file**).

### Perché la card Trasmittal interno è bloccata?

Manca il **Sito costruttivo** della commessa. Impostalo in **Informazioni archivio** (vedi **6.1 Tempi di revisione**) e salva.

### Perché un documento è grigio in Nuova lettera del trasmittal interno?

Il motivo è scritto accanto al documento: non ha revisioni, la sua ultima revisione è già stata inviata al cliente o ricevuta, oppure in `PROGETTO\UT` non c'è esattamente un file con il suo B&R Doc. Vedi **12.4 Nuova lettera: scegliere i documenti**.

### Perché non posso modificare il trasmittal interno?

Serve il flag **Può scrivere sul trasmittal interno** sul tuo utente, che un amministratore imposta dal pannello admin (scheda *Utenti* → *Permessi app*). È separato dal permesso generale di scrittura. Senza il flag vedi lo storico, le destinazioni e l'anteprima, ma non puoi salvare né emettere.

### Nel PDF del trasmittal interno mancano le firme

Per ogni sito coinvolto la firma compare solo se la persona ha caricato la firma nel proprio **Profilo** ed è registrata come **Firmatario stabilimento** per quel sito e quel ruolo (Produzione o Qualità). Vedi **12.8 Il PDF della lettera**.

### Posso modificare lo stato interno di una revisione?

Non dall'interfaccia lista documenti (sola lettura). Puoi farlo dal pannello **admin** oppure tramite le operazioni di Emissione e Ricezione che aggiornano automaticamente gli stati.

### Come funziona l'integrazione ERP?

Quando crei una nuova commessa e digiti il Job, l'app interroga **Business Central** per recuperare automaticamente cliente, PO, descrizione e data consegna. Richiede che il server abbia accesso al database SQL Server configurato in `.env`.

### I dati presi da Business Central restano aggiornati?

Sì: ogni giorno alle 17:00 il sistema riconfronta cliente, PO, descrizione e data consegna delle commesse aperte con Business Central e le riallinea se in BC sono cambiate. Le modifiche applicate sono elencate in **Informazioni archivio → Aggiornamenti da Business Central** (vedi [6.4 Aggiornamenti da Business Central](#64-aggiornamenti-da-business-central)). Un valore vuoto in BC non cancella mai quello inserito nel sistema.

### Come importo dati dal vecchio database Access?

Usa **Apri Commessa → Importa da Report** dalla Home. Il server deve avere accesso al database Access indicato in `ACCESS_MDB_PATH` nel file `.env`.

---

*Ultimo aggiornamento: ottobre 2026*
