# Changelog

## v0.3.0 - Development preview

The implementation is available in the repository; formal release acceptance remains incomplete. See [project status](docs/STATUS.md) and [validation](docs/VALIDATION.md) for evidence and open items.

### Added

- Native macOS PDFKit / Vision OCR, English and Chinese recognition passes, text boxes, and alternatives.
- Shared page text, structure, and split-plan models with separate analysis, validation, and export interfaces.
- Page previews, text correction, chapter-range editing, saved plans, and conflict handling for OCR reruns.
- Per-page status, caching, cancellation, isolated page failures, and batch processing.
- CLI OCR settings, dry-run, apply-plan, explicit warning acceptance, and a review exit code.
- Final text, OCR JSON, and plan JSON exports; native tests, annotated samples, and CI configuration.

### Fixed

- Repeated chapter numbers, Part parents, chapter synthesis from section-only bookmarks, and same-page heading groups.
- Chinese numbering, Appendix letters, compound English numbers, body references, and contents-page mapping.
- Invalid depths, output paths, duplicate names, page ranges, and input consistency checks.
- Output overwrite and stale-file risks through independent staging and whole-directory publication.

### Pending

Physical Finder drag-and-drop, remote CI, older macOS / Intel validation, and complex real-document acceptance. Searchable PDF layers, an installer, and OCR on other platforms are outside this iteration.

## v0.2.0

Previous baseline at commit `1d29020`. v0.3.0 adds the analysis and review workflow and native OCR on top of that version.
