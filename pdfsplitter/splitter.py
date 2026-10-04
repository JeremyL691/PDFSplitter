from __future__ import annotations
from collections import Counter
from dataclasses import asdict
import ctypes
import errno
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata
from typing import Any
from pypdf import PdfReader, PdfWriter
from pypdf.generic import Destination
from .headings import parse_heading
from .models import StructureEntry, SplitItem, SplitPlan, PageText, TextBlock, Diagnostic, OCROptions, ReviewRequired, CancelledError, check_cancel, input_hash, VERSION
from .ocr import extract_pages, reading_order, has_cjk
BookmarkEntry = StructureEntry

def sanitize_name(value: str) -> str:
    value = unicodedata.normalize('NFC', value).replace(':', ' -').replace('/', ' - ').replace('\\', ' - ')
    value = re.sub('[\\x00-\\x1f<>"|?*]', '', value)
    value = re.sub('\\s+', ' ', value).strip(' .') or 'Untitled'
    while len(value.encode('utf-8')) > 220:
        value = value[:-1]
    return value

def _strip_number_prefix(title: str) -> str:
    heading = parse_heading(title)
    return heading.title or title if heading else title

def _key(value: str) -> str:
    return ''.join((c.casefold() for c in value if c.isalnum()))

def _section_label(label: tuple[int, ...]) -> str:
    return '.'.join(map(str, label))

def _identify(entries: list[StructureEntry]) -> list[StructureEntry]:
    used = set()
    result = []
    identities = Counter()
    for index, e in enumerate(entries):
        h = parse_heading(e.title)
        if not e.kind:
            e.kind = h.kind if h else 'chapter' if e.level == 1 else 'section'
        if not e.display_label:
            e.display_label = h.display if h else _section_label(e.label)
        if not e.id:
            base = f'{e.source}-{e.page_index}-{e.kind}-{_section_label(e.label)}'
            identities[base] += 1
            e.id = base + f'-{identities[base]}'
        key = (e.parent_id, e.kind, _key(e.title), e.page_index)
        if key not in used:
            result.append(e)
            used.add(key)
    return result

def extract_bookmark_entries(reader: PdfReader) -> list[StructureEntry]:
    collected = []

    def walk(items, level=1, parent=None):
        previous = parent
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1, previous)
                continue
            if not isinstance(item, Destination):
                continue
            try:
                page = reader.get_destination_page_number(item)
            except Exception:
                continue
            if not isinstance(page, int) or not 0 <= page < len(reader.pages):
                continue
            heading = parse_heading(str(item.title))
            if not heading:
                continue
            entry = StructureEntry(str(item.title).strip(), page, level, heading.label, f'outline-{len(collected)}', parent, heading.kind, heading.display, 'outline', evidence=['PDF bookmark'])
            collected.append(entry)
            previous = entry.id
    walk(getattr(reader, 'outline', []) or [])
    return _identify(collected)

def _dedupe_and_sort_bookmarks(entries):
    return sorted(_identify(entries), key=lambda e: (e.page_index, e.level))

def _filter_redundant_chapter_entries(entries):
    return _identify(entries)

def _normalize(entries: list[StructureEntry]) -> list[StructureEntry]:
    entries = _identify(sorted(entries, key=lambda e: (e.page_index, e.level)))
    result = []
    part = None
    chapter = None
    last_section = None
    known = {e.id: e for e in entries}
    for entry in entries:
        if entry.kind == 'part':
            part = entry
            chapter = None
            last_section = None
        elif entry.kind == 'chapter':
            if not entry.parent_id and part:
                entry.parent_id = part.id
            chapter = entry
            last_section = None
        elif entry.kind == 'section':
            original_parent = known.get(entry.parent_id)
            parent = original_parent
            visited = set()
            while parent and parent.kind == 'section':
                if parent.id in visited:
                    raise ValueError('Cyclic chapter hierarchy.')
                visited.add(parent.id)
                parent = known.get(parent.parent_id)
            if parent and parent.kind == 'chapter':
                chapter = parent
            if len(entry.label) == 1 and chapter:
                entry.label = chapter.label + entry.label
            compatible = chapter is not None and (not chapter.label or not entry.label or entry.label[0] == chapter.label[0])
            reset = not parent and last_section is not None and (entry.label <= last_section.label) and (entry.page_index > last_section.page_index)
            if not compatible or reset:
                label = (entry.label[0],) if entry.label else ()
                chapter = StructureEntry(f'Chapter {_section_label(label)}', entry.page_index, max(1, entry.level - 1), label, f'synthetic-{entry.id}', part.id if part else None, 'chapter', _section_label(label), entry.source, evidence=['Synthesized from consecutive sections'])
                result.append(chapter)
                known[chapter.id] = chapter
            if not original_parent or original_parent.kind != 'section':
                entry.parent_id = chapter.id
            last_section = entry
        result.append(entry)
    return result

def _page_headings(pages: list[PageText], skip: set[int] | None=None) -> list[StructureEntry]:
    found = []
    for page in pages:
        if skip and page.page_no - 1 in skip:
            continue
        blocks = reading_order(page.blocks)
        lines = [b for b in blocks if b.text.strip()]
        for index, block in enumerate(lines[:12]):
            if block.bbox and block.bbox[1] > 0.55:
                continue
            title = block.text.strip()
            if re.match('^\\d+\\s+(Chapter|Section)\\b', title, re.I):
                continue
            if re.search('\\.{2,}\\s*\\d+$', title):
                continue
            if re.fullmatch('\\d+', title) and index + 1 < len(lines):
                title += ' ' + lines[index + 1].text.strip()
            h = parse_heading(title)
            if h and (not h.title) and (index + 1 < len(lines)) and (not parse_heading(lines[index + 1].text)):
                title += ' ' + lines[index + 1].text.strip()
                h = parse_heading(title)
            if not h or len(title) > 180 or (not re.search('[A-Za-z\\u3400-\\u9fff]', h.title or title)):
                continue
            found.append(StructureEntry(title, page.page_no - 1, len(h.label), h.label, kind=h.kind, display_label=h.display, source='scan', evidence=['Standalone heading line']))
    counts = Counter((_key(e.title) for e in found))
    return _identify([e for e in found if counts[_key(e.title)] < 4])

def _toc_raw(pages: list[PageText]) -> tuple[list[StructureEntry], set[int]]:
    start = next((p.page_no - 1 for p in pages[:40] if re.search('\\bcontents\\b|目录|目錄', p.text, re.I)), None)
    if start is None:
        return ([], set())
    entries = []
    span = set()
    for p in pages[start:start + 6]:
        rows = []
        blocks = reading_order(p.blocks)
        for i, b in enumerate(blocks):
            line = b.text.strip()
            m = re.match('^(.+?)\\s*\\.{2,}\\s*(\\d{1,4})$', line) or re.match('^(.+?)\\s+(\\d{1,4})$', line)
            if m and parse_heading(m.group(1)):
                rows.append((m.group(1), int(m.group(2))))
                continue
            if not parse_heading(line):
                continue
            if b.bbox:
                candidates = [v for v in blocks if v.bbox and v.text.strip().isdigit() and (v.bbox[0] > b.bbox[0] + b.bbox[2] - 0.01) and (abs(v.bbox[1] - b.bbox[1]) < max(0.012, b.bbox[3] * 0.65))]
                if candidates:
                    rows.append((line, int(min(candidates, key=lambda v: v.bbox[0]).text.strip())))
                    continue
            if i + 1 < len(blocks) and blocks[i + 1].text.strip().isdigit():
                rows.append((line, int(blocks[i + 1].text.strip())))
        if p.page_no - 1 != start and len(rows) < 2:
            break
        span.add(p.page_no - 1)
        for title, printed in rows:
            h = parse_heading(title)
            entries.append(StructureEntry(title, -1, len(h.label), h.label, kind=h.kind, display_label=h.display, source='toc', printed_page=printed))
    return (entries, span)

def _toc_resolve(raw: list[StructureEntry], heads: list[StructureEntry], reader, span: set[int], warnings: list[Diagnostic]):
    resolved = []
    previous = -1
    chapter = None
    offset = None
    for entry in raw:
        matches = [e for e in heads if e.page_index not in span and _key(e.title) == _key(entry.title) and (e.page_index >= previous)]
        if matches:
            chosen = min(matches, key=lambda e: e.page_index)
            if resolved and entry.kind == 'chapter' and (chosen.page_index == previous):
                matches = [e for e in matches if e.page_index > previous]
                if not matches:
                    continue
                chosen = min(matches, key=lambda e: e.page_index)
            entry.page_index = chosen.page_index
            entry.evidence = ['Standalone body heading']
            if entry.kind == 'chapter':
                chapter = entry
                offset = entry.page_index - entry.printed_page
            elif offset is not None and abs(entry.page_index - (entry.printed_page + offset)) > 2:
                warnings.append(Diagnostic('page_offset_conflict', f'TOC page offset conflicts with heading: {entry.title}', page_no=entry.page_index + 1))
        else:
            labels = getattr(reader, 'page_labels', []) or []
            candidates = [i for i, label in enumerate(labels) if label == str(entry.printed_page) and i not in span and (i >= previous)]
            predicted = entry.printed_page + offset if offset is not None else candidates[0] if len(candidates) == 1 else None
            if predicted is None or not 0 <= predicted < len(reader.pages):
                warnings.append(Diagnostic('unresolved_toc', f'Cannot locate TOC heading: {entry.title}'))
                continue
            if predicted < previous:
                warnings.append(Diagnostic('nonmonotonic_toc', f'TOC heading is out of order: {entry.title}'))
                continue
            entry.page_index = predicted
            entry.evidence = ['Predicted from page labels/offset']
            warnings.append(Diagnostic('unverified_boundary', f'Confirm predicted heading: {entry.title}', page_no=predicted + 1))
        resolved.append(entry)
        previous = entry.page_index
    return _identify(resolved)

def _proxy_pages(reader):
    return [PageText(i + 1, [TextBlock(t) for t in (p.extract_text() or '').splitlines() if t.strip()]) for i, p in enumerate(reader.pages)]

def extract_scanned_entries(reader):
    pages = _proxy_pages(reader)
    _, span = _toc_raw(pages)
    return _page_headings(pages, span)

def extract_toc_entries(reader):
    pages = _proxy_pages(reader)
    raw, span = _toc_raw(pages)
    return _toc_resolve(raw, _page_headings(pages, span), reader, span, [])

def load_structure(reader, source='auto'):
    if source not in {'auto', 'outline', 'toc', 'scan'}:
        raise ValueError('Unsupported source')
    pages = _proxy_pages(reader)
    return _detect(reader, pages, source, [])

def _detect(reader, pages, source, warnings):
    raw, span = _toc_raw(pages)
    heads = _page_headings(pages, span)
    candidates = {'scan': heads, 'outline': extract_bookmark_entries(reader)}
    toc_warnings = []
    candidates['toc'] = _toc_resolve(raw, heads, reader, span, toc_warnings)
    if source == 'auto':

        def score(pair):
            name, entries = pair
            unique = {(e.kind, e.page_index, e.label) for e in entries}
            if not entries:
                return -1
            order_errors = sum((a.page_index > b.page_index for a, b in zip(entries, entries[1:])))
            coverage = (max((e.page_index for e in entries)) - min((e.page_index for e in entries))) / max(1, len(reader.pages))
            body_keys = {(h.page_index, _key(h.title)) for h in heads}
            title_evidence = sum(((e.page_index, _key(e.title)) in body_keys for e in entries)) / len(entries)
            return sum((3 if kind == 'chapter' else 1 if kind == 'section' else 0 for kind, page, label in unique)) + {'outline': 2, 'toc': 1, 'scan': 0}[name] + coverage + title_evidence - 4 * order_errors
        chosen = max(candidates.items(), key=score)[0]
        if chosen != 'outline' and candidates['outline']:
            warnings.append(Diagnostic('partial_outline', 'Bookmarks were incomplete; a richer structure was selected.', 'info'))
    else:
        chosen = source
    if chosen == 'toc':
        warnings.extend(toc_warnings)
    return (_normalize(candidates[chosen]), chosen)

def build_split_items(entries, total_pages, include_chapter_intro=True, max_section_depth=None):
    if max_section_depth is not None and (type(max_section_depth) is not int or max_section_depth < 1):
        raise ValueError('Section depth must be a positive integer.')
    entries = _normalize(entries)
    from copy import deepcopy
    entries = deepcopy(entries)
    chapter_groups = {}
    for entry in entries:
        if entry.kind == 'chapter':
            chapter_groups.setdefault(entry.page_index, []).append(entry)
    aliases = {}
    for group in chapter_groups.values():
        first = group[0]
        if len(group) > 1:
            first.title = ' + '.join((e.title for e in group))
            for entry in group[1:]:
                aliases[entry.id] = first.id
    chapters = [group[0] for group in chapter_groups.values()]
    sections = [e for e in entries if e.kind == 'section']
    for section in sections:
        section.parent_id = aliases.get(section.parent_id, section.parent_id)
    if not chapters:
        raise ValueError('No chapter entries were found. Add a manual split plan or change detection/OCR settings.')
    depths = Counter((len(e.label) for e in sections))
    if max_section_depth is not None and sections and (max_section_depth not in depths):
        raise ValueError(f'No sections at depth {max_section_depth}. Available depths: {sorted(depths)}')
    if max_section_depth is not None and (not sections) and (max_section_depth != 1):
        raise ValueError('No sections found at the requested depth. Available depth: 1')
    depth = max_section_depth if max_section_depth is not None else max(depths, key=lambda d: (depths[d], -d)) if depths else None
    selected = [e for e in sections if len(e.label) == depth]
    items = []
    used = {}
    by_id = {e.id: e for e in entries}
    boundaries = sorted({e.page_index for e in entries if e.kind in {'chapter', 'part'}})

    def unique(base):
        key = base.casefold()
        used[key] = used.get(key, 0) + 1
        return base if used[key] == 1 else f'{base} ({used[key]})'

    def chapter_of(section):
        parent = by_id.get(section.parent_id)
        seen = set()
        while parent and parent.kind == 'section':
            if parent.id in seen:
                raise ValueError('Cyclic chapter hierarchy.')
            seen.add(parent.id)
            parent = by_id.get(parent.parent_id)
        return aliases.get(parent.id, parent.id) if parent else None
    for chapter in chapters:
        following = next((p for p in boundaries if p > chapter.page_index), total_pages)
        siblings = [s for s in selected if chapter_of(s) == chapter.id and chapter.page_index <= s.page_index < following]
        title = _strip_number_prefix(chapter.title)
        label = chapter.display_label or _section_label(chapter.label)
        parent = by_id.get(chapter.parent_id)
        prefix = sanitize_name(f'Part {parent.display_label} - {_strip_number_prefix(parent.title)}') + '/' if parent and parent.kind == 'part' else ''
        directory = prefix + unique(sanitize_name(f'Chapter {label} - {title}'))
        if not siblings:
            items.append(SplitItem(label, title, label, title, chapter.page_index + 1, following, directory, sanitize_name(f'01 {title}') + '.pdf', [e.id for e in chapter_groups[chapter.page_index]], part_id=chapter.parent_id))
            continue
        if include_chapter_intro and chapter.page_index < siblings[0].page_index:
            items.append(SplitItem(label, title, '00', 'Chapter Intro', chapter.page_index + 1, siblings[0].page_index, directory, '00 Chapter Intro.pdf', [e.id for e in chapter_groups[chapter.page_index]], part_id=chapter.parent_id))
        grouped = {}
        for section in siblings:
            grouped.setdefault(section.page_index, []).append(section)
        starts = list(grouped)
        for index, start in enumerate(starts):
            group = grouped[start]
            end = starts[index + 1] if index + 1 < len(starts) else following
            names = ' + '.join((_strip_number_prefix(e.title) for e in group))
            display = ' + '.join((e.display_label or _section_label(e.label) for e in group))
            items.append(SplitItem(label, title, display, names, start + 1, end, directory, sanitize_name(f'{index + 1:02d} {display} {names}') + '.pdf', [e.id for e in group], part_id=chapter.parent_id))
    for part in [e for e in entries if e.kind == 'part']:
        children = [e for e in chapters if e.parent_id == part.id]
        if children and part.page_index < children[0].page_index and include_chapter_intro:
            title = _strip_number_prefix(part.title)
            directory = sanitize_name(f'Part {part.display_label} - {title}')
            items.append(SplitItem(part.display_label, title, '00', 'Part Intro', part.page_index + 1, children[0].page_index, directory, '00 Part Intro.pdf', [part.id], part_id=part.id))
    return sorted(items, key=lambda i: (i.start_page, i.end_page))

def _text_diagnostics(pages):
    warnings = []
    for page in pages:
        if page.status == 'error':
            warnings.append(Diagnostic('page_error', page.error or 'Page extraction failed.', 'error', page.page_no))
    for page in pages:
        if any((b.confidence is not None and b.confidence < 0.45 for b in page.blocks)):
            warnings.append(Diagnostic('low_confidence', 'Some OCR text has low model confidence; inspect this page.', page_no=page.page_no))
        if any((has_cjk(b.text) and any((c.get('source') == 'ocr_en' and has_cjk(c.get('text', '')) and (_key(c['text']) != _key(b.text)) for c in b.candidates)) for b in page.blocks)):
            warnings.append(Diagnostic('ocr_disagreement', 'English and Chinese passes disagree on Chinese text; inspect candidates.', page_no=page.page_no))
    return warnings

def analyze_pdf(input_pdf: Path, source='auto', include_chapter_intro=True, max_section_depth=None, *, ocr_options=None, progress_callback=None, cancel_token=None) -> SplitPlan:
    input_pdf = Path(input_pdf).expanduser().resolve()
    check_cancel(cancel_token)
    if source not in {'auto', 'outline', 'toc', 'scan'}:
        raise ValueError('Unsupported detection source.')
    if max_section_depth is not None and (type(max_section_depth) is not int or max_section_depth < 1):
        raise ValueError('Section depth must be a positive integer.')
    digest = input_hash(input_pdf)
    reader = PdfReader(input_pdf)
    if reader.is_encrypted:
        raise ValueError('Password-protected PDFs are not supported in this version.')
    options = ocr_options or OCROptions()
    if progress_callback:
        progress_callback({'stage': 'init', 'total': len(reader.pages)})
    pages, capability = extract_pages(input_pdf, reader, options, cancel_token, progress_callback)
    check_cancel(cancel_token)
    warnings = []
    warnings.extend(_text_diagnostics(pages))
    entries, detected = _detect(reader, pages, source, warnings)
    try:
        items = build_split_items(entries, len(reader.pages), include_chapter_intro, max_section_depth)
    except ValueError as exc:
        if 'depth' in str(exc):
            raise
        items = []
        warnings.append(Diagnostic('no_structure', str(exc), 'error'))
    for item in items:
        if len(item.entry_ids) > 1:
            warnings.append(Diagnostic('shared_page', f'Merged same-page headings: {item.section_label}', page_no=item.start_page))
    plan = SplitPlan(str(input_pdf), digest, len(reader.pages), pages, entries, items, warnings, {'version': VERSION, 'structure_source': detected, 'total_pages': len(reader.pages), 'detected_entries': len(entries), 'include_chapter_intro': include_chapter_intro, 'max_section_depth': max_section_depth, 'ocr': asdict(options), 'native': capability})
    validate_plan(plan, verify_input=False)
    if progress_callback:
        progress_callback({'stage': 'done', 'plan': plan})
    return plan

def rebuild_plan(plan: SplitPlan) -> SplitPlan:
    from copy import deepcopy
    candidate = deepcopy(plan)
    proxy = type('Reader', (), {'pages': [None] * plan.total_pages, 'page_labels': [], 'outline': []})()
    warnings = [w for w in plan.warnings if w.code in {'reocr_conflict'}]
    warnings.extend(_text_diagnostics(plan.pages))
    entries, detected = _detect(proxy, plan.pages, 'auto', warnings)
    if plan.metadata.get('structure_source') == 'outline':
        entries = deepcopy(plan.entries)
        detected = 'outline'
        heads = _page_headings(plan.pages)
        for entry in entries:
            replacements = [h for h in heads if h.page_index == entry.page_index and h.kind == entry.kind and (h.label == entry.label)]
            if len(replacements) == 1 and plan.pages[entry.page_index].source == 'user':
                entry.title = replacements[0].title
                entry.evidence.append('User-corrected page heading')
    options = plan.metadata
    try:
        rebuilt = build_split_items(entries, plan.total_pages, options.get('include_chapter_intro', True), options.get('max_section_depth'))
    except ValueError:
        if any((i.manual for i in plan.items)) and (not entries):
            rebuilt = []
        else:
            raise
    manual = [deepcopy(i) for i in plan.items if i.manual]
    reserved = {identifier for item in manual for identifier in item.entry_ids}
    candidate.items = [i for i in rebuilt if not reserved.intersection(i.entry_ids)] + manual
    candidate.entries = entries
    candidate.dirty = False
    candidate.warnings = warnings
    candidate.metadata['structure_source'] = detected
    if manual:
        candidate.warnings.append(Diagnostic('manual_preserved', 'Manual split items were preserved; review the rebuilt boundaries.'))
    for item in candidate.items:
        if len(item.entry_ids) > 1 and (not item.excluded):
            candidate.warnings.append(Diagnostic('shared_page', f'Merged same-page headings: {item.section_label}', page_no=item.start_page))
    validate_plan(candidate, verify_input=False)
    plan.items = candidate.items
    plan.entries = candidate.entries
    plan.dirty = False
    plan.warnings = candidate.warnings
    plan.metadata = candidate.metadata
    plan.omitted_pages = candidate.omitted_pages
    return plan

def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or any((p in {'..', '.'} for p in path.parts)) or ('\\' in value) or ('\x00' in value):
        raise ValueError('Unsafe output path in split plan.')
    return path

def validate_plan(plan: SplitPlan, output_dir: Path | None=None, *, verify_input=True) -> list[Diagnostic]:
    if verify_input:
        if input_hash(Path(plan.input_pdf)) != plan.input_sha256:
            raise ValueError('Input PDF changed since analysis; analyze again.')
        if len(PdfReader(plan.input_pdf).pages) != plan.total_pages:
            raise ValueError('Plan page count does not match the input PDF.')
    if not isinstance(plan.total_pages, int) or plan.total_pages < 1:
        raise ValueError('Invalid total page count.')
    occupied = set()
    targets = set()
    active = [i for i in plan.items if not i.excluded]
    for item in active:
        if type(item.start_page) != int or type(item.end_page) != int or (not 1 <= item.start_page <= item.end_page <= plan.total_pages):
            raise ValueError('Invalid split page range.')
        relative = _safe_relative(item.chapter_dir_name) / _safe_relative(item.file_name)
        key = unicodedata.normalize('NFC', str(relative)).casefold()
        if key in targets:
            raise ValueError('Duplicate output filenames in split plan.')
        targets.add(key)
        pages = set(range(item.start_page, item.end_page + 1))
        if occupied.intersection(pages):
            raise ValueError('Overlapping split page ranges. Merge or correct the items.')
        occupied.update(pages)
        if output_dir:
            target = Path(output_dir) / relative
            source = Path(plan.input_pdf).resolve()
            if target.resolve() == source or (target.exists() and os.path.samefile(target, source)):
                raise ValueError('Output would overwrite the input PDF.')
    missing = sorted(set(range(1, plan.total_pages + 1)) - occupied)
    first = min(occupied) if occupied else plan.total_pages + 1
    plan.omitted_pages = {'front_matter': [p for p in missing if p < first], 'excluded_or_intro': [p for p in missing if p >= first]}
    return plan.warnings

def _publish(stage: Path, target: Path):
    if os.uname().sysname == 'Darwin':
        libc = ctypes.CDLL(None, use_errno=True)
        # RENAME_EXCL publishes atomically and refuses to replace an existing target.
        result = libc.renamex_np(os.fsencode(stage), os.fsencode(target), ctypes.c_uint(4))
        if result != 0:
            raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()), str(target))
    else:
        if target.exists():
            raise FileExistsError(str(target))
        os.rename(stage, target)

def export_plan(plan: SplitPlan, output_dir: Path, *, accept_warnings=False, unique_output=False, progress_callback=None, cancel_token=None) -> dict[str, Any]:
    output_dir = Path(output_dir).expanduser().resolve()
    validate_plan(plan, output_dir)
    if plan.pending_pages:
        raise ReviewRequired('Compare pending OCR results before export.')
    if plan.dirty:
        raise ReviewRequired('Text changed; rebuild the split plan before export.')
    if not any((not i.excluded for i in plan.items)):
        raise ValueError('No active split items.')
    unresolved = [w for w in plan.warnings if w.severity == 'error']
    covered = {p for i in plan.items if not i.excluded for p in range(i.start_page, i.end_page + 1)}
    unresolved = [w for w in unresolved if w.code != 'no_structure' and (not (w.code == 'page_error' and w.page_no not in covered))]
    if unresolved:
        raise ReviewRequired('; '.join((w.message for w in unresolved)))
    if not accept_warnings and any((w.severity == 'warning' for w in plan.warnings)):
        raise ReviewRequired('Review warnings before export; use --accept-warnings after checking the plan.')
    if output_dir.exists():
        if unique_output:
            base = output_dir
            index = 2
            while output_dir.exists():
                output_dir = base.with_name(f'{base.name} ({index})')
                index += 1
        elif output_dir.is_dir() and (not any(output_dir.iterdir())):
            pass
        else:
            raise ValueError('Explicit output directory must be empty or absent.')
    validate_plan(plan, output_dir)
    check_cancel(cancel_token)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.pdfsplitter-', dir=output_dir.parent))
    active = [i for i in plan.items if not i.excluded]
    try:
        reader = PdfReader(plan.input_pdf)
        for n, item in enumerate(active, 1):
            check_cancel(cancel_token)
            destination = stage / _safe_relative(item.chapter_dir_name) / _safe_relative(item.file_name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            writer = PdfWriter()
            for index in range(item.start_page - 1, item.end_page):
                check_cancel(cancel_token)
                writer.add_page(reader.pages[index])
            writer.add_metadata({'/Title': item.section_title, '/Producer': f'PDFSplitter {VERSION}'})
            writer.add_outline_item(item.section_label + ' ' + item.section_title, 0)
            with destination.open('xb') as handle:
                writer.write(handle)
            if len(PdfReader(destination).pages) != item.page_count:
                raise ValueError('Exported page count verification failed.')
            if progress_callback:
                progress_callback({'stage': 'export', 'done': n, 'total': len(active)})
        manifest = {'schema_version': 2, 'input_pdf': plan.input_pdf, 'output_dir': str(output_dir), 'metadata': plan.metadata | {'text_sources': dict(Counter((p.source for p in plan.pages)))}, 'items': [asdict(i) | {'page_count': i.page_count} for i in active], 'warnings': [asdict(w) for w in plan.warnings], 'omitted_pages': plan.omitted_pages}
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        (stage / 'manifest.txt').write_text(_render_text_manifest(manifest), encoding='utf-8')
        (stage / 'document.txt').write_text('\n\n'.join((f'[PDF page {p.page_no}]\n{p.text}' for p in plan.pages)), encoding='utf-8')
        (stage / 'ocr.json').write_text(json.dumps({'pages': [asdict(p) for p in plan.pages], 'settings': plan.metadata.get('ocr')}, ensure_ascii=False, indent=2), encoding='utf-8')
        plan.save(stage / 'split-plan.json')
        check_cancel(cancel_token)
        validate_plan(plan, output_dir)
        if output_dir.exists() and output_dir.is_dir() and (not any(output_dir.iterdir())):
            output_dir.rmdir()
        _publish(stage, output_dir)
        return {'output_dir': output_dir, 'split_count': len(active), 'metadata': manifest['metadata'], 'items': active, 'plan': plan}
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise

def _render_text_manifest(manifest):
    lines = [f"Input PDF: {manifest['input_pdf']}", f"Output Dir: {manifest['output_dir']}", f"Detection Source: {manifest['metadata']['structure_source']}", f"Total PDF Pages: {manifest['metadata']['total_pages']}", f"Split Files: {len(manifest['items'])}", '']
    lines += [f"{i['chapter_dir_name']}/{i['file_name']}: PDF pages {i['start_page']}-{i['end_page']} ({i['page_count']} pages)" for i in manifest['items']]
    lines += ['', 'Warnings:'] + [w['message'] for w in manifest.get('warnings', [])]
    return '\n'.join(lines)

def split_pdf(input_pdf, output_dir, source='auto', include_chapter_intro=True, max_section_depth=None, *, ocr_options=None, accept_warnings=False, unique_output=False, progress_callback=None, cancel_token=None):
    plan = analyze_pdf(input_pdf, source, include_chapter_intro, max_section_depth, ocr_options=ocr_options, progress_callback=progress_callback, cancel_token=cancel_token)
    return export_plan(plan, output_dir, accept_warnings=accept_warnings, unique_output=unique_output, progress_callback=progress_callback, cancel_token=cancel_token)

def export_split_items(reader, input_pdf, output_dir, split_items, metadata):
    plan = SplitPlan(str(Path(input_pdf).resolve()), input_hash(Path(input_pdf)), len(reader.pages), [], [], split_items, metadata=metadata)
    return export_plan(plan, output_dir)
