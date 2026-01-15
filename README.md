# amenity-stuff

Terminal UI to analyze files in a folder using a local LLM (via Ollama) and propose:
- category and reference year,
- a more meaningful file name,
- a target location in an archive structured as `{category}/{year}`,
with (in upcoming milestones) per-file approval and applying changes.

## Run

```bash
python3 -m venv .venv
./.venv/bin/pip install .
amenity-stuff
```

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
- `s` rescan
- `a` analyze `pending` files (LLM)
- `c` stop analysis (you can restart with `a`)
- `enter/space` pin/unpin the details panel (below the table)
- `A` force reanalyze all (reset + clear cache)
- `R` force reanalyze selected row
- `q` or `ctrl+c` quit

During `a`, status transitions to `analysis` and the UI remains interactive while results update row by row.

### Status
The `Status` column includes a marker:
- `· pending` discovered, waiting
- `… analysis` being analyzed
- `✓ ready` proposal available
- `↷ skipped` not classifiable / low confidence
- `× error` I/O or Ollama error
