from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
import hashlib
import json
import threading
from typing import Any
VERSION = '0.3.0'

class CancelledError(Exception):
    pass

class ReviewRequired(Exception):
    pass

@dataclass
class OCROptions:
    mode: str = 'auto'
    languages: str = 'mixed'
    dpi: int = 300
    cache: bool = True

    def validate(self) -> None:
        if self.mode not in {'auto', 'off', 'force'}:
            raise ValueError('OCR mode must be auto, off or force.')
        if self.languages not in {'mixed', 'en', 'zh-Hans', 'zh-Hant'}:
            raise ValueError('Unsupported OCR language profile.')
        if self.dpi not in {150, 300, 450}:
            raise ValueError('OCR DPI must be 150, 300 or 450.')

@dataclass
class TextBlock:
    text: str
    bbox: list[float] | None = None
    confidence: float | None = None
    source: str = 'native'
    candidates: list[dict[str, Any]] = field(default_factory=list)
    original_text: str | None = None

@dataclass
class PageText:
    page_no: int
    blocks: list[TextBlock] = field(default_factory=list)
    source: str = 'native'
    status: str = 'ready'
    error: str | None = None
    cached: bool = False

    @property
    def text(self) -> str:
        return '\n'.join((block.text for block in self.blocks))

@dataclass
class StructureEntry:
    title: str
    page_index: int
    level: int
    label: tuple[int, ...]
    id: str = ''
    parent_id: str | None = None
    kind: str = ''
    display_label: str = ''
    source: str = 'outline'
    printed_page: int | None = None
    evidence: list[str] = field(default_factory=list)

@dataclass
class SplitItem:
    chapter_label: str
    chapter_title: str
    section_label: str
    section_title: str
    start_page: int
    end_page: int
    chapter_dir_name: str
    file_name: str
    entry_ids: list[str] = field(default_factory=list)
    excluded: bool = False
    manual: bool = False
    part_id: str | None = None

    @property
    def page_count(self) -> int:
        return self.end_page - self.start_page + 1

@dataclass
class Diagnostic:
    code: str
    message: str
    severity: str = 'warning'
    page_no: int | None = None

@dataclass
class SplitPlan:
    input_pdf: str
    input_sha256: str
    total_pages: int
    pages: list[PageText]
    entries: list[StructureEntry]
    items: list[SplitItem]
    warnings: list[Diagnostic] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    omitted_pages: dict[str, list[int]] = field(default_factory=dict)
    dirty: bool = False
    schema_version: int = 1
    pending_pages: dict[int, PageText] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        import os
        import tempfile
        path = Path(path).expanduser().resolve()
        source = Path(self.input_pdf).resolve()
        if path == source or (path.exists() and source.exists() and os.path.samefile(path, source)):
            raise ValueError('Plan output cannot overwrite the input PDF.')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.plan-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(self.to_dict(), stream, ensure_ascii=False, indent=2)
            Path(temporary).replace(path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> SplitPlan:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema_version') != 1:
            raise ValueError('Unsupported split plan schema.')
        data['pages'] = [PageText(**p | {'blocks': [TextBlock(**b) for b in p['blocks']]}) for p in data['pages']]
        data['entries'] = [StructureEntry(**e | {'label': tuple(e['label'])}) for e in data['entries']]
        data['items'] = [SplitItem(**i) for i in data['items']]
        data['warnings'] = [Diagnostic(**w) for w in data['warnings']]
        data['pending_pages'] = {int(n): PageText(**p | {'blocks': [TextBlock(**b) for b in p['blocks']]}) for n, p in data.get('pending_pages', {}).items()}
        return cls(**data)

def input_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def check_cancel(token: threading.Event | None) -> None:
    if token is not None and token.is_set():
        raise CancelledError('Operation cancelled.')
