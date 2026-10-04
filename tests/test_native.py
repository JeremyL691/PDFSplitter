import os
import platform
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pdfsplitter.models import OCROptions
from pdfsplitter.ocr import extract_pages, NativeClient
from pdfsplitter.splitter import analyze_pdf
from tests.fixtures import scanned, book

@unittest.skipUnless(os.environ.get('PDFSPLITTER_NATIVE_TESTS')=='1','Set PDFSPLITTER_NATIVE_TESTS=1 on macOS for real Vision tests')
class NativeTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_real_multilingual(self):
        labels=[['Chapter 1 Conditional Probability','1.1 Independent Events'],['第十二章 条件概率','第一节 随机事件'],['第十三章 條件機率','第一節 隨機事件'],['Chapter 2 Conditional Probability','第二章 条件概率','第二章 條件機率'],['Conditional Probability 条件概率','Independent Events 隨機事件']]
        path=scanned(self.root/'languages.pdf',labels)
        pages,cap=extract_pages(path,PdfReader(path),OCROptions('force',cache=False))
        self.assertEqual(cap['revision'],3)
        for page,expected in zip(pages,labels):
            with self.subTest(page=page.page_no):
                self.assertEqual(page.status,'ready');self.assertEqual([b.text for b in page.blocks],expected)
                self.assertTrue(all(b.bbox and all(0<=v<=1 for v in b.bbox) for b in page.blocks))
        en,_=extract_pages(path,PdfReader(path),OCROptions('force','en',cache=False),selected=[4])
        self.assertNotEqual(en[0].text,pages[3].text)
    def test_auto_cache_force_and_plan(self):
        path=scanned(self.root/'scan.pdf',[['Chapter 1 Alpha'],['1.1 First'],['Chapter 2 Beta'],['2.1 Second']])
        first=analyze_pdf(path,source='scan',ocr_options=OCROptions('auto'))
        self.assertEqual([(i.start_page,i.end_page) for i in first.items],[(1,1),(2,2),(3,3),(4,4)])
        second=analyze_pdf(path,source='scan',ocr_options=OCROptions('auto'));self.assertTrue(all(p.cached for p in second.pages))
        changed=analyze_pdf(path,source='scan',ocr_options=OCROptions('auto',dpi=150));self.assertFalse(any(p.cached for p in changed.pages))
        force=analyze_pdf(path,source='scan',ocr_options=OCROptions('force'));self.assertFalse(any(p.cached for p in force.pages))
    def test_scanned_toc_and_mixed_native_document(self):
        path=scanned(self.root/'toc.pdf',[['Contents','Chapter 1 Alpha .... 1','1.1 First .... 2','Chapter 2 Beta .... 3'],['Chapter 1 Alpha'],['1.1 First'],['Chapter 2 Beta']])
        plan=analyze_pdf(path,ocr_options=OCROptions(cache=False))
        self.assertEqual(plan.metadata['structure_source'],'toc')
        self.assertEqual([(i.start_page,i.end_page) for i in plan.items],[(2,2),(3,3),(4,4)])
        native=book(self.root/'native.pdf',[['Chapter 1 Alpha','Native text is readable and has at least forty useful characters.']])
        writer=PdfWriter();writer.append(PdfReader(native));writer.append(PdfReader(path),pages=(2,4))
        mixed=self.root/'mixed.pdf'
        with mixed.open('wb') as f:writer.write(f)
        plan=analyze_pdf(mixed,source='scan',ocr_options=OCROptions(cache=False))
        self.assertEqual([p.source for p in plan.pages],['native','ocr','ocr'])
        self.assertEqual([(i.start_page,i.end_page) for i in plan.items],[(1,1),(2,2),(3,3)])

    def test_real_two_column_toc(self):
        from PIL import Image, ImageDraw, ImageFont
        font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',38)
        image=Image.new('RGB',(1700,2200),'white');draw=ImageDraw.Draw(image);draw.text((100,100),'Contents',fill='black',font=font)
        left=['Chapter 1 Alpha .... 1','1.1 First .... 2','1.2 Second .... 3']
        right=['Chapter 2 Beta .... 4','2.1 Third .... 5','2.2 Fourth .... 6']
        for x,column in [(100,left),(950,right)]:
            for row,line in enumerate(column):draw.text((x,230+row*100),line,fill='black',font=font)
        toc=self.root/'columns.pdf';image.save(toc,'PDF',resolution=200)
        body=scanned(self.root/'body.pdf',[[s.rsplit(' .... ',1)[0]] for s in left+right]);writer=PdfWriter();writer.append(PdfReader(toc));writer.append(PdfReader(body));path=self.root/'two-columns.pdf'
        with path.open('wb') as stream:writer.write(stream)
        plan=analyze_pdf(path,source='toc',ocr_options=OCROptions(cache=False))
        self.assertEqual([e.page_index for e in plan.entries],[1,2,3,4,5,6])
        self.assertEqual([(i.start_page,i.end_page) for i in plan.items],[(n,n) for n in range(2,8)])

    def test_native_crop_rotation_preview(self):
        original=book(self.root/'original.pdf',[['Chapter 1 Alpha','A clear native text layer contains more than forty characters.'],['Chapter 2 Beta','Another native text layer with more than forty characters.'],[]])
        writer=PdfWriter();reader=PdfReader(original)
        reader.pages[0].cropbox.lower_left=(30,30);reader.pages[0].cropbox.upper_right=(580,760)
        reader.pages[1].rotate(90)
        for page in reader.pages:writer.add_page(page)
        path=self.root/'rotate.pdf'
        with path.open('wb') as f:writer.write(f)
        pages,_=extract_pages(path,PdfReader(path),OCROptions('auto',cache=False));self.assertEqual([p.source for p in pages[:2]],['native']*2);self.assertEqual(pages[2].status,'blank')
        with NativeClient() as client:
            for number in [1,2]:
                image=client.preview(path,number);self.assertTrue(image.exists())
        self.assertTrue(all(-.001<=value<=1.001 for p in pages for b in p.blocks for value in b.bbox))
        force,_=extract_pages(path,PdfReader(path),OCROptions('force',cache=False),selected=[2])
        self.assertIn('Chapter 2 Beta',force[0].text)
        self.assertGreater(force[0].blocks[0].bbox[3],force[0].blocks[0].bbox[2])

if __name__=='__main__':unittest.main()
