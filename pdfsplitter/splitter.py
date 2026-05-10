from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import Destination

from .toc_parser import TocEntry, parse_toc_entries, resolve_toc_page_indices, title_to_label


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
    return sorted(deduped.values(), key=lambda item: (item.page_index, item.level, item.label))


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


def load_structure(reader: PdfReader, source: str = "auto") -> tuple[list[BookmarkEntry], str]:
    if source not in {"auto", "outline", "toc"}:
        raise ValueError(f"Unsupported source {source!r}")

    if source in {"auto", "outline"}:
        outline_entries = extract_bookmark_entries(reader)
        if outline_entries:
            return outline_entries, "outline"
        if source == "outline":
            return [], "outline"

    toc_entries = extract_toc_entries(reader)
    return toc_entries, "toc"


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
    chapters = [entry for entry in entries if len(entry.label) == 1]
    sections = [entry for entry in entries if len(entry.label) >= 2]
    if not chapters:
        raise ValueError("No numbered chapter entries were found.")
    if not sections:
        raise ValueError("No numbered section entries were found under the chapters.")

    chapter_map = {entry.label[0]: entry for entry in chapters}
    section_depth = max_section_depth or max(len(entry.label) for entry in sections)
    target_sections = [entry for entry in sections if len(entry.label) == section_depth]
    if not target_sections:
        raise ValueError(f"No sections were found at depth {section_depth}.")

    ordered_targets = sorted(target_sections, key=lambda item: (item.page_index, item.label))
    split_items: list[SplitItem] = []

    by_chapter: dict[int, list[BookmarkEntry]] = {}
    for section in ordered_targets:
        by_chapter.setdefault(section.label[0], []).append(section)

    ordered_labels = sorted(chapter_map)
    for position, chapter_number in enumerate(ordered_labels):
        chapter_entry = chapter_map[chapter_number]
        chapter_sections = sorted(by_chapter.get(chapter_number, []), key=lambda item: item.page_index)
        if not chapter_sections:
            continue

        chapter_title = _strip_number_prefix(chapter_entry.title)
        chapter_dir_name = sanitize_name(f"Chapter {chapter_number} - {chapter_title}")

        if include_chapter_intro and chapter_entry.page_index < chapter_sections[0].page_index:
            intro_end = chapter_sections[0].page_index - 1
            split_items.append(
                SplitItem(
                    chapter_label=str(chapter_number),
                    chapter_title=chapter_title,
                    section_label="00",
                    section_title="Chapter Intro",
                    start_page=chapter_entry.page_index + 1,
                    end_page=intro_end + 1,
                    chapter_dir_name=chapter_dir_name,
                    file_name="00 Chapter Intro.pdf",
                )
            )

        for index, section in enumerate(chapter_sections):
            next_start = (
                chapter_sections[index + 1].page_index
                if index + 1 < len(chapter_sections)
                else _chapter_end_page_index(chapter_number, ordered_labels, chapter_map, total_pages)
            )
            start_page = section.page_index + 1
            end_page = next_start
            section_label = _section_label(section.label)
            file_name = sanitize_name(f"{index + 1:02d} {section_label} {_strip_number_prefix(section.title)}.pdf")
            split_items.append(
                SplitItem(
                    chapter_label=str(chapter_number),
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


def _chapter_end_page_index(
    chapter_number: int,
    ordered_labels: list[int],
    chapter_map: dict[int, BookmarkEntry],
    total_pages: int,
) -> int:
    position = ordered_labels.index(chapter_number)
    if position + 1 < len(ordered_labels):
        return chapter_map[ordered_labels[position + 1]].page_index
    return total_pages


def _strip_number_prefix(title: str) -> str:
    title = title.strip()
    title = re.sub(r"^(chapter\s+\d+|\d+(?:\.\d+)*)\s*", "", title, flags=re.IGNORECASE)
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
