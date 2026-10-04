import json
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfReader
from pdfsplitter.models import OCROptions, SplitPlan, TextBlock, PageText, CancelledError, ReviewRequired
from pdfsplitter.headings import parse_heading
from pdfsplitter.ocr import merge_blocks, reading_order
from pdfsplitter.splitter import analyze_pdf, build_split_items, export_plan, validate_plan, rebuild_plan, sanitize_name
from tests.fixtures import book

class CoreTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def analyze(self,path,**kwargs):
        with patch('pdfsplitter.ocr.NativeClient',side_effect=RuntimeError('Unavailable test helper')):
            return analyze_pdf(path,ocr_options=OCROptions('off',cache=False),**kwargs)
    def sample(self):
        return book(self.root/'book.pdf', [['Chapter 1 Alpha'],['1.1 First'],['Body text'],['1.2 Second'],['Body text'],['Chapter 2 Beta'],['2.1 Third']], [('Chapter 1 Alpha',0,None),('1.1 First',1,'Chapter 1 Alpha'),('1.2 Second',3,'Chapter 1 Alpha'),('Chapter 2 Beta',5,None),('2.1 Third',6,'Chapter 2 Beta')])
    def test_headings(self):
        for text,label,kind in [('Appendix C',(3,),'chapter'),('Chapter Twenty-One',(21,),'chapter'),('Chapter TwentyOne',(21,),'chapter'),('第十二章 概率',(12,),'chapter'),('第一节 引言',(1,),'section'),('附录 A 补充',(1,),'chapter'),('Chapter IV',(4,),'chapter')]:
            with self.subTest(text=text):h=parse_heading(text);self.assertEqual((h.label,h.kind),(label,kind))
    def test_happy_export_and_roundtrip(self):
        path=self.sample();before=path.read_bytes();plan=self.analyze(path)
        self.assertEqual([(i.start_page,i.end_page) for i in plan.items],[(1,1),(2,3),(4,5),(6,6),(7,7)])
        saved=self.root/'plan.json';plan.save(saved);loaded=SplitPlan.load(saved)
        result=export_plan(loaded,self.root/'output');self.assertEqual(result['split_count'],5);self.assertEqual(path.read_bytes(),before)
        manifest=json.loads((self.root/'output/manifest.json').read_text());pdfs=list((self.root/'output').rglob('*.pdf'))
        self.assertEqual(len(pdfs),len(manifest['items']))
        for item in manifest['items']:
            exported=PdfReader(self.root/'output'/item['chapter_dir_name']/item['file_name']);self.assertEqual(len(exported.pages),item['page_count'])
            self.assertEqual(exported.pages[0].get_contents().get_data(),PdfReader(path).pages[item['start_page']-1].get_contents().get_data())
        for name in ['document.txt','ocr.json','split-plan.json','manifest.txt']:self.assertTrue((self.root/'output'/name).exists())
    def test_repeated_chapters_with_parts(self):
        path=book(self.root/'parts.pdf',[[]]*8,[('Part I First',0,None),('Chapter 1 Alpha',1,'Part I First'),('1.1 Start',2,'Chapter 1 Alpha'),('Part II Second',4,None),('Chapter 1 Beta',5,'Part II Second'),('1.1 Later',6,'Chapter 1 Beta')])
        plan=self.analyze(path,source='outline');chapters=[e for e in plan.entries if e.kind=='chapter'];self.assertEqual(len(chapters),2);self.assertNotEqual(chapters[0].parent_id,chapters[1].parent_id);self.assertEqual(len({e.id for e in plan.entries}),len(plan.entries));self.assertEqual(plan.items[-1].start_page,7)
    def test_sections_only_group_consecutive_chapters(self):
        path=book(self.root/'sections.pdf',[[]]*7,[('1.1 First',0,None),('1.2 Second',2,None),('1.3 Third',3,None),('2.1 Last',5,None)])
        plan=self.analyze(path,source='outline');self.assertEqual(len([e for e in plan.entries if e.kind=='chapter']),2);self.assertEqual(len({i.chapter_dir_name for i in plan.items}),2)
    def test_partial_outline_and_body_reference(self):
        path=book(self.root/'partial.pdf',[['Chapter 1 Alpha'],['1.1 First'],['In Chapter 2 Beta we shall examine this.'],['Chapter 2 Beta'],['2.1 Last']],[('Chapter 1 Alpha',0,None)])
        plan=self.analyze(path);self.assertEqual(plan.metadata['structure_source'],'scan');self.assertEqual([e.page_index for e in plan.entries if e.kind=='chapter'],[0,3])
    def test_toc_repeat_and_early_reference(self):
        path=book(self.root/'toc.pdf',[['Contents','Chapter 1 Alpha .... 1','Chapter 1 Beta .... 4'],['See Chapter 1 Beta in this book.'],['Chapter 1 Alpha'],['Body'],['Body'],['Chapter 1 Beta'],['Body']])
        plan=self.analyze(path,source='toc');self.assertEqual([e.page_index for e in plan.entries if e.kind=='chapter'],[2,5])
    def test_depth_samepage(self):
        plan=self.analyze(self.sample())
        for depth in [0,-1,3]:
            with self.assertRaises(ValueError):build_split_items(plan.entries,plan.total_pages,max_section_depth=depth)
        path=book(self.root/'same.pdf',[[]]*3,[('Chapter 1 Alpha',0,None),('1.1 First',1,'Chapter 1 Alpha'),('1.2 Second',1,'Chapter 1 Alpha')]);plan=self.analyze(path,source='outline');self.assertEqual(len(plan.items),2);self.assertEqual(len(plan.items[1].entry_ids),2)
        with self.assertRaises(ReviewRequired):export_plan(plan,self.root/'sameout')
        export_plan(plan,self.root/'sameout',accept_warnings=True)
    def test_safety_input_output_and_plan(self):
        plan=self.analyze(self.sample());out=self.root/'out';out.mkdir();(out/'old.pdf').write_bytes(b'old')
        with self.assertRaises(ValueError):export_plan(plan,out)
        self.assertEqual((out/'old.pdf').read_bytes(),b'old');result=export_plan(plan,out,unique_output=True);self.assertNotEqual(result['output_dir'],out)
        for mutation in ['range','overlap','path','duplicate']:
            other=deepcopy(plan)
            if mutation=='range':other.items[0].start_page=0
            elif mutation=='overlap':other.items[1].start_page=1
            elif mutation=='path':other.items[0].chapter_dir_name='../escape'
            else:other.items[1].file_name=other.items[0].file_name
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_plan(other)
        Path(plan.input_pdf).write_bytes(b'changed')
        with self.assertRaises(ValueError):export_plan(plan,self.root/'changed')
    def test_failure_and_cancel_cleanup(self):
        plan=self.analyze(self.sample())
        with patch('pdfsplitter.splitter.PdfWriter.write',side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):export_plan(plan,self.root/'failed')
        self.assertFalse((self.root/'failed').exists());self.assertFalse(list(self.root.glob('.pdfsplitter-*')))
        cancel=threading.Event()
        def progress(event):cancel.set()
        with self.assertRaises(CancelledError):export_plan(plan,self.root/'cancelled',cancel_token=cancel,progress_callback=progress)
        self.assertFalse((self.root/'cancelled').exists());self.assertFalse(list(self.root.glob('.pdfsplitter-*')))
    def test_manual_rebuild(self):
        plan=self.analyze(self.sample());item=plan.items[1];item.manual=True;item.section_title='人工标题';plan.dirty=True;rebuild_plan(plan);self.assertEqual(next(i for i in plan.items if i.manual).section_title,'人工标题');self.assertFalse(plan.dirty)
    def test_unicode_paths(self):self.assertEqual(sanitize_name('第十二章 / 概率:补充'),'第十二章 - 概率 -补充')
    def test_dual_pass_merge(self):
        raw=[dict(text='Conditional Probability',bbox=[.1,.1,.5,.03],source='ocr_en',confidence=.8),dict(text='Conaitional Probability',bbox=[.1,.1,.5,.03],source='ocr_zh',confidence=1),dict(text='garbled',bbox=[.1,.2,.4,.03],source='ocr_en',confidence=1),dict(text='第十二章 概率',bbox=[.1,.2,.4,.03],source='ocr_zh',confidence=.5)]
        result=merge_blocks(raw);self.assertEqual([b.text for b in result],['Conditional Probability','第十二章 概率']);self.assertEqual(len(result[1].candidates),1)
    def test_nested_outline_parent_and_depth(self):
        path=book(self.root/'nested.pdf',[[]]*5,[('Chapter 1 Alpha',0,None),('1.1 First',1,'Chapter 1 Alpha'),('1.1.1 Detail',2,'1.1 First'),('1.1.2 Second Detail',4,'1.1 First')])
        plan=self.analyze(path,source='outline',max_section_depth=3)
        by_title={e.title:e for e in plan.entries}
        self.assertEqual(by_title['1.1.1 Detail'].parent_id,by_title['1.1 First'].id)
        self.assertEqual([(i.start_page,i.end_page) for i in plan.items],[(1,2),(3,4),(5,5)])
    def test_bilingual_samepage_chapters_and_sections(self):
        from pdfsplitter.models import StructureEntry
        entries=[StructureEntry('Chapter 1 Alpha',0,1,(1,),kind='chapter',source='scan'),StructureEntry('第一章 概率',0,1,(1,),kind='chapter',source='scan'),StructureEntry('1.1 First',1,2,(1,1),kind='section',source='scan'),StructureEntry('第一节 引言',1,1,(1,),kind='section',source='scan')]
        items=build_split_items(entries,3);self.assertEqual([(i.start_page,i.end_page) for i in items],[(1,1),(2,3)]);self.assertEqual(len(items[1].entry_ids),2)

    def test_two_columns(self):
        blocks=[TextBlock(str(i),[x,y,.25,.03]) for i,(x,y) in enumerate([(.1,.1),(.6,.1),(.1,.2),(.6,.2),(.1,.3),(.6,.3)])]
        self.assertEqual([b.text for b in reading_order(blocks)],['0','2','4','1','3','5'])

if __name__=='__main__':unittest.main()
