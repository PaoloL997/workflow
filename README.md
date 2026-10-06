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

### Storage S3 per foto profilo e firme (Garage con Docker)

Foto profilo e firme degli utenti stanno su [Garage](https://garagehq.deuxfleurs.fr/), uno
storage compatibile S3 che gira in Docker sulla stessa macchina (`docker-compose.yml`, unico
servizio `storage`). Il bucket è privato e Garage ascolta solo su `127.0.0.1:3900`: le
immagini le serve l'applicazione, solo agli utenti loggati. Senza `S3_BUCKET` nel `.env`
(per esempio in sviluppo) i file restano nella cartella `media\` del progetto.

Docker deve eseguire **container Linux**: `docker info --format "{{.OSType}}"` deve rispondere
`linux`. Con Docker Desktop attiva l'avvio automatico: se Docker non è partito, foto e firme
non si vedono e il PDF del trasmittal interno fallisce (con **Riprova**) finché non riparte.

**Prima attivazione**, dalla root del progetto in PowerShell:

```powershell
# 1. Credenziali: generale una volta sola e non cambiarle più
poetry run python -c "import secrets;print('S3_ACCESS_KEY=GK'+secrets.token_hex(16));print('S3_SECRET_KEY='+secrets.token_hex(32));print('GARAGE_RPC_SECRET='+secrets.token_hex(32))"
```

```env
# .env — aggiungere
S3_BUCKET=workflow-media
S3_ACCESS_KEY=GK...
S3_SECRET_KEY=...
GARAGE_RPC_SECRET=...
```

```powershell
# 2. Avvio di Garage: crea da solo chiave e bucket
docker compose up -d
docker compose exec storage /garage bucket info workflow-media

# 3. L'app legge il nuovo .env
Restart-Service WorkflowWaitress

# 4. Copia nel bucket delle foto e firme già caricate (stessi nomi, rilanciabile)
poetry run python manage.py copia_media_su_storage --dry-run
poetry run python manage.py copia_media_su_storage
```

La cartella `media\` non serve più dopo la copia, ma conviene tenerla finché non si è
verificato che foto e firme si vedono tutte.

**Backup.** I dati sono nei volumi Docker `workflow_garage_meta` e `workflow_garage_data`
(nomi esatti con `docker volume ls`). Per una copia coerente fermare il servizio:

```powershell
docker compose stop storage
docker run --rm -v workflow_garage_meta:/meta -v workflow_garage_data:/data -v "${PWD}\backups:/backup" alpine tar czf "/backup/garage-$(Get-Date -Format yyyy-MM-dd).tgz" /meta /data
docker compose start storage
```

**Cambio delle credenziali.**

```powershell
docker compose exec storage /garage key create workflow-nuova
docker compose exec storage /garage bucket allow --read --write --key workflow-nuova workflow-media
# aggiorna S3_ACCESS_KEY/S3_SECRET_KEY nel .env con quelle stampate, poi:
docker compose up -d
Restart-Service WorkflowWaitress
docker compose exec storage /garage key delete <vecchia-chiave> --yes
```

**Attenzione:** non rinominare mai `S3_BUCKET`. Garage creerebbe un bucket nuovo e vuoto,
e l'applicazione non troverebbe più le immagini già caricate.

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

## Allineamento giornaliero con Business Central

Alla creazione di una commessa, cliente, PO, descrizione e data consegna vengono precompilati da
Business Central. Poiché in BC quei dati possono cambiare, un controllo giornaliero li riconfronta
e aggiorna le commesse disallineate, registrando ogni modifica (visibile in *Informazioni archivio*
della commessa e nell'admin sotto *Aggiornamenti da Business Central*).

Il controllo parte **da solo**: l'applicazione avvia un thread interno (`core/services/scheduler.py`)
che ogni giorno alle **17:00** esegue la sincronizzazione. Non c'è nessuna attività pianificata né
crontab da registrare sul server: si aggiorna con `git pull` e un riavvio del servizio.

```env
# .env — valori predefiniti
BC_SYNC_SCHEDULER=True          # attivo in produzione, spento quando DEBUG=True
BC_SYNC_ORARIO=17:00
BC_SYNC_INTERVALLO_SECONDI=300  # ogni quanto il thread controlla se è ora
```

Dettagli utili:

- **Una sola esecuzione al giorno**, anche con più processi dell'applicazione: il turno si
  prenota su una riga PostgreSQL con `SELECT ... FOR UPDATE SKIP LOCKED`, gli altri processi escono
  subito.
- **Recupero**: se il server era spento alle 17:00, la sincronizzazione parte al primo controllo
  utile dopo l'avvio (la condizione è «sono passate le 17:00 e oggi non ho ancora girato»).
- **In caso di errore** (ERP irraggiungibile) l'esito viene registrato e si ritenta il giorno dopo:
  un tentativo al giorno, niente retry a raffica.
- **Esito visibile** nell'admin sotto *Esecuzioni schedulate*: data dell'ultima esecuzione e
  riepilogo. Cancellando quella riga si forza una nuova esecuzione al controllo successivo.

Il comando resta disponibile per esecuzioni manuali e anteprime:

```bash
# Tutte le commesse aperte
python manage.py sync_business_central

# Anteprima senza salvare / singola commessa / includi anche le commesse chiuse
python manage.py sync_business_central --dry-run
python manage.py sync_business_central --job 26010
python manage.py sync_business_central --tutte
```

Un valore vuoto in Business Central non sovrascrive mai un dato già inserito nel sistema.

Le modifiche a `BC_SYNC_*` richiedono un riavvio: `Restart-Service WorkflowWaitress`.

## Database

PostgreSQL. Le credenziali di connessione sono caricate da `.env` — non committare questo file.

Con database esterno, verifica anche sul server PostgreSQL:

- `listen_addresses` abiliti connessioni dalla rete aziendale
- `pg_hba.conf` consenta l'IP del server dell'applicazione
- firewall aperto sulla porta `5432` solo per la LAN necessaria

## Struttura

```
config/          Configurazione Django (settings, urls, wsgi)
core/            App principale: modelli, viste, template, migrazioni
code_template/   Codice legacy (solo riferimento, non usato)
```
