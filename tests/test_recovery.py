import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from pdfsplitter.models import OCROptions, SplitPlan, PageText, TextBlock, CancelledError, ReviewRequired
from pdfsplitter.ocr import extract_pages, clear_cache
from pdfsplitter.splitter import analyze_pdf, export_plan, validate_plan, rebuild_plan, extract_bookmark_entries
from pdfsplitter.cli import main
from tests.fixtures import book

class FakeClient:
    instances=[]; fail=None
    def __init__(self,cancel=None):
        self.capabilities={'revision':3,'languages':['en-US','zh-Hans','zh-Hant']};self.process=self;self.closed=False;self.instances.append(self)
    def poll(self):return 1 if self.closed else None
    def close(self):self.closed=True
    def send(self,request):
        self.number=request['pages'][0];self.events=iter([{'event':'progress','page_no':self.number},{'event':'page','page_no':self.number,'blocks':[{'text':f'Chapter {self.number} Test','source':'ocr_en','bbox':[.1,.1,.5,.04],'confidence':1}],'source':'ocr','status':'ready'},{'event':'done'}])
    def receive(self,timeout=60):
        if self.number==1 and self.fail:raise self.fail('simulated page failure')
        return next(self.events)

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=book(self.root/'book.pdf',[['Chapter 1 Test'],['Chapter 2 Test']]);FakeClient.instances=[];FakeClient.fail=None
    def tearDown(self):self.tmp.cleanup()
    def native_patch(self):return patch('pdfsplitter.ocr.NativeClient',FakeClient)
    def plan(self):
        with self.native_patch():return analyze_pdf(self.path,source='scan',ocr_options=OCROptions(cache=False))
    def test_timeout_restarts_and_continues(self):
        FakeClient.fail=TimeoutError
        with self.native_patch():pages,_=extract_pages(self.path,NoneReader(self.path),OCROptions(cache=False))
        self.assertEqual([p.status for p in pages],['error','ready']);self.assertEqual(len(FakeClient.instances),2);self.assertTrue(all(c.closed for c in FakeClient.instances))
    def test_cancel_closes_process(self):
        token=threading.Event()
        def progress(event):
            if event['stage']=='page':token.set()
        with self.native_patch(),self.assertRaises(CancelledError):extract_pages(self.path,NoneReader(self.path),OCROptions(cache=False),token,progress)
        self.assertTrue(all(c.closed for c in FakeClient.instances))
    def test_cache_partial_and_parameter_change(self):
        cache=self.root/'cache';token=threading.Event()
        with self.native_patch(),patch('pdfsplitter.ocr.CACHE',cache):
            with self.assertRaises(CancelledError):extract_pages(self.path,NoneReader(self.path),OCROptions(),token,lambda e:token.set() if e['stage']=='page' else None)
            token.clear();pages,_=extract_pages(self.path,NoneReader(self.path),OCROptions());self.assertTrue(pages[0].cached);self.assertFalse(pages[1].cached)
            pages,_=extract_pages(self.path,NoneReader(self.path),OCROptions(dpi=450));self.assertFalse(any(p.cached for p in pages))
            (cache/'unrelated.txt').write_text('keep');clear_cache();self.assertEqual((cache/'unrelated.txt').read_text(),'keep');self.assertFalse(list((cache/'pages').iterdir()))
    def test_pending_manual_results_roundtrip(self):
        plan=self.plan();plan.pages[0].blocks[0].source='user';plan.pending_pages[1]=PageText(1,[TextBlock('new OCR')],source='ocr');plan.dirty=True;path=self.root/'plan.json';plan.save(path);loaded=SplitPlan.load(path)
        self.assertEqual(loaded.pages[0].blocks[0].source,'user');self.assertEqual(loaded.pending_pages[1].text,'new OCR')
        with self.assertRaises(ReviewRequired):export_plan(loaded,self.root/'out',accept_warnings=True)
    def test_plan_cannot_overwrite_input_or_alias(self):
        plan=self.plan()
        with self.assertRaises(ValueError):plan.save(self.path)
        alias=self.root/'alias.json';alias.hardlink_to(self.path)
        with self.assertRaises(ValueError):plan.save(alias)
    def test_plan_page_count_and_invalid_schema(self):
        plan=self.plan();plan.total_pages=99
        with self.assertRaises(ValueError):validate_plan(plan)
        path=self.root/'plan.json';path.write_text(json.dumps({'schema_version':5}))
        with self.assertRaises(ValueError):SplitPlan.load(path)
    def test_cli_dryrun_apply_warning_and_depth(self):
        saved=self.root/'plan.json'
        with self.native_patch(),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(main([str(self.path),'--dry-run','--plan-out',str(saved),'--no-ocr-cache']),0)
            self.assertEqual(main(['--apply-plan',str(saved),'-o',str(self.root/'out')]),0)
        with self.assertRaises(SystemExit) as exc,patch('sys.stderr',new=io.StringIO()):main([str(self.path),'--section-depth','0'])
        self.assertEqual(exc.exception.code,2)
    def test_bad_bookmark_is_not_an_anchor(self):
        from pypdf import PdfReader
        path=book(self.root/'bad.pdf',[['Chapter 1 Test']],[('Chapter 1 Test',0,None)]);reader=PdfReader(path)
        with patch.object(reader,'get_destination_page_number',return_value=999):self.assertEqual(extract_bookmark_entries(reader),[])
    def test_native_corrected_outline_rebuild(self):
        path=book(self.root/'outline.pdf',[['Chapter 1 Alpha'],['1.1 First']],[('Chapter 1 Alpha',0,None),('1.1 First',1,'Chapter 1 Alpha')])
        with patch('pdfsplitter.ocr.NativeClient',side_effect=RuntimeError('off')):plan=analyze_pdf(path,source='outline',ocr_options=OCROptions('off',cache=False))
        plan.pages[1].blocks=[TextBlock('1.1 Corrected',source='user')];plan.pages[1].source='user';plan.dirty=True;rebuild_plan(plan);self.assertIn('Corrected',[i.section_title for i in plan.items])

def NoneReader(path):
    from pypdf import PdfReader
    return PdfReader(path)

if __name__=='__main__':unittest.main()
