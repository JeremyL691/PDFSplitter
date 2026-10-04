# Development handoff

Updated: 2026-10-03 (America/Los_Angeles). Run commands from the repository root unless stated otherwise.

## Objective and scope

Continue v0.3.0, prioritizing open M5 acceptance gates and defects found through independent review. Read [STATUS.md](STATUS.md), [VALIDATION.md](VALIDATION.md), and [README.md](../README.md). Use current source and fresh results; historical logs do not prove that later changes pass.

Keep Python 3.12, Tkinter/ttk, pypdf, and the small Swift PDFKit/Vision helper. Preserve existing product copy, orange accents, system fonts, and the Soft 5/5/5 design. OCR serves structure recognition and text outputs; split PDFs always use original pages. Searchable layers, an installer, and other-platform OCR are outside this closeout.

Development began at `1d29020` (v0.2.0). The implementation and handoff were published in the repository update. Start with `git status --short` and `git log -1`; inspect changes and preserve existing work. Do not reset/clean or overwrite the handoff. Repository publication does not complete M5 or constitute a formal release.

## Code map

| File | Responsibility |
| --- | --- |
| `pdfsplitter/models.py` | Models, plan persistence, source hashes, cancellation, OCR settings |
| `pdfsplitter/headings.py` | English/Chinese numbering, heading types and titles |
| `pdfsplitter/splitter.py` | Bookmark/contents/body candidates, scoring, range building, rebuild, validation, safe export |
| `pdfsplitter/toc_parser.py` | Compatibility objects and helpers; public entry points delegate to shared logic |
| `pdfsplitter/ocr.py` | Native subprocess, per-page timeout/cancellation, caching, pass merging, layout and preview |
| `native/vision-helper.swift` | JSON Lines protocol 1, PDFKit rendering/positions, Vision revision 3 accurate recognition |
| `native/build.py` | Builds `.build/vision-helper`, targets macOS 13, uses host architecture |
| `pdfsplitter/gui.py` | Batch files, page/text preview, corrections, OCR conflicts, plan editing, export state |
| `pdfsplitter/cli.py` | OCR settings, dry-run/apply-plan, warning acknowledgment, exit codes |
| `tests/test_core.py` / `test_recovery.py` | Structure, export, caching/faults, and CLI regressions |
| `tests/test_native.py` / `test_gui.py` | Opt-in real Vision / Tk tests |
| `tests/acceptance.py` / `gui_demo.py` | Accessible annotated sample acceptance and manual desktop entry point |
| `.github/workflows/tests.yml` | Linux core and macOS native tests; remote execution remains pending |

Core APIs: `analyze_pdf(...) -> SplitPlan`, `validate_plan(...)`, and `export_plan(...)`; `split_pdf(...)` remains compatible. Manual text and original/candidate OCR are stored separately. Stale plans and unresolved OCR alternatives must prevent accidental export.

## Resume and run

The interpreter below passed local acceptance. Default `python3` may resolve to a different version; verify Python, Tk, and dependencies first.

```bash
cd PDFSplitter
git status --short
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 --version
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 native/build.py
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 main.py --ocr-status
```

Dependencies are in `requirements.txt` and `requirements-dev.txt`. Follow the README to create a Python 3.12 virtual environment if needed. Avoid replacing a working runtime without a reason.

Full local acceptance:

```bash
PDFSPLITTER_CACHE_DIR=/private/tmp/pdfsplitter-v030-cache \
PDFSPLITTER_NATIVE_TESTS=1 PDFSPLITTER_GUI_TESTS=1 \
PYTHONDONTWRITEBYTECODE=1 \
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest discover -v

/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m tests.gui_demo --theme light
```

Real Vision and Tk execution requires normal desktop access. In the restricted agent environment, approved host execution succeeded; Swift compilation worked within the sandbox. Do not report sandbox service restrictions as product defects or count a suite with native/GUI skips as full acceptance.

`python3.12 -m tests.acceptance` regenerates annotated inputs and records in `docs/evidence`. Regenerated PDF content changes its hash: regenerate matching records and plans together and review differences. Do not mix a new sample with an old plan. Export acceptance uses temporary directories; the repository retains result records.

## Initial review targets

These are investigation targets, **not all confirmed defects**. Reproduce before describing them as current bugs:

- If the native helper is unavailable, does a pypdf extraction failure become a page error while later pages continue? Is garbled-text detection consistent across native and fallback paths?
- Do loaded manual plans adequately validate boolean page counts, page text indices, structure parents, and item references?
- Do preview and text caches invalidate consistently when the helper, system version, rotation, or crop changes?
- Can compound English numbers, wrapped contents titles, multiple columns, or repeated headers produce wrong boundaries? Are ordinary body references still rejected as anchors?
- Under real long-document pressure, do memory limits, process restart after timeout, close-during-work, and staging cleanup hold?

Preserve the core invariants: changed source hashes reject old plans; warning acknowledgment cannot bypass invalid/overlapping ranges; failure/cancellation only cleans this task's staging; explicit nonempty outputs are never overwritten; OCR reruns never silently replace manual text.

## Open acceptance and delivery

1. Physical Finder dragging. Parsing and batch tests exist, but earlier coordinate automation did not reliably generate Tk events. Verify actual dragging and state changes; calling `_on_drop` is not physical interaction evidence.
2. Remote CI. The configuration exists, but GitHub Actions is disabled and no run is available. When execution is authorized and enabled, record the commit, platform, passed/skipped/failed checks, and fixes.
3. macOS 13/14 and Intel. Only arm64 macOS 27.0 is validated. A deployment target does not replace hardware testing.
4. Large, complex real documents. The historical textbook source is missing; old outputs are not a rerun. Use accessible inputs, predefined manual annotations, and explicit review outcomes.

Update STATUS and VALIDATION as work completes, recording fresh evidence and remaining unverified scope. Keep unavailable environment gates pending while continuing independent implementation and testing. Report actual fixes, results, and open gaps rather than declaring completion from a README or historical green suite.
