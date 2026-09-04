# Changelog

## [Unreleased]

### Added

- Campanella delle notifiche in alto a destra: avvisa tutti gli utenti quando qualcuno propone una nuova feature o segnala un problema; le notifiche spariscono una volta visualizzate
- Nuova voce di menu **Scarica**: si cerca una commessa, si spuntano le tabelle desiderate (Commessa, Indirizzi spedizione, Documenti, Revisioni; con "Seleziona tutte") e si scarica un Excel con i dati grezzi, un foglio per tabella e il solo header in grassetto. Il foglio Revisioni riporta Client Doc N°, Client Doc Class, Contractor Doc N°, B&R Doc, Item e la lettera della risposta del cliente al posto degli id tecnici

### Changed

- Situazione documenti: le celle legate alla risposta del cliente usano il colore configurato sullo stato, pieno e uguale a quello della legenda, al posto della vecchia tinta sbiadita. Il testo diventa automaticamente bianco o nero — quello dei due che si legge meglio — così restano leggibili anche gli stati bianchi, gialli, neri o grigi. Nella vista orizzontale sono colorate la colonna B&R Doc e la cella Status di ogni revisione (con la lettera dello stato), nella vista verticale il badge Risposta cliente, con la riga evidenziata in modo più deciso di prima. La legenda ripete la stessa coppia colore/lettera delle celle e il PDF orizzontale usa gli stessi colori

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
