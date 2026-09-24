# Changelog

## [Unreleased]

### Added

- Notifiche sui commenti: quando qualcuno commenta un thread di feature o problemi, ricevono la notifica nella campanella chi ha aperto il thread e chi lo ha già commentato (escluso chi scrive il commento). Il testo è del tipo *Anna Bianchi ha commentato «Titolo del thread»*; resta una sola notifica per thread, che torna da leggere ad ogni nuovo commento
- Barra di ricerca: digitando il codice completo di una commessa e premendo **Invio** si apre direttamente la pagina di quella commessa, senza dover cliccare il risultato. Se il codice non corrisponde esattamente a nessuna commessa vengono mostrati i risultati come prima
- Situazione documenti: anche la vista orizzontale, oltre alla verticale, ha l'export in Excel accanto a quello in PDF (pulsante **Esporta** → Excel / PDF). L'Excel riproduce la tabella a schermo: una riga per documento, colonne fisse, gruppo Planning (Submission date, Receipt date) e un gruppo per ogni revisione (Dispatch, Received, Status), con la colonna B&R Doc e le celle Status colorate come la risposta del cliente

### Changed

- Nuovi colori delle risposte del cliente: Approved e For Information verde `#4AF536`, i due Commented rosso `#E32400`, Final - As Built e Superseeded blu `#1649F0`, Old quasi nero `#131314`, Rejected nero `#000000`. Valgono ovunque — situazione documenti, legende, export Excel e PDF — e sono anche i colori di partenza delle risposte create dall'import
- *Final - As Built* e *For Information* non creano più in automatico una nuova revisione alla ricezione: con quelle risposte il documento chiude il giro
- Situazione documenti, vista orizzontale: a colorarsi è solo la colonna **B&R Doc**, che da sola dice come sta il documento; le celle Status delle singole revisioni riportano la lettera della risposta senza colore. Il colore è quello dell'ultimo stato dell'ultima revisione: il colore della risposta del cliente quando è arrivata, il giallo *Inviato al Cliente* quando il documento è partito e la risposta manca ancora, il grigio *Da inviare* finché la revisione non è partita. La legenda sotto la tabella elenca gli stati che le celle mostrano davvero, e la stessa regola vale per l'export Excel e per il PDF della vista orizzontale
- Nelle pagine della commessa il nome che compare in alto (titolo della scheda del browser) riporta il numero di commessa al posto della scritta generica: `26042` sulla pagina della commessa e `26042 · Lista documenti`, `26042 · Archivio`, `26042 · Gestisci emissione`, `26042 · Gestisci ricezione`, `26042 · Situazione documenti` nelle sue sezioni, così con più schede aperte si riconosce subito di quale commessa si tratta
- La revisione si legge sempre come dice l'archivio: con il flag **Revisioni con lettera** attivo esce ovunque la lettera (A, B, C…), con il flag spento esce ovunque il numero (0, 1, 2…). Vale per situazione documenti (viste orizzontale e verticale, comprese le intestazioni di colonna), elenco documenti, emissione, ricezione, sblocco e anomalie revisioni, per gli export Excel e PDF, per il trasmittal e per l'admin. Se il valore richiesto non è compilato viene ricavato dall'altro (0 ↔ A, 1 ↔ B, … 26 ↔ AA), quindi non compaiono più numeri al posto delle lettere sulle revisioni senza `RevLet`
- I colori della legenda STATUS nell'header del PDF di situazione documenti seguono le risposte del cliente configurate nell'admin: quadratino, lettera e descrizione arrivano dagli stati a sistema (colore mancante → default storico della lettera, lettera mancante → dedotta dal nome) invece di essere fissi nel codice. Vale sia per la vista orizzontale sia per quella verticale

### Fixed

- Registra ricezioni: un documento già registrato poteva restare "in bozza" nel browser e venire reinviato ad ogni click successivo su **Registra ricezioni** nella stessa sessione di pagina, marcando come rientrata dal cliente una revisione mai spedita e generando una revisione fantasma in più. Ora la bozza non viene più letta per i documenti già evasi e il server ignora un rientro inviato per una revisione che non è "inviata al cliente"

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
