"""Run:  python -m pytest -q     (needs LibreOffice for the Office tests)"""
import base64
import io
import zipfile
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pytest
from PIL import Image
from pypdf import PdfReader

from app import engine, office
from app.errors import UserError

F = Path(__file__).parent / "fixtures"
LIMITS = {"office_timeout": 120, "max_pages": 300, "max_pages_docx": 100}
needs_office = pytest.mark.skipif(office.soffice_path() is None, reason="LibreOffice not installed")


def conv(tmp_path, name, target, **opts):
    return engine.convert(F / name, target, tmp_path, stem=Path(name).stem, profile=tmp_path / "profile",
                          limits=LIMITS, options=opts)


@needs_office
@pytest.mark.parametrize("name,target", [
    ("report.docx", "pdf"), ("report.docx", "odt"), ("report.docx", "doc"), ("report.docx", "txt"),
    ("deck.pptx", "pdf"), ("deck.pptx", "odp"), ("sheet.xlsx", "pdf"), ("sheet.xlsx", "csv"),
])
def test_office_conversions(tmp_path, name, target):
    out = conv(tmp_path, name, target)
    assert out.suffix == f".{target}" and out.stat().st_size > 0


@needs_office
def test_powerpoint_to_pdf_keeps_every_slide(tmp_path):
    assert len(PdfReader(conv(tmp_path, "deck.pptx", "pdf")).pages) == 3


@needs_office
def test_excel_to_csv_content(tmp_path):
    assert conv(tmp_path, "sheet.xlsx", "csv").read_text().splitlines()[1] == '"Pen",10,5.5'


def test_pdf_to_word_and_back_text(tmp_path):
    import docx
    out = conv(tmp_path, "text.pdf", "docx")
    text = " ".join(p.text for p in docx.Document(out).paragraphs)
    assert "Hello page 1" in text


def test_pdf_to_powerpoint_one_slide_per_page(tmp_path):
    from pptx import Presentation
    prs = Presentation(conv(tmp_path, "text.pdf", "pptx"))
    assert len(prs.slides) == 3
    assert "Hello page 2" in prs.slides[1].notes_slide.notes_text_frame.text


def test_pdf_to_excel_finds_tables(tmp_path):
    import openpyxl
    wb = openpyxl.load_workbook(conv(tmp_path, "text.pdf", "xlsx"))
    values = [c.value for row in wb["Page 1"].iter_rows() for c in row if c.value is not None]
    assert "Asha" in values and 91 in values


def test_pdf_to_images_zip(tmp_path):
    out = conv(tmp_path, "text.pdf", "png", dpi=72)
    assert len(zipfile.ZipFile(out).namelist()) == 3


@pytest.mark.skipif(not engine.tesseract_available(), reason="tesseract not installed")
def test_scanned_pdf_text_uses_ocr(tmp_path):
    assert "4471" in conv(tmp_path, "scan.pdf", "txt").read_text()


def test_images_to_pdf_and_back(tmp_path):
    pdf = engine.images_to_pdf([F / "photo.jpg", F / "logo.png"], tmp_path / "x.pdf", {"page_size": "a4"})
    r = PdfReader(pdf)
    assert len(r.pages) == 2 and round(float(r.pages[0].mediabox.height)) == 595   # landscape A4 for a wide photo
    assert conv(tmp_path, "logo.png", "jpg").suffix == ".jpg"


def test_merge_split_organize(tmp_path):
    merged = engine.merge([F / "text.pdf", F / "text.pdf"], tmp_path / "m.pdf", 300)
    assert len(PdfReader(merged).pages) == 6
    z = engine.split(F / "text.pdf", tmp_path, "t", "ranges", "1-2, 3", 300)
    assert sorted(zipfile.ZipFile(z).namelist()) == ["t-pages-1-2.pdf", "t-pages-3.pdf"]
    org = PdfReader(engine.organize(F / "text.pdf", tmp_path / "o.pdf", [{"page": 2, "rotate": 90}, {"page": 0}], 300))
    assert [p.rotation for p in org.pages] == [90, 0] and "page 3" in org.pages[0].extract_text()


def test_bad_page_ranges(tmp_path):
    for bad in ("0", "2-1", "9", "abc"):
        with pytest.raises(UserError):
            engine.split(F / "text.pdf", tmp_path, "t", "ranges", bad, 300)


def test_compress_shrinks_and_never_grows(tmp_path):
    _, info = engine.compress(F / "heavy.pdf", tmp_path / "c.pdf", "medium")
    assert info["after"] < info["before"] / 4
    _, info = engine.compress(F / "text.pdf", tmp_path / "c2.pdf", "high")
    assert info["after"] <= info["before"]


def test_protect_unlock(tmp_path):
    locked = engine.protect(F / "text.pdf", tmp_path / "p.pdf", "secret12")
    assert PdfReader(locked).is_encrypted
    with pytest.raises(UserError, match="not correct"):
        engine.unlock(locked, tmp_path / "u.pdf", "nope")
    with pytest.raises(UserError, match="password-protected"):
        engine.open_pdf(locked)
    assert not PdfReader(engine.unlock(locked, tmp_path / "u.pdf", "secret12")).is_encrypted


def _changed_box(before, after, i):
    a = np.asarray(pdfium.PdfDocument(str(before))[i].render(scale=1).to_pil().convert("L")).astype(int)
    b = np.asarray(pdfium.PdfDocument(str(after))[i].render(scale=1).to_pil().convert("L")).astype(int)
    ys, xs = np.where(np.abs(a - b) > 60)
    h, w = a.shape
    return xs.min() / w, ys.min() / h, xs.max() / w, ys.max() / h


@pytest.mark.parametrize("page", [0, 1, 2])          # pages rotated 90, 180 and 270 degrees
def test_edits_land_where_they_were_placed_on_rotated_pages(tmp_path, page):
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "black").save(buf, "PNG")
    data = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    out = engine.edit(F / "rotated.pdf", tmp_path / "e.pdf",
                      [{"page": page, "type": "image", "x": 0.1, "y": 0.05, "w": 0.2, "h": 0.1, "data": data}])
    x0, y0, x1, y1 = _changed_box(F / "rotated.pdf", out, page)
    assert abs(x0 - 0.1) < 0.01 and abs(y0 - 0.05) < 0.01 and abs(x1 - 0.3) < 0.01 and abs(y1 - 0.15) < 0.01


def test_edit_text_ink_rect(tmp_path):
    ops = [{"page": 0, "type": "text", "x": 0.1, "y": 0.5, "text": "Approved ✓", "size": 18, "color": "#123456", "font": "serif-bold"},
           {"page": 0, "type": "rect", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.05, "fill": "#ffffff", "opacity": 1},
           {"page": 1, "type": "ink", "points": [[0.1, 0.1], [0.5, 0.5]], "color": "#ff0000", "width": 3}]
    out = PdfReader(engine.edit(F / "text.pdf", tmp_path / "e.pdf", ops))
    assert "Approved" in out.pages[0].extract_text()


@pytest.mark.parametrize("ops", [[{"page": 0, "type": "nope"}], [{"page": 0, "type": "text", "x": "a"}],
                                 [{"page": 0, "type": "image", "x": 0, "y": 0, "w": .1, "h": .1, "data": "javascript:x"}]])
def test_edit_rejects_bad_ops(tmp_path, ops):
    with pytest.raises(UserError):
        engine.edit(F / "text.pdf", tmp_path / "e.pdf", ops)


def test_watermark_and_page_numbers(tmp_path):
    w = PdfReader(engine.watermark(F / "text.pdf", tmp_path / "w.pdf", {"text": "DRAFT", "layout": "tiled"}))
    assert "DRAFT" in w.pages[0].extract_text()
    n = PdfReader(engine.page_numbers(F / "text.pdf", tmp_path / "n.pdf", {"format": "page-n-of-total", "skip_first": True}))
    assert "Page 1 of 2" in n.pages[1].extract_text() and "Page" not in n.pages[0].extract_text().split("Hello")[0]


def test_not_a_pdf(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(UserError):
        engine.merge([bad, bad], tmp_path / "m.pdf", 300)


# ---------------------------------------------------------------- watermarks
from app import watermark  # noqa: E402


def _pixels_changed(a, b, i):
    x = np.asarray(pdfium.PdfDocument(str(a))[i].render(scale=1).to_pil().convert("L")).astype(int)
    y = np.asarray(pdfium.PdfDocument(str(b))[i].render(scale=1).to_pil().convert("L")).astype(int)
    return int((np.abs(x - y) > 40).sum())


@pytest.mark.parametrize("name", ["wm-tiled.pdf", "wm-center.pdf", "wm-artifact.pdf"])
def test_pdf_watermark_removed_and_page_restored(tmp_path, name):
    out, meta = watermark.remove_from_pdf(F / name, tmp_path / "c.pdf")
    assert meta["removed"] > 0
    for i in range(3):           # identical to the page before it was watermarked
        assert _pixels_changed(out, F / "text.pdf", i) == 0
    assert "Asha" in PdfReader(out).pages[0].extract_text()


def test_faint_logo_watermark_removed(tmp_path):
    out, meta = watermark.remove_from_pdf(F / "wm-logo.pdf", tmp_path / "c.pdf")
    assert meta["removed"] == 3 and "Report page 2" in PdfReader(out).pages[1].extract_text()


def test_watermark_by_typed_text(tmp_path):
    out, _ = watermark.remove_from_pdf(F / "wm-center.pdf", tmp_path / "c.pdf", "draft copy")
    assert "DRAFT" not in PdfReader(out).pages[0].extract_text()


def test_clean_pdf_reports_nothing_found(tmp_path):
    with pytest.raises(UserError, match="couldn't find a watermark"):
        watermark.remove_from_pdf(F / "text.pdf", tmp_path / "c.pdf")


@needs_office
@pytest.mark.parametrize("name", ["report.docx", "deck.pptx", "sheet.xlsx"])
def test_ordinary_documents_are_never_changed(tmp_path, name):
    pdf = office.convert(F / name, "pdf", tmp_path / "lo", tmp_path / "profile", 120)
    out, meta = watermark.remove_from_pdf(pdf, tmp_path / "c.pdf", must_find=False)
    assert meta["removed"] == 0
    assert all(_pixels_changed(pdf, out, i) == 0 for i in range(len(PdfReader(pdf).pages)))


@needs_office
def test_word_watermark_exported_to_pdf_is_removed(tmp_path):
    pdf = office.convert(F / "wm.docx", "pdf", tmp_path / "lo", tmp_path / "profile", 120)
    out, meta = watermark.remove_from_pdf(pdf, tmp_path / "c.pdf")
    assert meta["removed"] >= 1 and "Body text that must stay." in PdfReader(out).pages[0].extract_text()


def test_word_watermark_removed_from_docx(tmp_path):
    out, meta = watermark.remove_from_docx(F / "wm.docx", tmp_path / "c.docx")
    header = zipfile.ZipFile(out).read("word/header1.xml").decode()
    assert meta["removed"] == 1 and "WaterMark" not in header and "Company header" in header
    import docx
    assert docx.Document(out).paragraphs[0].text == "Body text that must stay."


def test_docx_without_watermark(tmp_path):
    with pytest.raises(UserError, match="couldn't find a watermark"):
        watermark.remove_from_docx(F / "report.docx", tmp_path / "c.docx")


def test_pdf_to_word_without_watermark(tmp_path):
    import docx
    out = conv(tmp_path, "wm-tiled.pdf", "docx", remove_watermark=True)
    text = " ".join(p.text for p in docx.Document(out).paragraphs)
    assert "Hello page 1" in text and "CONFIDENTIAL" not in text


# ---------------------------------------------------------------- PowerPoint -> Word
def _rich_deck(path):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Introduction to NoSQL"
    body = s.placeholders[1].text_frame
    body.text = "Document stores"
    sub = body.add_paragraph()
    sub.text, sub.level = "MongoDB", 1
    s.notes_slide.notes_text_frame.text = "Mention CAP theorem"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Comparison"
    t = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(6), Inches(1)).table
    for (r, c), v in zip([(0, 0), (0, 1), (1, 0), (1, 1)], ["Type", "Example", "Key-value", "Redis"]):
        t.cell(r, c).text = v
    s2.shapes.add_picture(str(F / "photo.jpg"), Inches(1), Inches(4), Inches(3))
    prs.save(path)
    return path


@needs_office
def test_powerpoint_to_word_outline(tmp_path):
    import docx
    deck = _rich_deck(tmp_path / "rich.pptx")
    out = engine.convert(deck, "docx", tmp_path, stem="rich", profile=tmp_path / "p", limits=LIMITS, options={"ppt_word": "outline"})
    d = docx.Document(out)
    texts = [p.text for p in d.paragraphs]
    assert "Slide 1: Introduction to NoSQL" in texts and "MongoDB" in texts
    assert any("Mention CAP theorem" in t for t in texts)
    assert d.tables[0].cell(1, 1).text == "Redis"
    assert len(d.inline_shapes) == 1                     # the picture came across


@needs_office
def test_powerpoint_to_word_keeps_slide_look(tmp_path):
    import docx
    out = conv(tmp_path, "deck.pptx", "docx", ppt_word="layout")
    text = " ".join(p.text for p in docx.Document(out).paragraphs)
    assert "Welcome Slide" in text and "Thank You" in text


@needs_office
def test_old_ppt_to_word_outline(tmp_path):
    ppt = office.convert(F / "deck.pptx", "ppt", tmp_path / "lo", tmp_path / "p", 120)
    import docx
    out = engine.convert(ppt, "docx", tmp_path, stem="old", profile=tmp_path / "p", limits=LIMITS, options={"ppt_word": "outline"})
    assert "Slide 2: Second Slide" in [p.text for p in docx.Document(out).paragraphs]
