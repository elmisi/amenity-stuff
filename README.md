# amenity-stuff

Terminal UI to organize files using a local LLM (via Ollama) with a 2-phase workflow:
1) extract high-signal facts (no classification yet),
2) batch classify + propose coherent file names (taxonomy-driven).

Upcoming milestones include per-file approval and applying rename/move operations into an archive structured as `{category}/{year}`.

## Run

```bash
python3 -m venv .venv
./.venv/bin/pip install .
amenity-stuff
```

## Settings

You can change:
- output language (`auto`, `it`, `en`)
- taxonomy (allowed categories)
- models (text / vision), archive folder, filename separator, OCR mode

Press `F2` in the TUI to open Settings. Configuration is stored in `~/.config/amenity-stuff/config.json`.

Taxonomy format (one per line):
`name | description | examples` (examples are optional, separated by `;`).

## Security & Privacy
- Local-first: the goal is to avoid sending content to external services.
- Files are read and analyzed locally; when OCR is enabled, text is extracted from scans/images too.
- If you switch provider/models, review their policies and how they handle data.

## Limitations (updated over time)
- Parsing and OCR are best-effort: some files may be `skipped` or produce incomplete output.
- The “approve and move” phase is not implemented yet (proposal/preview only).

## Optional System Dependencies

### OCR for scanned PDFs (recommended)
If a PDF has no extractable text (i.e. it's effectively an image), amenity-stuff can use Tesseract OCR.

- Ubuntu / Linux Mint:
  - `sudo apt-get install tesseract-ocr tesseract-ocr-ita`

## LLM Provider

On startup the app tries to detect:
- `ollama` (if available in `PATH`)

Models: the app uses a text model and (for images) a vision model; exact model names are configurable.

## Scan (MVP)

The table lists (up to `--max-files`) `pdf` and `jpg/jpeg` files found in the selected source folder.

### Keys
- `ctrl+r` reload dir
- `s` scan row (facts extraction, force)
- `S` scan pending (facts extraction)
- `c` classify row (requires `scanned`)
- `C` classify scanned (`scanned` + `classified`, for coherence)
- `x` stop current task
- `r` reset selected row (back to `pending`, invalidate cache)
- `R` reset all + clear cache (confirmation)
- `F2` settings
- `q` or `ctrl+c` quit

During extraction/classification, status transitions and the UI remains interactive while results update row by row.

Mouse text selection is supported (so you can select/copy fields like absolute paths).

### Status
The `Status` column includes a marker:
- `· pending` discovered, waiting
- `… scan` scanning (phase 1)
- `✓ scan` scanned (facts collected)
- `≈ cls` classifying (phase 2)
- `★ done` classification proposal available
- `↷ skipped` not classifiable / low confidence
- `× error` I/O or Ollama error

### Cache (MVP)

Results are cached in `<source>/.amenity-stuff/cache.json` and reused on re-scan.
- `r` invalidates cache for the selected file
- `R` clears the cache for the whole batch
