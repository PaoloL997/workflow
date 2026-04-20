# Workflow — Sistema di Gestione Commesse

Applicazione Django per la gestione di commesse, documenti, revisioni e ticket di lavoro.

## 📋 Stato Attuale

### Modelli Implementati

**Archivio Commesse**
- **Testata** — Archivio principale delle commesse (numero commessa, cliente, PO, date di consegna, termini)
- **IndirSped** — Indirizzi di spedizione collegati alle commesse

**Documenti e Revisioni**
- **Documento** — Documenti di progetto (titolo, numero cliente, classificazione, assegnazione reparto)
- **Revisione** — Revisioni dei documenti con tracciamento stati interni/esterni, date pianificate e effettive
- **StatoEsterno** — Elenco stati esterni (es. "Ricevuto", "In revisione") con colori personalizzabili

**Gestione Ticket e Persone**
- **Ticket** — Sistema di assegnazione lavoro con esecutore, revisore, approvatore e tracciamento stato
- **TicketNota** — Note associate ai ticket per comunicazione tra team
- **User** — Utenti estesi con ruolo, email unica e assegnazione a reparto
- **Reparto** — Elenchi di reparti/team

**Sistema di Notifiche**
- **Notifica** — Notifiche per utenti relative a ticket, con stato di lettura

### Funzionalità

✅ **Amministrazione Django**
- Interfaccia admin completa per tutti i modelli
- Filtri per stato, reparto, responsabile
- Ricerca avanzata per commesse, documenti, ticket
- Inline editing per indirizzi e note

✅ **Tracciamento Flusso di Lavoro**
- Stati ticket: "Da iniziare" → "In lavorazione" → "In revisione" → "In approvazione" → "Concluso"
- Stati interni revisioni: "Da iniziare" → "In lavorazione" → "In revisione" → "In approvazione" → "Da emettere" → "Inviato al Cliente" → "Ricevuto"
- Assegnazione chiara di responsabilità (esecutore, revisore, approvatore)

✅ **Gestione Commesse**
- Archivio commesse con cliente, PO number, termini di consegna
- Tracciamento documenti e revisioni per commessa
- Supporto per flag di revisione lettere e trasmissione

## 🚀 Avvio Rapido

### Setup Ambiente
```bash
# Installa dipendenze
poetry install

# Crea file .env (vedi custom_instruction)
# DB_PASSWORD=your_password

# Esegui migrazioni
python manage.py migrate

# Crea superutente
python manage.py createsuperuser
```

### Avvia Server
```bash
python manage.py runserver
```

Accedi all'admin: `http://localhost:8000/admin`

## 📁 Struttura Progetto

```
.
├── config/              # Configurazione Django
│   ├── settings.py      # Variabili d'ambiente, app registrate
│   ├── urls.py
│   └── wsgi.py
├── core/                # Applicazione principale
│   ├── models.py        # Tutti i modelli
│   ├── views.py         # Viste (in sviluppo)
│   ├── admin.py         # Registrazione admin
│   ├── urls.py
│   └── templates/       # Template (in sviluppo)
├── code_template/       # Codice legacy (SQLite, VBA) — solo riferimento
├── static/              # File statici
├── manage.py
├── db.sqlite3
└── .env                 # Variabili d'ambiente (non committare)
```

## 🗄️ Database

- **Engine**: PostgreSQL (via psycopg2)
- **Credenziali**: Caricate da `.env`
- **Stato**: Tabelle esistenti in produzione, modelli Django mappati con `managed = True`

## 📝 Note di Sviluppo

- Tutti i modelli hanno `verbose_name` e `verbose_name_plural` in italiano
- Chiavi esterne a `User` usano `on_delete=models.RESTRICT` per prevenire cancellazioni accidentali
- FK a `Testata` usano il campo `job` come `to_field`
- Date pianificate e effettive sono nullable per supportare attività non ancora iniziate