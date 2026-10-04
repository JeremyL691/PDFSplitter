# User guide

[Project overview](../README.md) · [Validation record](VALIDATION.md)

## Installation and launch

Target: macOS 13+, Python 3.12, and Xcode Command Line Tools. See [validation](VALIDATION.md) for tested platforms and limits. Python needs working Tk; use a python.org Python 3.12 installation or another environment configured with Tk.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python native/build.py
python main.py --ocr-status
python main.py --gui
```

Install Xcode Command Line Tools through the system if unavailable. The Swift helper is built as `.build/vision-helper` for macOS 13 and the host architecture, independently of Python. Rebuild after changing its source. Without the helper, `--ocr off` can use pypdf text and bookmarks; pages needing OCR report explicit errors.

## Desktop workflow

- Select or drop multiple PDFs. Files are analyzed sequentially; a failed file does not block later files. The left panel shows page status and cache hits. Physical Finder dragging still needs acceptance on the tested setup.
- Navigate and zoom in `Page and text`. Click a text box to locate text; the current text line highlights its region. Overlays are not written into exported pages.
- After editing text, select `Save text`, then `Rebuild plan` in `Split plan`. Export rejects a stale plan.
- `Run OCR` accepts a page or range such as `2-5`. Manual text is preserved while new results become pending alternatives. Compare in `Candidates`, then select `Use new OCR` or `Keep edits`. Both results persist with the plan.
- Edit titles, labels, chapter assignment, and ranges. Add entries, exclude/restore, merge consecutive ranges, or divide ranges. `Boundary` navigates to the start page; check adjacent pages before export.
- Save or load JSON plans. Loading verifies the source hash. The CLI can supply a relocated input path if the content is unchanged.
- After reviewing warnings, select `Accept reviewed nonfatal warnings` before export. Invalid/overlapping ranges, changed input, and unresolved page errors still block export.
- System, light, and dark themes and reduced motion are supported. Narrow windows collapse settings and offer page/text switching; `Settings` expands controls. Keyboard actions include Tab, Space, Command-S / Control-S, Escape, and Alt-Left/Right.

## CLI

```bash
# Analyze without exporting and save a reviewable plan
python main.py book.pdf --dry-run --plan-out review.json
# Export a reviewed plan
python main.py --apply-plan review.json -o output --accept-warnings
# Supply a relocated source; content must still match the saved hash
python main.py /new/path/book.pdf --apply-plan review.json -o output
# Analyze and export directly
python main.py book.pdf --ocr auto --ocr-languages mixed --ocr-dpi 300
# Use native text only and choose a structure source
python main.py book.pdf --source outline --ocr off
python main.py book.pdf --source toc --section-depth 2
# Force recognition of the full document
python main.py book.pdf --ocr force --ocr-languages zh-Hant --ocr-dpi 450
python main.py --clear-ocr-cache
python main.py --help
```

`--source auto|outline|toc|scan` selects structure acquisition. OCR independently controls text acquisition:

| Setting | Behavior |
| --- | --- |
| `--ocr auto` | Prefer native text; OCR when effective text has fewer than 40 characters or replacement characters exceed 10%; skip clearly blank pages |
| `--ocr off` | No text recognition; the macOS helper can still provide native positions and previews |
| `--ocr force` | Recognize the full document again, bypassing page cache; the GUI can rerun selected pages |
| `--ocr-languages mixed` | English pass plus a Chinese pass prioritizing Simplified Chinese, Traditional Chinese, then English |
| `--ocr-languages en` | Single English pass |
| `--ocr-languages zh-Hans / zh-Hant` | English pass plus a Simplified/Traditional Chinese priority pass |
| `--ocr-dpi 150 / 300 / 450` | Default 300; rendering is capped at 25 million pixels per page |
| `--no-ocr-cache` | Disable page cache reads and writes |

Mixed recognition merges by position and script. The Chinese pass supplies Chinese text; the English pass supplies matching English segments. Alternatives and model candidates are retained. **Confidence is not recognition accuracy** and is not the sole cross-language selection criterion. Low confidence or Chinese-pass conflicts require review.

Exit codes: `0` success, `1` operation failure, `2` invalid arguments, `3` review required, `130` cancelled. An unavailable section depth reports available depths instead of silently exporting whole chapters.

## Analysis, cache, and export rules

Chapters have independent identities and parents. Detection supports Parts, repeated numbering, chapter synthesis from section-only bookmarks, Appendix letters, compound English numbers, and common Chinese chapter/section numbering. Auto compares bookmark, contents, and body candidates. Contents matching uses document order and standalone headings; ordinary references are not anchors. Unconfirmed offsets and same-page boundaries trigger review. Same-page headings share the original page; the tool does not crop within pages.

Page text is acquired once and reused for contents and body analysis. Default cache: `~/Library/Caches/PDFSplitter`. Page keys include input hash, page number, system version, Vision revision, language, DPI, helper content, and processing version. Completed pages remain reusable after cancellation. `PDFSPLITTER_CACHE_DIR` isolates test caches. Cache clearing removes only tool-named cache contents.

Each page has a 60-second processing timeout. Timeout closes the helper, records the page error, and restarts for the next page. Normally one process serves the document. Cancellation terminates it, then forcibly ends it if it has not exited within two seconds. Window closure waits for work to exit and staging to be cleaned.

- Default output: `<filename> - split`; existing names allocate `(2)` and subsequent directories.
- Explicit `-o` must not exist or must be empty. Nonempty directories are never overwritten.
- Source hashes are checked before export and publication; outputs cannot overwrite the source.
- Files are built in an independent staging directory under the same parent. Page counts are checked before whole-directory publication. Failure/cancellation cleans only that staging directory.
- Omitted front matter, excluded pages, and skipped chapter introductions are recorded in the plan and manifest.

Exports include chapter PDFs, compatible `manifest.json` / `manifest.txt`, and:

- `document.txt`: final text separated by PDF page.
- `ocr.json`: positions, sources, candidates, and confidence.
- `split-plan.json`: structure, ranges, manual edits, pending alternatives, and source hash.

## Development and acceptance

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -v
# Real OCR and desktop tests need a graphical Mac session
PDFSPLITTER_NATIVE_TESTS=1 PDFSPLITTER_GUI_TESTS=1 python -m unittest discover -v
python -m tests.acceptance
```

CI configuration covers Linux core and macOS native tests; desktop interaction is accepted locally. See [VALIDATION.md](VALIDATION.md) for results, annotations, and comparisons.

Python APIs: `analyze_pdf(...) -> SplitPlan`, `validate_plan(...)`, and `export_plan(...)`. Compatible `split_pdf(...)` combines analysis/export, retaining existing return fields and adding plan diagnostics.

## Scope and limitations

Complex contents, handwriting, skew/blur, formulas, charts, and unusual layouts require manual review. Layout recovery uses positional heuristics and cannot guarantee every multi-column document. Vision updates can change results. Searchable PDF layers, an application installer, and OCR on other platforms are not available. Encrypted PDFs are not supported. macOS 13/14, Intel Macs, and other Python versions have not received local hardware acceptance.

[MIT License](../LICENSE).
