# Changelog

## [Unreleased]

## [0.1.2] - 2026-08-31

### Added

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
