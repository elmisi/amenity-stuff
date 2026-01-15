# Progetto: Archiviatore TUI con LLM locale

## Obiettivo
Realizzare una applicazione **TUI (Terminal User Interface)** che analizza il contenuto di una cartella, propone per ogni file una **catalogazione basata sul contenuto** (categoria + anno di riferimento) e un **nuovo nome significativo**, e **solo dopo approvazione dell’utente per file** sposta/rinomina i file in un archivio organizzato in cartelle `{categoria}/{anno}`.

## Ambito (MVP)
Supporto iniziale a:
- **PDF** (estrazione testo da PDF “testuali”; scansioni/OCR come estensione successiva).
- **JPG/JPEG** (descrizione del contenuto immagine tramite modello “vision” locale, se disponibile; fallback senza classificazione se non disponibile).

Estensioni successive: PNG, DOCX, TXT/MD, EML, XLSX, ecc.

## Requisiti funzionali

### 1) Scansione input
- L’utente seleziona una **cartella sorgente** da analizzare.
- L’app elenca i file (ricorsivo configurabile) e filtra per tipi supportati.
- Deve essere possibile limitare il carico:
  - `max_files` (es. 100 per batch),
  - profondità massima,
  - esclusioni per pattern (es. `node_modules`, `.git`, `*.tmp`).

### 2) Estrazione contenuto
Per ogni file:
- **PDF**
  - Estrarre testo se presente (senza OCR nell’MVP).
  - Se il testo non è estraibile o è vuoto: il file viene marcato come **non classificabile** (skip) nell’MVP.
- **JPG/JPEG**
  - Se esiste un provider LLM “vision” locale: ottenere una descrizione (caption) del contenuto.
  - Se non esiste: il file viene marcato come **non classificabile** (skip).

### 3) Analisi semantica e metadati
Per ogni file classificabile, l’LLM produce una proposta strutturata con:
- **Riassunto** (1–3 righe).
- **Categoria** (da un set generale predefinito ma configurabile).
- **Anno di riferimento** (primary): “a quale anno si riferisce il documento”.
- **Anno di produzione** (secondary): tipicamente derivabile da metadata filesystem o dal contenuto; se non disponibile -> `unknown`.
- **Nuovo nome suggerito**: descrittivo del contenuto, senza includere categoria/anno salvo manchino altri dati utili.
- **Confidenza** e/o motivazione breve (utile per decidere skip automatico).

Regole anno:
- L’LLM deve tentare prima l’**anno di riferimento** dal contenuto (es. “dichiarazione 2022”, “bilancio 2021”).
- In seconda battuta, proporre **anno di produzione** (es. data firma/emissione; se non disponibile, data file system).
- Se più anni: scegliere l’anno “principale” (document year) e riportare l’altro come secondario se rilevante.

### 4) Catalogazione (tassonomia di base)
Default iniziale (configurabile) pensato per uso generico:
- `finance` (fatture, ricevute, estratti conto, tasse)
- `legal` (contratti, privacy, certificati)
- `work` (documenti lavoro, progetti)
- `personal` (documenti personali non legali, note)
- `medical` (referti, ricette, visite)
- `education` (corsi, attestati)
- `media` (foto, immagini non-documentali)
- `technical` (manuali, schede tecniche)
- `unknown` (fallback)

Nota: per immagini “fotografiche”, spesso la categoria sarà `media` e l’anno di riferimento potrà essere `unknown` o derivato da EXIF (estensione successiva).

### 5) Lista di lavoro (TUI interattiva)
La TUI mostra una tabella con righe = file e colonne minime:
- **File originale** (path relativo/assoluto)
- **Nuovo nome proposto**
- **Categoria + anno (riferimento)** (es. `finance/2022` oppure `unknown/unknown`)
- **Nuova posizione nell’archivio** (path completo risultante)
- **Stato**: `pending / approved / rejected / skipped / error`

Azioni nella TUI (MVP):
- Navigazione righe, preview sintetica (riassunto) e motivazione/confidenza.
- Edit inline di: nome, categoria, anno (e opzionalmente anno produzione).
- Approva/rifiuta per file.
- Filtri: mostra solo `pending`, solo `skipped`, solo `error`.
- Comando “Applica” che esegue lo spostamento **solo** per i file `approved`.

### 6) Esecuzione (dry-run + apply)
- Default: **dry-run** (nessun file spostato).
- “Apply”: sposta e rinomina i file approvati nell’**archivio**:
  - destinazione: `{archive_root}/{categoria}/{anno}/<nuovo_nome>.<ext>`
  - se `anno` non disponibile: usare `unknown` (configurabile).
  - se collisione nome: aggiungere suffisso incrementale o hash breve (configurabile).
- Gestire in modo sicuro:
  - creare cartelle mancanti,
  - preservare estensione,
  - sanitizzare nome file (caratteri proibiti, spazi multipli, lunghezza max).

### 7) Esclusioni e gestione fallimenti
- Se il modello non capisce / output non parseabile / confidenza bassa:
  - segnare `skipped` e non proporre move.
- Errori di I/O o permessi:
  - segnare `error` con motivo.

## Requisiti non funzionali
- **Locale by default**: nessun invio dati a servizi esterni.
- **Prestazioni**: supporto a migliaia di file tramite:
  - batching (`max_files`),
  - cache risultati (hash contenuto o mtime+size) per evitare rianalisi,
  - rate-limit / parallelismo controllato.
- **Tracciabilità**:
  - file di log dell’operazione,
  - “piano di spostamento” esportabile (es. JSON/CSV) per revisione/backup.
- **Reversibilità (estensione consigliata)**:
  - scrivere un `operations_log.jsonl` per permettere un comando `undo` (dopo apply).

## LLM locale: strategia di rilevamento e selezione
L’app deve tentare di usare il “miglior” provider disponibile, in questo ordine (configurabile):
1. **Ollama** (se `ollama` è installato e server attivo).
   - Modello testo: es. `llama3`/`mistral` (dipende da cosa è presente).
   - Modello vision (per JPG): es. `llava` o altro modello multimodale disponibile in locale.
2. **llama.cpp** (se binario disponibile + modello GGUF configurato).
3. Fallback: nessun LLM -> solo scanning e tabella “skipped”.

Requisito: all’avvio, una fase di **discovery** ispeziona l’ambiente locale (in particolare `/home/elmisi/Project` e PATH) per capire cosa è installato e proporre un default.

## Prompting e formato output
Per robustezza, l’LLM deve restituire output in un formato **strettamente parseabile**:
- JSON con schema definito (campi: `summary`, `category`, `reference_year`, `production_year`, `proposed_name`, `confidence`, `notes`).
- Se parsing fallisce: `skipped`.

Lingue:
- Input documenti IT/EN; prompt bilingue o istruzioni per rispondere in IT con termini neutri.

## Configurazione
Config file (es. `config.toml` o `config.yaml`) con:
- `source_root`
- `archive_root`
- `max_files`
- `recursive`, `max_depth`
- `include_extensions`, `exclude_patterns`
- `categories` (lista)
- `unknown_year_label` (default `unknown`)
- `provider_preference` + modelli
- `dry_run_default` (true)
- regole naming (max length, collision strategy)

## Flusso utente (alto livello)
1. Avvio TUI, scelta cartella sorgente (o da config/argomento).
2. Discovery provider LLM e scelta modello (auto + override).
3. Scansione file (con limite batch).
4. Analisi file -> popolamento tabella con proposte o `skipped`.
5. Revisione: edit/approve/reject per riga.
6. “Apply”: move/rename dei file approvati, scrittura log operazioni.

## Milestone suggerite
1. Skeleton app + config + scanning + tabella TUI (anche senza LLM).
2. Provider Ollama testo (PDF) + JSON parsing + confidenza/skip.
3. Provider vision (JPG) se modello disponibile.
4. Apply con dry-run, collision handling, log operazioni.
5. Cache + batching + export piano (CSV/JSON).
6. Estensioni (OCR per PDF scansiti, altri formati, undo).

