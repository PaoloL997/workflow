# Manuale utente — Workflow (Gestione Documentale)

Applicazione web per la gestione di commesse, documenti e revisioni in ambito industriale (Brembana&Rolle).

Questo documento descrive **tutte le operazioni disponibili** nell'interfaccia per gli utenti dell'applicazione: chi consulta soltanto, chi ha il permesso di scrittura e chi può emettere il trasmittal interno. Le attività riservate agli amministratori (configurazione di reparti, stabilimenti, risposte del cliente, modelli, utenti) non sono descritte: dove servono, il manuale dice solo a chi rivolgersi.

---

## 1. Panoramica

Workflow consente di:

- Creare e consultare **commesse** (job) con dati cliente, PO, date di consegna e persone di riferimento
- Gestire l'**elenco documenti** di ogni commessa
- Tracciare le **revisioni** di ogni documento con stati interni ed esterni
- **Emettere** documenti al cliente (con generazione e archiviazione del PDF trasmittal)
- **Distribuire** internamente i documenti UT agli stabilimenti con il **trasmittal interno** (modulo MQ 7.5-04)
- **Registrare la ricezione** delle risposte del cliente
- Visualizzare la **situazione** complessiva dei documenti, filtrarla ed esportarla
- Collegare e aprire i **file** sul fileserver di rete (cartelle JOBS)
- Scaricare i **dati grezzi** di una commessa in Excel
- Proporre **nuove funzionalità** e segnalare **problemi** ai colleghi
- Chiedere aiuto a **Workflow Agent**, l'assistente integrato

### 1.1 Concetti principali

| Concetto | Descrizione |
|----------|-------------|
| **Commessa (Job)** | Identificativo univoco del progetto (es. `25056`) |
| **Documento** | Singolo documento tecnico/commerciale della commessa |
| **Revisione** | Iterazione di un documento (Rev. 0, 1, 2…, con lettera A, B, C… oppure con una sequenza personalizzata dell'archivio) |
| **Stato interno** | Fase di lavorazione interna (da inviare → inviato al cliente → ricevuto) |
| **Risposta cliente** | Esito della revisione da parte del cliente (Approved, Commented, ecc.) |
| **Trasmittal** | Lettera di accompagnamento PDF inviata al cliente con i documenti |
| **Trasmittal interno** | Lettera (modulo MQ 7.5-04) con cui i documenti UT vengono distribuiti agli stabilimenti e preparati per il DCC, prima dell'invio al cliente |
| **Sito costruttivo** | Stabilimento che costruisce la commessa; serve per il trasmittal interno |
| **Persone commessa** | PM, PE, QCI e WE della commessa; servono per i destinatari del trasmittal interno |

### 1.2 Permessi degli utenti

Ogni utente ha un **permesso generale**, assegnato da un amministratore:

| Permesso | Cosa può fare |
|----------|---------------|
| **Lettura** | Consultare tutto: commesse, documenti, situazione, storico dei trasmittal, file sul fileserver, export Excel e PDF. Può inoltre pinnare commesse, usare le notifiche, scrivere nel forum **Proposte e segnalazioni** e parlare con Workflow Agent |
| **Scrittura** | Tutto quanto sopra, più creare e modificare commesse, documenti, indirizzi, impostazioni dell'archivio; emettere e annullare trasmittal; registrare ricezioni; risolvere anomalie; sbloccare revisioni; collegare file |
| **Admin** | Come Scrittura, più l'eliminazione diretta delle commesse e il pannello di amministrazione (non trattato in questo manuale) |

Un nuovo account nasce con il permesso **Lettura**: per scrivere va chiesto a un amministratore.

A parte c'è il flag **Può scrivere sul trasmittal interno**, anch'esso assegnato da un amministratore e **indipendente** dal permesso generale: solo chi lo ha può impostare destinazioni, emettere, annullare o ritentare una lettera di trasmittal interno (vedi **12. Trasmittal interno**). Un utente con permesso Lettura e questo flag può emettere lettere; un utente con permesso Scrittura senza flag no.

Nell'interfaccia i pulsanti di scrittura sono **visibili a tutti**. Chi non ha il permesso li vede ma, cliccandoli, ottiene un avviso rosso in alto: *"Non hai i permessi per eseguire questa operazione."* (oppure *"Permesso negato."*). L'avviso sparisce da solo dopo pochi secondi e non apre nessuna finestra.

In questo manuale ogni capitolo riporta, dove serve, chi può usare la funzione.

---

## 2. Accesso e account

Questo capitolo spiega come accedere all'applicazione, registrarsi, recuperare la password e gestire il proprio profilo.

### 2.1 Accedere all'applicazione

1. Apri l'indirizzo dell'applicazione nel browser.
2. Se non sei autenticato, vieni portato alla pagina **Accedi** (*"Bentornato — Accedi al tuo account Workflow"*).
3. Inserisci **Username** e **Password**.
4. Clicca **Accedi**.

In caso di credenziali errate compare il messaggio *"Credenziali non valide. Riprova."*

La sessione dura **8 ore** e resta valida anche chiudendo il browser. Se avevi aperto direttamente una pagina interna, dopo il login ci arrivi subito.

### 2.2 Registrarsi

1. Dalla pagina di login, clicca **Registrati** (*"Crea un account — Unisciti a Workflow"*).
2. Compila i campi:
   - **Nome** e **Cognome** (facoltativi, ma compaiono nelle email, nei PDF e nel forum)
   - **Username** * (obbligatorio)
   - **Email** * (obbligatoria, deve essere un indirizzo **@brembanarolle.com**)
   - **Password** * e **Conferma password** *
3. Clicca **Crea account**.

Regole della password: almeno 8 caratteri, non troppo simile a nome, cognome, username o email, non una password comune, non solo numeri. I messaggi di errore possibili sono *"Username, email e password sono obbligatori."*, *"Le password non coincidono."*, *"È necessario usare un'email con dominio @brembanarolle.com."*, *"Username già in uso."*, *"Email già registrata."*, oltre a quelli sulla robustezza della password.

Dopo la registrazione vieni automaticamente loggato e portato alla Home, con permesso **Lettura** (vedi **1.2 Permessi degli utenti**).

### 2.3 Recuperare la password

Dal profilo non si cambia la password: si usa la procedura di recupero dalla pagina di login.

1. Nella pagina di login clicca **Recuperala** (sotto *"Hai dimenticato la password?"*).
2. Inserisci la tua **email aziendale** (@brembanarolle.com) e clicca **Invia link**.
3. La pagina **Controlla la posta** conferma l'invio: se l'indirizzo è registrato ricevi un'email con oggetto *"Recupero password — Workflow"*. Il link vale **24 ore**; controlla anche la cartella spam.
4. Apri il link: nella pagina **Nuova password** inserisci la nuova password e la conferma (stesse regole della registrazione) e clicca **Aggiorna password**.
5. La pagina **Password aggiornata** conferma l'operazione: clicca **Accedi** per entrare con le nuove credenziali.

Se il link è scaduto o già usato compare *"Link non valido"* con il pulsante **Richiedi un nuovo link**.

### 2.4 Profilo utente

Clicca sull'**avatar** in alto a destra (la foto, oppure l'iniziale del nome) per aprire la pagina **Profilo**. La pagina non ha la barra di navigazione: al salvataggio torni alla Home.

#### Foto profilo

Clicca sull'immagine circolare a sinistra (icona della fotocamera, *"Cambia foto profilo"*) e scegli un file PNG, JPEG, GIF o WebP. **La foto viene salvata subito**, insieme a tutti gli altri campi del profilo così come sono in quel momento.

#### Dati personali e aziendali

1. **Nome**, **Cognome**, **Email** (obbligatoria; errori possibili: *"L'email è obbligatoria."*, *"Email già utilizzata da un altro account."*).
2. **Ruolo** (testo libero, es. *Progettista*): viene stampato nella chiusura del PDF trasmittal (vedi **9.7 Il PDF del trasmittal**).
3. **Reparto**: scegli uno dei reparti presenti nel menu.
4. Clicca **Salva modifiche**.

#### Firma

Nel riquadro **Firma** carichi l'immagine della tua firma: viene stampata nel PDF del trasmittal interno se sei registrato come firmatario di uno stabilimento (vedi **12.8 Il PDF della lettera**).

- **Carica immagine** / **Sostituisci immagine**: PNG (meglio con sfondo trasparente) oppure JPEG, al massimo **1 MB**. Compare subito l'anteprima.
- Spunta **Rimuovi** per cancellare la firma attuale.
- La firma si salva con **Salva modifiche**.

Errori possibili: *"L'immagine di firma può pesare al massimo 1 MB."*, *"Formato non ammesso: carica un PNG, meglio se trasparente, o un JPEG."*, *"Impossibile salvare l'immagine: archivio non raggiungibile, riprova."* In quest'ultimo caso la firma precedente resta al suo posto.

#### Uscire dall'account

Dalla pagina Profilo, clicca **Logout** (in basso nella colonna sinistra). È l'unico punto da cui si esce.

---

## 3. Navigazione generale

Questo capitolo descrive gli elementi comuni a tutte le pagine: barra di navigazione, ricerca rapida, tema, notifiche, assistente Workflow Agent e riquadro delle novità.

### 3.1 Barra di navigazione

Su Home, Elenco commesse, Scarica e in tutte le pagine di una commessa trovi una barra centrale con:

| Voce | Funzione |
|------|----------|
| **Home** | Torna alla pagina principale con le commesse pinnate e recenti |
| **Cerca** | Apre la ricerca rapida (Spotlight) |
| **Scarica** | Esporta in Excel i dati grezzi di una commessa (vedi **13. Scarica dati grezzi**) |
| **Impostazioni** | Riservata agli amministratori: agli altri utenti mostra l'avviso *"Non hai accesso al pannello amministrazione."* |

In alto a sinistra compare sempre il marchio **Brembana&Rolle / Gestione di commessa**, puramente decorativo. In alto a destra ci sono la **campanella** delle notifiche e l'**avatar** che apre il profilo. Non c'è un pulsante "indietro": per tornare alla pagina della commessa usa la ricerca, la Home o il tasto indietro del browser.

La **scheda del browser** riporta il contesto: `Home`, `Elenco Commesse`, `Profilo`, e nelle pagine di una commessa il suo numero, ad esempio `25056` oppure `25056 · Situazione documenti`, così con più schede aperte riconosci subito di quale commessa si tratta.

### 3.2 Ricerca commesse (Spotlight)

La ricerca è disponibile ovunque:

- Clicca **Cerca** nella barra di navigazione, oppure
- Clicca **Cerca Commessa** dalla Home, oppure
- Premi **Ctrl+K** (Windows) / **Cmd+K** (Mac)

**Come usarla:**

1. Digita il numero job o il nome cliente (*"Cerca commessa per job o cliente…"*): la ricerca è "contiene" e non distingue maiuscole.
2. I risultati appaiono in tempo reale (al massimo 8), prima le commesse pinnate; ogni voce mostra job, cliente, descrizione e data di consegna.
3. Clicca su una commessa per aprirla. Premendo **Invio** la commessa si apre solo se il testo digitato è **esattamente** il suo codice; altrimenti Invio aggiorna soltanto i risultati.
4. Premi **Esc** o clicca fuori dal riquadro per chiudere.

Messaggi possibili: *"Nessun risultato trovato."*, *"Errore durante la ricerca."*

### 3.3 Tema chiaro/scuro

In basso a destra trovi il pulsante circolare per cambiare tema (luna in tema chiaro, sole in tema scuro). Alla prima visita il tema segue quello del sistema operativo; la preferenza viene poi salvata nel browser.

### 3.4 Formato delle date

Nelle schermate le date compaiono nel formato *giorno mese anno* con il mese abbreviato in inglese, ad esempio `10 jan 2026`. Nei campi di inserimento vale quanto indicato nel capitolo della singola funzione.

### 3.5 Notifiche

In alto a destra, subito a sinistra dell'avatar, c'è una **campanella**. Un pallino rosso con il numero indica quante notifiche non hai ancora letto (oltre 99 compare `99+`).

**Quando arriva una notifica:**

| Evento | Testo | A chi arriva |
|--------|-------|--------------|
| Un collega propone una nuova feature nel forum | *"Mario Rossi ha proposto una nuova feature"* | Tutti gli utenti attivi, tranne l'autore |
| Un collega segnala un problema nel forum | *"Mario Rossi ha evidenziato un problema"* | Tutti gli utenti attivi, tranne l'autore |
| Qualcuno commenta un post | *"Anna Bianchi ha commentato «Titolo del post»"* | Chi ha aperto il post e chi lo ha già commentato, tranne chi scrive |

Per i commenti esiste **una sola notifica per post**: un nuovo commento la riporta in cima e la segna di nuovo come da leggere, con il nome dell'ultimo commentatore. Voti, chiusure e riaperture dei post non generano notifiche.

**Come si usano:**

1. Clicca la campanella: si apre il riquadro **Notifiche** con le notifiche non lette, dalla più recente (al massimo 50). Se non ce ne sono: *"Nessuna nuova notifica."*
2. Clicca una notifica per aprire la pagina **Proposte e segnalazioni** (vedi **14. Proposte e segnalazioni**).
3. Una volta aperto il riquadro, le notifiche mostrate risultano lette: il contatore si azzera e alla prossima apertura non compaiono più.
4. Clicca fuori dal riquadro, di nuovo la campanella o premi **Esc** per chiudere.

Il contatore si aggiorna automaticamente ogni minuto, senza ricaricare la pagina.

### 3.6 Workflow Agent (assistente)

Il pulsante con l'icona del **robot**, subito sopra quello del tema in basso a destra, apre in ogni pagina la finestra di **Workflow Agent**: un assistente che risponde sulle commesse e sui documenti e sull'uso dell'applicazione. È disponibile a tutti gli utenti e lavora **con il tuo utente e i tuoi permessi**: quello che non puoi fare tu non lo fa nemmeno lui.

**Come si usa:**

1. Clicca il pulsante robot: si apre una finestra in basso a destra (*"Chiedi a Workflow Agent dei documenti o di come usare l'applicazione"*).
2. Scrivi nel campo *"Scrivi un messaggio…"* (al massimo 4000 caratteri). **Invio** manda il messaggio, **Maiusc+Invio** va a capo.
3. La risposta arriva formattata (grassetto, elenchi, tabelle, codice). Mentre l'assistente lavora il campo è disabilitato.
4. Chiudi con la **✕**, con **Esc**, cliccando fuori dalla finestra o di nuovo sul pulsante robot.

**Cosa sa fare per tutti gli utenti:**

- Controllare un documento: titolo e ultima revisione.
- Leggere una revisione: stato interno, risposta del cliente, date di invio e di rientro, revisione successiva.
- Spiegare come si usa Workflow, a partire da questo manuale.

Non elenca commesse o documenti: per gli elenchi usa le pagine della commessa, come **Gestisci ricezione** o **Situazione documenti**.

**Cosa sa fare in più con il permesso di scrittura** (PM e Document Controller):

- Correggere la risposta del cliente di una revisione già rientrata. Workflow allinea la revisione successiva: la crea se la nuova risposta la richiede, la elimina se non serve più ed è ancora vuota. Se la revisione successiva è già stata inviata o ha dati propri, la correzione viene rifiutata e non cambia nulla.
- Annullare un invio al cliente registrato per errore, solo sull'ultima revisione e solo se il cliente non ha ancora risposto. La revisione torna *Da emettere*; il trasmittal e i file restano com'erano.
- Correggere una ricezione registrata male. Può cambiare la data di rientro (non prima della data di invio e non nel futuro): se la revisione successiva è ancora vuota, la sua data di invio prevista si ricalcola dalla nuova data. Oppure può annullare la ricezione, se il documento in realtà non è rientrato: la revisione torna *Inviato al Cliente*, senza data di rientro né risposta del cliente, e la revisione successiva ancora vuota viene eliminata. Se la revisione successiva è già stata inviata o ha dati propri, l'annullamento viene rifiutato e non cambia nulla. La data di invio e la data di ricezione prevista restano com'erano.

**Azioni da confermare.** Quando l'assistente propone modifiche, nella risposta compare il blocco **Azione da confermare** (o **Azioni da confermare**) con una card per azione e i pulsanti **Rifiuta** / **Approva**; con più azioni c'è anche **Approva tutte**. Finché non hai deciso su tutte non puoi scrivere (*"Decidi sulle azioni proposte…"*). Prese tutte le decisioni, l'assistente le riceve e continua. Controlla sempre cosa propone prima di approvare: può sbagliare. Se non hai il permesso di scrittura, le modifiche che approvi vengono comunque rifiutate dall'applicazione.

**Buono a sapersi:**

- Nelle pagine di una commessa l'assistente sa già di quale commessa stai parlando.
- La conversazione continua anche cambiando pagina nella stessa scheda del browser; ricaricando la pagina i messaggi a schermo spariscono ma l'assistente ricorda la conversazione.
- Nell'intestazione il tasto **ℹ** apre la scheda **Informazioni sull'agent**, con quello che può fare un utente standard e un utente con permesso di scrittura; la **matita** inizia una nuova conversazione.
- Se l'assistente non è raggiungibile compare *"Workflow Agent non è disponibile al momento."* oppure *"Workflow Agent non raggiungibile: controlla la connessione e riprova."*; se la sessione è scaduta *"Sessione scaduta: ricarica la pagina e accedi di nuovo."*

### 3.7 Novità della versione

In basso a sinistra nella Home c'è il badge con il numero di versione (es. **v0.1.6**). Cliccandolo si apre il riquadro **Novità** con le sezioni **Aggiunte**, **Modifiche** e **Correzioni** della versione in uso. Si chiude con ✕, Esc o cliccando fuori.

---

## 4. Home e gestione commesse

La **Home** mostra una griglia di card con le commesse **pinnate** (nell'ordine in cui le hai pinnate) seguite dalle commesse più recenti, fino a **8** card in tutto. Ogni card mostra job, cliente, descrizione e data di consegna; cliccandola si apre la commessa. Se non ci sono commesse: *"Nessuna commessa trovata. Premi Apri Commessa per crearne una."*

Sotto la griglia il link *"Qualcosa da segnalare? proponila qui"* porta al forum (vedi **14. Proposte e segnalazioni**).

### 4.1 Pinnare una commessa

Ogni card ha in alto un pulsante a forma di spillo (**Pinna commessa** / **Rimuovi pin**). Le commesse pinnate compaiono per prime nella Home, nell'**Elenco commesse** e nella ricerca Spotlight. I pin sono personali e valgono per tutti gli utenti, anche con permesso Lettura. Si possono pinnare al massimo **8** commesse: oltre compare l'avviso *"Puoi pinnare al massimo 8 commesse."*

### 4.2 Visualizzare tutte le commesse

Clicca **Visualizza tutte** sotto i pulsanti principali per aprire la pagina **Elenco Commesse** (`/commesse/`). Mostra tutte le commesse, comprese quelle chiuse, con lo stesso formato di card della Home (pinnate prima, poi dalla più recente) e il contatore *"N commesse"*. Non ci sono filtri né ordinamenti: per trovare una commessa usa la ricerca Spotlight (vedi **3.2 Ricerca commesse (Spotlight)**).

### 4.3 Creare una nuova commessa

**Permessi:** Scrittura. Con permesso Lettura il pulsante **Apri Commessa** mostra l'avviso di permesso negato e il menu non si apre.

1. Clicca **Apri Commessa** → **Nuova commessa**.
2. Compila il modulo **Nuova Commessa**:
   - **Job** * (obbligatorio, univoco) — numero commessa
   - **Cliente** * (obbligatorio)
   - **PO No.** — numero ordine cliente
   - **Bid No.** — numero offerta
   - **Ruoli commessa**: quattro righe **PM**, **PE**, **QCI**, **WE**. In ogni riga scrivi nel campo *"Aggiungi persona…"*: dalla seconda lettera compaiono gli utenti registrati (*"Nome Cognome (username)"*), clicca per aggiungerli. Premendo **Invio** o la **virgola** (o uscendo dal campo) il testo digitato viene aggiunto come nome libero, non legato a un utente. Ogni persona è una "etichetta" con la ✕ per toglierla; per ruolo si possono indicare più persone. Le persone commessa servono per i destinatari del trasmittal interno (vedi **12.6 A chi va: destinatari e invio**)
   - **Descrizione** — dettaglio commessa
   - **Data consegna**
   - **Termini consegna** — es. DDP, FCA
3. Clicca **Crea commessa** (o premi Invio in un campo qualsiasi, tranne quelli dei ruoli).

La commessa compare nella griglia; il modulo si chiude. Errori possibili: *"I campi Job e Cliente sono obbligatori."*, *"Una commessa con questo Job esiste già."*

> **Suggerimento ERP:** quando digiti il Job (almeno 3 caratteri), l'app interroga Business Central e, se trova la commessa, compila **Cliente**, **PO No.**, **Descrizione** e **Data consegna** (solo i valori presenti in BC). Accanto all'etichetta Job compare *✓ Trovata* oppure *Non trovata in ERP*. Bid No. e Termini consegna non vengono mai compilati. Dopo la creazione l'applicazione prova anche a impostare da sola il **Sito costruttivo**; se in seguito i dati cambiano in Business Central, il controllo giornaliero riallinea la commessa (vedi **6.4 Aggiornamenti da Business Central**).

### 4.4 Importare una commessa dal vecchio sistema (Report/Access)

**Permessi:** Scrittura.

1. Clicca **Apri Commessa** → **Importa da Report**.
2. Inserisci il **Numero commessa** e clicca **Importa** (o premi Invio).

L'importazione recupera dal vecchio database Access testata, primo indirizzo di spedizione, documenti, revisioni e risposte del cliente; le revisioni orfane vengono escluse. Subito dopo l'applicazione registra i trasmittal già presenti nella cartella della commessa (vedi **9.6 Storico trasmittal**), importa PM, PE, QCI e WE dal foglio "Organizzazione Commesse" (i cognomi vengono abbinati agli utenti registrati, gli altri restano nomi liberi) e prova a impostare il Sito costruttivo da Business Central.

Al termine vieni portato alla pagina della commessa; se l'import ha trovato revisioni incoerenti, il riquadro delle anomalie si apre da solo (vedi **5.5 Revisioni da risolvere (anomalie)**).

Errori possibili: *"Specificare il numero di commessa."*, *"La commessa "X" esiste già nel database."*, *"Commessa "X" non trovata nel database Access."*. In caso di errore il pulsante diventa **Riprova**.

### 4.5 Aprire una commessa esistente

- Clicca su una card dalla Home o dall'Elenco commesse
- Usa la ricerca Spotlight (Ctrl+K)

---

## 5. Pagina commessa (dashboard)

URL: `/commesse/<job>/`

La dashboard della commessa è il punto centrale per tutte le attività.

### 5.1 Intestazione

In alto compaiono il nome del cliente, il titolo **Commessa <job>**, la riga con **PO No.**, **Bid No.**, **Termini consegna**, **PM**, **PE**, **QCI**, **WE** (un trattino se il dato manca) e la descrizione.

**Persone non abbinate.** Un nome inserito come testo libero alla creazione e non collegato a un utente registrato compare in rosso con sottolineatura tratteggiata. Chi ha il permesso Scrittura può cliccarlo: nel riquadro *"Cerca utente…"* dalla seconda lettera compaiono gli utenti registrati; scegliendone uno il nome viene abbinato all'utente e torna in testo normale. Le persone commessa non si aggiungono né si modificano da questa pagina: si inseriscono alla creazione della commessa (vedi **4.3 Creare una nuova commessa**) e per cambiarle dopo serve un amministratore.

### 5.2 Chiudere la commessa

**Permessi:** Scrittura.

Il pulsante **Chiudi commessa** (accanto a Elimina commessa) registra la data odierna come data di consegna effettiva, senza richiesta di conferma. Al posto del pulsante compare poi *"Chiusa il 10 jan 2026"* e la barra di avanzamento passa a **Completato**. La commessa chiusa resta consultabile e modificabile in tutte le sue sezioni; il controllo giornaliero con Business Central la salta (il pulsante **Aggiorna da BC** funziona comunque, vedi **6.4 Aggiornamenti da Business Central**). Non esiste un pulsante per riaprirla: chiedi a un amministratore.

### 5.3 Eliminare una commessa o chiederne l'eliminazione

Sotto il titolo c'è il pulsante **Elimina commessa**. Cosa succede dipende dal permesso:

- **Scrittura**: si apre il riquadro *"Verrà inviata una richiesta di eliminazione per la commessa <job>. La commessa non verrà eliminata automaticamente."* Cliccando **Invia richiesta** parte un'email agli amministratori con il tuo nome e la commessa; compare *"Richiesta di eliminazione inviata."* e la commessa resta al suo posto finché un amministratore non la elimina.
- **Admin**: il riquadro avvisa che l'operazione è irreversibile e il pulsante **Elimina** cancella la commessa con tutti i documenti, le revisioni e i dati collegati.
- **Lettura**: compare l'avviso di permesso negato.

### 5.4 Barra di avanzamento (Stato commessa)

La barra tratteggiata sotto l'intestazione è puramente **temporale**, non legata allo stato dei documenti: parte da un anno prima di oggi e finisce alla **data di consegna** (o un anno dopo oggi se manca). Alle estremità sono stampate le due date. L'etichetta sopra la barra è:

| Etichetta | Quando |
|-----------|--------|
| **Da iniziare** | La commessa non ha data di consegna |
| **In corso** | Oggi è prima della data di consegna |
| **In ritardo** | Oggi è oltre la data di consegna |
| **Completato** | La commessa è chiusa (barra al 100%) |

### 5.5 Revisioni da risolvere (anomalie)

Se alcune revisioni hanno dati incoerenti, sotto l'intestazione compare il pulsante giallo *"Ci sono N revisioni da risolvere"* (dopo un'importazione da Report lampeggia). Lo stesso pulsante, in formato compatto, è nella barra della **Situazione documenti**.

Cliccandolo si apre il riquadro **Revisioni da risolvere**: una riga per revisione con documento, revisione (badge *Ultima revisione* o *Revisione precedente*), i problemi rilevati e lo stato suggerito (*Da emettere*, *Da ricevere*, *Completata*). I problemi riconosciuti sono:

- *Risposta cliente registrata senza data di rientro effettiva.*
- *Stato interno «Inviato al Cliente» senza data di invio effettiva.*
- *Invio effettivo registrato senza data di rientro prevista.*
- *Stato interno «Ricevuto» senza data di rientro effettiva.*
- *Stato interno «Inviato al Cliente» con data di rientro già valorizzata.*

Per ogni riga ci sono due azioni (**permessi: Scrittura**; chiunque può aprire il riquadro e consultarlo):

- **Ignora**: dopo la conferma *"Ignorare questa revisione? Non comparirà più tra le anomalie da risolvere."* la revisione viene esclusa per sempre dal controllo. Per riattivarla serve un amministratore.
- **Risolvi**: apre la scheda della revisione con i campi modificabili **N. revisione**, **Lettera revisione**, **Invio previsto**, **Invio effettivo**, **Rientro previsto**, **Rientro effettivo**, **Stato interno**, **Risposta cliente** e la spunta **Crea nuova revisione alla prossima ricezione**; i campi legati al problema sono evidenziati. Il blocco **Classifica documento** precompila i campi con tre scelte rapide:

  | Scelta | Effetto |
  |--------|---------|
  | **Da emettere** | Documento in attesa di invio al cliente: azzera stato interno, risposta, invio effettivo, rientro previsto ed effettivo |
  | **Da ricevere** | Documento inviato, in attesa di risposta: invio effettivo = quello esistente o oggi, stato *Inviato al Cliente*, rientro previsto = invio + giorni revisione cliente |
  | **Conclusi** | Risposta registrata su questa revisione: rientro effettivo = quello esistente o oggi, stato *Ricevuto* |

  Clicca **Risolvi** per salvare. Se la revisione resta incoerente compare *"Salvato, ma restano incongruenze su questa revisione. Verifica i campi e riprova."*; altrimenti la riga sparisce e, a zero anomalie, sparisce anche il pulsante giallo.

### 5.6 Sezioni disponibili

Sei card cliccabili portano alle sezioni della commessa:

| Sezione | Contenuto |
|---------|-----------|
| **Informazioni archivio** | Tempi di revisione, sito costruttivo, indirizzi di consegna, modalità delle revisioni, aggiornamenti da Business Central (capitolo **6. Informazioni archivio**) |
| **Elenco documenti** | Lista e gestione documenti (capitolo **7. Elenco documenti**) |
| **Gestisci emissione** | Invio documenti al cliente (capitolo **9. Gestione emissione**) |
| **Gestisci ricezione** | Registrazione risposte cliente (capitolo **10. Gestione ricezione**) |
| **Situazione documenti** | Vista tabellare completa (capitolo **11. Situazione documenti**) |
| **Trasmittal interno** | Distribuzione interna dei documenti UT agli stabilimenti (capitolo **12. Trasmittal interno**) |

> **Nota:** finché l'archivio non è completo, cioè finché non sono stati impostati sia i **giorni revisione cliente** sia i **giorni revisione B&R** (vedi **6.1 Tempi di revisione**), tutte le card tranne **Informazioni archivio** sono bloccate con il messaggio *"Completa prima le informazioni archivio"*. La card **Trasmittal interno** resta inoltre bloccata (*"Completa prima il sito costruttivo della commessa"*) finché non è impostato il **Sito costruttivo**.

### 5.7 Anteprime nella dashboard

- **Informazioni archivio:** quattro riquadri con *Giorni revisione cliente*, *Giorni revisione B&R*, *Revisioni* (Numero / Lettera / Personalizzata) e numero di *Indirizzi di consegna*; se l'archivio è incompleto, *"Clicca per compilare"*.
- **Elenco documenti:** fino a 7 riquadri con titolo e codice dei documenti, più un riquadro *"+N"* se ce ne sono altri.
- **Gestisci emissione:** fino a 4 documenti da emettere con revisione e scadenza rispetto alla data di invio prevista: *Ngg fa* / *Ieri* (rosso), *Oggi*, *Domani*, *2gg*/*3gg*, fino a 7 giorni, *>7gg* (verde), *—* senza data; poi *"+N altri"*.
- **Gestisci ricezione:** stessa impaginazione per i documenti inviati in attesa di risposta, con scadenza rispetto alla data di ricezione prevista.
- **Situazione documenti** e **Trasmittal interno:** un'illustrazione fissa della sezione.

---

## 6. Informazioni archivio

URL: `/commesse/<job>/archivio/`

Questa sezione configura i parametri che governano il calcolo automatico delle date nelle fasi di emissione e ricezione, gli indirizzi per il trasmittal e il modo in cui si leggono le revisioni. Tutti possono consultarla; i pulsanti di salvataggio richiedono il permesso **Scrittura**.

### 6.1 Tempi di revisione

| Campo | Significato | Effetto |
|-------|-------------|---------|
| **Revisione cliente** | Giorni concessi al cliente per rispondere (0–999) | All'emissione: `Data ricezione prevista = Data emissione + giorni cliente` |
| **Revisione interna** | Giorni a disposizione di B&R per emettere la revisione successiva (0–999) | Alla ricezione con nuova rev.: `Data invio prevista = Data ricezione + giorni interni` |

**Procedura:**

1. Inserisci i valori nei campi numerici.
2. Clicca **Salva modifiche**: compare *"✓ Salvato"* (oppure *"Errore durante il salvataggio."*).

Entrambi i campi devono essere compilati perché la pagina commessa sblocchi le altre sezioni (vedi **5.6 Sezioni disponibili**). Se un campo è vuoto, la data corrispondente non viene calcolata e resta vuota.

Nello stesso riquadro c'è il campo **Sito costruttivo**: lo stabilimento che costruisce la commessa, scelto tra quelli con un codice sito Business Central. Serve a sbloccare il **Trasmittal interno** (capitolo **12. Trasmittal interno**). Se è vuoto, il controllo giornaliero con Business Central prova a impostarlo da solo; un valore già impostato non viene mai sovrascritto. Si salva con lo stesso **Salva modifiche**.

Come vengono indicate le revisioni (numero, lettera o sequenza personalizzata) si sceglie nella sezione **6.3 Revisioni**.

### 6.2 Indirizzi di consegna

Gli indirizzi sono i destinatari proposti in **Gestisci emissione** e stampati nel PDF trasmittal (vedi **9.7 Il PDF del trasmittal**). L'elenco mostra per ogni indirizzo il destinatario in grassetto e, sotto, indirizzo, città e paese; se è vuoto: *"Nessun indirizzo aggiunto"*.

#### Aggiungere un indirizzo

1. In **Informazioni archivio**, sezione **Indirizzi di consegna**, clicca **+ Aggiungi indirizzo**.
2. Nel riquadro **Nuovo indirizzo** compila i campi, tutti facoltativi: **Destinatario**, **Indirizzo**, **CAP**, **Città**, **Paese**, **Att.ne** (persona di riferimento), **Telefono**.
3. Clicca **Salva**.

#### Modificare o eliminare un indirizzo

- Clicca **Modifica** sulla riga dell'indirizzo, aggiorna i campi nel riquadro **Modifica indirizzo** e clicca **Salva**.
- Clicca **Elimina** e conferma *"Eliminare questo indirizzo?"*.

### 6.3 Revisioni

La sezione, sotto gli indirizzi di consegna, decide come si legge la revisione in tutta l'applicazione. Le scelte sono tre:

| Scelta | Revisioni | Esempio |
|--------|-----------|---------|
| **Numero** | Sempre il numero, partendo da 0 | 0, 1, 2, 3… |
| **Lettera** | Sempre la lettera, partendo da A | A, B, C, D… |
| **Personalizzata** | Le etichette scritte nel campo **Sequenza**, nell'ordine dato | 1, 2, 3, D, E, F, 4, 5, 6 |

**Procedura:**

1. Scegli **Numero**, **Lettera** o **Personalizzata**.
2. Con **Personalizzata**, scrivi nel campo **Sequenza** le etichette separate da virgole (es. `1,2,3,D,E,F,4,5,6`). La riga **Anteprima** mostra come si leggeranno le revisioni, comprese le prime che proseguono da sole oltre l'ultima etichetta.
3. Clicca **Salva revisioni**: compare *"✓ Salvato"*.

Regole della sequenza personalizzata:

- la **prima** etichetta è la prima revisione del documento (quella che con i numeri sarebbe la Rev. 0), la seconda la successiva e così via;
- oltre l'ultima etichetta la sequenza **prosegue da sola** partendo dall'ultima: se finisce con un numero continua con i numeri (`…, 5, 6` → 7, 8…), se finisce con una lettera continua con le lettere (`…, E, F` → G, H…);
- ogni etichetta è lunga al massimo 10 caratteri, non può essere vuota, contenere virgole né essere ripetuta (maiuscole e minuscole contano come uguali). Gli errori vengono mostrati in rosso sotto il campo, ad esempio *"L'etichetta «x» è ripetuta."* o *"Inserisci almeno un'etichetta nella sequenza."*

Scegliendo **Numero** o **Lettera** e salvando, la sequenza personalizzata viene cancellata.

#### Come viene mostrata la revisione

La scelta fatta nella sezione **6.3 Revisioni** (Numero, Lettera o Personalizzata) è l'unica cosa che decide come si legge la revisione. Vale per ogni schermata (elenco documenti, situazione documenti in entrambe le viste comprese le intestazioni di colonna, emissione, ricezione, trasmittal interno, sblocco e anomalie revisioni) e per ogni stampa o export (Excel, PDF, trasmittal).

Sotto, ogni revisione resta un numero progressivo. Numero e lettera sono due modi di scrivere lo stesso dato (`0 = A`, `1 = B`, … `25 = Z`, `26 = AA`): se sulla revisione manca il valore richiesto, viene ricavato dall'altro. Con la sequenza personalizzata conta solo il numero progressivo, e la lettera eventualmente salvata sulla revisione viene ignorata. Cambiare la scelta non modifica quindi i dati, solo la loro lettura: i PDF già emessi e le lettere di trasmittal interno già create mantengono la revisione con cui sono state prodotte.

### 6.4 Aggiornamenti da Business Central

Ogni giorno (di norma alle **17:00**) il sistema riconfronta con **Business Central** i dati che l'ERP aveva precompilato alla creazione della commessa — **Cliente**, **PO cliente**, **Descrizione**, **Data consegna** e, se ancora vuoto, **Sito costruttivo** — e aggiorna la commessa se in BC sono cambiati.

La sezione elenca le ultime dieci modifiche applicate, con data, campo e valore precedente → nuovo. Se non compare nulla: *"Nessun aggiornamento da Business Central: i dati sono allineati."*

Regole del controllo automatico:

- vengono controllate le commesse **aperte** (senza data consegna effettiva);
- un valore **vuoto** in Business Central non sovrascrive mai un dato già inserito nel sistema;
- gli altri campi (tempi di revisione, indirizzi, documenti…) non vengono toccati;
- una commessa non presente in BC viene semplicemente saltata;
- se il server era spento all'orario previsto, il controllo viene recuperato alla prima riaccensione;
- se Business Central non risponde, l'errore viene registrato e si ritenta il giorno successivo.

**Aggiorna da BC** (permessi: Scrittura). Il pulsante accanto al titolo della sezione lancia subito il confronto sulla sola commessa corrente, senza aspettare il controllo giornaliero, e funziona **anche sulle commesse chiuse**. Durante l'operazione compare *"Sincronizzazione con Business Central…"*, poi *"✓ N campi aggiornati"* oppure *"✓ Nessuna modifica: i dati sono già allineati"*; l'elenco si aggiorna sul posto. Se Business Central non risponde o la commessa non esiste in BC (*"Commessa "<job>" non trovata in Business Central."*) l'errore compare in rosso.

Lo storico completo, oltre le ultime dieci modifiche, è consultabile solo dagli amministratori.

---

## 7. Elenco documenti

URL: `/commesse/<job>/documenti/`

Pagina principale per la gestione dell'elenco documenti della commessa (titolo **Lista documenti**). Tutti possono consultarla ed esportarla; aggiungere, modificare ed eliminare documenti richiede il permesso **Scrittura**.

### 7.1 Visualizzare i documenti

Ogni documento è una riga con:

- il **titolo** in maiuscolo (*"Titolo non specificato"* se manca) e, accanto, il badge con il **Client Doc Class**;
- la riga dei codici: **Item** • **B&R Doc** • **Client Doc N°** • **Contractor Doc N°** • **Reparto** (gli ultimi tre solo se valorizzati);
- le pillole **Penale**, **Pagamento**, **Rev. Generale** quando il flag è attivo;
- a destra i **chip revisioni** (Rev. 0, Rev. 1, … secondo la modalità dell'archivio; l'ultima è evidenziata in blu, *"Nessuna revisione"* se non ce ne sono) — cliccabili per aprire il file (vedi **8.2 Apertura automatica dei file**);
- il pulsante **···** con le azioni **Modifica** ed **Elimina**.

Usa la **barra di ricerca** (*"Cerca per titolo, item, doc…"*) per filtrare all'istante per Item, B&R Doc, Client Doc N°, Contractor Doc N°, Client Doc Class, Titolo o Reparto. I documenti sono in ordine di inserimento; non ci sono altri filtri né ordinamenti.

> Le revisioni nella lista sono in **sola lettura**: lo stato interno viene aggiornato tramite Emissione e Ricezione, oppure dal riquadro delle anomalie (vedi **5.5 Revisioni da risolvere (anomalie)**).

### 7.2 Aggiungere un documento manualmente

1. Clicca **Aggiungi** → **Crea manualmente**.
2. Compila il modulo **Aggiungi documento** (nessun campo è obbligatorio):
   - **Item** — numero progressivo
   - **B&R Doc** — numero documento interno (es. `25056-QMDBI`)
   - **Client Doc N°**, **Contractor Doc N°**, **Client Doc Class**
   - **Titolo**
   - **Reparto** — scegli uno dei reparti presenti nel menu (*"— Nessun reparto —"* per lasciarlo vuoto); se il reparto manca, chiedi a un amministratore. Il reparto serve per trovare i file sul fileserver (vedi **8.1 Struttura cartelle sul fileserver**)
   - **Note**
   - **Data invio prevista (Rev. 0)** — data pianificata della prima emissione (l'etichetta mostra la prima revisione secondo la modalità dell'archivio, es. *Rev. A*)
   - **Penale**, **Pagamento**, **Rev. Generale** — interruttori on/off
3. Clicca **Salva**: compare *"Documento aggiunto."*

Alla creazione viene automaticamente generata la **Revisione 0**, con la data di invio prevista indicata. Non c'è controllo di duplicati.

### 7.3 Importare documenti da Excel

1. Clicca **Aggiungi** → **Importa da Excel**.
2. Facoltativo: clicca **Scarica template** per ottenere `template_lista_documenti.xlsx`, con le intestazioni già pronte, il menu a tendina dei reparti nella colonna *Department* e la colonna data pre-formattata.
3. Prepara un file `.xlsx` o `.xls` con la **prima riga come intestazione**; viene letto solo il **primo foglio** e le righe vuote vengono saltate.
4. Trascina il file nell'area *"Trascina qui il file Excel"* oppure clicca per selezionarlo.
5. Clicca **Importa**.

**Colonne riconosciute** (non sensibili a maiuscole; nomi italiani o inglesi):

| Colonna Excel | Campo |
|---------------|-------|
| Item / Item no | Numero item |
| B&R Doc / Vendor Doc | Numero doc. B&R |
| Client Doc N° / Client Doc No | Numero doc. cliente |
| Contractor Doc N° / Contractor Doc No | Numero doc. contractor |
| Client Doc Class | Classe doc. cliente |
| Titolo / Titolo documento / Document title / Doc Title | Titolo |
| Reparto / Department | Nome reparto (deve esistere) |
| Penale / Penalty, Pagamento / Payment, Rev. generale / General rev. | `Sì`, `Si`, `Yes`, `1`, `X`, `true`, `vero` per attivo |
| Data invio prevista (Rev. 0) / Data prima emissione / Planned send date | Data invio prevista della Rev. 0: cella data di Excel, `AAAA-MM-GG` o `GG/MM/AAAA` |
| Note / Notes / Remarks | Note libere |

Per ogni riga importata viene creato un nuovo documento con la Revisione 0, anche se un documento con lo stesso codice esiste già. Al termine compare *"Importati N documenti."* e il riquadro si chiude da solo; se ci sono avvisi (*"Riga 5: reparto "XYZ" non trovato, ignorato."*, *"Riga 7: data non riconosciuta…"*) restano visibili in giallo. Errori bloccanti: *"File Excel non valido o corrotto."*, *"Il file è vuoto."*, *"Nessuna colonna riconosciuta. Verifica le intestazioni."*

### 7.4 Generare documenti da modello

Le **cartelle di modelli** raccolgono i documenti standard (titolo, item, codice fisso, reparto) e sono predisposte da un amministratore.

1. Clicca **Aggiungi** → **Genera da modello**.
2. Scegli una cartella tra quelle proposte (nome, descrizione e numero di documenti); sotto compare l'anteprima dei modelli che contiene.
3. Clicca **Genera documenti**.

Per ogni modello viene creato un documento con **Titolo**, **Item**, **Reparto** e **B&R Doc** calcolato come `{job}-{codice fisso}` (es. `25056-QMDBI`), più la Revisione 0; gli altri campi si completano con **Modifica**. I modelli il cui B&R Doc esiste già nella commessa vengono saltati: il messaggio finale è del tipo *"Creati 5 documenti (2 già presenti)"*. Se il riquadro dice *"Nessuna cartella modelli configurata"*, chiedi a un amministratore di crearne una.

### 7.5 Modificare un documento

1. Clicca **···** sulla riga del documento → **Modifica**.
2. Aggiorna i campi nel riquadro **Modifica documento** (gli stessi di **7.2 Aggiungere un documento manualmente**). Il campo **Data invio prevista** aggiorna la data della prima revisione.
3. Clicca **Salva**: compare *"Documento aggiornato."*

### 7.6 Eliminare un documento

1. Clicca **···** → **Elimina**.
2. Conferma *"Eliminare questo documento? L'operazione è irreversibile."*

> L'eliminazione rimuove anche tutte le revisioni, i collegamenti ai file e le destinazioni del trasmittal interno del documento.

### 7.7 Esportare l'elenco documenti

Clicca **Esporta** per scaricare `<job>_document_list.xlsx` con **tutti** i documenti della commessa (la ricerca a schermo non viene applicata): colonne Item, B&R Doc, Client Doc N°, Contractor Doc N°, Client Doc Class, Title, Department, Penalty, Payment, Notes. Disponibile a tutti gli utenti.

---

## 8. Revisioni e file collegati

Questo capitolo spiega dove stanno i file delle revisioni sul fileserver e come l'applicazione li apre o li collega. Aprire un file è possibile per tutti; salvare un collegamento manuale richiede il permesso **Scrittura**.

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

L'acronimo di ciascun reparto (es. Quality Control → `QC`) è impostato da un amministratore: un documento senza reparto, o con un reparto senza acronimo, non può essere cercato automaticamente.

### 8.2 Apertura automatica dei file

Clicca su un **chip revisione** (es. `Rev. 0`, `Rev. A`) nella lista documenti, oppure su una riga o cella della situazione documenti (vedi **11.6 Apertura file**). L'app procede in quest'ordine:

1. Se per la revisione esiste un **collegamento manuale** (vedi **8.3 Collegamento manuale di un file**), apre sempre quel file.
2. Altrimenti servono un **B&R Doc** e un **reparto con acronimo**; se mancano, passa al collegamento manuale.
3. Cerca nella cartella giusta:
   - Se la revisione ha una **data ricezione effettiva** → cerca in `RICEVUTI/<data>/`
   - Se ha solo una **data emissione effettiva** → cerca nella cartella base del reparto
   - Se non ha **nessuna data effettiva** (solo date previste) → non cerca e apre subito il collegamento manuale
   - Il nome file deve **contenere** il B&R Doc (senza distinguere maiuscole)
4. Se trova **un solo file** → lo apre direttamente.
5. Se trova **più file** → il riquadro **Scegli il file da aprire** elenca i file con un pulsante **Apri** ciascuno. Succede anche quando un codice è contenuto in un altro (es. `…-ESH1` e `…-ESH10`).
6. Se **non trova nulla** → apre il riquadro **Collega un file alla revisione**.

**Comportamento per tipo file:**

| Tipo | Apertura |
|------|----------|
| Word (.doc, .docx) | Direttamente in Microsoft Word |
| Excel (.xls, .xlsx) | Direttamente in Microsoft Excel |
| PDF | In una nuova scheda del browser |
| Altri formati (DWG, …) | Scaricati dal browser, da aprire con l'applicazione predefinita |

Per Word ed Excel servono Office installato e la share JOBS raggiungibile dal tuo PC **con lo stesso percorso del server** (es. unità `Z:`); se il file non esiste è Office a segnalarlo.

### 8.3 Collegamento manuale di un file

Se il file non viene trovato automaticamente:

1. Si apre il riquadro **Collega un file alla revisione** (*"Nessun file trovato automaticamente per questa revisione. Naviga il fileserver e seleziona il file corretto."*).
2. Naviga le cartelle del fileserver partendo dalla cartella della commessa (`Z:\JOBS\<job>`): clicca una cartella per entrarci, **↑ Su** per risalire, un file per selezionarlo (*"Cartella vuota"* se non c'è nulla).
3. Con il file selezionato compare *"File selezionato"* con il percorso: clicca **Salva collegamento** (permessi: Scrittura; chi ha solo Lettura può navigare ma al salvataggio riceve l'avviso di permesso negato).

Compare *"Collegamento salvato."* e il file si apre subito. Il collegamento viene memorizzato e da quel momento ha sempre la precedenza: il riquadro non ricompare più per quella revisione. Il file deve stare dentro la cartella JOBS. Per cambiare o togliere un collegamento salvato rivolgiti a un amministratore.

---

## 9. Gestione emissione

URL: `/commesse/<job>/emissione/`

Questa sezione gestisce l'invio dei documenti al cliente con la lettera di trasmittal. Tutti possono consultarla, filtrarla, esportarla e vedere lo storico; **Stampa**, **Emetti e scarica** e **Annulla** richiedono il permesso **Scrittura**.

### 9.1 Quali documenti compaiono

Vengono elencati i documenti la cui revisione corrente **non** è ancora in stato *Inviato al Cliente* o *Ricevuto*: le Rev. 0 appena create, le revisioni successive generate dalla ricezione e i documenti senza revisioni. Colonne: **B&R Doc**, **Rev.**, **Title**, **Planned date** (data di invio prevista). Di default i documenti sono ordinati per data prevista, prima le scadute (in rosso), in coda quelli senza data. Se non c'è nulla: *"Nessun documento pronto per l'emissione."*

### 9.2 Filtri e ordinamento delle colonne

Le pagine Emissione, Ricezione e Situazione condividono gli stessi comandi di colonna:

- Clicca l'**intestazione** di una colonna per ordinare; un secondo clic inverte l'ordine.
- Clicca l'**imbuto** accanto all'intestazione per filtrare. Per le colonne di testo il riquadro offre la casella *"Cerca…"*, la spunta **(Seleziona tutto)**, l'elenco dei valori presenti (*—* per i vuoti) e il campo **Contiene**. Per le colonne data c'è un calendario con intervallo **Dal / Al**: clicca la data di inizio, poi quella di fine (una sola delle due è sufficiente).
- **Applica** conferma, **Cancella** azzera il filtro di quella colonna; Esc o un clic fuori chiudono senza applicare.
- Con filtri attivi la barra mostra *"N di T righe"* e il pulsante **Azzera filtri**.

I filtri agiscono solo a schermo: in Emissione e Ricezione **non** influenzano l'export. In Emissione, le righe nascoste da un filtro perdono la spunta.

### 9.3 Procedura di emissione

1. **Imposta la data** di invio nella barra superiore (default: oggi). È obbligatoria (*"Inserisci la data di invio."*).
2. **Controlla i destinatari**: il pulsante mostra *"N selezionati"* e un'etichetta per ogni indirizzo scelto, con la ✕ per toglierlo. All'apertura sono preselezionati **tutti** gli indirizzi di consegna della commessa (vedi **6.2 Indirizzi di consegna**); cliccando il pulsante si apre **Seleziona destinatari** con una spunta per indirizzo. Si può emettere anche senza destinatari.
3. **Seleziona i documenti** spuntando le righe (o cliccando la riga); la casella nell'intestazione seleziona tutte le righe visibili. Il contatore dice *"N di T documenti selezionati"*.
4. Scegli l'azione:
   - **Stampa** — genera e scarica solo il PDF (`trasmittal_<job>_<data>.pdf`) senza registrare nulla: le revisioni non cambiano, non viene consumato un numero di trasmittal e il PDF non compare nello storico.
   - **Emetti e scarica** — registra l'emissione e archivia il PDF sul fileserver.

Entrambi i pulsanti sono attivi solo con almeno un documento selezionato e aprono prima il riquadro **Opzioni trasmittal**.

### 9.4 Opzioni trasmittal (PDF)

| Campo | Descrizione |
|-------|-------------|
| **Our Ref. (numero trasmittal)** | Precompilato con il prossimo numero libero della commessa, nella forma `<job>-<n>` (es. `25056-7`). È modificabile; compare solo nel PDF |
| **Stabilimento (città)** | Sede di emissione, scelta dall'elenco stabilimenti; se il tuo utente ha uno stabilimento assegnato è già selezionato. Compare nella riga della data del PDF |
| **ID documento in tabella** | Tre spunte, tutte attive: **ID interno (Vendor Doc)**, **ID cliente (Client Doc)**, **Contractor Doc**. Decidono quali colonne di codice compaiono nella tabella del PDF |
| **Modalità spedizione** | **In allegato / Attached** (default), **Per pacco postale / By mail**, **Per Corriere / By Courier**, **Brevi manu / Direct through Mr.** |
| **Nome (Direct through Mr.)** | Solo con Brevi manu: nome di chi consegna |

Clicca **Procedi** per continuare.

### 9.5 Conferma emissione

1. Verifica il riepilogo nel riquadro **Conferma emissione**: numero di **Documenti**, **Data invio**, **Destinatari** (o *Nessuno*) e **File**, cioè il percorso in cui il PDF verrà archiviato.
2. Clicca **Conferma ed emetti**.

**Cosa succede automaticamente:**

- Il PDF viene salvato in `Z:\JOBS\<job>\PROGETTO\DCC\TRANSMITTAL\Transmittal <job>-<n>.pdf` e si apre in una **nuova scheda** del browser. Se il salvataggio sul fileserver fallisce, non viene emesso nulla.
- Per ogni documento selezionato, sulla revisione corrente (creata come Rev. 0 se il documento non ne aveva):
  - `Data invio effettivo` = data scelta
  - `Stato interno` = **Inviato al Cliente**
  - `Data ricezione prevista` = data emissione + giorni revisione cliente (vuota se i giorni non sono impostati)
- Il trasmittal viene registrato nello **storico** con il numero `<n>`.

Compare *"✓ N documenti emessi"* e i documenti emessi spariscono dall'elenco.

### 9.6 Storico trasmittal

Il pulsante **Storico Trasmittal** apre l'elenco dei trasmittal della commessa, dal più recente: *"Transmittal <job>-<n>"* con accanto la data di emissione (*"Non presente"* se non è nota). Cliccando la data il PDF si apre in una nuova scheda. Il riquadro si chiude cliccando fuori.

Alla prima apertura, se la commessa non ha ancora trasmittal registrati, l'applicazione legge i PDF già presenti nella cartella `DCC\TRANSMITTAL` (nomi `Transmittal <job>-<n>.pdf`, anche `Trasmittal` o con zeri iniziali) e li registra, senza revisioni collegate. Se la cartella è vuota compare il messaggio *"Nessun trasmittal trovato per questa commessa…"* con il pulsante **Aggiorna** (permessi: Scrittura) che rilegge la cartella. Se la cartella TRANSMITTAL si trova per errore dentro `DA SPEDIRE`, un avviso chiede di spostarla accanto a DA SPEDIRE: i PDF vengono letti anche da lì, ma quelli nuovi finiscono sempre in `DCC\TRANSMITTAL`.

#### Annullare un trasmittal

**Permessi:** Scrittura. Il pulsante rosso **Annulla** compare solo sull'**ultimo** trasmittal, se è stato emesso dall'applicazione (ha revisioni collegate) e nessuna delle sue revisioni è già stata ricevuta.

Dopo la conferma *"Annullare Transmittal <job>-<n>? I documenti torneranno da emettere e il PDF verrà rimosso."*:

- le revisioni collegate tornano **Da inviare**: data di invio effettivo e data di ricezione prevista vengono azzerate;
- il PDF viene eliminato dalla cartella `DCC\TRANSMITTAL`;
- il numero `<n>` viene riutilizzato alla prossima emissione;
- i documenti ricompaiono nell'elenco da emettere.

Errori possibili: *"Si può annullare solo l'ultimo transmittal."*, *"Non si può annullare: una o più revisioni sono già state ricevute."*, *"Questo transmittal non può essere annullato (nessuna revisione collegata)."*

### 9.7 Il PDF del trasmittal

Il PDF (sia con **Stampa** sia con **Emetti e scarica**) contiene:

- il logo B&R; a sinistra la riga **"<Stabilimento>, 10 jan 2026"**, **Our Ref.** (dal riquadro opzioni), **Your Ref.** (il PO della commessa), **Subject: DOCUMENTS**; a destra il riquadro del destinatario con **Messr's** (Att.ne), **Address** (destinatario e indirizzo), città, paese, **Ph. No.**. Nel PDF compare **un solo indirizzo**, il primo tra quelli selezionati;
- la frase *"Please find herewith the following documents"* e le quattro caselle della modalità di spedizione, con una X su quella scelta (e il nome, per Brevi manu);
- la tabella dei documenti, in ordine di Item: **ITEM**, le colonne codice scelte (**CLIENT DOC.**, **VENDOR DOC.**, **CONTRACTOR DOC.**), **REV.** (secondo la modalità dell'archivio), **DOCUMENT** (titolo) e **REQUIRED BY**, cioè la data del trasmittal più i giorni concessi al cliente (**Revisione cliente** in Informazioni archivio). Una colonna vuota per tutti i documenti viene omessa; senza giorni configurati REQUIRED BY non compare;
- l'intestazione **Note** con spazio bianco per annotazioni a mano;
- in fondo la chiusura *"Best Regards / Brembana&Rolle S.p.A. / <Nome Cognome> - <Ruolo>"*, con nome e ruolo presi dal profilo di chi emette (vedi **2.4 Profilo utente**).

### 9.8 Esportare l'elenco da emettere

Il menu **Esporta** offre **Excel** (*senza header*) e **PDF** (*con header Document Status*), disponibili a tutti. Contengono tutti i documenti da emettere della commessa, ordinati per data prevista, con le date scadute in rosso; i filtri e la selezione a schermo non vengono applicati. File: `<job>_to_be_issued_<gg_mm_aaaa>.xlsx` oppure `.pdf`, colonne Item, B&R Doc, Rev., Client Doc N°, Contractor Doc N°, Client Doc Class, Title, Planned date.

---

## 10. Gestione ricezione

URL: `/commesse/<job>/ricezione/`

Questa sezione registra le risposte del cliente sui documenti già inviati. Tutti possono consultarla, compilarla ed esportarla; **Registra ricezioni** richiede il permesso **Scrittura**.

### 10.1 Quali documenti compaiono

Solo i documenti la cui revisione corrente è in stato **Inviato al Cliente** (in attesa di risposta). Colonne: **B&R Doc**, **Rev.**, **Title**, **Issued** (data di invio effettiva), **Planned return date** (data di ricezione prevista), **Client response**, **Return date**, **New rev.**

I documenti sono ordinati per data di ricezione prevista: quelli con data scaduta hanno la riga **rossa**, quelli in scadenza entro 7 giorni (oggi compreso) la riga **ambra**. Se non c'è nulla: *"Nessun documento in attesa di risposta"*. Le prime cinque colonne si ordinano e si filtrano come descritto in **9.2 Filtri e ordinamento delle colonne**.

### 10.2 Compilare le righe

Per ogni documento da registrare:

1. **Client response** — scegli la risposta del cliente dal menu *"— Seleziona —"* (es. Approved, Commented…). È facoltativa: una riga con la sola data viene registrata senza risposta. L'elenco delle risposte è configurato da un amministratore.
2. **Return date** — scrivi la data nel formato `gg/mm/aaaa` oppure `10 jan 2026`, o usa il **calendario** (icona accanto al campo; mesi in italiano, settimana da lunedì, oggi evidenziato). È l'**unico campo obbligatorio**: una data non riconosciuta viene azzerata.
3. **New rev.** — interruttore che indica se creare automaticamente la revisione successiva. È **acceso di default**; quando scegli una risposta si allinea da solo all'impostazione di quella risposta (*Crea nuova revisione*), e puoi comunque cambiarlo a mano.

Il contatore in alto dice *"N di T documenti compilati"* (le righe con una data valida). I valori inseriti restano anche cambiando filtri o ordinamento, ma **non** sopravvivono a un ricaricamento della pagina.

### 10.3 Registrare le ricezioni

1. Compila almeno una riga con la data (altrimenti: *"Inserisci almeno una data di rientro."*).
2. Clicca **Registra ricezioni**.
3. Nel riquadro **Registra ricezioni** (*"N documenti verranno registrati"*) clicca **Conferma**.

**Cosa succede automaticamente:**

- Sulla revisione corrente di ogni riga compilata:
  - `Data ricezione effettiva` = data inserita
  - `Risposta cliente` = risposta selezionata (può restare vuota)
  - `Stato interno` = **Ricevuto**
- Se l'interruttore **New rev.** è acceso:
  - viene creata una nuova revisione con numero incrementato, vuota e pronta per l'emissione
  - `Data invio prevista` = data ricezione + giorni revisione interna B&R (vuota se i giorni non sono impostati)

Compare *"✓ N documenti registrati"*, l'elenco si ricarica e la bozza viene azzerata. La registrazione è **tutto o niente**: se una riga non è valida (es. risposta inesistente, data malformata) non viene salvato nulla. Una riga la cui revisione nel frattempo non è più "inviata al cliente" viene ignorata.

Se una revisione con risposta non ha generato la revisione successiva e serve crearla dopo, usa **Sblocca revisione** nella Situazione documenti (vedi **11.7 Sblocca revisione**).

### 10.4 Esportare l'elenco in attesa

Il menu **Esporta** offre **Excel** e **PDF** (*con header Document Status*), disponibili a tutti: tutti i documenti in attesa di risposta, ordinati per data di ricezione prevista (scadute in rosso), senza applicare i filtri a schermo. File: `<job>_to_be_received_<gg_mm_aaaa>.xlsx` oppure `.pdf`, colonne Item, B&R Doc, Rev., Client Doc N°, Contractor Doc N°, Client Doc Class, Title, Emission date, Planned return date.

---

## 11. Situazione documenti

URL: `/commesse/<job>/situazione/`

Vista tabellare completa dello stato di tutti i documenti e revisioni. Tutti possono consultarla, filtrarla ed esportarla e aprire i file; **Sblocca revisione**, **Risolvi**/**Ignora** delle anomalie e **Salva collegamento** richiedono il permesso **Scrittura**.

### 11.1 Tipi di visualizzazione

| Vista | Descrizione |
|-------|-------------|
| **Orizzontale** (default) | Una riga per documento, con un gruppo di colonne per ogni revisione |
| **Verticale** | Una riga per ogni combinazione documento × revisione, con tutte le colonne di stato |

Usa i pulsanti **Verticale** / **Orizzontale** a destra nella barra. Cambiando vista si azzerano ordinamento, filtri e l'interruttore *Mostra solo ultima revisione*.

### 11.2 Vista orizzontale

Colonne fisse (restano visibili scorrendo): **Client Doc N°**, **Client Doc Class**, **Contractor Doc N°**, **B&R Doc**, **Title**, **Item**. Poi il gruppo **Planning** con **Submission date** e **Receipt date**, riferite all'ultima revisione: se è *Inviato al Cliente* compare solo la data di ricezione prevista, se è ancora da inviare solo la data di invio prevista, se è *Ricevuto* (o approvata) nessuna delle due. Infine un gruppo **Rev. <etichetta>** per ogni revisione con **Dispatch** (invio effettivo), **Received** (ricezione effettiva) e **Status** (lettera della risposta del cliente, es. `A`). Il numero di gruppi segue i documenti visibili.

**Colore della colonna B&R Doc.** La cella dice da sola come sta il documento:

| Colore | Significato |
|--------|-------------|
| Giallo *Inviato al Cliente* | L'ultima revisione è partita e la risposta manca ancora |
| Colore della risposta | L'ultima risposta arrivata, anche se sta su una revisione precedente |
| Grigio *Da inviare* | Documento mai inviato e su cui il cliente non si è mai espresso |
| Nessun colore | Documento senza revisioni |

Le celle **Status** riportano solo la lettera, senza colore. Passando il mouse su B&R Doc, Status o Received compare il nome completo della risposta. La **legenda** sotto la tabella elenca le risposte effettivamente presenti con lettera e colore, più *Inviato al Cliente* e *Da inviare*.

In questa vista si ordina su ogni colonna fissa, sulle colonne Planning e su ogni sottocolonna di revisione; i filtri di colonna sono sulle sei colonne fisse (elenco valori) e sulle due colonne Planning (intervallo di date).

### 11.3 Vista verticale

Colonne: **Item**, **B&R Doc**, **Client Doc N°**, **Contractor Doc N°**, **Client Doc Class**, **Title**, **Department** (acronimo del reparto), **Penalty**, **Payment**, **Rev.**, **Planned send**, **Actual send**, **Planned receipt**, **Actual receipt**, **Internal status**, **Client response**. Un documento senza revisioni ha una riga con i campi di revisione a *—*.

- **Internal status** è un badge colorato: *Da inviare* (stato vuoto), *Da iniziare*, *In lavorazione*, *In revisione*, *In approvazione*, *Da emettere*, *Inviato al cliente*, *Ricevuto*.
- **Client response** è un badge con il colore della risposta; il testo è bianco o nero, quello che si legge meglio. La riga di una revisione con risposta ha il bordo sinistro del colore della risposta e lo sfondo leggermente tinto.
- Si ordina cliccando ogni intestazione tranne Penalty e Payment; i filtri sono a elenco valori per le colonne di testo e *Client response*, a scelta singola per Penalty, Payment e Internal status, a intervallo di date per le quattro colonne data.

**Stato interno dedotto.** Se una revisione non ha lo stato interno salvato, lo stato si ricava dai fatti registrati: risposta del cliente o data di ricezione effettiva → *Ricevuto*; data di invio effettiva → *Inviato al cliente*; altrimenti *Da inviare*. La stessa regola vale per i colori della vista orizzontale, per gli export e per gli elenchi di Emissione e Ricezione.

### 11.4 Filtri della barra

Oltre ai filtri di colonna (vedi **9.2 Filtri e ordinamento delle colonne**), la barra in alto offre un controllo per vista:

- **Orizzontale → Filtra per risposta del cliente**: spunte multiple sullo *stato dell'ultima revisione* (le risposte del cliente presenti, più *Inviato al Cliente* e *Da inviare*, ognuna con il quadratino del colore della colonna B&R Doc). Serve a includere o escludere in un colpo solo i documenti in attesa di risposta o mai inviati.
- **Verticale → Mostra solo ultima revisione**: riduce la tabella a una riga per documento. Per la risposta del cliente resta il filtro sulla colonna *Client response*, che guarda la singola revisione.

Con un filtro attivo la barra mostra *"N di T righe"* e **Azzera filtri**; se non resta nulla: *"Nessun risultato per i filtri selezionati"*.

### 11.5 Schermo intero

Clicca l'icona **Schermo intero** per espandere la tabella a tutto lo schermo. Clicca di nuovo (o premi Esc) per uscire.

### 11.6 Apertura file

- **Vista verticale:** clicca una riga (che abbia una revisione).
- **Vista orizzontale:** clicca la cella **Received** (se ha una data) o la cella **Status** di una revisione.

Vale la stessa logica di **8.2 Apertura automatica dei file**, compresi i riquadri **Scegli il file da aprire** e **Collega un file alla revisione** (vedi **8.3 Collegamento manuale di un file**).

### 11.7 Sblocca revisione

Una revisione che ha già la risposta del cliente ma non ha una revisione successiva è "bloccata": non compare né in Emissione né in Ricezione. Il pulsante **Sblocca revisione (N)** nella barra elenca queste revisioni (**Document**, **Revision**, **Client response**, **Return**); se non ce ne sono: *"Nessuna revisione da sbloccare."*

Per crearne la successiva (**permessi: Scrittura**):

1. Clicca **Sblocca** sulla riga.
2. Nel riquadro di conferma (*"Verrà creata la revisione successiva, vuota e pronta per l'emissione."*) indica, se vuoi, la **Data emissione (opzionale)**, cioè la data di invio prevista della nuova revisione.
3. Clicca **Sblocca**.

La nuova revisione compare in **Gestisci emissione**. Si può sbloccare solo l'ultima revisione del documento e solo se ha una risposta del cliente.

### 11.8 Esportazione Excel e PDF

1. Clicca **Esporta**.
2. Scegli il formato:
   - **Excel** (senza header): `situazione_documenti_<vista>_<job>.xlsx` con la vista corrente.
   - **PDF** (con header Document Status): `<job>_document_status_<data>.pdf` con la vista corrente.

Con un **filtro attivo** (di colonna, *Filtra per risposta del cliente* o *Mostra solo ultima revisione*) l'export contiene solo i documenti rimasti a schermo e, in verticale, solo le revisioni mostrate.

L'Excel della vista orizzontale riproduce la tabella a schermo: colonne fisse, gruppo **Planning** e un gruppo per ogni revisione (Dispatch, Received, Status); solo la colonna **B&R Doc** è colorata, con la stessa regola dello schermo. L'Excel della vista verticale ha una riga per ogni revisione, senza colori, con i gruppi **Planning** (Submission date, Receipt date) e **Actual** (Dispatch, Received).

Il PDF ha l'intestazione **Document Status** con la legenda **STATUS** costruita sulle risposte del cliente configurate a sistema: lettera, nome e colore del quadratino (al massimo dieci righe; senza risposte configurate viene usata la legenda storica delle otto risposte standard). Nel PDF orizzontale è colorata la cella B&R Doc; nel PDF verticale ogni riga è tinta con il colore della risposta.

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
| Flag **Può scrivere sul trasmittal interno** sul tuo utente | Lo assegna un amministratore. È indipendente dal permesso generale di scrittura (vedi **1.2 Permessi degli utenti**): chi non lo ha vede storico, Destinazioni e Nuova lettera ma non può modificare destinazioni, emettere, annullare o ritentare un passo |
| **Stabilimenti** con sigla, codice sito Business Central e indirizzi email | Sono configurati da un amministratore: per ogni sito gli indirizzi **A (TO)** / **CC** e gli indirizzi sempre in copia. Se un sito non compare tra i siti coinvolti o manca un indirizzo, chiedi a un amministratore |
| **Persone commessa** (PM, PE, QCI) | Si inseriscono alla creazione della commessa (vedi **4.3 Creare una nuova commessa**); per cambiarle dopo serve un amministratore. Servono per i destinatari automatici dell'email: se mancano, il pannello *A chi va* lo segnala |
| **Firmatari stabilimento** | Chi firma per Produzione e Qualità di ogni sito è registrato da un amministratore (vedi **12.8 Il PDF della lettera**) |

### 12.2 La schermata

La pagina mostra lo **storico delle lettere emesse** per la commessa (*"N lettere"*), le più recenti in cima; se non ce ne sono: *"Nessuna lettera emessa per questa commessa."* Ogni lettera ha un nome del tipo `<job>_<aaaa-mm-gg>_E<n>` (es. `25056_2026-10-21_E1`): il progressivo `E<n>` riparte da 1 ogni giorno per ogni commessa.

Per ogni lettera:

- la **data** è un link che apre il PDF salvato sul fileserver. Se il PDF non è più nella cartella, la data è grigia con l'indicazione *"PDF non trovato sul fileserver"*;
- il pulsante **Annulla** compare solo sull'ultima lettera emessa in quel giorno e solo per chi ha il flag (vedi **12.9 Annullare una lettera**).

In alto a destra ci sono i due pulsanti **Destinazioni** e **Nuova Lettera**. L'icona informativa accanto al titolo spiega come compaiono le firme nel PDF.

Senza il flag di scrittura, nei riquadri Destinazioni e Nuova lettera le caselle sono disabilitate e ogni tentativo di modifica mostra *"Permesso negato: solo alcuni utenti possono modificare il trasmittal interno."* La scritta *"Sola lettura: non hai i permessi…"* che può comparire in quei riquadri si riferisce al permesso generale di scrittura: per il trasmittal interno conta comunque solo il flag.

### 12.3 Destinazioni (siti coinvolti)

**Destinazioni** apre l'elenco di tutti i documenti UT della commessa con i siti a cui va la copia cartacea di ciascuno. Sono le destinazioni che la lettera riporta nella colonna *INVOLVED SITES* e che decidono quali stabilimenti ricevono l'email.

Colonne: **Documento**, **Titolo**, **Ultima modifica** (data del file in `PROGETTO\UT`, in grigio) e **Siti coinvolti**. Si ordinano cliccando l'intestazione e si filtrano con l'imbuto, come in Gestisci emissione (vedi **9.2 Filtri e ordinamento delle colonne**). Di default i documenti modificati più di recente sono in cima, quelli senza file in coda.

Per impostare i siti (**permessi: flag trasmittal interno**):

- **Un documento alla volta:** clicca la cella **Siti coinvolti** del documento e spunta gli stabilimenti nel menu a tendina. Il salvataggio è immediato (*"✓ Salvato"*).
- **Più documenti insieme:** spunta i documenti (cliccando la riga o la casella; la casella nell'intestazione seleziona tutti), scegli lo stabilimento in *Assegna sito ai documenti selezionati* (`<sigla> — <nome>`) e clicca **Aggiungi** oppure **Rimuovi**. Con un filtro attivo, la casella dell'intestazione seleziona solo i documenti visibili.

Le destinazioni dei documenti che non ne hanno ancora nessuna vengono **precompilate automaticamente** ogni giorno, insieme al controllo con Business Central, dal vecchio file `<job>-RecipientsData.txt` sul fileserver, se esiste. Una destinazione impostata (a mano o dall'import) non viene più toccata dall'import.

### 12.4 Nuova lettera: scegliere i documenti

**Nuova Lettera** apre l'elenco dei documenti UT con le stesse colonne, ordinamenti e filtri di **Destinazioni**, più la casella **Cerca documento…** (su B&R Doc e titolo). Il caricamento può richiedere qualche secondo perché l'applicazione verifica i file sul fileserver. Anche da qui si può modificare la cella **Siti coinvolti** di un documento prima di emettere.

Un documento si può selezionare solo se:

1. ha almeno una revisione registrata;
2. la sua **ultima revisione è ancora da emettere** al cliente, cioè lo stato interno non è né *Inviato al Cliente* né *Ricevuto* (lo stesso criterio di Gestisci emissione);
3. nella cartella `PROGETTO\UT` c'è **un solo file** che corrisponde al B&R Doc (un codice contenuto in un altro, es. `ESH1` ed `ESH10`, viene risolto dalla corrispondenza esatta).

Gli altri documenti compaiono in grigio con il motivo (*"Nessuna revisione registrata"*, *"Rev 1 già inviata al cliente"*, *"Rev 1 già ricevuta dal cliente"*, *"Nessun file trovato sul fileserver"*, *"Più file corrispondenti sul fileserver"*) e non si possono spuntare.

Spunta i documenti (cliccando la riga o la casella; il contatore dice *"N selezionati"*) e clicca **Emetti trasmittal interno** per passare alla compilazione. **Chiudi** abbandona.

### 12.5 Cosa stai trasmettendo: compilare la lettera

Il pannello **Cosa stai trasmettendo** mostra in alto le sigle dei siti coinvolti (*"Nessun sito coinvolto"* se mancano) e una riga per ogni documento scelto:

| Colonna | Cosa indica |
|---------|-------------|
| **Documento** | B&R Doc e titolo |
| **Revisione** | Revisione trasmessa. Lo stepper ± sceglie solo tra le revisioni ammesse del documento: oggi è l'ultima, quindi un solo valore |
| **Siti** | Siti coinvolti della riga (*"Nessuno"* se vuoti). Si possono modificare qui, cliccando la cella: il cambio aggiorna anche le destinazioni del documento e le sigle in alto |
| **Copie** | Numero di copie cartacee, proposto a **1**; lascialo vuoto (o 0) se non servono copie |
| **Cliente** | Spuntato (default): il documento va al cliente e il suo PDF viene copiato nella cartella DCC. Deselezionalo per un documento solo interno |
| **TPI** | Spunta se il documento va a un ispettore terzo e scrivi a chi (suggerimenti: `No.Bo.`, `AI`). Con TPI spuntato il destinatario è obbligatorio: altrimenti al passo successivo compare *"<B&R Doc>: specificare il destinatario TPI."* |
| **Nota** | Richiama una o più delle note libere della lettera (*"Nessuna nota"* se nessuna): nel PDF la riga riporta il numero della nota |

Sotto la tabella, le **Note libere della lettera** (si aggiungono con **+ Aggiungi nota**, si tolgono con **Rimuovi**) finiscono nella sezione *NOTES* del PDF. Il modulo ha **tre** righe NOTES: le prime tre note non vuote vengono stampate, le altre ignorate. Compila le note in ordine senza lasciare righe vuote in mezzo, così il numero richiamato nella colonna **Nota** coincide con quello stampato nel PDF.

Clicca **Emetti** per passare ai destinatari, **Annulla** per tornare all'elenco.

### 12.6 A chi va: destinatari e invio

Il pannello **A chi va** riepiloga cosa succederà all'invio (nome previsto della lettera, percorso del PDF, cartella DCC oppure l'avviso *"Nessun documento è marcato "Cliente": non viene preparata nessuna cartella DCC."*, casella email di partenza) e propone i destinatari calcolati automaticamente, divisi in **A (TO)** e **CC** e raggruppati per origine:

| Gruppo | Chi | Colonna |
|--------|-----|---------|
| **Stabilimenti** | Indirizzi A/CC dei siti coinvolti (tra parentesi la sigla del sito) | TO o CC come da anagrafica |
| **PM** | Project manager della commessa | TO |
| **PE** / **QCI** | Project engineer e ispettore qualità della commessa | CC |
| **Export** | `export@brembanarolle.com`, solo se nella lettera c'è almeno un documento SHn (B&R Doc del tipo `xxxxx-xx-ESH…`) | CC |
| **Manuale** | Indirizzi aggiunti a mano e gli indirizzi "sempre in copia" configurati per i siti coinvolti | dove sono inseriti |

Se sulla commessa manca una persona per un ruolo (PM, PE o QCI), un avviso lo segnala (*"Ruoli non valorizzati sulla commessa: PM, PE — nessun destinatario verrà aggiunto per questi ruoli."*). Il ruolo WE non ha una lista di distribuzione e non genera destinatari. Un indirizzo presente sia in A sia in CC viene tenuto solo in A.

Prima di inviare puoi:

- togliere un destinatario con la **×** sulla sua etichetta;
- aggiungerne uno scrivendolo nel campo **Aggiungi email…** della colonna giusta e premendo **+** o **Invio**. Mentre scrivi compaiono gli indirizzi già noti all'applicazione (utenti attivi, indirizzi degli stabilimenti, destinatari delle lettere precedenti). Un indirizzo già presente nella stessa colonna non viene duplicato;
- scrivere un **Messaggio nell'email** (facoltativo, massimo 2000 caratteri): compare nell'email sopra la tabella dei documenti, non nel PDF;
- aprire in una nuova scheda un'**Anteprima PDF** della lettera così com'è: non crea nulla e non occupa un progressivo.

Serve almeno un destinatario in **A (TO)** (*"Serve almeno un destinatario in TO."*). Clicca **Invia a N destinatari** per emettere la lettera; **Annulla** torna a *Cosa stai trasmettendo*.

### 12.7 Cosa succede all'invio

L'emissione è una sequenza di passi. Il primo è l'unico che può bloccare tutto: se la selezione o un destinatario non sono validi, non viene creata nessuna lettera. Gli altri sono indipendenti: un passo che fallisce non annulla la lettera e non blocca i successivi.

| Passo (etichetta a schermo) | Cosa fa |
|-----------------------------|---------|
| **Trasmittal creato e archiviato** | Crea la lettera con il progressivo del giorno, le righe e i destinatari. I siti di ogni riga sono una fotografia delle destinazioni in quel momento: cambiarle dopo non modifica la lettera |
| **PDF salvato sul fileserver** | Salva il PDF in `Z:\JOBS\<job>\Progetto\UT\Transmittal\<nome>.pdf` |
| **Cartella DCC preparata** | Copia il PDF di ogni documento con **Cliente** spuntato nella cartella `Z:\JOBS\<job>\PROGETTO\DCC\DA SPEDIRE\<nome>` (*"N file copiati, M mancanti."*). Un documento di cui non si trova il file viene segnalato come mancante, gli altri vengono copiati comunque. Senza documenti per il cliente la cartella non viene creata |
| **Email inviata** | Invia l'email ai destinatari confermati (*"Da: … — A: … — CC: …"*) |

Al termine il pannello **Lettera <nome>** mostra l'esito di ogni passo con ✓ o ✗. Su un passo fallito compare **Riprova**, che ripete solo quel passo (ad esempio il PDF se lo storage delle firme non rispondeva, o l'email se il server di posta era fermo). **Fatto** chiude il pannello e aggiorna lo storico.

L'email:

- parte dalla **casella dell'applicazione**; chi ha emesso la lettera è scritto nella prima riga del testo (*"Trasmittal interno <nome> — commessa <job> — emesso da Nome Cognome (email)."*), è in copia e riceve le risposte. Vale anche se **Riprova** sull'email lo preme un'altra persona;
- ha come oggetto `DOCUMENT TRANSMITTAL [Form MQ 7.5-04 Rev.0]: <nome lettera>`;
- riporta nel corpo il messaggio facoltativo, la tabella dei documenti con le stesse colonne del PDF e, in fondo, *"Salvato in: <percorso>"*. Il PDF **non è allegato**: si apre dal percorso indicato.

### 12.8 Il PDF della lettera

Il PDF riproduce il modulo **MQ 7.5-04**, dall'alto in basso:

1. **Intestazione** con logo, titolo *DOCUMENT TRANSMITTAL SHEET* con il nome della lettera e *JOB No.* con il numero di commessa.
2. **Tabella dei documenti**: *B&R DOC. No.*, *REV.*, *INVOLVED SITES (a)* (sigle unite da `-`), *No. OF COPIES*, *CLIENT (b)* (`YES`/`NO`), *TPI (b)(c)* (il destinatario indicato, oppure `NO`), *NOTES* (numero della nota).
3. **REMARKS LEGENDA**: la legenda delle sigle dei siti (a), il significato di CLIENT/TPI (b) e dei destinatari TPI (c).
4. **NOTES**: le note libere della lettera, numerate (al massimo tre).
5. **PAPER COPIES DISTRIBUTION**: una riga **PRODUCTION** e una **QUALITY** con firma e data. La data è il giorno lavorativo successivo all'emissione (il venerdì diventa lunedì): è il termine entro cui distribuire le copie cartacee, non la data della firma.
6. I riferimenti fissi del modulo (*B&R Form: MQ 7.5-04 · Rif.: PQHSE 7.5-01 · Rev.0*).

La revisione è scritta come indicato in **6.3 Revisioni** al momento dell'emissione; una lettera già emessa non cambia se la scelta cambia dopo.

**Firme di Produzione e Qualità.** Per ogni sito coinvolto, la firma compare in automatico solo se valgono entrambe le condizioni:

1. la persona ha caricato la propria firma nella pagina **Profilo** (vedi **2.4 Profilo utente**);
2. è registrata da un amministratore come **Firmatario stabilimento** per quel sito e quel ruolo.

Chi è firmatario ma non ha caricato la firma ha nel PDF un riquadro vuoto da firmare a mano. Se per un ruolo non c'è nessun firmatario, per quel ruolo non compare nulla; lo stesso firmatario compare una volta sola anche se firma per più siti. Se lo storage delle firme non risponde, il passo PDF fallisce e va ripetuto con **Riprova**: la lettera non viene emessa senza firme.

### 12.9 Annullare una lettera

**Annulla** è disponibile solo sull'**ultima lettera emessa in quel giorno** per la commessa, così il progressivo liberato è davvero l'ultimo, e solo per chi ha il flag. Dopo la conferma (*"Annullare la lettera <nome>? Il PDF e la cartella preparata per il DCC verranno rimossi. Se era già stata inviata via email, quell'invio resta valido…"*):

- la lettera e le sue righe vengono eliminate dall'archivio;
- il PDF viene rimosso dal fileserver;
- i file copiati nella cartella DCC vengono rimossi, e la cartella viene eliminata se resta vuota;
- l'email, se era già partita, **non può essere richiamata**: avvisa tu i destinatari.

Una lettera che non è più l'ultima del suo giorno non si può annullare dall'applicazione: chiedi a un amministratore.

---

## 13. Scarica dati grezzi

URL: `/scarica/`, dalla voce **Scarica** della barra di navigazione. Disponibile a tutti gli utenti.

La pagina permette di esportare in Excel i dati di una commessa così come sono salvati sul database, senza elaborazioni né formattazioni.

**Come si usa:**

1. Nel campo **Commessa** digita job o cliente (*"Cerca per job o cliente…"*) e scegli la commessa dai risultati (al massimo 8; usa **Cambia** per sceglierne un'altra).
2. Spunta le **tabelle** da esportare, oppure usa **Seleziona tutte**.
3. Clicca **Scarica**: compare *"Preparazione del file…"* e poi *"File scaricato."*; il browser scarica `{job}_dati_grezzi_{gg_mm_aaaa}.xlsx` (gli spazi nel job diventano `_`).

Il pulsante **Scarica** resta disabilitato finché non hai scelto sia la commessa sia almeno una tabella.

Il file contiene **un foglio per ogni tabella selezionata**, sempre in quest'ordine; la prima riga riporta in grassetto i **nomi delle colonne del database** (non le etichette usate nelle schermate), le righe successive i dati grezzi. Una tabella vuota produce un foglio con la sola intestazione.

| Tabella | Contenuto |
|---------|-----------|
| **Commessa** | La riga di testata della commessa (job, cliente, PO, descrizione, date, tempi di revisione, modalità revisioni, sito costruttivo) |
| **Indirizzi spedizione** | Gli indirizzi di spedizione collegati |
| **Documenti** | Tutti i documenti della commessa |
| **Revisioni** | Tutte le revisioni dei documenti della commessa |

Il foglio **Revisioni** riporta, prima dei dati della revisione, gli identificativi del documento a cui appartiene (`client_doc_no`, `client_doc_class`, `contractor_doc_no`, `vendor_doc` cioè il B&R Doc, `item_no`), poi numero e lettera, le quattro date, lo stato interno, la **lettera** della risposta del cliente (`ext_status`, es. `A`) e il flag *crea nuova revisione*. Le date sono vere date di Excel nel formato `gg/mm/aaaa` (con l'ora, se presente), quindi si ordinano e si filtrano come date; i valori sì/no compaiono come `TRUE`/`FALSE`.

---

## 14. Proposte e segnalazioni

URL: `/segnalazioni/`. Si raggiunge dal link *"Qualcosa da segnalare? proponila qui"* in fondo alla Home oppure cliccando una notifica (vedi **3.5 Notifiche**). Tutti gli utenti, anche con permesso Lettura, possono pubblicare, votare e commentare.

È il forum interno in cui si propongono **nuove funzionalità** dell'applicazione e si segnalano **problemi**. Come dice il sottotitolo della pagina, le proposte che raggiungono almeno **10 voti positivi** vengono prese in carico per l'implementazione, per favorire il confronto tra gli stabilimenti e trovare soluzioni condivise. I voti sono **anonimi**.

### 14.1 Pubblicare un post

1. Clicca **Nuova proposta** nella colonna di destra.
2. Scegli il **Tipo**: **Feature** (nuova funzionalità, default) o **Problema**.
3. Scrivi il **Titolo** (*"In sintesi…"*, obbligatorio, massimo 200 caratteri) e la **Descrizione** (*"Descrivi l'idea o il problema."*, obbligatoria, massimo 8000 caratteri).
4. Clicca **Pubblica**.

Il post compare in cima all'elenco con la tua foto (o iniziale), il nome, la data e la pillola del tipo. Tutti gli altri utenti ricevono una notifica. Un post pubblicato non si può modificare né eliminare.

### 14.2 Leggere, votare e commentare

- Ogni card mostra le prime due righe del testo: clicca la card (o il pulsante *"N commenti"*) per espanderla e aprire il thread dei commenti; clicca di nuovo per richiuderla.
- **Pollice in su** / **Pollice in giù**: un voto per utente e per post. Clicca lo stesso pollice per togliere il voto, l'altro per cambiarlo. Accanto ai pollici ci sono i conteggi e il punteggio (positivi meno negativi). Nessuno vede chi ha votato.
- **Commentare**: nel thread scrivi nel campo *"Scrivi un commento…"* (massimo 2000 caratteri) e clicca **Invia**. I commenti sono in ordine cronologico con autore e data; oltre tre commenti vengono mostrati solo gli ultimi due, con il link *"Mostra tutti i N commenti"* / *"Comprimi commenti"*. Chi ha aperto il post e chi lo ha già commentato riceve una notifica.

### 14.3 Filtri

Nella colonna di destra, un filtro alla volta:

| Filtro | Cosa mostra |
|--------|-------------|
| **Tutti i post** | Tutti i post aperti, dal più recente |
| **I miei post** | I tuoi post aperti |
| **Top 10 per voti** | I dieci post aperti con il punteggio più alto |
| **Nuove funzionalità** | I post aperti di tipo Feature |
| **Segnalazioni** | I post aperti di tipo Problema |
| **Post chiusi** | Solo i post chiusi, di chiunque |

I post chiusi non compaiono in nessun altro filtro. Se non c'è nulla: *"Nessuna proposta in questa vista. Sii il primo a segnalare qualcosa."*

### 14.4 Post chiusi

Quando una proposta è stata realizzata o un problema risolto, un amministratore chiude il post: la card diventa attenuata, mostra il badge **Risolto** e *"chiuso da <Nome>"*, e il thread riporta *"Thread chiuso"*: non si possono aggiungere commenti, mentre i voti restano possibili. Solo gli amministratori vedono i pulsanti per chiudere o riaprire un post.

---

## 15. Flusso di lavoro completo

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
│ Stato: Da inviare       │
│ Imposta data invio      │
│ prevista (Rev. 0)       │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ (UT) TRASMITTAL INTERNO │
│ → copie agli stabilim.  │
│ → PDF pronti per il DCC │
│ (lo stato non cambia)   │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ EMISSIONE               │
│ → Stato: Inviato al     │
│   Cliente               │
│ → Calcola data ric.     │
│   prevista              │
│ → PDF trasmittal        │
│   archiviato            │
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

Un esempio del ciclo descritto nel capitolo **15. Flusso di lavoro completo**:

1. Crei la commessa `25056` con cliente "ACME Corp".
2. In archivio imposti: 14 giorni revisione cliente, 7 giorni revisione interna.
3. Aggiungi il documento `25056-QMDBI` con data invio prevista 15/06/2026.
4. Il 15/06 emetti il documento → stato *Inviato al Cliente*, ricezione prevista 29/06, PDF `Transmittal 25056-1.pdf` archiviato.
5. Il 25/06 registri ricezione con stato *Commented* e nuova revisione → stato *Ricevuto*, creata Rev. 1 con invio previsto 02/07.
6. Il 02/07 emetti la Rev. 1 → ciclo continua.

---

## 16. Glossario

Questo capitolo raccoglie il significato degli stati interni e dei campi di documenti e revisioni.

### Stati interni

| Etichetta | Significato |
|-----------|-------------|
| Da inviare | Stato vuoto: revisione mai inviata (è così che compare nelle schermate) |
| Da iniziare | Documento non ancora avviato |
| In lavorazione | In preparazione |
| In revisione | In revisione interna |
| In approvazione | In attesa approvazione interna |
| Da emettere | Pronto per l'invio |
| Inviato al Cliente | Emesso, in attesa risposta |
| Ricevuto | Risposta cliente registrata |

> Gli stati vengono impostati dall'applicazione tramite **Emissione** (*Inviato al Cliente*) e **Ricezione** (*Ricevuto*), oppure a mano nel riquadro delle anomalie (vedi **5.5 Revisioni da risolvere (anomalie)**). Se lo stato salvato manca, viene dedotto dalle date e dalla risposta registrate (vedi **11.3 Vista verticale**).

### Campi documento

| Campo | Descrizione |
|-------|-------------|
| **Item** | Numero progressivo nella lista documenti del cliente |
| **B&R Doc** | Numero documento interno Brembana&Rolle (nei file e negli export anche *Vendor Doc*) |
| **Client Doc N°** | Numero documento del cliente |
| **Contractor Doc N°** | Numero documento del contractor |
| **Client Doc Class** | Classe/categoria documento cliente |
| **Reparto** | Reparto responsabile; il suo acronimo è la cartella sul fileserver |
| **Penale** | Documento soggetto a penale contrattuale |
| **Pagamento** | Documento collegato a milestone di pagamento |
| **Rev. Generale** | Documento di revisione generale |
| **Note** | Note libere |

### Campi revisione

| Campo | Descrizione |
|-------|-------------|
| **Rev. No** | Numero revisione (0, 1, 2…) |
| **Rev. Let** | Lettera revisione (A, B, C…) |
| | Come si vede la revisione a schermo e nelle stampe dipende solo dalla sezione **6.3 Revisioni** in Informazioni archivio: numero, lettera o sequenza personalizzata; se il valore manca viene ricavato dall'altro |
| **Inv. previsto** (Planned send) | Data pianificata di invio al cliente |
| **Inv. effettivo** (Actual send / Dispatch) | Data effettiva di invio |
| **Ric. previsto** (Planned receipt) | Data entro cui ci si aspetta la risposta |
| **Ric. effettivo** (Actual receipt / Received) | Data effettiva di ricezione risposta |
| **Crea nuova revisione** | Se attivo, alla ricezione viene proposta la creazione della revisione successiva |

---

## 17. Scorciatoie da tastiera

| Scorciatoia | Dove | Azione |
|-------------|------|--------|
| **Ctrl+K** / **Cmd+K** | Ovunque | Apri ricerca commesse (Spotlight) |
| **Invio** | Spotlight | Apre la commessa se il testo è esattamente il suo codice |
| **Invio** | Modali e riquadri filtro | Conferma / applica |
| **Invio** o **,** | Ruoli commessa (Nuova commessa) | Aggiunge il nome digitato come testo libero |
| **Invio** | Workflow Agent | Invia il messaggio (**Maiusc+Invio** va a capo) |
| **Invio** | Destinatari del trasmittal interno | Aggiunge l'indirizzo scritto |
| **Esc** | Ovunque | Chiude modale, ricerca, notifiche, Workflow Agent, menu, schermo intero |

---

## 18. Domande frequenti

Questo capitolo risponde ai dubbi più comuni su permessi, emissione, ricezione, file e integrazioni.

### Perché cliccando un pulsante compare "Non hai i permessi per eseguire questa operazione"?

Il tuo utente ha il permesso **Lettura**: puoi consultare tutto ma non modificare. Per avere il permesso di scrittura rivolgiti a un amministratore (vedi **1.2 Permessi degli utenti**).

### Perché le card della commessa sono bloccate?

Finché non compili **entrambi** i campi giorni revisione in **Informazioni archivio → 6.1 Tempi di revisione**, l'archivio è considerato incompleto e tutte le sezioni tranne Informazioni archivio restano bloccate con *"Completa prima le informazioni archivio"*.

### Perché non vedo documenti in Emissione/Ricezione?

In **Emissione** compaiono solo i documenti la cui ultima revisione non è stata inviata né ricevuta; in **Ricezione** solo quelli in stato *Inviato al Cliente*. Una revisione che ha già la risposta del cliente e non ha una revisione successiva non compare in nessuna delle due: usa **Sblocca revisione** nella Situazione documenti (vedi **11.7 Sblocca revisione**).

### Perché non si apre il file di una revisione?

Possibili cause:
- La revisione non ha ancora una **data effettiva** di invio o di ricezione (solo date previste): l'app non cerca e apre il collegamento manuale
- Il documento non ha un **reparto** con acronimo, o non ha il B&R Doc
- Il file non esiste nella cartella prevista sul fileserver, o il suo nome non contiene il B&R Doc
- La share JOBS non è raggiungibile dal server, oppure (per Word ed Excel) non è mappata sul tuo PC con lo stesso percorso (es. `Z:`)

Soluzione: usa il **collegamento manuale** tramite il browser file (vedi **8.3 Collegamento manuale di un file**).

### Ho collegato il file sbagliato a una revisione

Un collegamento salvato ha sempre la precedenza e non si può cambiare dall'applicazione: chiedi a un amministratore di rimuoverlo.

### Ho emesso un trasmittal per errore

Apri **Storico Trasmittal** in Gestisci emissione e usa **Annulla** sull'ultimo trasmittal: le revisioni tornano da emettere e il PDF viene rimosso (vedi **9.6 Storico trasmittal**). Non è possibile se una delle revisioni è già stata ricevuta.

### Perché la card Trasmittal interno è bloccata?

Manca il **Sito costruttivo** della commessa. Impostalo in **Informazioni archivio** (vedi **6.1 Tempi di revisione**) e salva.

### Perché un documento è grigio in Nuova lettera del trasmittal interno?

Il motivo è scritto accanto al documento: non ha revisioni, la sua ultima revisione è già stata inviata al cliente o ricevuta, oppure in `PROGETTO\UT` non c'è esattamente un file con il suo B&R Doc. Vedi **12.4 Nuova lettera: scegliere i documenti**.

### Perché non posso modificare il trasmittal interno?

Serve il flag **Può scrivere sul trasmittal interno** sul tuo utente, che assegna un amministratore. È separato dal permesso generale di scrittura. Senza il flag vedi lo storico delle lettere, l'elenco Destinazioni e l'elenco Nuova lettera (con i motivi di esclusione), ma non puoi spuntare documenti, salvare destinazioni, emettere, annullare o ritentare un passo.

### Nel PDF del trasmittal interno mancano le firme

Per ogni sito coinvolto la firma compare solo se la persona ha caricato la firma nel proprio **Profilo** ed è registrata da un amministratore come **Firmatario stabilimento** per quel sito e quel ruolo (Produzione o Qualità). Vedi **12.8 Il PDF della lettera**.

### Posso modificare lo stato interno di una revisione?

Non dall'elenco documenti (sola lettura). Gli stati vengono aggiornati da Emissione e Ricezione; per correggere una revisione incoerente usa **Risolvi** nel riquadro delle anomalie (vedi **5.5 Revisioni da risolvere (anomalie)**). Per altre correzioni rivolgiti a un amministratore.

### Come cambio la password?

Dal profilo non è possibile: usa **Recuperala** nella pagina di login (vedi **2.3 Recuperare la password**).

### Come funziona l'integrazione ERP?

Quando crei una nuova commessa e digiti il Job, l'app interroga **Business Central** per recuperare automaticamente cliente, PO, descrizione e data consegna.

### I dati presi da Business Central restano aggiornati?

Sì: ogni giorno il sistema riconfronta cliente, PO, descrizione, data consegna e sito costruttivo delle commesse aperte con Business Central e le riallinea se in BC sono cambiate. Le modifiche applicate sono elencate in **Informazioni archivio → Aggiornamenti da Business Central**, dove il pulsante **Aggiorna da BC** lancia il confronto subito, anche su una commessa chiusa (vedi **6.4 Aggiornamenti da Business Central**). Un valore vuoto in BC non cancella mai quello inserito nel sistema.

### Come importo dati dal vecchio database Access?

Usa **Apri Commessa → Importa da Report** dalla Home (vedi **4.4 Importare una commessa dal vecchio sistema (Report/Access)**).

---

*Ultimo aggiornamento: ottobre 2026*
