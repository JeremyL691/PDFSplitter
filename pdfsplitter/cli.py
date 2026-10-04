from __future__ import annotations
import argparse
from pathlib import Path
import sys
from .models import OCROptions, SplitPlan, ReviewRequired, CancelledError, VERSION
from .splitter import analyze_pdf, export_plan, validate_plan
from .ocr import NativeClient, clear_cache

def default_output_dir(input_pdf: Path) -> Path:
    return input_pdf.parent / f"{input_pdf.stem.strip() or 'book'} - split"

def positive_depth(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('Section depth must be a positive integer.')
    return number

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='pdfsplitter', description='Analyze structured or scanned PDFs with local Apple Vision OCR, review and export chapter splits.')
    p.add_argument('input_pdf', nargs='?', type=Path)
    p.add_argument('-o', '--output-dir', type=Path)
    p.add_argument('--source', choices=['auto', 'outline', 'toc', 'scan'], default='auto')
    p.add_argument('--section-depth', type=positive_depth)
    p.add_argument('--no-chapter-intro', action='store_true')
    p.add_argument('--ocr', choices=['auto', 'off', 'force'], default='auto')
    p.add_argument('--ocr-languages', choices=['mixed', 'en', 'zh-Hans', 'zh-Hant'], default='mixed')
    p.add_argument('--ocr-dpi', type=int, choices=[150, 300, 450], default=300)
    p.add_argument('--no-ocr-cache', action='store_true')
    p.add_argument('--clear-ocr-cache', action='store_true')
    p.add_argument('--ocr-status', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--plan-out', type=Path)
    p.add_argument('--apply-plan', type=Path)
    p.add_argument('--accept-warnings', action='store_true')
    p.add_argument('--version', action='version', version=VERSION)
    return p

def main(argv: list[str] | None=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.clear_ocr_cache:
        clear_cache()
        print('OCR cache cleared.')
        return 0
    if args.ocr_status:
        try:
            with NativeClient() as client:
                import json
                print(json.dumps(client.capabilities, ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            print(f'Error: {exc}', file=sys.stderr)
            return 1
    if args.input_pdf is None and args.apply_plan is None:
        parser.error('Provide an input PDF or --apply-plan.')
    if args.plan_out and (not args.dry_run):
        parser.error('--plan-out requires --dry-run.')
    try:
        if args.apply_plan:
            plan = SplitPlan.load(args.apply_plan.expanduser().resolve())
            if args.input_pdf:
                plan.input_pdf = str(args.input_pdf.expanduser().resolve())
            input_pdf = Path(plan.input_pdf)
            validate_plan(plan)
        else:
            input_pdf = args.input_pdf.expanduser().resolve()
            if not input_pdf.is_file() or input_pdf.suffix.lower() != '.pdf':
                parser.error('Input must be an existing PDF file.')
            plan = analyze_pdf(input_pdf, args.source, not args.no_chapter_intro, args.section_depth, ocr_options=OCROptions(args.ocr, args.ocr_languages, args.ocr_dpi, not args.no_ocr_cache))
        if args.dry_run:
            destination = (args.plan_out or input_pdf.with_suffix('.split-plan.json')).expanduser().resolve()
            if destination == input_pdf:
                raise ValueError('Plan output cannot overwrite the input PDF.')
            plan.save(destination)
            print(f'Plan: {destination}\nSplit Files: {len(plan.items)}')
            for warning in plan.warnings:
                print(f'{warning.severity}: {warning.message}')
            return 3 if any((w.severity in {'warning', 'error'} for w in plan.warnings)) else 0
        output = args.output_dir.expanduser().resolve() if args.output_dir else default_output_dir(input_pdf)
        result = export_plan(plan, output, accept_warnings=args.accept_warnings, unique_output=args.output_dir is None)
        print(f"Input PDF: {input_pdf}\nOutput Dir: {result['output_dir']}\nDetection Source: {plan.metadata['structure_source']}\nSplit Files: {result['split_count']}\nManifest: {result['output_dir'] / 'manifest.txt'}")
        return 0
    except (CancelledError, KeyboardInterrupt):
        print('Cancelled.', file=sys.stderr)
        return 130
    except ReviewRequired as exc:
        print(f'Review required: {exc}', file=sys.stderr)
        return 3
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
if __name__ == '__main__':
    raise SystemExit(main())
