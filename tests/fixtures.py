from io import BytesIO
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


def book(path, lines, bookmarks=()):
    buffer=BytesIO();c=canvas.Canvas(buffer,pagesize=(612,792))
    for page in lines:
        y=730
        for line in page:
            c.drawString(60,y,line);y-=30
        c.showPage()
    c.save();w=PdfWriter();w.append(PdfReader(buffer))
    parents={}
    for title,page,parent in bookmarks:
        parents[title]=w.add_outline_item(title,page,parent=parents.get(parent))
    with Path(path).open('wb') as f:w.write(f)
    return Path(path)


def scanned(path, lines):
    from PIL import Image, ImageDraw, ImageFont
    fontpath='/System/Library/Fonts/STHeiti Medium.ttc'
    if not Path(fontpath).exists():fontpath='/System/Library/Fonts/Supplemental/Arial.ttf'
    font=ImageFont.truetype(fontpath,48)
    images=[]
    for page in lines:
        image=Image.new('RGB',(1700,2200),'white');draw=ImageDraw.Draw(image)
        for index,line in enumerate(page):draw.text((140,140+index*100),line,fill='black',font=font)
        images.append(image)
    images[0].save(path,'PDF',resolution=200,save_all=True,append_images=images[1:])
    return Path(path)
