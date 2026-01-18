# amenity-stuff

Terminal UI to organize files using a local LLM (via Ollama) with a 2-phase workflow:
1) extract high-signal facts (no classification yet),
2) batch classify + propose coherent file names (taxonomy-driven).

Upcoming milestones include per-file approval and applying rename/move operations into an archive structured as `{category}/{year}`.

See `PROJECT_SPEC.md` for a more detailed (and up-to-date) project specification.

## Run

```bash
python3 -m venv .venv
./.venv/bin/pip install .
amenity-stuff run
```

System-wide (recommended):
```bash
pipx install git+https://github.com/elmisi/amenity-stuff.git
amenity-stuff run
```

## Performance report

After running Scan/Classify on a folder, you can print a short timing summary from the cache:

```bash
amenity-stuff report --source /path/to/folder
```

## Settings

You can change:
- output language (`auto`, `it`, `en`)
- taxonomy (allowed categories)
- models (facts / classify / vision), archive folder, filename separator, OCR mode

Press `F2` in the TUI to open Settings. Configuration is stored in `~/.config/amenity-stuff/config.json`.

Taxonomy format (one per line):
`name | description | examples` (examples are optional, separated by `;`).

Example taxonomy (Italian slugs):
```
casa | Abitazione e immobili: affitto, condominio, utenze, manutenzione, tasse/assicurazione casa | affitto; contratto locazione; condominio; amministratore; manutenzione; assicurazione casa; IMU; TARI; bolletta; luce; gas; acqua; internet; energia
acquisti | Acquisti e abbonamenti: ordini, ricevute, garanzie, servizi | ricevuta; scontrino; ordine; conferma ordine; abbonamento; rinnovo; garanzia; fattura acquisto; e-commerce; marketplace
viaggi | Viaggi e trasporti: prenotazioni, biglietti, itinerari | volo; biglietto; hotel; prenotazione; itinerario; noleggio auto; assicurazione viaggio; treno; trasporto
tasse | Tasse e pubblica amministrazione: pagamenti e comunicazioni ufficiali | F24; dichiarazione redditi; Agenzia Entrate; tributo; avviso pagamento; PagoPA; Comune; protocollo; cartella; imposta
banca | Banca e pagamenti “generici”: estratti conto e movimenti non riconducibili ad altro | estratto conto; bonifico; carta; transazione; addebito; accredito; ricevuta pagamento; conto corrente
legale | Documenti legali e compliance | contratto; termini; privacy; diffida; procura; atto; denuncia; ricorso; NDA; lettera legale
lavoro | Documenti di lavoro e professionali | busta paga; cedolino; payroll; timesheet; contratto lavoro; offerta; HR; CU/CUD; lettera assunzione; dimissioni
personale | Documenti personali, identità, lettere, appunti scritti a mano | carta d'identità; passaporto; patente; certificato; lettera personale; appunti; nota; testo canzone; poesia; scritto a mano
salute | Documenti sanitari e medici | referto; ricetta; analisi; visita; certificato medico; vaccino; fattura medica; terapia
studio | Scuola, università e formazione | attestato; certificato; diploma; transcript; materiale corso; iscrizione; esame; tesi
media | Contenuti e media: libri, foto, screenshot, audio/video | ebook; libro; articolo; foto; screenshot; scansione foto; audio; video
tecnica | Documenti tecnici: manuali, specifiche, documentazione | manuale; specifica; datasheet; documentazione API; architettura; configurazione; log; guida
sconosciuto | Non classificato / saltato |
```

## Security & Privacy
- Local-first: the goal is to avoid sending content to external services.
- Files are read and analyzed locally; when OCR is enabled, text is extracted from scans/images too.
- If you switch provider/models, review their policies and how they handle data.

## Limitations (updated over time)
- Parsing and OCR are best-effort: some files may be `skipped` or produce incomplete output.
- The “approve and move” phase is not implemented yet (proposal/preview only).

## Optional System Dependencies

### OCR for scanned PDFs and images (recommended)
If a PDF has no extractable text (i.e. it's effectively an image), or if you scan documents as images, amenity-stuff can use Tesseract OCR.

- Ubuntu / Linux Mint:
  - `sudo apt-get install tesseract-ocr tesseract-ocr-ita`

### `.doc` / `.xls` extraction (optional)
`amenity-stuff` can extract text from:
- `.docx` and `.xlsx` without extra dependencies (best-effort)
- `.doc` and `.xls` via LibreOffice (best-effort)

- Ubuntu / Linux Mint:
  - `sudo apt-get install libreoffice`

### `.rtf` extraction (optional)
RTF is supported without dependencies via a naive fallback, but you get better results with `unrtf`.

- Ubuntu / Linux Mint:
  - `sudo apt-get install unrtf`

## LLM Provider

On startup the app tries to detect:
- `ollama` (if available in `PATH`)

Models: the app uses a text model and (for images) a vision model; exact model names are configurable.

## Scan (MVP)

The table lists common formats found in the selected source folder:
- `pdf`
- images: `jpg/jpeg/png`
- office: `doc/docx/odt/xls/xlsx` (see optional dependencies above)
- text: `txt/md/json/rtf/svg/kmz`

### Keys
- `ctrl+r` reload dir
- `s` scan row (facts extraction, force)
- `S` scan pending (facts extraction)
- `c` classify row (requires `scanned`)
- `C` classify scanned (`scanned` only, per-file)
- `m` move selected eligible file to archive (`classified`, `skipped`, `error`)
- `M` move all eligible files to archive
- `x` stop current task (scan or classify)
- `enter` open selected file (default app)
- `u` unclassify selected row (keep scan results)
- `r` reset selected row (back to `pending`, invalidate cache)
- `R` reset all + clear cache (confirmation)
- `F2` settings
- `q` or `ctrl+c` quit

During extraction/classification, status transitions and the UI remains interactive while results update row by row.

Mouse text selection is supported (so you can select/copy fields like absolute paths).

### Status
The `Status` column is icon-only (with color):
- `·` pending
- `✓` scanning / classifying (running)
- `✓` scanned (facts available, not yet classified)
- `✓` classified (category/year/name proposed)
- `✗` skipped / error

### Cache (MVP)

Results are cached in `<source>/.amenity-stuff/cache.json` and reused on re-scan.

When you move files to the archive, a separate cache is maintained in `<archive>/.amenity-stuff/cache.json`,
and the source cache entries are kept with status `moved` (including `moved_to`).

An append-only move log is also written to `<archive>/.amenity-stuff/moves.jsonl` (one JSON record per moved file).
- `r` invalidates cache for the selected file
- `R` clears the cache for the whole batch
- `u` keeps scan results but clears classification fields
