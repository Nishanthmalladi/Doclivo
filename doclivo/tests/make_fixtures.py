"""Builds small sample files used by the tests:  python -m tests.make_fixtures"""
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches, Pt
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "fixtures"


def main():
    OUT.mkdir(exist_ok=True)
    d = Document()
    d.add_heading("Quarterly Report", 0)
    d.add_paragraph("Revenue grew by 12 percent compared to last quarter.")
    t = d.add_table(rows=3, cols=2)
    for r, (a, b) in enumerate([("Region", "Sales"), ("North", "1200"), ("South", "950")]):
        t.cell(r, 0).text, t.cell(r, 1).text = a, b
    d.save(OUT / "report.docx")

    p = Presentation()
    for title in ("Welcome Slide", "Second Slide", "Thank You"):
        s = p.slides.add_slide(p.slide_layouts[1])
        s.shapes.title.text = title
        s.placeholders[1].text = f"Content for {title.lower()}"
    p.save(OUT / "deck.pptx")

    wb = Workbook()
    ws = wb.active
    ws.append(["Item", "Qty", "Price"])
    ws.append(["Pen", 10, 5.5])
    ws.append(["Book", 2, 120])
    wb.save(OUT / "sheet.xlsx")

    c = canvas.Canvas(str(OUT / "text.pdf"), pagesize=A4)
    for i in range(1, 4):
        c.setFont("Helvetica", 18)
        c.drawString(72, 760, f"Hello page {i}")
        c.setFont("Helvetica", 11)
        y = 700
        for row in (["Name", "Score"], ["Asha", "91"], ["Ravi", "84"]):
            c.drawString(72, y, row[0]); c.drawString(250, y, row[1])
            c.rect(66, y - 6, 120, 22); c.rect(244, y - 6, 80, 22)
            y -= 22
        c.showPage()
    c.save()

    w = PdfWriter(clone_from=PdfReader(str(OUT / "text.pdf")))
    for pg, rot in zip(w.pages, (90, 180, 270)):
        pg.rotate(rot)
    w.write(str(OUT / "rotated.pdf"))

    img = Image.new("RGB", (1600, 1000), "white")
    dr = ImageDraw.Draw(img)
    dr.rectangle([100, 100, 1500, 900], outline="navy", width=12)
    dr.ellipse([600, 300, 1000, 700], fill="orange")
    img.save(OUT / "photo.jpg", quality=95)
    Image.new("RGBA", (400, 400), (0, 128, 0, 120)).save(OUT / "logo.png")

    # a "scan": the page is only a picture of text
    scan = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(scan).text((150, 200), "INVOICE NUMBER 4471", fill="black",
                              font=__import__("PIL.ImageFont", fromlist=["x"]).truetype(
                                  str(Path(__file__).parents[1] / "app/fonts/DejaVuSans.ttf"), 64))
    scan.save(OUT / "scan.pdf", "PDF", resolution=150)

    big = Image.effect_noise((2400, 3200), 60).convert("RGB")
    c = canvas.Canvas(str(OUT / "heavy.pdf"), pagesize=A4)
    big.save("/tmp/_big.png")
    c.drawImage("/tmp/_big.png", 0, 0, *A4)
    c.showPage(); c.save()




def watermark_fixtures():
    """Watermarked samples: our own text watermark, an Acrobat-style labelled one,
    a faint repeated logo, and a Word file with a real Word watermark."""
    import pikepdf
    from docx import Document as _Doc
    from lxml import etree
    from app import engine

    engine.watermark(OUT / "text.pdf", OUT / "wm-tiled.pdf", {"text": "CONFIDENTIAL", "layout": "tiled"})
    engine.watermark(OUT / "text.pdf", OUT / "wm-center.pdf", {"text": "DRAFT COPY", "layout": "center"})

    pdf = pikepdf.open(OUT / "text.pdf")
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
    for page in pdf.pages:
        page.obj.Resources.Font[pikepdf.Name.WMF] = font
        page.contents_add(pdf.make_stream(
            b"/Artifact <</Subtype /Watermark /Type /Pagination>> BDC q 0.6 g BT /WMF 64 Tf 1 0 0 1 120 420 Tm (SAMPLE) Tj ET Q EMC"), prepend=False)
    pdf.save(OUT / "wm-artifact.pdf")

    c = canvas.Canvas(str(OUT / "wm-logo.pdf"), pagesize=A4)
    for i in range(1, 4):
        c.setFont("Helvetica", 18)
        c.drawString(72, 760, f"Report page {i}")
        c.saveState()
        c.setFillAlpha(0.15)
        c.drawImage(str(OUT / "photo.jpg"), 150, 300, 300, 190)
        c.restoreState()
        c.showPage()
    c.save()

    d = _Doc()
    d.add_paragraph("Body text that must stay.")
    header = d.sections[0].header
    p = header.paragraphs[0]
    p.add_run("Company header")
    vml = (
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">'
        '<w:pict><v:shapetype id="_x0000_t136" coordsize="21600,21600" o:spt="136" adj="10800" '
        'path="m@7,l@8,m@5,21600l@6,21600e"/>'
        '<v:shape id="PowerPlusWaterMarkObject357476642" o:spid="_x0000_s2049" type="#_x0000_t136" '
        'style="position:absolute;margin-left:0;margin-top:0;width:494.9pt;height:164.95pt;rotation:315;'
        'z-index:-251657216;mso-position-horizontal:center;mso-position-horizontal-relative:margin;'
        'mso-position-vertical:center;mso-position-vertical-relative:margin" o:allowincell="f" '
        'fillcolor="silver" stroked="f"><v:fill opacity=".5"/>'
        '<v:textpath style="font-family:&quot;Calibri&quot;;font-size:1pt" string="CONFIDENTIAL"/>'
        '</v:shape></w:pict></w:r>')
    p._p.append(etree.fromstring(vml))
    d.save(OUT / "wm.docx")


if __name__ == "__main__":
    main()
    watermark_fixtures()
