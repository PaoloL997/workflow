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

## Deploy su Windows Server (IIS + Waitress)

Produzione consigliata: **IIS** come front door HTTP e **Waitress** come server WSGI persistente
(sostituisce wfastcgi).

```mermaid
flowchart LR
    Browser --> IIS
    IIS -->|"proxy :8000"| Waitress
    Waitress --> Django
```

### Prerequisiti

- IIS con sito `workflow` su `C:\inetpub\wwwroot\workflow`
- Moduli IIS: **URL Rewrite** e **Application Request Routing (ARR)**
- **NSSM** per il servizio Windows ([nssm.cc](https://nssm.cc/download))
- Python venv con dipendenze: `poetry install`

### Prima installazione

Eseguire come **Administrator** dalla root del progetto:

```powershell
# 1. Dipendenze (include waitress)
powershell -ExecutionPolicy Bypass -File .\deploy\install-waitress-deps.ps1

# 2. Test manuale Waitress (Ctrl+C per fermare)
powershell -ExecutionPolicy Bypass -File .\deploy\waitress-serve.ps1
# Verificare: http://127.0.0.1:8000/login/
# Oppure: powershell -File .\deploy\smoke-waitress.ps1

# 3. Servizio Windows (usa identità app pool per accesso a Z:\ e UNC)
powershell -ExecutionPolicy Bypass -File .\deploy\install-waitress-service.ps1

# 4. Switch IIS da wfastcgi a reverse proxy Waitress
powershell -ExecutionPolicy Bypass -File .\deploy\switch-to-waitress.ps1

# 5. Tuning app pool (opzionale)
powershell -ExecutionPolicy Bypass -File .\deploy\iis-workflow-pool.ps1
```

### Aggiornamenti codice

```powershell
git pull
poetry install
Restart-Service WorkflowWaitress
```

**Nota:** modifiche al file `.env` richiedono `Restart-Service WorkflowWaitress` (non basta
recycle del pool IIS).

### Rollback a wfastcgi

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\rollback-wfastcgi.ps1
```

Script in `deploy/`:

| File | Scopo |
|------|--------|
| `install-waitress-deps.ps1` | `pip install waitress` nel venv |
| `smoke-waitress.ps1` | Test HTTP su `:8000` prima dello switch |
| `switch-to-waitress.ps1` | Backup web.config, ARR, deploy proxy |
| `waitress-serve.ps1` | Avvio manuale Waitress |
| `install-waitress-service.ps1` | Registra servizio `WorkflowWaitress` |
| `iis-waitress-proxy.ps1` | Abilita ARR reverse proxy |
| `web.config` | Template IIS → proxy a `127.0.0.1:8000` |
| `rollback-wfastcgi.ps1` | Ripristina web.config wfastcgi |
| `iis-workflow-pool.ps1` | AlwaysRunning / idle timeout |
| `install-bc-sync-task.ps1` | Registra il controllo giornaliero Business Central |

## Allineamento giornaliero con Business Central

Alla creazione di una commessa, cliente, PO, descrizione e data consegna vengono precompilati da
Business Central. Poiché in BC quei dati possono cambiare, un controllo giornaliero li riconfronta
e aggiorna le commesse disallineate, registrando ogni modifica (visibile in *Informazioni archivio*
della commessa e nell'admin sotto *Aggiornamenti da Business Central*).

```bash
# Tutte le commesse aperte
python manage.py sync_business_central

# Anteprima senza salvare / singola commessa / includi anche le commesse chiuse
python manage.py sync_business_central --dry-run
python manage.py sync_business_central --job 26010
python manage.py sync_business_central --tutte
```

Un valore vuoto in Business Central non sovrascrive mai un dato già inserito nel sistema.

Schedulazione:

```powershell
# Windows Server: attività pianificata giornaliera (default 06:00)
powershell -ExecutionPolicy Bypass -File .\deploy\install-bc-sync-task.ps1 -At 06:00
```

```cron
# Linux/Docker: crontab dell'host, ogni giorno alle 06:00
0 6 * * * docker compose -f /percorso/workflow/docker-compose.yml exec -T web python manage.py sync_business_central >> /var/log/workflow-bc-sync.log 2>&1
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
