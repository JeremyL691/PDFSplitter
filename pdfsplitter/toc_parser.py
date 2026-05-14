from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re

from pypdf import PdfReader


TOC_HEADING_RE = re.compile(r"\b(contents|table of contents)\b", re.IGNORECASE)
TRAILING_PAGE_RE = re.compile(r"^(?P<title>.+?)\s+\.{0,}\s*(?P<page>\d{1,4})$")
NUMBERED_TITLE_RE = re.compile(
    r"^(?P<label>(?:chapter\s+\d+|\d+(?:\.\d+)*\.?))(?P<rest>\s+.+)?$",
    re.IGNORECASE,
)
GENERIC_PREFIX_RE = re.compile(
    r"^(?P<prefix>chapter|part|book|unit|lesson|lecture|module|appendix|appendices|section)\s+"
    r"(?P<label>[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*\.?)(?P<rest>(?:\s+|:|-).+)?$",
    re.IGNORECASE,
)
BARE_HIERARCHY_RE = re.compile(
    r"^(?P<label>(?:\d+(?:[.\-][A-Za-z0-9]+)*\.?|[IVXLCDM]+\.|[A-Za-z]\.(?:\d+(?:[.\-]\d+)*)?))(?P<rest>\s+.+)?$",
    re.IGNORECASE,
)
ROMAN_NUMERAL_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
DIGITS_ONLY_RE = re.compile(r"^\d{1,4}$")
TRAILING_ROMAN_PAGE_RE = re.compile(r"^.+\s+[ivxlcdm]+$", re.IGNORECASE)

SMALL_NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "first": 1,
    "two": 2,
    "second": 2,
    "three": 3,
    "third": 3,
    "four": 4,
    "fourth": 4,
    "five": 5,
    "fifth": 5,
    "six": 6,
    "sixth": 6,
    "seven": 7,
    "seventh": 7,
    "eight": 8,
    "eighth": 8,
    "nine": 9,
    "ninth": 9,
    "ten": 10,
    "tenth": 10,
    "eleven": 11,
    "eleventh": 11,
    "twelve": 12,
    "twelfth": 12,
    "thirteen": 13,
    "thirteenth": 13,
    "fourteen": 14,
    "fourteenth": 14,
    "fifteen": 15,
    "fifteenth": 15,
    "sixteen": 16,
    "sixteenth": 16,
    "seventeen": 17,
    "seventeenth": 17,
    "eighteen": 18,
    "eighteenth": 18,
    "nineteen": 19,
    "nineteenth": 19,
    "twenty": 20,
    "twentieth": 20,
    "thirty": 30,
    "thirtieth": 30,
    "forty": 40,
    "fortieth": 40,
    "fifty": 50,
    "fiftieth": 50,
    "sixty": 60,
    "sixtieth": 60,
    "seventy": 70,
    "seventieth": 70,
    "eighty": 80,
    "eightieth": 80,
    "ninety": 90,
    "ninetieth": 90,
    "hundred": 100,
}


@dataclass(frozen=True)
class TocEntry:
    title: str
    printed_page: int
    label: tuple[int, ...]
    level: int
    pdf_page_index: int | None = None


def normalize_text(value: str) -> str:
    value = value.replace("\u00ad", "")
    value = value.replace("\u2019", "'")
    value = value.replace("\u2018", "'")
    value = value.replace("\u2013", "-")
    value = value.replace("\u2014", "-")
    value = value.replace("\u2212", "-")
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_toc_title(title: str) -> str:
    title = normalize_text(title)
    title = re.sub(r"\s*\.\s*\.\s*", " ", title)
    title = re.sub(r"\.{2,}", " ", title)
    title = re.sub(r"(?:\s*\.)+$", "", title)
    return normalize_text(title).strip(" .")


def _roman_to_int(token: str) -> int | None:
    roman = token.upper()
    if not roman or not ROMAN_NUMERAL_RE.fullmatch(roman):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for char in reversed(roman):
        value = values[char]
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total if total > 0 else None


def _word_to_int(token: str) -> int | None:
    token = token.lower().replace("-", " ").strip()
    if token in SMALL_NUMBER_WORDS:
        return SMALL_NUMBER_WORDS[token]
    parts = token.split()
    if not parts:
        return None
    total = 0
    current = 0
    for part in parts:
        value = SMALL_NUMBER_WORDS.get(part)
        if value is None:
            return None
        if value == 100:
            current = max(current, 1) * 100
        else:
            current += value
    total += current
    return total if total > 0 else None


def _alpha_to_int(token: str) -> int | None:
    return ord(token.upper()) - ord("A") + 1 if len(token) == 1 and token.isalpha() else None


def _parse_label_component(token: str) -> int | None:
    token = token.strip().rstrip(".")
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if (word_value := _word_to_int(token)) is not None:
        return word_value
    if (roman_value := _roman_to_int(token)) is not None:
        return roman_value
    if (alpha_value := _alpha_to_int(token)) is not None:
        return alpha_value
    return None


def _parse_hierarchy(raw_label: str) -> tuple[int, ...]:
    cleaned = raw_label.strip().rstrip(".")
    if not cleaned:
        return ()
    parts = [part for part in re.split(r"[.\-]", cleaned) if part]
    values: list[int] = []
    for part in parts:
        parsed = _parse_label_component(part)
        if parsed is None:
            return ()
        values.append(parsed)
    return tuple(values)


def title_to_label(title: str) -> tuple[int, ...]:
    cleaned = clean_toc_title(title)
    if not cleaned:
        return ()

    for pattern in (GENERIC_PREFIX_RE, NUMBERED_TITLE_RE, BARE_HIERARCHY_RE):
        match = pattern.match(cleaned)
        if not match:
            continue
        raw_label = match.group("label")
        parsed = _parse_hierarchy(raw_label)
        if parsed:
            return parsed
    return ()


def _extract_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line]


def find_toc_start_page(reader: PdfReader, max_scan_pages: int = 40) -> int | None:
    limit = min(len(reader.pages), max_scan_pages)
    for index in range(limit):
        text = reader.pages[index].extract_text() or ""
        if TOC_HEADING_RE.search(normalize_text(text)):
            return index
    return None


def find_toc_page_span(
    reader: PdfReader,
    max_scan_pages: int = 40,
    page_window: int = 6,
) -> tuple[int, int] | None:
    start_index = find_toc_start_page(reader, max_scan_pages=max_scan_pages)
    if start_index is None:
        return None

    end_index = start_index
    upper_bound = min(len(reader.pages), start_index + page_window)
    for page_index in range(start_index, upper_bound):
        lines = [normalize_text(line) for line in _extract_lines(reader.pages[page_index].extract_text() or "")]
        digits_only = sum(1 for line in lines if DIGITS_ONLY_RE.match(line))
        numbered_titles = sum(1 for line in lines if title_to_label(line))
        same_line_entries = sum(1 for line in lines if TRAILING_PAGE_RE.match(line))
        score = digits_only + numbered_titles + same_line_entries
        if page_index == start_index or score >= 4 or digits_only >= 2 or numbered_titles >= 2:
            end_index = page_index
            continue
        break
    return (start_index, end_index)


def _is_noise_line(line: str) -> bool:
    lowered = line.lower()
    if TOC_HEADING_RE.search(lowered):
        return True
    if line == ".":
        return True
    if ROMAN_NUMERAL_RE.fullmatch(line):
        return True
    simplified = re.sub(r"[.\s]+", " ", lowered).strip()
    return simplified == "contents"


def parse_toc_entries(reader: PdfReader, max_scan_pages: int = 40) -> list[TocEntry]:
    span = find_toc_page_span(reader, max_scan_pages=max_scan_pages)
    if span is None:
        return []

    start_index, end_index = span
    entries: list[TocEntry] = []
    seen: set[tuple[str, int]] = set()
    pending_titles: deque[str] = deque()

    for page_index in range(start_index, end_index + 1):
        text = reader.pages[page_index].extract_text() or ""
        for raw_line in _extract_lines(text):
            line = normalize_text(raw_line)
            if not line or _is_noise_line(line):
                continue

            if DIGITS_ONLY_RE.match(line):
                if pending_titles:
                    title = clean_toc_title(pending_titles.popleft())
                    printed_page = int(line)
                    label = title_to_label(title)
                    if label:
                        key = (title.lower(), printed_page)
                        if key not in seen:
                            seen.add(key)
                            entries.append(
                                TocEntry(
                                    title=title,
                                    printed_page=printed_page,
                                    label=label,
                                    level=len(label),
                                )
                            )
                continue

            if TRAILING_ROMAN_PAGE_RE.match(line):
                continue

            match = TRAILING_PAGE_RE.match(line)
            if match:
                title = clean_toc_title(match.group("title"))
                printed_page = int(match.group("page"))
                label = title_to_label(title)
                if label:
                    key = (title.lower(), printed_page)
                    if key not in seen:
                        seen.add(key)
                        entries.append(
                            TocEntry(
                                title=title,
                                printed_page=printed_page,
                                label=label,
                                level=len(label),
                            )
                        )
                continue

            pending_titles.append(clean_toc_title(line))
    return entries


def _match_key(value: str) -> str:
    value = clean_toc_title(value)
    value = re.sub(r"[^0-9A-Za-z]+", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def _find_title_matches(reader: PdfReader, titles: list[str]) -> dict[str, list[int]]:
    normalized_titles = {title: _match_key(title) for title in titles}
    matches: dict[str, list[int]] = {title: [] for title in titles}
    for page_index, page in enumerate(reader.pages):
        page_text = _match_key(page.extract_text() or "")
        for title, normalized_title in normalized_titles.items():
            if normalized_title and normalized_title in page_text:
                matches[title].append(page_index)
    return matches


def resolve_toc_page_indices(reader: PdfReader, entries: list[TocEntry]) -> list[TocEntry]:
    if not entries:
        return []

    title_matches = _find_title_matches(reader, [entry.title for entry in entries])
    toc_span = find_toc_page_span(reader) or (0, 0)
    toc_end_index = toc_span[1]

    chapter_entries = sorted((entry for entry in entries if len(entry.label) == 1), key=lambda item: item.label)
    chapter_entry_map = {entry.label[0]: entry for entry in chapter_entries}
    chapter_starts: dict[int, int] = {}
    for chapter in chapter_entries:
        candidate_matches = [page for page in title_matches.get(chapter.title, []) if page > toc_end_index]
        if candidate_matches:
            chapter_starts[chapter.label[0]] = min(candidate_matches)

    if not chapter_starts:
        return []

    resolved: list[TocEntry] = []
    sorted_chapter_numbers = sorted(chapter_starts)
    for entry in entries:
        if len(entry.label) == 1:
            page_index = chapter_starts.get(entry.label[0])
            if page_index is None:
                continue
        else:
            chapter_number = entry.label[0]
            chapter_start = chapter_starts.get(chapter_number)
            if chapter_start is None:
                continue
            chapter_entry = chapter_entry_map[chapter_number]
            if entry.printed_page == chapter_entry.printed_page:
                page_index = chapter_start
                resolved.append(
                    TocEntry(
                        title=entry.title,
                        printed_page=entry.printed_page,
                        label=entry.label,
                        level=entry.level,
                        pdf_page_index=page_index,
                    )
                )
                continue
            later_chapters = [number for number in sorted_chapter_numbers if number > chapter_number]
            next_chapter_start = chapter_starts[later_chapters[0]] if later_chapters else len(reader.pages)
            predicted_page = chapter_start + (entry.printed_page - chapter_entry.printed_page)
            predicted_page = max(chapter_start, min(predicted_page, next_chapter_start - 1))
            candidate_matches = [
                page
                for page in title_matches.get(entry.title, [])
                if chapter_start <= page < next_chapter_start
            ]
            if candidate_matches:
                closest = min(candidate_matches, key=lambda page: abs(page - predicted_page))
                page_index = closest if abs(closest - predicted_page) <= 2 else predicted_page
            else:
                page_index = predicted_page

        resolved.append(
            TocEntry(
                title=entry.title,
                printed_page=entry.printed_page,
                label=entry.label,
                level=entry.level,
                pdf_page_index=page_index,
            )
        )
    return resolved
