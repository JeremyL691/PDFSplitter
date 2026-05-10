# PDFSplitter

PDFSplitter is a local Python CLI for splitting structured English PDF books into chapter folders and per-section PDF files.

It is built for textbooks and similar documents with headings like:

- `1 Introduction`
- `1.1 Basics`
- `1.2 Examples`
- `2 Advanced Topics`

PDFSplitter works in two stages:

1. It first reads the PDF outline/bookmarks if they exist.
2. If no useful outline is found, it falls back to parsing the English table of contents.

## Features

- Splits one PDF into many section PDFs
- Groups outputs by chapter
- Optionally exports chapter intro pages
- Writes `manifest.txt` and `manifest.json`
- Uses a lightweight dependency set

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Usage

```bash
python3 main.py "/path/to/book.pdf"
```

Set an output directory:

```bash
python3 main.py "/path/to/book.pdf" -o "/path/to/output"
```

Force a specific detection mode:

```bash
python3 main.py "/path/to/book.pdf" --source outline
python3 main.py "/path/to/book.pdf" --source toc
```

Split at a specific numbering depth:

```bash
python3 main.py "/path/to/book.pdf" --section-depth 2
```

Skip chapter intro exports:

```bash
python3 main.py "/path/to/book.pdf" --no-chapter-intro
```

## Output

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

## Notes

- PDFSplitter is optimized for English books with numbered headings.
- Documents with clean bookmarks usually produce the best results.
- TOC parsing is heuristic-based, so unusual layouts may need `--source` or `--section-depth`.

## License

This project is licensed under the MIT License. See `LICENSE`.
