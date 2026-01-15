# amenity-stuff

TUI (Terminal UI) per analizzare file in una cartella usando un LLM locale (via Ollama) e proporre:
- categoria e anno di riferimento,
- nuovo nome significativo,
- destinazione in un archivio `{categoria}/{anno}`,
con (nelle prossime milestone) approvazione per file e applicazione delle modifiche.

## Avvio

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m archiviatore_tui --source /percorso/da/analizzare --archive /percorso/archivio
```

## Sicurezza e privacy
- Esecuzione locale: l’obiettivo è non inviare contenuti a servizi esterni.
- I file vengono letti e analizzati localmente; con OCR attivo, il testo viene estratto anche da scansioni/immagini.
- Prima di cambiare provider/modelli, verifica policy e gestione dati del provider.

## Limitazioni (aggiornate nel tempo)
- Parsing e OCR sono best-effort: alcuni file possono risultare `skipped` o avere output incompleto.
- La fase “approva e sposta” non è ancora implementata (solo proposta/preview).

## Provider LLM

La schermata iniziale prova a rilevare:
- `ollama` (se installato in PATH)

Modelli: il progetto usa un modello testuale e (per immagini) un modello vision; i nomi esatti sono configurabili.

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
