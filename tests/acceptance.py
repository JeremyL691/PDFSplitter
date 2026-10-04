"""Generate an accessible annotated scan and persist a real native acceptance record.
Run from the repository: python3 -m tests.acceptance
"""
from pathlib import Path
from dataclasses import asdict
import json
import platform
import sys
from tests.fixtures import scanned
from pdfsplitter import OCROptions, analyze_pdf, export_plan
from pdfsplitter.models import input_hash

ROOT=Path(__file__).resolve().parent.parent

def main():
    evidence=ROOT/'docs/evidence';evidence.mkdir(parents=True,exist_ok=True)
    labels=[['Contents','Chapter 1 Conditional Probability .... 1','1.1 Independent Events .... 2','Chapter 2 Random Variables .... 3'],['Chapter 1 Conditional Probability','第一章 条件概率'],['1.1 Independent Events','独立事件与条件概率'],['Chapter 2 Random Variables','第二章 隨機變數']]
    path=scanned(evidence/'annotated-scan.pdf',labels)
    annotation={'pages':labels,'expected_ranges':[[2,2],[3,3],[4,4]],'note':'Generated clear image-only sample. Labels were specified before OCR. PDF pages, not printed page numbers.'}
    (evidence/'annotation.json').write_text(json.dumps(annotation,ensure_ascii=False,indent=2))
    plan=analyze_pdf(path,ocr_options=OCROptions('auto',cache=False));actual=[[i.start_page,i.end_page] for i in plan.items]
    assert actual==annotation['expected_ranges'],actual
    for page,expected in zip(plan.pages,labels):assert [b.text for b in page.blocks]==expected,(page.page_no,page.text)
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        before=input_hash(path);result=export_plan(plan,Path(temporary)/'output',accept_warnings=True)
        assert before==input_hash(path)
        manifest=json.loads((result['output_dir']/'manifest.json').read_text())
        assert len(list(result['output_dir'].rglob('*.pdf')))==result['split_count']==3
    plan.save(evidence/'verified-plan.json')
    record={'platform':platform.platform(),'architecture':platform.machine(),'python':sys.version,'input_sha256':input_hash(path),'native':plan.metadata['native'],'expected_ranges':annotation['expected_ranges'],'actual_ranges':actual,'exact_page_text_match':True,'original_unchanged':True,'exported_pdfs':3,'warnings':[asdict(w) for w in plan.warnings]}
    (evidence/'native-acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    print(json.dumps(record,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
