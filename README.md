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

### Storage S3 per foto profilo e firme (SeaweedFS)

Foto profilo e firme degli utenti stanno su [SeaweedFS](https://github.com/seaweedfs/seaweedfs),
uno storage compatibile S3 che gira come servizio Windows (`WorkflowStorage`, con NSSM come
`WorkflowWaitress`) sulla stessa macchina. Ascolta solo su `127.0.0.1` (porte 3900-3903): il
bucket è privato e le immagini le serve l'applicazione, solo agli utenti loggati. Senza
`S3_BUCKET` nel `.env` (per esempio in sviluppo) i file restano nella cartella `media\`.

**Prima installazione**, dalla root del progetto in PowerShell come **Administrator**:

```powershell
# 1. Scarica windows_amd64.zip da https://github.com/seaweedfs/seaweedfs/releases
#    (provato con la 4.48) ed estrai weed.exe in C:\SeaweedFS\weed.exe

# 2. Credenziali: generale una volta sola
poetry run python -c "import secrets;print('S3_ACCESS_KEY='+secrets.token_hex(10));print('S3_SECRET_KEY='+secrets.token_hex(32))"
```

```env
# .env — aggiungere
S3_BUCKET=workflow-media
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_ENDPOINT_URL=http://127.0.0.1:3900
```

```powershell
# 3. Servizio WorkflowStorage + bucket (dati in C:\SeaweedFS\data; -DryRun per un'anteprima)
powershell -ExecutionPolicy Bypass -File .\deploy\install-seaweedfs-service.ps1

# 4. L'app legge il nuovo .env
Restart-Service WorkflowWaitress

# 5. Copia nel bucket delle foto e firme già caricate (stessi nomi, rilanciabile)
poetry run python manage.py copia_media_su_storage --dry-run
poetry run python manage.py copia_media_su_storage
```

Percorsi e porte si cambiano con i parametri dello script (`-WeedPath`, `-DataDir`, `-S3Port`;
con un'altra porta va aggiornato anche `S3_ENDPOINT_URL`). La cartella `media\` non serve più
dopo la copia, ma conviene tenerla finché non si è verificato che foto e firme si vedono tutte.

Se il servizio è fermo, foto e firme non si vedono e il PDF del trasmittal interno fallisce
(con **Riprova**) finché non riparte; log in `logs\seaweedfs-service.log`.

**Backup.** Tutto (dati e metadati) è nella cartella dati. Per una copia coerente:

```powershell
Stop-Service WorkflowStorage
Compress-Archive C:\SeaweedFS\data "C:\Backup\seaweedfs-$(Get-Date -Format yyyy-MM-dd).zip"
Start-Service WorkflowStorage
```

**Cambio delle credenziali.** Aggiorna `S3_ACCESS_KEY`/`S3_SECRET_KEY` nel `.env`, rilancia lo
script (reinstalla il servizio con le nuove chiavi, i dati restano) e poi
`Restart-Service WorkflowWaitress`.

**Attenzione:** non rinominare `S3_BUCKET`: l'applicazione cercherebbe le immagini in un bucket
nuovo e vuoto.

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
| `install-seaweedfs-service.ps1` | Servizio `WorkflowStorage` (SeaweedFS, S3 per foto e firme) |

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
