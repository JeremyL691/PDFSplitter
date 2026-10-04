# Contributing

Read [project status](docs/STATUS.md), the [development handoff](docs/HANDOFF.md), and the [validation record](docs/VALIDATION.md) first. The current priority is completing v0.3.0 correctness, desktop interaction, and compatibility acceptance.

## Development environment

Use Python 3.12. Native OCR requires macOS and Xcode Command Line Tools. Desktop tests additionally require working Tk and a graphical session.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python native/build.py
python main.py --ocr-status
```

Do not commit `.build/`, `.codegraph/`, or runtime caches. Page caches default to `~/Library/Caches/PDFSplitter`; use `PDFSPLITTER_CACHE_DIR` to isolate test data.

## Validate changes

```bash
# Core and recovery tests; native and GUI tests are skipped unless enabled
python -m unittest discover -v

# Enable all tests on a Mac with a graphical session
PDFSPLITTER_NATIVE_TESTS=1 PDFSPLITTER_GUI_TESTS=1 \
python -m unittest discover -v

# Manual desktop acceptance
python -m tests.gui_demo --theme light
git diff --check
```

`python -m tests.acceptance` regenerates the annotated sample and acceptance records in the repository. Review the input, plan, and matching hashes together. Record the platform and validation scope when submitting evidence.

Provide a reproducible input or meaningful regression for a bug fix. OCR claims need real Vision evidence. Fault substitutes, drag-data parsing, and Tk geometry tests each have specific limits and do not replace full external interaction. Check GUI changes at widths 320, 768, 1024, and 1440 in light and dark themes.

## Issues and pull requests

Include the operating system, architecture, Python version, reproduction steps, expected and actual behavior, and logs or a minimal PDF you can share publicly. For boundary issues, distinguish physical PDF page numbers from printed page numbers. Do not upload documents you cannot share publicly.

Describe the trigger, resulting behavior, actual validation, and remaining limitations in a PR. For structure or export changes, verify unchanged input content, valid ranges, and agreement between files and manifests. Update the relevant user documentation and validation record.

Keep untested platforms and unexecuted CI marked as pending. A deployment target or local passing suite does not establish platform acceptance.
