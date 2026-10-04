"""Build the native helper: python3 native/build.py."""
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent

def build() -> Path:
    if sys.platform != 'darwin':
        raise RuntimeError('Apple Vision OCR requires macOS.')
    target = ROOT / '.build' / 'vision-helper'
    target.parent.mkdir(exist_ok=True)
    cache = target.parent / 'modules'
    subprocess.run(['xcrun', 'swiftc', '-O', '-target', f'{platform.machine()}-apple-macosx13.0', '-module-cache-path', str(cache), str(ROOT/'native/vision-helper.swift'), '-o', str(target)], check=True)
    return target

if __name__ == '__main__':
    print(build())
