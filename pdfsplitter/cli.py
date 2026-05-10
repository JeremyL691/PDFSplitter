from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .splitter import split_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfsplitter",
        description=(
            "Split a structured English PDF into chapter folders and section PDFs. "
            "The tool prefers PDF bookmarks and falls back to the table of contents."
        ),
    )
    parser.add_argument("input_pdf", type=Path, help="Path to the source PDF.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Directory for exported PDFs. Defaults to a sibling folder named after the input PDF.",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "outline", "toc"],
        default="auto",
        help="How to detect the book structure. Default: auto.",
    )
    parser.add_argument(
        "--section-depth",
        type=int,
        default=None,
        help="Split at a specific numbering depth. Example: 2 means 1.1, 1.2, 2.1.",
    )
    parser.add_argument(
        "--no-chapter-intro",
        action="store_true",
        help="Do not export chapter intro pages that appear before the first numbered subsection.",
    )
    return parser


def default_output_dir(input_pdf: Path) -> Path:
    safe_stem = input_pdf.stem.strip() or "book"
    return input_pdf.parent / f"{safe_stem} - split"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_pdf: Path = args.input_pdf.expanduser().resolve()
    if not input_pdf.exists():
        parser.error(f"Input PDF not found: {input_pdf}")
    if input_pdf.suffix.lower() != ".pdf":
        parser.error("Input file must be a PDF.")

    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else default_output_dir(input_pdf).resolve()
    )

    try:
        result = split_pdf(
            input_pdf=input_pdf,
            output_dir=output_dir,
            source=args.source,
            include_chapter_intro=not args.no_chapter_intro,
            max_section_depth=args.section_depth,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Input PDF: {input_pdf}")
    print(f"Output Dir: {result['output_dir']}")
    print(f"Detection Source: {result['metadata']['structure_source']}")
    print(f"Split Files: {result['split_count']}")
    print(f"Manifest: {output_dir / 'manifest.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
