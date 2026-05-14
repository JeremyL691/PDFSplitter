from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import Destination

from .toc_parser import (
    TocEntry,
    clean_toc_title,
    find_toc_page_span,
    normalize_text,
    parse_toc_entries,
    resolve_toc_page_indices,
    title_to_label,
)


SAFE_CHAR_RE = re.compile(r"[^A-Za-z0-9._'() -]+")


@dataclass(frozen=True)
class BookmarkEntry:
    title: str
    page_index: int
    level: int
    label: tuple[int, ...]


@dataclass(frozen=True)
class SplitItem:
    chapter_label: str
    chapter_title: str
    section_label: str
    section_title: str
    start_page: int
    end_page: int
    chapter_dir_name: str
    file_name: str

    @property
    def page_count(self) -> int:
        return self.end_page - self.start_page + 1


@dataclass(frozen=True)
class ChapterGroup:
    entry: BookmarkEntry
    dir_name: str
    order: int


def sanitize_name(value: str) -> str:
    value = value.replace(":", " -")
    value = value.replace("/", " - ")
    value = value.replace("\\", " - ")
    value = SAFE_CHAR_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.rstrip(".")


def _walk_outline(reader: PdfReader, items: list[Any], level: int, collected: list[BookmarkEntry]) -> None:
    for item in items:
        if isinstance(item, list):
            _walk_outline(reader, item, level + 1, collected)
            continue
        if isinstance(item, Destination):
            try:
                page_index = reader.get_destination_page_number(item)
            except Exception:
                continue
            title = str(item.title).strip()
            label = title_to_label(title)
            if label:
                collected.append(
                    BookmarkEntry(
                        title=title,
                        page_index=page_index,
                        level=level,
                        label=label,
                    )
                )


def extract_bookmark_entries(reader: PdfReader) -> list[BookmarkEntry]:
    outline = getattr(reader, "outline", None)
    if not outline:
        return []
    collected: list[BookmarkEntry] = []
    _walk_outline(reader, outline, level=1, collected=collected)
    return _dedupe_and_sort_bookmarks(collected)


def _dedupe_and_sort_bookmarks(entries: list[BookmarkEntry]) -> list[BookmarkEntry]:
    deduped: dict[tuple[tuple[int, ...], int], BookmarkEntry] = {}
    for entry in entries:
        deduped[(entry.label, entry.page_index)] = entry
    ordered = sorted(deduped.values(), key=lambda item: (item.page_index, item.level, item.label))
    return _filter_redundant_chapter_entries(ordered)


def _filter_redundant_chapter_entries(entries: list[BookmarkEntry]) -> list[BookmarkEntry]:
    filtered: list[BookmarkEntry] = []
    first_rich_chapter_by_label: dict[tuple[int, ...], BookmarkEntry] = {}

    for entry in entries:
        title = clean_toc_title(entry.title)
        normalized = title.lower()
        is_bare_chapter = bool(re.fullmatch(r"chapter\s+\d+", normalized))

        if len(entry.label) == 1 and not is_bare_chapter:
            first_rich_chapter_by_label.setdefault(entry.label, entry)
            filtered.append(entry)
            continue

        if len(entry.label) == 1 and is_bare_chapter and entry.label in first_rich_chapter_by_label:
            continue

        filtered.append(entry)

    return filtered


def extract_toc_entries(reader: PdfReader) -> list[BookmarkEntry]:
    raw_entries: list[TocEntry] = parse_toc_entries(reader)
    resolved = resolve_toc_page_indices(reader, raw_entries)
    return [
        BookmarkEntry(
            title=entry.title,
            page_index=entry.pdf_page_index if entry.pdf_page_index is not None else -1,
            level=entry.level,
            label=entry.label,
        )
        for entry in resolved
        if entry.pdf_page_index is not None
    ]


def extract_scanned_entries(reader: PdfReader) -> list[BookmarkEntry]:
    toc_span = find_toc_page_span(reader)
    toc_end_index = toc_span[1] if toc_span is not None else -1
    candidates: list[BookmarkEntry] = []
    seen: set[tuple[tuple[int, ...], int, str]] = set()

    for page_index, page in enumerate(reader.pages):
        if page_index <= toc_end_index:
            continue
        raw_lines = [normalize_text(line) for line in (page.extract_text() or "").splitlines()]
        meaningful_lines: list[str] = []
        for line in raw_lines:
            if not line:
                continue
            lowered = line.lower()
            if "page " in lowered and " of " in lowered:
                continue
            if lowered.startswith("sid:"):
                continue
            if "course notes export" in lowered:
                continue
            if lowered.startswith("generated:"):
                continue
            meaningful_lines.append(line)
            if len(meaningful_lines) >= 3:
                break

        lines = meaningful_lines
        for line in lines:
            title = clean_toc_title(line)
            if not re.search(r"[A-Za-z]", title):
                continue
            if title.startswith(("(", "[", "{")):
                continue
            if title.lower().startswith("solution"):
                continue
            label = title_to_label(title)
            if not label:
                continue
            if len(title) > 180:
                continue
            key = (label, page_index, title.lower())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                BookmarkEntry(
                    title=title,
                    page_index=page_index,
                    level=1,
                    label=label,
                )
            )
            break
    return _dedupe_and_sort_bookmarks(candidates)


def load_structure(reader: PdfReader, source: str = "auto") -> tuple[list[BookmarkEntry], str]:
    if source not in {"auto", "outline", "toc", "scan"}:
        raise ValueError(f"Unsupported source {source!r}")

    if source in {"auto", "outline"}:
        outline_entries = extract_bookmark_entries(reader)
        if outline_entries:
            return outline_entries, "outline"
        if source == "outline":
            return [], "outline"

    if source in {"auto", "toc"}:
        toc_entries = extract_toc_entries(reader)
        if toc_entries:
            return toc_entries, "toc"
        if source == "toc":
            return [], "toc"

    scanned_entries = extract_scanned_entries(reader)
    return scanned_entries, "scan"


def _chapter_label(label: tuple[int, ...]) -> str:
    return str(label[0])


def _section_label(label: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in label)


def build_split_items(
    entries: list[BookmarkEntry],
    total_pages: int,
    include_chapter_intro: bool = True,
    max_section_depth: int | None = None,
) -> list[SplitItem]:
    ordered_entries = sorted(entries, key=lambda item: (item.page_index, item.level, item.label))
    chapters = [entry for entry in ordered_entries if len(entry.label) == 1]
    sections = [entry for entry in ordered_entries if len(entry.label) >= 2]

    if not chapters and sections:
        chapters = _synthesize_chapters_from_sections(sections)
    if not chapters:
        raise ValueError("No numbered chapter entries were found.")

    chapters = sorted(chapters, key=lambda item: (item.page_index, item.level, item.label))
    if max_section_depth is not None:
        section_depth = max_section_depth
    elif sections:
        depth_counts = Counter(len(entry.label) for entry in sections)
        most_common_count = max(depth_counts.values())
        section_depth = min(
            depth for depth, count in depth_counts.items() if count == most_common_count
        )
    else:
        section_depth = None

    target_sections = (
        [entry for entry in sections if len(entry.label) == section_depth]
        if section_depth is not None
        else []
    )
    split_items: list[SplitItem] = []

    chapter_groups = _make_chapter_groups(chapters)

    for chapter_index, chapter_group in enumerate(chapter_groups):
        chapter_entry = chapter_group.entry
        next_chapter_page = (
            chapter_groups[chapter_index + 1].entry.page_index
            if chapter_index + 1 < len(chapter_groups)
            else total_pages
        )
        chapter_sections = [
            section
            for section in target_sections
            if chapter_entry.page_index <= section.page_index < next_chapter_page
        ]
        chapter_label = _section_label(chapter_entry.label)
        chapter_title = _strip_number_prefix(chapter_entry.title)
        chapter_dir_name = chapter_group.dir_name

        if not chapter_sections:
            split_items.append(
                SplitItem(
                    chapter_label=chapter_label,
                    chapter_title=chapter_title,
                    section_label=chapter_label or "01",
                    section_title=chapter_title,
                    start_page=chapter_entry.page_index + 1,
                    end_page=next_chapter_page,
                    chapter_dir_name=chapter_dir_name,
                    file_name=sanitize_name(f"01 {chapter_title}.pdf"),
                )
            )
            continue

        if include_chapter_intro and chapter_entry.page_index < chapter_sections[0].page_index:
            intro_end = chapter_sections[0].page_index
            split_items.append(
                SplitItem(
                    chapter_label=chapter_label,
                    chapter_title=chapter_title,
                    section_label="00",
                    section_title="Chapter Intro",
                    start_page=chapter_entry.page_index + 1,
                    end_page=intro_end,
                    chapter_dir_name=chapter_dir_name,
                    file_name="00 Chapter Intro.pdf",
                )
            )

        for index, section in enumerate(chapter_sections):
            next_start = (
                chapter_sections[index + 1].page_index
                if index + 1 < len(chapter_sections)
                else next_chapter_page
            )
            start_page = section.page_index + 1
            end_page = next_start
            section_label = _section_label(section.label)
            file_name = sanitize_name(f"{index + 1:02d} {section_label} {_strip_number_prefix(section.title)}.pdf")
            split_items.append(
                SplitItem(
                    chapter_label=chapter_label,
                    chapter_title=chapter_title,
                    section_label=section_label,
                    section_title=_strip_number_prefix(section.title),
                    start_page=start_page,
                    end_page=end_page,
                    chapter_dir_name=chapter_dir_name,
                    file_name=file_name,
                )
            )
    return _drop_invalid_ranges(split_items)


def _drop_invalid_ranges(items: list[SplitItem]) -> list[SplitItem]:
    return [item for item in items if item.start_page <= item.end_page]


def _synthesize_chapters_from_sections(sections: list[BookmarkEntry]) -> list[BookmarkEntry]:
    synthesized: list[BookmarkEntry] = []
    seen: set[tuple[int, int]] = set()
    for section in sorted(sections, key=lambda item: (item.page_index, item.level, item.label)):
        chapter_label = (section.label[0],)
        key = (section.page_index, chapter_label[0])
        if key in seen:
            continue
        seen.add(key)
        synthesized.append(
            BookmarkEntry(
                title=f"Chapter {section.label[0]}",
                page_index=section.page_index,
                level=max(1, section.level - 1),
                label=chapter_label,
            )
        )
    return synthesized


def _make_chapter_groups(chapters: list[BookmarkEntry]) -> list[ChapterGroup]:
    counts: dict[str, int] = {}
    groups: list[ChapterGroup] = []
    for order, chapter in enumerate(chapters, start=1):
        chapter_label = _section_label(chapter.label)
        chapter_title = _strip_number_prefix(chapter.title)
        base_name = sanitize_name(
            f"Chapter {chapter_label} - {chapter_title}" if chapter_label else chapter_title
        )
        counts[base_name] = counts.get(base_name, 0) + 1
        dir_name = base_name if counts[base_name] == 1 else sanitize_name(f"{base_name} ({counts[base_name]})")
        groups.append(ChapterGroup(entry=chapter, dir_name=dir_name, order=order))
    return groups


def _strip_number_prefix(title: str) -> str:
    title = title.strip()
    title = re.sub(
        r"^((chapter|part|book|unit|lesson|lecture|module|appendix|appendices|section)\s+[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*|\d+(?:[.\-]\d+)*\.?|[A-Za-z](?:[.\-]\d+)*)\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return title.strip(" .:-") or title


def export_split_items(
    reader: PdfReader,
    input_pdf: Path,
    output_dir: Path,
    split_items: list[SplitItem],
    metadata: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for item in split_items:
        chapter_dir = output_dir / item.chapter_dir_name
        chapter_dir.mkdir(parents=True, exist_ok=True)

        writer = PdfWriter()
        for page_index in range(item.start_page - 1, item.end_page):
            writer.add_page(reader.pages[page_index])
        destination = chapter_dir / item.file_name
        with destination.open("wb") as handle:
            writer.write(handle)

    manifest = {
        "input_pdf": str(input_pdf),
        "output_dir": str(output_dir),
        "metadata": metadata,
        "items": [asdict(item) | {"page_count": item.page_count} for item in split_items],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_dir / "manifest.txt").write_text(_render_text_manifest(manifest), encoding="utf-8")


def _render_text_manifest(manifest: dict[str, Any]) -> str:
    lines = [
        f"Input PDF: {manifest['input_pdf']}",
        f"Output Dir: {manifest['output_dir']}",
        f"Detection Source: {manifest['metadata']['structure_source']}",
        f"Total PDF Pages: {manifest['metadata']['total_pages']}",
        f"Split Files: {len(manifest['items'])}",
        "",
    ]
    for item in manifest["items"]:
        lines.append(
            f"{item['chapter_dir_name']}/{item['file_name']}: "
            f"PDF pages {item['start_page']}-{item['end_page']} ({item['page_count']} pages)"
        )
    return "\n".join(lines)


def split_pdf(
    input_pdf: Path,
    output_dir: Path,
    source: str = "auto",
    include_chapter_intro: bool = True,
    max_section_depth: int | None = None,
) -> dict[str, Any]:
    reader = PdfReader(str(input_pdf))
    entries, detected_source = load_structure(reader, source=source)
    split_items = build_split_items(
        entries=entries,
        total_pages=len(reader.pages),
        include_chapter_intro=include_chapter_intro,
        max_section_depth=max_section_depth,
    )
    metadata = {
        "structure_source": detected_source,
        "total_pages": len(reader.pages),
        "detected_entries": len(entries),
        "include_chapter_intro": include_chapter_intro,
        "max_section_depth": max_section_depth,
    }
    export_split_items(
        reader=reader,
        input_pdf=input_pdf,
        output_dir=output_dir,
        split_items=split_items,
        metadata=metadata,
    )
    return {
        "output_dir": output_dir,
        "split_count": len(split_items),
        "metadata": metadata,
        "items": split_items,
    }
