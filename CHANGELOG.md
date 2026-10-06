# Changelog

## [Unreleased]

### Added

- Foto profilo e firme degli utenti su uno storage compatibile S3 ([SeaweedFS](https://github.com/seaweedfs/seaweedfs)) che gira come servizio Windows (`WorkflowStorage`) sul server, installato con `deploy\install-seaweedfs-service.ps1`. Si attiva con le variabili `S3_*` nel `.env` (vedi README); il bucket è privato e raggiungibile solo dal server. Il comando `python manage.py copia_media_su_storage` (con `--dry-run`) copia nel bucket le foto e le firme già caricate, con lo stesso nome. Senza `S3_BUCKET` (sviluppo) i file restano nella cartella `media`
- Informazioni archivio: nuova sezione **Revisioni**, sotto gli indirizzi di consegna, per scegliere come si indicano le revisioni dei documenti: **Numero** (0, 1, 2…), **Lettera** (A, B, C…) oppure **Personalizzata**, con una sequenza di etichette scritta a mano separata da virgole (es. `1,2,3,D,E,F,4,5,6`). La prima etichetta è la prima revisione; oltre l'ultima la sequenza prosegue da sola dall'ultima etichetta (6 → 7, F → G). Un'anteprima mostra le revisioni prima di salvare. Come per le lettere, cambia solo come la revisione si legge — schermate, Excel, PDF, trasmittal — non i dati salvati
- Informazioni archivio: pulsante **Aggiorna da BC** accanto ad "Aggiornamenti da Business Central" per lanciare a mano il confronto con Business Central sulla singola commessa, senza aspettare il controllo giornaliero delle 17:00. Funziona anche sulle commesse già chiuse
- Informazioni archivio: nuovo campo **Sito costruttivo**, con la lista degli stabilimenti che hanno un codice sito Business Central. Serve a sbloccare il trasmittal interno quando Business Central non ha (o non ha ancora) il dato: fino ad ora l'unico modo per impostarlo era l'admin di Django
- Trasmittal interno: le destinazioni cartacee dei documenti UT vengono precompilate automaticamente, ogni giorno insieme al controllo BC, dal vecchio file `<job>-RecipientsData.txt` sul fileserver quando presente. Tocca solo i documenti senza nessuna destinazione già registrata: una volta impostate (a mano o dall'import) non vengono più toccate. Comando manuale: `python manage.py import_destinazioni_ut` (opzioni `--job`, `--tutte`, `--dry-run`)

### Changed

- Foto profilo e firme le serve l'applicazione, solo a utenti loggati. Sostituendo una foto o una firma, quella vecchia viene cancellata solo dopo aver salvato la nuova: se lo storage non risponde resta quella di prima e il profilo mostra un errore. Se lo storage non risponde mentre si genera il PDF del trasmittal interno, il passo PDF fallisce in modo visibile (con **Riprova**) invece di emettere la lettera senza firme. Dopo un errore dello storage, per 30 secondi foto e firme rispondono subito con un errore invece di riprovare: se il servizio è fermo l'app non rallenta
- Informazioni archivio: il toggle **Revisioni con lettera** esce da *Tempi di revisione* e diventa una delle tre scelte della nuova sezione **Revisioni**. Nella pagina della commessa il riquadro dell'archivio mostra *Revisioni: Numero / Lettera / Personalizzata* al posto di *Revisioni con lettere: Sì/No*
- Trasmittal interno: l'email della lettera mostra come mittente il nome di chi l'ha compilata ed emessa (es. *Mario Rossi (Workflow)*), le risposte vanno a lui (*Rispondi a*) e gliene arriva una copia. Nel testo dell'email ci sono anche le note scritte nella lettera e, in fondo, chi l'ha inviata. L'indirizzo resta la casella dell'applicazione: il server di posta non permette di spedire con l'indirizzo di un altro utente. Vale anche quando si usa **Riprova** sul passo Email: conta chi ha emesso la lettera, non chi preme il pulsante. Il pannello di conferma prima dell'invio mostra come apparirà il mittente
- Admin di Django: un superuser può eliminare una lettera di trasmittal interno (prima l'admin era di sola lettura). Serve per pulire dati di test o errore che il tasto **Annulla** dell'app non copre (funziona solo sull'ultima lettera emessa in un giorno). Eliminare qui non tocca il PDF su Z:\JOBS, l'eventuale cartella DCC preparata né un'email già inviata: per l'uso normale resta preferibile Annulla
- Trasmittal interno: la scrittura (impostare destinazioni, generare/emettere una lettera, annullarla, ritentare un passo) è ora riservata agli utenti con il nuovo flag **"Può scrivere sul trasmittal interno"**, impostabile per singolo utente dall'admin di Django (scheda Utenti → Permessi app) — indipendente dal permesso generale. Tutti gli altri vedono la sezione ma non possono modificarla; l'anteprima resta accessibile a tutti perché non scrive nulla
- Il controllo giornaliero delle 17:00 allinea anche il sito costruttivo delle commesse che ne sono ancora sprovviste (prima lo faceva solo il comando manuale `sync_business_central`)

### Removed

- Deploy Docker dell'applicazione pensato per Ubuntu Server (Dockerfile, docker-compose.yml, entrypoint, nginx, dipendenza gunicorn): non era usato, l'applicazione gira su Windows con IIS + Waitress

### Fixed

- Sul server Windows/IIS le foto profilo non si vedevano (l'indirizzo `/media/` rispondeva 404): ora si vedono
- Import commessa da Access: il campo Requisition ("Bid no.") passa da 100 a 300 caratteri. Alcune commesse hanno in Access una Requisition più lunga del vecchio limite (es. due bid concatenate) e l'importazione falliva con un errore generico di troncamento
- Tutti i modali dell'app (aggiungi/modifica documento, componi lettera, anomalie, destinazioni, ricerca commessa e altri — una ventina di punti in 12 pagine) non si chiudono più da soli quando si seleziona del testo in un campo per copiarlo e il rilascio del mouse finisce di poco fuori dal bordo del campo. Il controllo "click fuori per chiudere" ora richiede che anche il clic sia partito dallo sfondo, non solo che sia terminato lì

## [0.1.5] - 2026-09-24

### Added

- Situazione documenti: nella barra in alto c'è un controllo nuovo per ogni vista. In **orizzontale**, dove una riga è un documento, *Filtra per risposta del cliente* tiene i documenti in base a come sta l'ultima revisione, a spunte multiple: ci sono le risposte del cliente in uso più *Inviato al Cliente* e *Da inviare*, così si includono o si escludono in un colpo solo quelli in attesa di risposta e quelli mai inviati; ogni voce porta il quadratino del colore che si vede nella colonna B&R Doc. In **verticale**, dove una riga è una revisione, c'è *Mostra solo ultima revisione*, che riduce la tabella a una riga per documento; per la risposta del cliente resta il filtro sulla colonna *Client response*, che guarda la singola revisione
- Situazione documenti: con un filtro attivo l'export Excel e PDF contiene solo i documenti rimasti a schermo e, con *Mostra solo ultima revisione* acceso, solo quella revisione. Vale per entrambe le viste e per tutti i filtri, anche quelli di colonna già esistenti
- Notifiche sui commenti: quando qualcuno commenta un thread di feature o problemi, ricevono la notifica nella campanella chi ha aperto il thread e chi lo ha già commentato (escluso chi scrive il commento). Il testo è del tipo *Anna Bianchi ha commentato «Titolo del thread»*; resta una sola notifica per thread, che torna da leggere ad ogni nuovo commento
- Barra di ricerca: digitando il codice completo di una commessa e premendo **Invio** si apre direttamente la pagina di quella commessa, senza dover cliccare il risultato. Se il codice non corrisponde esattamente a nessuna commessa vengono mostrati i risultati come prima
- Situazione documenti: anche la vista orizzontale, oltre alla verticale, ha l'export in Excel accanto a quello in PDF (pulsante **Esporta** → Excel / PDF). L'Excel riproduce la tabella a schermo: una riga per documento, colonne fisse, gruppo Planning (Submission date, Receipt date) e un gruppo per ogni revisione (Dispatch, Received, Status), con la colonna B&R Doc e le celle Status colorate come la risposta del cliente

### Changed

- Situazione documenti, vista verticale: il filtro **Client response** sulla colonna passa da una risposta sola alle spunte multiple, come gli altri filtri di colonna
- Situazione documenti, vista orizzontale: i gruppi di colonne *Rev.* seguono i documenti rimasti dopo i filtri, quindi non restano più gruppi vuoti e la tabella coincide con quello che esce nell'export
- Nuovi colori delle risposte del cliente: Approved e For Information verde `#4AF536`, i due Commented rosso `#E32400`, Final - As Built e Superseeded blu `#1649F0`, Old quasi nero `#131314`, Rejected nero `#000000`. Valgono ovunque — situazione documenti, legende, export Excel e PDF — e sono anche i colori di partenza delle risposte create dall'import
- *Final - As Built* e *For Information* non creano più in automatico una nuova revisione alla ricezione: con quelle risposte il documento chiude il giro
- Situazione documenti, vista orizzontale: a colorarsi è solo la colonna **B&R Doc**, che da sola dice come sta il documento; le celle Status delle singole revisioni riportano la lettera della risposta senza colore. Il colore è quello dell'ultimo stato: il giallo *Inviato al Cliente* quando l'ultima revisione è partita e la risposta manca ancora, altrimenti il colore dell'ultima risposta arrivata, anche se sta su una revisione precedente; il grigio *Da inviare* resta ai documenti mai inviati e su cui il cliente non si è mai espresso. La legenda sotto la tabella elenca gli stati che le celle mostrano davvero, e la stessa regola vale per l'export Excel e per il PDF della vista orizzontale
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
