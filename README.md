# Archiviatore TUI (LLM locale)

TUI per scansionare una cartella, rilevare i provider LLM locali disponibili e (nelle prossime milestone) proporre catalogazione/rinomina/spostamento con approvazione per file.

## Avvio

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m archiviatore_tui --source /percorso/da/analizzare --archive /percorso/archivio
```

## Note LLM locali (discovery)

La schermata iniziale prova a rilevare:
- `ollama` (se installato in PATH)

### Modelli consigliati (setup attuale)
Con GPU NVIDIA GTX 1060 6GB e 32GB RAM, i modelli Ollama scaricati e adatti come base sono:
- Testo (catalogazione/anno/rename): `qwen2.5:7b-instruct`
- Immagini (descrizione contenuto): `moondream`

## Scansione (MVP)

La tabella elenca (fino a `--max-files`) i file `pdf` e `jpg/jpeg` trovati nella cartella sorgente.

### Tasti
- `s` per riscansionare
- `a` per avviare l’analisi (LLM) dei file in `pending`
- `c` per stoppare l’analisi (poi puoi ripartire con `a`)
- `invio/spazio` per bloccare/sbloccare il pannello dettagli (mostrato sotto la tabella)
- `q` o `ctrl+c` per uscire

Durante `a`, lo stato passa a `analysis` e la TUI resta utilizzabile mentre i risultati arrivano riga per riga.

### Stati
La colonna `Stato` include un marcatore:
- `· pending` trovato, in attesa
- `… analysis` in analisi
- `✓ ready` proposta pronta
- `↷ skipped` non classificabile / confidenza bassa
- `× error` errore I/O o Ollama

## Limitazioni attuali
- PDF: niente OCR (PDF “scansione” -> `skipped`).
- Nessuna fase di approvazione/spostamento ancora (solo proposta/preview).
