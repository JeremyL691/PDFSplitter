from __future__ import annotations
from collections import deque
from dataclasses import asdict
import json
import platform
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable
from .models import CancelledError, OCROptions, PageText, TextBlock, check_cancel, input_hash
ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get('PDFSPLITTER_CACHE_DIR', str(Path.home() / 'Library' / 'Caches' / 'PDFSplitter')))
PROCESSING_VERSION = 1

def has_cjk(text: str) -> bool:
    return any(('㐀' <= char <= '鿿' for char in text))

def overlap(a: list[float], b: list[float]) -> float:
    x = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    y = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return x * y / max(min(a[2] * a[3], b[2] * b[3]), 1e-09)

def reading_order(blocks: list[TextBlock]) -> list[TextBlock]:
    if not blocks or any((b.bbox is None for b in blocks)):
        return blocks
    spanners = sorted([b for b in blocks if b.bbox[2] > 0.65], key=lambda b: b.bbox[1])
    remaining = [b for b in blocks if b not in spanners]
    result = []

    def band(values: list[TextBlock]) -> list[TextBlock]:
        left = [b for b in values if b.bbox[0] + b.bbox[2] / 2 < 0.5]
        right = [b for b in values if b not in left]
        key = lambda b: (round(b.bbox[1], 2), b.bbox[0])
        if len(left) >= 3 and len(right) >= 3 and (max((b.bbox[0] + b.bbox[2] for b in left)) + 0.035 < min((b.bbox[0] for b in right))):
            return sorted(left, key=key) + sorted(right, key=key)
        return sorted(values, key=key)
    for span in spanners:
        earlier = [b for b in remaining if b.bbox[1] < span.bbox[1]]
        result.extend(band(earlier))
        result.append(span)
        remaining = [b for b in remaining if b not in earlier]
    result.extend(band(remaining))
    return result

def merge_blocks(raw: list[dict]) -> list[TextBlock]:
    groups: list[list[dict]] = []
    for candidate in raw:
        group = next((g for g in groups if candidate.get('bbox') and g[0].get('bbox') and (overlap(candidate['bbox'], g[0]['bbox']) >= 0.5) and (candidate.get('source') not in {c.get('source') for c in g})), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)
    merged = []
    for group in groups:
        chosen = next((c for c in group if c.get('source') == 'ocr_zh' and has_cjk(c['text'])), None)
        if chosen is None:
            chosen = next((c for c in group if c.get('source') == 'ocr_en'), group[0])
        final_text = chosen['text']
        english = next((c for c in group if c.get('source') == 'ocr_en'), None)
        if has_cjk(final_text) and english:
            replacements = []
            for segment in chosen.get('segments', []):
                matches = []
                for alternate in english.get('segments', []):
                    a, b = (segment['bbox'], alternate['bbox'])
                    inter = overlap(a, b) * min(a[2] * a[3], b[2] * b[3])
                    iou = inter / max(a[2] * a[3] + b[2] * b[3] - inter, 1e-09)
                    if iou > 0.65:
                        matches.append((iou, alternate['text']))
                if matches:
                    replacements.append((segment['start'], segment['end'], max(matches)[1]))
            for start, end, replacement in sorted(replacements, reverse=True):
                final_text = final_text[:start] + replacement + final_text[end:]
        merged.append(TextBlock(final_text, chosen.get('bbox'), chosen.get('confidence'), chosen.get('source', 'native'), chosen.get('candidates', []) + [dict(c) for c in group if c is not chosen], chosen['text'] if final_text != chosen['text'] else None))
    return reading_order(merged)

class NativeClient:

    def __init__(self, cancel: threading.Event | None=None):
        if sys.platform != 'darwin' or int(platform.mac_ver()[0].split('.')[0]) < 13:
            raise RuntimeError('Native OCR requires macOS 13 or later.')
        executable = ROOT / '.build' / 'vision-helper'
        source = ROOT / 'native' / 'vision-helper.swift'
        if not executable.exists() or executable.stat().st_mtime < source.stat().st_mtime:
            raise RuntimeError('Native helper is not built. Run: python3 native/build.py')
        self.cancel = cancel
        self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1)
        self.events: queue.Queue = queue.Queue()
        self.errors = deque(maxlen=20)

        def read_stdout():
            for line in self.process.stdout:
                try:
                    self.events.put(json.loads(line))
                except ValueError:
                    self.events.put({'event': 'error', 'message': 'Invalid native helper response.'})
            self.events.put({'event': 'eof'})

        def read_stderr():
            for line in self.process.stderr:
                self.errors.append(line.strip())
        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()
        try:
            self.send({'op': 'capabilities'})
            self.capabilities = self.receive(15)
        except BaseException:
            self.close()
            raise
        if self.capabilities.get('event') != 'capabilities' or self.capabilities.get('protocol_version') != 1:
            self.close()
            raise RuntimeError(self.capabilities.get('message', 'Native OCR is unavailable.'))
        if not {'en-US', 'zh-Hans', 'zh-Hant'}.issubset(self.capabilities['languages']):
            self.close()
            raise RuntimeError('Required English/Chinese OCR models are unavailable.')

    def send(self, data: dict):
        check_cancel(self.cancel)
        self.process.stdin.write(json.dumps(data, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def receive(self, timeout: float=60) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                check_cancel(self.cancel)
                event = self.events.get(timeout=0.1)
                if event['event'] == 'eof':
                    raise RuntimeError('Native helper stopped: ' + '; '.join(self.errors))
                return event
            except queue.Empty:
                pass
            except CancelledError:
                self.close()
                raise
        self.close()
        raise TimeoutError('OCR page timed out after 60 seconds.')

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for stream in [self.process.stdin, self.process.stdout, self.process.stderr]:
            if stream:
                stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def preview(self, pdf: Path, page_no: int, dpi: int=100) -> Path:
        CACHE.mkdir(parents=True, exist_ok=True)
        target = CACHE / f'preview-{input_hash(pdf)}-{page_no}-{dpi}.png'
        if not target.exists():
            self.send({'op': 'preview', 'pdf': str(pdf), 'page_no': page_no, 'dpi': dpi, 'output': str(target)})
            event = self.receive()
            if event['event'] != 'preview':
                raise RuntimeError(event.get('message', 'Preview failed.'))
        return target

def clear_cache():
    if not CACHE.exists():
        return
    for path in CACHE.glob('preview-*.png'):
        path.unlink(missing_ok=True)
    directory = CACHE / 'pages'
    if directory.is_dir() and (not directory.is_symlink()):
        import re
        for path in directory.iterdir():
            if re.fullmatch('[a-f0-9]{64}', path.name) and path.is_dir() and (not path.is_symlink()):
                shutil.rmtree(path)

def trim_cache(limit: int=2 * 1024 ** 3):
    files = sorted((p for p in CACHE.rglob('*') if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum((p.stat().st_size for p in files))
    for path in files:
        if total <= limit:
            break
        total -= path.stat().st_size
        path.unlink(missing_ok=True)

def is_blank(page) -> bool:
    contents = page.get_contents()
    if contents is None:
        return True
    paints = {b'Do', b'Tj', b'TJ', b"'", b'"', b'f', b'f*', b'S', b's', b'B', b'B*', b'b', b'b*', b'sh', b'INLINE IMAGE'}
    try:
        return not any((operator in paints for operands, operator in contents.operations))
    except (AttributeError, ValueError):
        return False

def extract_pages(pdf: Path, reader, options: OCROptions, cancel=None, progress: Callable | None=None, selected: list[int] | None=None) -> tuple[list[PageText], dict]:
    options.validate()
    digest = input_hash(pdf)
    pages = []
    numbers = selected if selected is not None else list(range(1, len(reader.pages) + 1))
    if any((type(n) is not int or not 1 <= n <= len(reader.pages) for n in numbers)):
        raise ValueError('OCR page selection is out of range.')
    client = None
    native_error = None
    # PDFKit provides native text coordinates even when OCR is off.
    try:
        client = NativeClient(cancel)
    except (RuntimeError, OSError, TimeoutError) as exc:
        native_error = str(exc)
    capability = client.capabilities if client else {'unavailable': native_error}
    identity = input_hash(ROOT / 'native/vision-helper.swift')
    cache_key = json.dumps([digest, asdict(options), platform.platform(), capability.get('revision'), identity, PROCESSING_VERSION], sort_keys=True)
    import hashlib
    directory = CACHE / 'pages' / hashlib.sha256(cache_key.encode()).hexdigest()
    cache_enabled = options.cache
    if cache_enabled:
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=448)
        except OSError:
            cache_enabled = False
    pending = []
    cached_pages = {}
    for number in numbers:
        path = directory / f'{number}.json'
        if cache_enabled and options.mode != 'force' and path.exists():
            try:
                raw = json.loads(path.read_text())
                cached_pages[number] = PageText(**raw | {'blocks': [TextBlock(**b) for b in raw['blocks']], 'cached': True})
                continue
            except (ValueError, TypeError, KeyError):
                pass
        pending.append(number)
    try:
        if client and pending:
            for number in pending:
                check_cancel(cancel)
                if progress:
                    progress({'stage': 'ocr', 'page_no': number, 'total': len(reader.pages), 'message': f'Processing page {number}'})
                try:
                    if client.process.poll() is not None:
                        client.close()
                        client = NativeClient(cancel)
                    blanks = [number] if is_blank(reader.pages[number - 1]) else []
                    client.send({'op': 'extract', 'pdf': str(pdf), 'pages': [number], 'mode': options.mode, 'languages': options.languages, 'dpi': options.dpi, 'blank_pages': blanks})
                    page = None
                    deadline = time.monotonic() + 60
                    while True:
                        event = client.receive(max(0.01, deadline - time.monotonic()))
                        if event['event'] == 'done':
                            break
                        if event['event'] == 'error':
                            page = PageText(number, status='error', error=event.get('message', 'OCR failed.'))
                        elif event['event'] == 'page':
                            page = PageText(number, merge_blocks(event['blocks']), event['source'], event['status'])
                    if page is None:
                        raise RuntimeError('Native helper returned no page result.')
                except (RuntimeError, OSError, TimeoutError) as exc:
                    client.close()
                    page = PageText(number, status='error', error=str(exc))
                cached_pages[number] = page
                if cache_enabled and page.status != 'error':
                    target = directory / f'{number}.json'
                    temporary = target.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
                    try:
                        temporary.write_text(json.dumps(asdict(page), ensure_ascii=False))
                        temporary.replace(target)
                    except OSError:
                        temporary.unlink(missing_ok=True)
                if progress:
                    progress({'stage': 'page', 'page': page, 'page_no': number, 'total': len(reader.pages)})
        elif pending:
            for number in pending:
                check_cancel(cancel)
                text = reader.pages[number - 1].extract_text() or ''
                needs = options.mode == 'force' or (options.mode == 'auto' and sum((c.isalnum() for c in text)) < 40 and (not is_blank(reader.pages[number - 1])))
                page = PageText(number, [TextBlock(line) for line in text.splitlines() if line.strip()], status='error' if needs else 'ready' if text else 'blank', error=native_error if needs else None)
                cached_pages[number] = page
                if progress:
                    progress({'stage': 'page', 'page': page, 'page_no': number, 'total': len(reader.pages)})
        for number in numbers:
            check_cancel(cancel)
            page = cached_pages[number]
            pages.append(page)
            if page.cached and progress:
                progress({'stage': 'page', 'page': page, 'page_no': number, 'total': len(reader.pages)})
        return (pages, capability)
    finally:
        if client:
            client.close()
        if cache_enabled:
            try:
                trim_cache()
            except OSError:
                pass
