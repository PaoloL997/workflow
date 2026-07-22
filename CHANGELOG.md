# Changelog

Tutte le modifiche rilevanti a questo progetto sono documentate in questo file.

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/),
e il progetto aderisce al [Semantic Versioning](https://semver.org/lang/it/).

## [Unreleased]

## [0.1.1] - 2026-07-22

### Added

- Colonna data Rev. 0 nel template Excel di import documenti
- Dropdown reparto nel template Excel di import documenti
- Flusso di reset password con invio email via SMTP
- Filtri colonna stile Excel in situazione documenti (lista valori, seleziona tutto, ricerca, contiene)
- Ordinamento colonne nella visualizzazione orizzontale di situazione documenti
- File `CHANGELOG.md` del progetto

### Fixed

- Evidenziazione di oggi nel calendario data ricezione (fuso orario locale invece di UTC)

## [0.1.0] - 2026-07-21

### Added

- Sblocco manuale delle revisioni nella situazione documenti
- Audit anomalie revisioni con UI modale per la risoluzione
- Script di deploy Waitress per migrazione da wfastcgi su IIS (Windows Server)
- Import commesse direttamente da database Access (.mdb) via ODBC
- Permessi utente basati su ruoli (lettura / scrittura / admin)
- Restrizione registrazione ai domini `@brembanarolle.com`
- Export XLSX per situazione documenti e workflow di import
- Stack di deploy Docker (Django + Gunicorn + Nginx)
- Anteprime scadenze documenti nelle card commessa (emissione e ricezione)
- Gestione ricezione documenti completa con layout tabellare
- Ridisegno pagine emissione e ricezione (layout full-width, modal indirizzi)
- Toggle "nuova revisione" visibile di default per ogni documento
- SQL chatbot per interrogazioni al database
- README e manuale utente

### Changed

- Miglioramenti al ciclo di vita commessa, PDF trasmittal e filtri situazione
- Gruppi creati automaticamente per i modelli documento
- Panoramica file dalla vista orizzontale
- Home limitata a 2 righe commesse con data invio pianificata per prima revisione
- Ordinamento documenti ricezione per urgenza con colori riga e date
- Allineamento stile pagine emissione, ricezione e archivio
- README semplificato

### Fixed

- Script di deploy in UTF-8 e runner per migrazione a Waitress
- Flag nuova revisione basato sulla risposta del cliente
- Apertura file revisioni inline in nuova tab (non download forzato)
- Networking Docker e dipendenze mancanti nel build
- Build Docker con pip al posto di poetry
- Servizio asset statici (Whitenoise)
- Revisione mostra `0` invece di `—` quando `rev_no=0`
- Cookie di sessione isolati per evitare collisioni tra applicazioni
- Stato ticket a livello documento
- `CSRF_TRUSTED_ORIGINS`, tabella `django_session`, connessione ERP/PostgreSQL

### Removed

- Ticket, note, notifiche e funzionalità rev-click nella situazione verticale
- Frontend legacy (branch per nuovo frontend da zero)

### Performance

- Riduzione chiamate N+1 e scritture sessione su database
