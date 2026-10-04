import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from pdfsplitter.models import OCROptions
from pdfsplitter.splitter import analyze_pdf
from tests.fixtures import book

@unittest.skipUnless(os.environ.get('PDFSPLITTER_GUI_TESTS')=='1','Set PDFSPLITTER_GUI_TESTS=1 on a desktop Mac')
class GUITests(unittest.TestCase):
    def setUp(self):
        from pdfsplitter.gui import PDFSplitterApp
        self.tmp=tempfile.TemporaryDirectory();self.app=PDFSplitterApp();self.callback_errors=[];self.app.root.report_callback_exception=lambda *error:self.callback_errors.append(error);self.app.root.update()
    def tearDown(self):self.app.shutdown.set();self.app.cancel.set();self.app.root.destroy();self.tmp.cleanup();self.assertFalse(self.callback_errors,self.callback_errors)
    def pump(self,seconds=.2):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.app.root.update();time.sleep(.01)
    def test_layout_and_theme(self):
        for width in [320,768,1024,1440]:
            self.app.root.geometry(f'{width}x760');self.pump()
            self.assertEqual(self.app.root.winfo_width(),width)
            for button in self.app.action_buttons:
                self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),self.app.root.winfo_rootx()+width)
            self.assertGreater(self.app.canvas.winfo_width(),50);self.assertGreater(self.app.canvas.winfo_height(),80)
            if width==320:
                self.app._small_panel('text');self.pump();self.assertGreater(self.app.text.winfo_width(),200)
            for theme in ['light','dark','system']:
                self.app.theme.set(theme);self.app.reduce_motion.set(True);self.pump(.03)
    def test_analyze_correct_save_rebuild_export_and_drop_parser(self):
        path=book(Path(self.tmp.name)/'test book.pdf',[['Chapter 1 Alpha'],['1.1 First'],['Chapter 2 Beta']])
        self.assertEqual(self.app._parse_drop_paths('{'+str(path)+'}'),[path])
        self.app.ocr_mode.set('off');self.app._start_jobs([path]);self.pump()
        deadline=time.monotonic()+20
        while self.app.busy and time.monotonic()<deadline:self.pump()
        self.assertFalse(self.app.busy);plan=self.app._plan();self.assertIsNotNone(plan)
        self.app.page_no=2;self.app._show_text();self.app.text.delete('1.0','end');self.app.text.insert('1.0','1.1 Corrected');self.app._edit_text();self.assertTrue(plan.dirty)
        self.app._rebuild();self.assertFalse(plan.dirty);self.assertIn('Corrected',[i.section_title for i in plan.items])
        self.app.output.set(self.tmp.name);self.app.accept.set(True);self.app._export()
        deadline=time.monotonic()+20
        while self.app.busy and time.monotonic()<deadline:self.pump()
        self.assertEqual(self.app.documents[str(path.resolve())]['state'],'Success');self.assertTrue((self.app.last_output_dir/'split-plan.json').exists())

    def test_plan_merge_split_exclude_and_pending_user_text(self):
        from pdfsplitter.models import PageText, TextBlock, Diagnostic
        path=book(Path(self.tmp.name)/'edits.pdf',[['Chapter 1 Alpha'],['1.1 First'],['Chapter 2 Beta']])
        self.app.ocr_mode.set('off');self.app._start_jobs([path])
        deadline=time.monotonic()+20
        while self.app.busy and time.monotonic()<deadline:self.pump()
        plan=self.app._plan();self.app.items.selection_set(['item-0','item-1']);self.app._merge();self.assertEqual(plan.items[0].end_page,2);self.assertTrue(plan.items[1].excluded)
        self.app.items.selection_set('item-0')
        with patch('pdfsplitter.gui.simpledialog.askinteger',return_value=2):self.app._split()
        self.assertEqual([(i.start_page,i.end_page) for i in plan.items if not i.excluded],[(1,1),(2,2),(3,3)])
        self.app.items.selection_set('item-1');self.app._exclude();self.assertTrue(plan.items[1].excluded);self.app.items.selection_set('item-1');self.app._exclude();self.assertFalse(plan.items[1].excluded)
        self.app.page_no=1;plan.pages[0].blocks=[TextBlock('Chapter 1 Manual',source='user')];plan.pages[0].source='user'
        self.app.queue.put(('reocr',self.app.selected,[PageText(1,[TextBlock('Chapter 1 Fresh OCR')],source='ocr')]))
        self.pump();self.assertEqual(plan.pages[0].text,'Chapter 1 Manual');self.assertEqual(plan.pending_pages[1].text,'Chapter 1 Fresh OCR')
        self.app._keep_manual();self.assertFalse(plan.pending_pages);self.assertEqual(plan.pages[0].text,'Chapter 1 Manual')
    def test_failed_file_does_not_stop_batch(self):
        bad=Path(self.tmp.name)/'bad.pdf';bad.write_bytes(b'not a PDF')
        good=book(Path(self.tmp.name)/'good.pdf',[['Chapter 1 Alpha']])
        self.app.ocr_mode.set('off');self.app._start_jobs([bad,good]);deadline=time.monotonic()+20
        while self.app.busy and time.monotonic()<deadline:self.pump()
        self.assertEqual(self.app.documents[str(bad.resolve())]['state'],'Failed');self.assertIsNotNone(self.app.documents[str(good.resolve())]['plan'])

if __name__=='__main__':unittest.main()
