"""Launch the annotated sample for manual desktop acceptance (no automatic export)."""
import argparse
from pathlib import Path
from pdfsplitter.gui import PDFSplitterApp

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--theme',choices=['system','light','dark'],default='system');args=parser.parse_args()
    app=PDFSplitterApp();app.theme.set(args.theme)
    sample=Path(__file__).resolve().parent.parent/'docs/evidence/annotated-scan.pdf'
    app.root.after(300,lambda:app._start_jobs([sample]))
    app.run()

if __name__=='__main__':main()
