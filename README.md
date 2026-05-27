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

## Deploy con Docker su Ubuntu Server

1. Copia il file di esempio e personalizza i valori:

```bash
cp .env.example .env
```

2. Configura in `.env` il PostgreSQL esterno. Nel tuo caso il formato e':

```env
DATABASE_URL=postgresql://brserver:PASSWORD_REALE@HOST_POSTGRESQL:5432/workflow
```

Se il database gira su un altro server della rete, sostituisci `HOST_POSTGRESQL` con IP o hostname reali.

3. Monta sul server Ubuntu la share di rete che contiene le cartelle JOBS e imposta in `.env`:

```env
FILESERVER_HOST_PATH=/mnt/jobs
FILESERVER_JOBS_PATH=/app/fileserver
```

4. Avvia lo stack:

```bash
docker compose up --build -d
```

L'applicazione sara' disponibile su `http://IP_DEL_SERVER:8000/` e l'admin su
`http://IP_DEL_SERVER:8000/admin/`.

Servizi inclusi nello stack:

- `web`: Django + Gunicorn
- `nginx`: reverse proxy e pubblicazione di static/media

Per aggiornare l'applicazione:

```bash
git pull
docker compose up --build -d
```

## Database

PostgreSQL. Le credenziali di connessione sono caricate da `.env` — non committare questo file.

Con database esterno, verifica anche sul server PostgreSQL:

- `listen_addresses` abiliti connessioni dalla rete aziendale
- `pg_hba.conf` consenta l'IP del server Ubuntu
- firewall aperto sulla porta `5432` solo per la LAN necessaria

## Struttura

```
config/          Configurazione Django (settings, urls, wsgi)
core/            App principale: modelli, viste, template, migrazioni
code_template/   Codice legacy (solo riferimento, non usato)
```
