# Project status

Updated: 2026-10-03 (America/Los_Angeles). Recheck this record against the current source and Git state after subsequent changes.

## Current assessment

The v0.3.0 core implementation supports local analysis, OCR, preview correction, and safe export. The latest complete local suite passed **33 tests with no skips**, including a rerun before repository publication. See the [validation record](VALIDATION.md) and raw log.

Development started at `1d29020` (v0.2.0). The v0.3.0 implementation, tests, documentation, and evidence were published in the repository update. No v0.3.0 tag or formal release has been created. Inspect the actual Git state and preserve the existing work instead of resetting to the old baseline.

## Milestones

| Milestone | Delivered | Still to verify |
| --- | --- | --- |
| M1 Correctness and safe export | Independent chapter identities and parents, Parts and repeated numbering, section-only bookmark synthesis, Chinese and Appendix numbering, ordered contents matching, strict depth and range validation, source hashing, staged publication, regressions | Independent review and more boundary cases from real long documents |
| M2 Native OCR | Swift PDFKit/Vision helper, capability checks, versioned protocol, rendering and positions, two recognition passes, CLI options, page failure isolation, timeout/cancellation, caching | macOS 13/14 and Intel hardware; recovery under real long-running failures |
| M3 Shared plans and text | PageText / StructureEntry / SplitPlan, analysis/validation/export interfaces, layout merging, scanned contents and mixed-page analysis, text and JSON outputs | Complex layouts, poor scans, and a broader document collection |
| M4 Preview and correction | Live page status, zoom and text boxes, text and item editing, OCR alternatives, saved plans, batch processing, three themes, responsive layout | Physical Finder dragging, additional keyboard/accessibility checks, full manual desktop acceptance |
| M5 Acceptance and version preparation | 33 local tests, real annotated samples, before/after screenshots, guides, CI configuration, Git repository delivery | Remote CI, platform hardware tests, physical dragging, independent release review |

M1-M4 have implementations and local evidence, with broader acceptance still needed. **M5 is incomplete; the current state is not full release acceptance.**

## Available evidence

- Local platform: Apple Silicon arm64, macOS 27.0 (26A428), Python 3.12.0, Swift 6.4.
- 33 tests: 15 structure/export, 9 fault recovery, 5 real Vision, and 4 desktop Tk.
- The four-page image-only sample matches predefined text annotations and ranges `[[2,2],[3,3],[4,4]]`, exports three PDFs, and preserves the source hash.
- Real native tests cover mixed text on one line, Chinese omitted by the English pass, two-column scanned contents, native/scanned mixed pages, rotation, and CropBox.
- Actual Tk geometry and control-boundary tests cover widths 320/768/1024/1440. Comparison screenshots show running applications.
- `git diff --check` passed during implementation and documentation preparation.

Confidence is not accuracy; correctly recognized text may still require review. Controlled timeout/cancellation tests use substitutes and do not establish real Vision fault-pressure behavior. Parsing drag data does not establish physical Finder dragging.

## Next priorities

1. Preserve existing work, independently review the core, and rerun local tests. Reproduce failures before adding meaningful regressions and fixes.
2. Complete desktop acceptance for multiple-file dragging, OCR reruns after manual edits, boundary corrections, cancellation, and safe export. Save actual interaction evidence.
3. Broaden testing with accessible real long documents and annotations prepared before recognition, including blur, complex contents, rotation/cropping, and memory behavior.
4. Run remote CI and macOS 13/14 / Intel acceptance when authorized and equipped. Keep unsupported environments explicitly unverified.
5. Prepare a formal release after closing M5. Searchable text layers, an installer, and other-platform OCR remain future scope.

See the [handoff](HANDOFF.md) for commands and review targets.
