# Changelog

## [Unreleased]

### Added

- Nuova sezione **Quality Control Plan** nella pagina di commessa, accanto a Informazioni archivio, Elenco documenti e le altre. La pagina elenca i piani della commessa come righe sottili con nome, item coperti, chi li ha preparati, la data e un anello di avanzamento con la percentuale al centro (per ora ferma a zero: la regola di completamento arriverà con gli step). Il pulsante **Crea QCP** apre un modulo con i sedici campi di testata, precompilati da Business Central dove il dato esiste (Project, Location, Owner, Purchaser, P.O. n.) e dal sistema per il resto (Job n., data odierna, chi sta compilando); Doc n., Sheet, Dwg n. e Serial n. restano da compilare a mano finché non avranno una regola di calcolo. Gli item si scelgono uno o più alla volta dalla distinta di fornitura dell'ERP, e la descrizione item segue il primo item scelto senza mai sovrascrivere quello che hai scritto. Se Business Central non risponde il modulo si apre lo stesso, avvisa quali campi mancano e lascia creare il piano a mano

### Fixed

- I dati commerciali letti da Business Central (PO cliente e data di consegna) tornano ad arrivare davvero: la query puntava a una tabella inesistente e falliva in silenzio, quindi quei due campi non sono mai stati precompilati alla creazione di una commessa né allineati dal controllo giornaliero

### Changed

- La revisione si legge sempre come dice l'archivio: con il flag **Revisioni con lettera** attivo esce ovunque la lettera (A, B, C…), con il flag spento esce ovunque il numero (0, 1, 2…). Vale per situazione documenti (viste orizzontale e verticale, comprese le intestazioni di colonna), elenco documenti, emissione, ricezione, sblocco e anomalie revisioni, per gli export Excel e PDF, per il trasmittal e per l'admin. Se il valore richiesto non è compilato viene ricavato dall'altro (0 ↔ A, 1 ↔ B, … 26 ↔ AA), quindi non compaiono più numeri al posto delle lettere sulle revisioni senza `RevLet`
- I colori della legenda STATUS nell'header del PDF di situazione documenti seguono le risposte del cliente configurate nell'admin: quadratino, lettera e descrizione arrivano dagli stati a sistema (colore mancante → default storico della lettera, lettera mancante → dedotta dal nome) invece di essere fissi nel codice. Vale sia per la vista orizzontale sia per quella verticale

## [0.1.4] - 2026-09-07

### Added

- Campanella delle notifiche in alto a destra: avvisa tutti gli utenti quando qualcuno propone una nuova feature o segnala un problema; le notifiche spariscono una volta visualizzate
- Controllo giornaliero di congruenza con Business Central: cliente, PO, descrizione e data consegna delle commesse aperte vengono riconfrontati con l'ERP e aggiornati se cambiati (un valore vuoto in BC non cancella mai un dato inserito nel sistema). Le modifiche applicate sono elencate in *Informazioni archivio* della commessa e nell'admin. Il controllo parte da solo ogni giorno alle 17:00 dall'applicazione stessa — nessuna attività pianificata da registrare sul server — e viene recuperato se il server era spento a quell'ora; data ed esito dell'ultima esecuzione sono nell'admin sotto *Esecuzioni schedulate*. Resta disponibile il comando `python manage.py sync_business_central` (opzioni `--job`, `--tutte`, `--dry-run`) per le esecuzioni manuali
- Nuova voce di menu **Scarica**: si cerca una commessa, si spuntano le tabelle desiderate (Commessa, Indirizzi spedizione, Documenti, Revisioni; con "Seleziona tutte") e si scarica un Excel con i dati grezzi, un foglio per tabella e il solo header in grassetto. Il foglio Revisioni riporta Client Doc N°, Client Doc Class, Contractor Doc N°, B&R Doc, Item e la lettera della risposta del cliente al posto degli id tecnici

### Changed

- Situazione documenti: le celle legate alla risposta del cliente usano il colore configurato sullo stato, pieno e uguale a quello della legenda, al posto della vecchia tinta sbiadita. Il testo diventa automaticamente bianco o nero — quello dei due che si legge meglio — così restano leggibili anche gli stati bianchi, gialli, neri o grigi. Nella vista orizzontale sono colorate la colonna B&R Doc e la cella Status di ogni revisione (con la lettera dello stato), nella vista verticale il badge Risposta cliente, con la riga evidenziata in modo più deciso di prima. La legenda ripete la stessa coppia colore/lettera delle celle e il PDF orizzontale usa gli stessi colori

### Fixed

- Le revisioni che hanno già la risposta del cliente non risultano più «Da inviare»: quando lo stato interno in archivio è vuoto viene dedotto dai fatti registrati (risposta del cliente o data di rientro → Ricevuto, data di invio → Inviato al cliente). Vale in situazione documenti, negli export Excel e PDF e negli elenchi di emissione e ricezione, dove queste revisioni non compaiono più come da emettere

## [0.1.3] - 2026-09-02

### Added

- Il numero del trasmittal viene precompilato in base all’ultimo documento in `Z:\JOBS\{commessa}\PROGETTO\DCC\TRANSMITTAL`
- È possibile visualizzare lo storico dei trasmittal per ciascuna commessa e visualizzare il file in anteprima
- È possibile annullare l’invio di un trasmittal in caso di errore

## [0.1.2] - 2026-08-31

### Added

- Forum per proposte di modifica e segnalazione di problemi: voti anonimi, commenti e chiusura da admin
- Campo Contractor Doc N° su documenti, import Excel, elenco, situazione ed export
- Commesse preferite pinnabili per utente
- Export Excel e PDF da emissione, ricezione e situazione documenti
- Header B&R aggiunto ad ogni export
- Filtri per colonna anche in emissione e ricezione, con calendario per intervallo di date
- Codice lettera dello stato cliente (es. A = Approved) visibile in situazione documenti
- Nel PDF di transmittal: selezione multipla degli ID documento (vendor / client / contractor), note e firma in corsivo di chi emette

### Fixed

- Le etichette di revisione (lettera o numero) rispettano il flag archivio della commessa
- Import da Access: le revisioni già spedite o ricevute non compaiono più come da emettere
- Layout del transmittal PDF: tabella e indirizzo restano nella pagina, colonne vuote omesse

## [0.1.1] - 2026-07-22

### Added

- È ora possibile definire la prima data di emissione di una revisione anche nell'Excel di import documenti
- Reset password possibile nel menu di accesso
- Aggiunti filtri in ciascuna colonna nella situazione documenti verticale e orizzontale
- Nella vista orizzontale, in situazione documenti, ora le celle con la data di ricezione effettiva delle revisioni sono colorate in base alla risposta del cliente

### Fixed

- Link incompleto nell'email di reset password (`http://host` senza percorso `/reset/...`)
- Evidenziazione di oggi nel calendario data ricezione (fuso orario locale invece di UTC)
- Tintature di stato (righe/celle situazione, badge sblocca) poco visibili in tema scuro
