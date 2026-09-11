# Audit di coerenza — Quality Control Plan

Branch `feat/quality-control-plan`, 11 settembre 2026. Audit della feature rispetto al documento originale: nessuna modifica al codice applicativo, solo test aggiunti in `core/tests.py`.

**Riferimenti**
- `core/data/catalogo_attivita_qcp.json`: 291 attività.
- `core/data/corpo_26026.json`: 34 sezioni, 224 step.
- Dati di copertina della 26026 e descrizione della 26004, dal brief.

**Metodo**
- Test Django su PostgreSQL di prova (`test_dati_brembana`, riusato con `--keepdb`: era rimasto da un'esecuzione precedente, e con `--noinput` Django l'avrebbe cancellato).
- Le difformità con un comportamento atteso chiaro sono test marcati `@expectedFailure`. Oggi passano; quando la difformità viene corretta falliscono come *unexpected success*, e a quel punto va tolto il decoratore.
- I tempi di risposta (5.2) sono misurati con uno script fuori dal repository (vedi 5.2).

---

## Esito dei comandi

| Comando | Esito |
|---|---|
| `poetry run ruff check .` | Tutti i controlli passati |
| `poetry run ruff format --check .` | 4 file da riformattare, **tutti preesistenti e fuori dal diff del branch**: `core/migrations/0028_statoesterno_crea_nuova_rev.py`, `core/migrations/0029_cartellamodellodocumento.py`, `core/services/revisioni_cleanup.py`, `core/services/stato_esterno_legenda.py`. `core/tests.py` è formattato |
| `poetry run python manage.py makemigrations --check --dry-run` | No changes detected |
| `poetry run python manage.py check` | No issues |
| Test d'audit (3 classi, 33 test) | OK: 29 superati e 4 fallimenti attesi (`expectedFailure`) |
| `poetry run python manage.py test core --keepdb` (suite completa) | 500 test (467 preesistenti + 33 d'audit): 1 errore, 8 saltati, 4 fallimenti attesi. L'errore è quello preesistente sotto; nessuna regressione |
| Suite completa **prima** dell'audit | 467 test, 1 errore, 8 saltati. L'errore è `test_export_situazione_pdf`: manca il modulo `fitz` (PyMuPDF). È preesistente, non riguarda il QCP ed è già in TECH-DEBT.md |

---

## Esito per punto

Gravità: **B** = blocca l'uso reale · **D** = degrada l'output · **C** = cosmetico. Le difformità (D1…D8) sono descritte nella sezione successiva.

### Parte 1 — Copertina (26026)

| Punto | Esito | Note | Test |
|---|---|---|---|
| Persistenza e resa dei valori | **Difforme** (D5, D6) | 24 valori tornano identici dopo POST e rilettura dall'API: project, owner, purchaser, P.O., item e descrizione, location, data ISO, prepared by, foglio QCP, rev, componenti della numerazione, MDMT, 4 requisiti, notification, 3 codici, 2 spec, 3 enti. Divergono il Vendor (D6) e la data scritta nel formato del documento (D5) | `test_1_copertina_26026_persistita_e_restituita_dall_api`, `test_1_il_vendor_e_quello_del_documento` (xfail), `test_1_la_data_nel_formato_del_documento_non_si_perde_in_silenzio` (xfail) |
| 1.1 Numerazione | Conforme | `26026-01-QCPA`, `26026-01-EGA1`, `26026-01-SNA` | `test_1_1_…` |
| 1.2 Serial base A→B | Conforme | QCPB e SNB; Dwg n. invariato | `test_1_2_…` |
| 1.3 Componente mancante | Conforme | Numero vuoto, mai `26026--…`. Senza Doc n. il titolo della copertina ripiega su `26026-QCPA`. Senza dwg base i tre numeri sono vuoti | `test_1_3_…` |
| 1.4 Doc n. a mano | Conforme | Vince sul calcolato, sia nella copertina sia nel riferimento `campo_piano` `doc_no` (con il limite descritto in D8) | `test_1_4_…` |
| 1.5 Ordine enti | Conforme | Ordine di inserimento (B&R, LNG CANADA, A.I.; alfabetico A.I. sarebbe primo), stabile dopo salvataggio e ricarica, uguale in copertina e nelle colonne del corpo | `test_1_5_…` |
| 1.6 Anteprima | Conforme (con D7) | Tutti i valori sono presenti, niente "None", nessun campo vuoto e nessun "Nessun … inserito". Le diciture non sono quelle del documento (D7). Dwg base, serial base e foglio disegno non compaiono come campi propri: si vedono attraverso Doc/Dwg/Serial n. | `test_1_6_…` |

### Parte 2 — Catalogo

| Punto | Esito | Note | Test |
|---|---|---|---|
| 2.1 291 attività | Conforme | | `test_2_1_2_2_2_3_…` |
| 2.2 Divisioni | Conforme | Gen 88, Div.1 197, Div.2 6 | idem |
| 2.3 Capitoli | Conforme | 10 (anche i capitoli attivi del selettore) | idem |
| 2.4 Codici ripetuti | Conforme | Convivono (unicità su codice + capitolo). Il file però ha **solo 2** codici ripetuti, "Final documentation index" e "Pickling and passivation": "VT-Complete base welding" è una riga sola (O2) | `test_2_4_…` |
| 2.5 Riferimenti | Conforme | Tutti i casi del brief tornano; conteggio per tipo 192/84/7/6/2. Nessuno dei 291 dà un riferimento con "\|" o "None", e ogni `suffisso_job`/`campo_piano` inizia per 26026. `da_proc` è vuoto come atteso, ma sul corpo reale pesa (D2). Il riferimento `campo_piano` è congelato all'inserimento (D8) | `test_2_5_…` (3 test) |
| 2.6 Reimport | Conforme | Creati 0, aggiornati 0, invariati 291 | `test_2_6_…` |

### Parte 3 — Corpo (26026)

| Punto | Esito | Note | Test |
|---|---|---|---|
| 3.1 34 sezioni in ordine | Conforme | | `test_3_1_…` |
| 3.2 224 step, conteggi per sezione | Conforme (con D4) | Conteggi uguali al file. Uno step (il n. 11) nasce scritto a mano, senza snapshot (D4) | `test_3_2_…` |
| 3.3 Numerazione | Conforme | Continua fra le sezioni (la seconda comincia da 18) e si ricalcola dopo la cancellazione dello step 20: 1…223, il 21 diventa 20, posizioni della sezione di nuovo 0…7 | `test_3_3_…` |
| 3.4 Snapshot | **Difforme** (D2) | Descrizione, test, acceptance criteria e documento richiesto di "Calculations" vengono dal catalogo. Il suo reference doc invece **non** è risolto: è `da_proc`, quindi vuoto. Stessa sorte per 8 step su 224. Gli altri 215 step da catalogo hanno lo snapshot identico al catalogo e il riferimento risolto (es. `26026-QNDE`, `26026-01-EGA1`) | `test_3_4_…` |
| 3.5 Un punto per ente | Conforme | 224 step × 3 punti, 3 enti distinti ciascuno, nessun punto di un ente estraneo | `test_3_5_…` |
| 3.6 Distribuzione dei punti | **Difforme** (D3) | I valori composti **sono rappresentati**: R/SW 41, F/SW 16 e (\*) 6 salvati identici, cella per cella, e resi identici nella pagina. Sono 63 celle su 58 step, non "63 step" (O1). Le 2 celle vuote diventano "-" (D3): in archivio "-" = 140 invece di 138 + 2 vuoti | `test_3_6_punti_composti_salvati_come_nel_file`, `test_3_6_le_celle_vuote_…` (xfail) |
| 3.7 Extent | Conforme | 223 × `1.000` e 1 × `0.050` (step 25). L'API restituisce `0.05`, la pagina mostra "5" con "%" | `test_3_7_…` |
| 3.8 Remarks | Conforme | Le 224 remarks sono identiche al file ("4", "6", "IF ANY", "\* SEE DEDICATED SHEET"…) e la pagina le rende (12 × "\* SEE DEDICATED SHEET"). Il contenuto a cui rimandano non è modellato (O10) | `test_3_8_…` |
| 3.9 Immutabilità | Conforme | Riscrivendo tutto il catalogo e disattivando "Calculations", i 224 step restano identici | `test_3_9_…` |
| 3.10 Quarto ente | Conforme (con O5) | `sincronizza_punti` crea 224 punti "-"; togliendo l'ente spariscono (CASCADE) e la distribuzione torna quella di prima. La sincronizzazione non è automatica: la chiama solo l'admin (O5) | `test_3_10_…` |

### Parte 4 — Secondo documento (26004)

| Punto | Esito | Note | Test |
|---|---|---|---|
| 4.1 4 codici, 3 enti | Conforme | I 4 codici veri della 26004 non sono nel brief: ho usato 4 codici dell'elenco proposto. Si verifica la cardinalità | `test_4_1_…` |
| 4.2 "A.I. (LRQA)" | Conforme | Si salva, mantiene l'ordine, il seed lo abbina per nome e la copertina lo mostra, così come l'intestazione di colonna e la cella del punto | `test_4_2_…` |
| 4.3 Owner vuoto | Conforme | `""` e `None` diventano un elemento vuoto, mostrato come trattino grigio; `"-"` si salva e si mostra così com'è. Mai "None" | `test_4_3_…` |
| 4.4 Revisioni con firme | **Difforme** (D1) | Nessun modello per le revisioni né per le firme checked / approved | `test_4_4_…` (xfail) |
| 15 sezioni / 104 step | Non verificabile | Il corpo della 26004 non è stato fornito | — |

### Parte 5 — Tenuta e prestazioni

| Punto | Esito | Note | Test |
|---|---|---|---|
| 5.1 N+1 | Conforme | **12 query** per la pagina di dettaglio, uguali con 1 step e con 224 step. Dettaglio: sessione e utente 2, commessa 1, piano con item/codici/spec/enti 5, sezioni/step/punti 3, capitoli del catalogo 1 | `test_5_1_…` (`assertNumQueries(12)`) |
| 5.2 Tempo di risposta | Conforme (con O9) | Pagina di dettaglio (34 sezioni, 224 step, 3 enti): **mediana 133 ms**, p90 153 ms (min 122, max 273) su 20 richieste. HTML di **1,16 MB** (O9) | Nessun test in repo (vedi sotto) |
| 5.3 Spostamento fra sezioni | Conforme | PATCH `{"sezione": …, "ordine": 0}`: lo step 5 della sezione 1 diventa il primo della sezione 3 con numero 26. Il 6 diventa 5, la numerazione resta 1…224, i punti seguono lo step, le posizioni delle due sezioni restano senza buchi | `test_5_3_…` |
| 5.4 Stati vuoti | Conforme | Piano senza enti: pagina 200 con avviso, "Nessun ente inserito", API corpo con `enti: []`, PATCH punti vuoto → 400. Sezione senza step: messaggio dedicato. Catalogo senza risultati: `attivita: []`, `totale: 0`, anche con `piano` o con un capitolo inesistente | `test_5_4_…` |

**Come è misurato il 5.2.** Client di test Django in-process, PostgreSQL locale, `DEBUG=False`, 1 richiesta di riscaldamento, niente rete, file statici né rendering del browser: è il costo lato server. Misurati nello stesso giro:
- API `GET corpo/`: mediana 29 ms, JSON di 105 KB.
- PATCH di un punto, che restituisce il corpo intero: mediana 33 ms.
- Seed dei 224 step: 1,3 s.

Lo script (`audit_timing.py`) è nello scratchpad della sessione e non è nel repository, perché una soglia di tempo in un test automatico darebbe esiti instabili.

---

## Difformità

### D1 — Revisioni e firme non rappresentabili (4.4) — **B: blocca l'uso reale**
- **Oggi:** il piano ha un solo `rev_no` scalare e un solo `prepared_by`, nessuno storico e nessun campo checked / approved. Emettere la Rev 1 vuol dire sovrascrivere la Rev 0 e perdere le sue firme.
- **Atteso:** per la 26004 tre revisioni, ognuna con prepared / checked / approved (Rev 0 F. Baldin / P. Facheris / F. Baldin; Rev 1 e 2 con F. Crotta come checked), tutte stampate nel riquadro revisioni.
- **Dove:** `core/models.py:719` (`rev_no`), `core/models.py:739` (`prepared_by`). Nessun modello collegato.
- **Impatto:** un QCP emesso al cliente senza storico delle revisioni né firme di verifica e approvazione non è un documento valido: blocca l'emissione dalla Rev 0 in poi.
- **Test:** `AuditCopertinaQCPTests.test_4_4_tre_revisioni_con_firme_prepared_checked_approved` (xfail).

### D2 — Reference doc vuoto sugli step `da_proc` (3.4, 2.5) — **D: degrada l'output**
- **Oggi:** i 6 codici `da_proc` del catalogo danno un riferimento vuoto. Sul corpo della 26026 sono **8 step su 224**: 2 Calculations, 4 Material requirement specification, 5 Welding book, 17 Validation, 49/112/162 Thickness measurement, 101 Weld monitoring-Tubes to tubesheet joint.
- **Atteso:** il riferimento che nell'Excel veniva dalla matrice saldature (`PROC!H17`…). Il brief chiede "Calculations" risolto sul job.
- **Dove:** `core/models.py:1039` e `:1065` (`risolvi_reference_doc`), `core/services/quality_control_plan.py:805-809` (`_snapshot_da_catalogo`).
- **Impatto:** 8 righe stampate senza documento di riferimento, fra cui calcoli e welding book, cioè documenti in approvazione. Ogni step si può correggere a mano con "Modifica".
- **Test:** `test_3_4_snapshot_dal_catalogo_e_riferimento_risolto` (conta gli 8 step), `test_2_5_riferimenti_documentali_risolti_sul_job`.

### D3 — Celle vuote del documento salvate come "-" (3.6) — **D: degrada l'output**
- **Oggi:** negli step 80 e 106 ("DC-Complete equipment") la cella dell'ente A.I. è vuota nel file (`null`). Il seed la lascia al valore di default "-" (non coinvolto) e la segnala fra le anomalie. Il modello non ha un valore per "non indicato".
- **Atteso:** distribuzione con "-" 138 e 2 vuoti, cioè due stati distinti.
- **Dove:** `core/services/seed_corpo_qcp.py:264-265`, `:281-282`; default del campo `core/models.py:1220-1225`; `normalizza_punto` `core/services/quality_control_plan.py:981-1001` (nessun valore vuoto ammesso).
- **Impatto:** 2 celle cambiano significato, da "da definire" a "l'ente non interviene".
- **Test:** `test_3_6_le_celle_vuote_del_file_restano_distinte_da_non_coinvolto` (xfail).

### D4 — Codice con doppio spazio: step scritto a mano senza snapshot (3.2) — **D: degrada l'output**
- **Oggi:** lo step 11 del file ha codice `"Preservation  procedure"` (due spazi), il catalogo `"Preservation procedure"`. Il seed non lo trova, crea uno step manuale con la sola descrizione (niente test/inspection, reference doc, acceptance criteria, documento richiesto, tecnica) e segnala il codice simile.
- **Atteso:** lo step con i dati dell'attività di catalogo.
- **Dove:** `core/services/seed_corpo_qcp.py:294-311`. L'origine è il file sorgente.
- **Impatto:** 1 riga su 224 incompleta.
- **Test:** `test_3_2_224_step_con_i_conteggi_per_sezione_del_file`.

### D5 — Data nel formato del documento persa senza errore (1) — **D: degrada l'output**
- **Oggi:** `create_piano` usa `_parse_date`, che accetta solo ISO. `"25/08/2026"` diventa `None` senza errore e il piano nasce senza data. Il modulo della pagina manda ISO, quindi dall'interfaccia il problema non si presenta; si presenta con chi usa l'API o un import.
- **Atteso:** 25/08/2026 salvata, oppure un errore esplicito.
- **Dove:** `core/services/commesse.py:289-298` (funzione condivisa con le commesse), `core/services/quality_control_plan.py:468`.
- **Test:** `test_1_la_data_nel_formato_del_documento_non_si_perde_in_silenzio` (xfail).

### D6 — Vendor fisso "Brembana & Rolle" (1) — **C: cosmetico**
- **Oggi:** il vendor è la costante `VENDOR = "Brembana & Rolle"`: non è una colonna e il valore mandato dal client si ignora.
- **Atteso:** "B&R", come nella copertina del documento.
- **Dove:** `core/services/quality_control_plan.py:44`, `:518`; template `quality_control_plan_detail.html:828`.
- **Test:** `test_1_il_vendor_e_quello_del_documento` (xfail).

### D7 — Diciture dell'anteprima diverse dal documento (1.6) — **C: cosmetico**
- **Oggi:**
  - I requisiti escono "Richiesto" / "Non richiesto" (in maiuscoletto via CSS). Eppure `serialize_piano` espone già `*_label` con REQUIRED / NOT REQUIRED, che il template non usa.
  - L'etichetta è "Hydrogen service" invece di "H2S service".
  - La data esce "25 aug 2026" invece di 25/08/2026.
- **Dove:** `core/templates/core/quality_control_plan_detail.html:884-887` e `:807`; `core/date_fmt.py:23`.
- **Impatto:** solo l'anteprima a schermo, il PDF non esiste ancora. Diventa sostanziale se il PDF riprende queste diciture.
- **Test:** `test_1_6_la_copertina_rende_tutti_i_campi_senza_none_ne_vuoti` verifica la resa attuale.
- **Aggiornamento, dopo il ridisegno della pagina (stesso giorno):** la testata mostra ora solo i requisiti richiesti, con le diciture ASME stamp, National board, H2S e Lethal service: "Richiesto / Non richiesto" e "Hydrogen service" non ci sono più. Resta la data "25 aug 2026". I numeri di riga del template citati in questo rapporto si riferiscono alla versione precedente della pagina.

### D8 — Riferimento `campo_piano` congelato all'inserimento (2.5) — **D: degrada l'output**
- **Oggi:** il riferimento si risolve quando lo step entra, come parte dello snapshot. Uno step "Drawings" inserito prima di compilare dwg base e foglio resta con reference doc vuoto; se in seguito il Dwg n. o il Doc n. cambiano (dall'admin, unico modo di modificare la copertina), gli step "Drawings" e "Inspections & tests plan" tengono il valore vecchio, senza avviso.
- **Atteso:** nel foglio Excel la formula era viva. Non è detto che vada replicata (vedi decisioni aperte), ma oggi la divergenza non si vede.
- **Dove:** `core/models.py:1062-1064`, `core/services/quality_control_plan.py:805-809`.
- **Impatto:** nessuno sulla 26026 seminata (copertina completa prima del corpo).
- **Test:** `test_2_5_il_riferimento_campo_piano_resta_quello_dell_inserimento` (documenta il comportamento attuale).

---

## Osservazioni (non difformità dal documento)

- **O1 — Brief, 3.6:** i valori composti sono 63 **celle** su **58 step**, non 63 step.
- **O2 — Brief, 2.4:** "VT-Complete base welding" non è ripetuto nel file. La riga fit-up ha il suo codice ("VT-Complete base welding fit-up"); un test preesistente cita anche "VT-Fit-up".
- **O3 — Brief, 2.5:** nel file il composito è `"/VT |/DC"` (con uno spazio) e `"BCI-006-CWC |-TMRS"`. La risoluzione ripulisce gli spazi e unisce le parti con **uno spazio**: `26026/VT 26026/DC`. Il separatore va confrontato con il documento stampato.
- **O4 — Non verificabile, step 198 "Pickling and passivation"** (sezione "Checks after channels removals"): il codice è in due capitoli e il seed prende il primo, NDE (riferimento `26026/QPKP`, test "Pickling and passivation of girth flanges and tubesheets"). L'altro, ISPEZIONI FINALI, ha riferimento vuoto e descrizione "Final inspection". Il file non dice quale intende il documento.
- **O5 — Sincronizzazione dei punti non automatica:** creare un ente fuori dall'admin lascia gli step senza il suo punto finché qualcuno non chiama `sincronizza_punti`; la pagina intanto mostra "-". Oggi la chiama solo `core/admin.py:345`. Visto che la copertina si modifica solo dall'admin, in pratica l'invariante regge.
- **O6 — Permesso dell'API corpo:** il `GET` dell'API corpo richiede il permesso di scrittura (`core/views.py:726`), mentre la pagina del piano è leggibile da tutti gli autenticati.
- **O7 — Ordine dei punti composti:** "R/SW" e "SW/R" si salvano come stringhe diverse, perché l'ordine si conserva (`core/services/quality_control_plan.py:996-1001`).
- **O8 — Commento superato:** `PERCENTUALE_INIZIALE` dice ancora "Nessuno step è ancora modellato" e la percentuale dell'elenco resta sempre 0 (`core/services/quality_control_plan.py:49-52`, `:558`).
- **O9 — Peso della pagina:** 1,16 MB di HTML a 224 step. Ogni step è disegnato con tutte le colonne e il suo menu, anche nelle sezioni chiuse.
- **O10 — Contenuti a cui rimandano le remarks:** i numeri "1"…"6" rimandano a note del documento e "\* SEE DEDICATED SHEET" / "(\*)" a un foglio dedicato. Le remarks si salvano fedeli, ma note e foglio non hanno un posto nel modello, e nemmeno in `corpo_26026.json`.
- **O11 — Candidati per TECH-DEBT.md:** O6, O7 e O8 hanno i requisiti di AGENTS.md per entrarci. Non li ho aggiunti per la regola dell'audit (nessuna modifica oltre ai test).

---

## Test aggiunti

In `core/tests.py`, in coda, sotto il blocco "AUDIT QCP". Riusano il catalogo e il corpo reali di `core/data/`.

- **`AuditCopertinaQCPTests`** (parti 1 e 4): 13 test, di cui 3 `expectedFailure`.
- **`AuditCatalogoQCPTests`** (parte 2): 6 test.
- **`AuditCorpo26026Tests`** (parti 3 e 5; il corpo si semina una volta in `setUpTestData`): 14 test, di cui 1 `expectedFailure`.

I 4 `expectedFailure`, uno per difformità:
- `test_4_4_tre_revisioni_con_firme_prepared_checked_approved` — D1.
- `test_3_6_le_celle_vuote_del_file_restano_distinte_da_non_coinvolto` — D3.
- `test_1_la_data_nel_formato_del_documento_non_si_perde_in_silenzio` — D5.
- `test_1_il_vendor_e_quello_del_documento` — D6.

Esecuzione mirata:

```
poetry run python manage.py test core.tests.AuditCopertinaQCPTests core.tests.AuditCatalogoQCPTests core.tests.AuditCorpo26026Tests --keepdb
```

---

## Decisioni aperte

Emerse dall'audit, da decidere; qui non sono risolte.

1. **Revisioni (D1).** Storico delle revisioni con data, descrizione e firme prepared / checked / approved? Firme come nomi liberi o come utenti? Quale revisione è quella corrente? Lettera o numero, come per gli archivi?
2. **`da_proc` (D2).** Modellare la matrice saldature (PROC), permettere un riferimento scritto a mano sullo step, o stampare vuoto finché la matrice non esiste?
3. **Cella vuota contro "-" (D3).** Serve un valore "non indicato" distinto da "non coinvolto", oppure la cella vuota è un errore da correggere nella sorgente?
4. **Codici quasi uguali (D4).** Il seed deve normalizzare gli spazi quando abbina i codici, o va corretto il file?
5. **Codici in più capitoli (O4).** Il file del corpo deve indicare il capitolo, o il seed deve dedurlo dalla sezione?
6. **Riferimenti vivi o congelati (D8).** Quando Dwg n. o Doc n. cambiano, gli step `campo_piano` vanno ricalcolati (almeno quelli non corretti a mano), segnalati, o lasciati come sono?
7. **Vendor (D6).** Costante con la ragione sociale, sigla del documento ("B&R"), o campo per piano?
8. **Lingua e formato della copertina (D7).** Quali diciture userà il PDF: REQUIRED / NOT REQUIRED, H2S service, data gg/mm/aaaa? Anteprima e PDF devono coincidere?
9. **Date non ISO (D5).** Accettare gg/mm/aaaa o rifiutare con un errore? `_parse_date` è condivisa con le commesse, quindi la scelta vale anche lì.
10. **Note e foglio dedicato (O10).** Dove vivono il testo delle note richiamate dalle remarks e il foglio dedicato dei punti "(\*)"?
11. **Separatore dei compositi (O3).** Lo spazio è quello del documento stampato?
12. **Peso della pagina (O9).** 1,16 MB a 224 step è accettabile, o le sezioni chiuse vanno caricate su richiesta?
13. **Sincronizzazione dei punti (O5).** Resta una chiamata esplicita (oggi solo l'admin) o diventa automatica sulla modifica degli enti?
14. **Controprova 26004.** Senza il corpo della 26004 (15 sezioni, 104 step) il seed non si può ripetere su una configurazione diversa: va fornito il file.
