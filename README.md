# Workflow — Gestione Commesse

Applicazione Django per la gestione di commesse, documenti e revisioni in ambito industriale.

## Funzionalità principali

- Archivio commesse con cliente, PO, date e termini di consegna
- Gestione documenti e revisioni per commessa, con stati interni ed esterni
- Tracciamento del flusso di lavoro per ogni revisione
- Visualizzazione situazione documenti (lista e vista verticale)
- Gestione ricezione documenti da cliente
- Browser file integrato per collegare file alle revisioni (cartelle JOB)

## Avvio

```bash
# Installa dipendenze
poetry install

# Configura .env con le credenziali del database
# DB_PASSWORD=your_password

# Applica le migrazioni
python manage.py migrate

# Avvia il server
python manage.py runserver
```

Interfaccia admin disponibile su `http://localhost:8000/admin`.

## Database

PostgreSQL. Le credenziali di connessione sono caricate da `.env` — non committare questo file.

## Struttura

```
config/          Configurazione Django (settings, urls, wsgi)
core/            App principale: modelli, viste, template, migrazioni
code_template/   Codice legacy (solo riferimento, non usato)
```
