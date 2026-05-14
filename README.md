# PDFSplitter

PDFSplitter is a local Python tool for splitting English PDF books into smaller PDFs.

It is designed for textbooks, lecture notes, exported course books, and similar documents that have a recognizable structure such as chapters, sections, appendices, or a table of contents.

PDFSplitter supports both:

- a drag-and-drop desktop GUI
- a command-line interface

## What It Does

Given a PDF, PDFSplitter tries to detect its structure and export smaller PDFs such as:

- one folder per chapter
- one PDF per section or subsection
- optional chapter intro PDFs when a chapter starts before the first subsection

It also writes:

- `manifest.txt`
- `manifest.json`

so you can review exactly what was split and which original page ranges were used.

## Detection Strategy

PDFSplitter uses a layered strategy:

1. PDF outline / bookmarks
2. table of contents parsing
3. page-top heading scanning as a fallback

This makes it work across a wider range of PDFs than a single-rule splitter.

## Supported Heading Styles

PDFSplitter tries to recognize many common English heading formats, including:

- `1 Title`
- `1. Title`
- `1.1 Title`
- `1.1.1 Title`
- `1-1 Title`
- `Chapter 1`
- `Chapter One`
- `Chapter IV`
- `Part I`
- `Book II`
- `Unit 3`
- `Lesson 4`
- `Lecture 12`
- `Module 5`
- `Appendix A`
- `Appendix A.1`
- `A.1 Title`

It also tries to handle:

- repeated numbering in later parts of a book
- books where some chapters have subsections and others do not
- chapter intro pages before the first subsection
- front matter, TOC pages, and page-header noise during scan fallback

## Important Limitation

PDFSplitter is much more flexible than the first version, but no fully automatic splitter can perfectly handle every PDF.

Some books still have poor or misleading source metadata, for example:

- broken or partial bookmarks
- repeated bookmark trees for answers or appendices
- scanned PDFs with weak OCR
- tables of contents that are visually present but text extraction is messy
- books whose actual headings are not present in extractable text

When that happens, you may need to:

- choose a different detection mode
- set a specific section depth
- inspect the output and rerun with different options

## Install

From the project folder:

```bash
python3 -m pip install -r requirements.txt
```

## Desktop GUI

Launch the drag-and-drop app:

```bash
python3 main.py
```

or:

```bash
python3 main.py --gui
```

Then:

- drag one or more PDF files into the window
- PDFSplitter will split each file automatically
- output is created next to the original PDF in a folder named `<file> - split`
- use `Open Last Output Folder` to jump to the newest result

The GUI also lets you choose:

- detection mode
- section depth
- whether to include chapter intro PDFs

## Command Line Usage

Split a PDF with automatic detection:

```bash
python3 main.py "/path/to/book.pdf"
```

Choose an output directory:

```bash
python3 main.py "/path/to/book.pdf" -o "/path/to/output"
```

Force a detection mode:

```bash
python3 main.py "/path/to/book.pdf" --source outline
python3 main.py "/path/to/book.pdf" --source toc
python3 main.py "/path/to/book.pdf" --source scan
```

Split using a specific heading depth:

```bash
python3 main.py "/path/to/book.pdf" --section-depth 2
```

Skip chapter intro exports:

```bash
python3 main.py "/path/to/book.pdf" --no-chapter-intro
```

See all options:

```bash
python3 main.py --help
```

## Example Output

```text
Book Name - split/
  Chapter 1 - Introduction/
    00 Chapter Intro.pdf
    01 1.1 Basics.pdf
    02 1.2 Examples.pdf
  Chapter 2 - Advanced Topics/
    01 2.1 Topic A.pdf
  manifest.txt
  manifest.json
```

## Typical Good Fits

PDFSplitter works best on:

- textbooks exported from modern publishers
- GitBook-style course books
- lecture notes with bookmarks
- Word / LaTeX / EPUB-derived PDFs with structured headings

## Project Structure

- [main.py](/Users/jeremyliu/Desktop/Projects/PDFSplitter/main.py): entry point for GUI and CLI
- [pdfsplitter/cli.py](/Users/jeremyliu/Desktop/Projects/PDFSplitter/pdfsplitter/cli.py): command-line interface
- [pdfsplitter/gui.py](/Users/jeremyliu/Desktop/Projects/PDFSplitter/pdfsplitter/gui.py): drag-and-drop desktop GUI
- [pdfsplitter/splitter.py](/Users/jeremyliu/Desktop/Projects/PDFSplitter/pdfsplitter/splitter.py): splitting logic
- [pdfsplitter/toc_parser.py](/Users/jeremyliu/Desktop/Projects/PDFSplitter/pdfsplitter/toc_parser.py): heading and TOC parsing

## License

This project is licensed under the MIT License. See `LICENSE`.
