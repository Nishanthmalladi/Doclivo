"""All file work.  Every function takes input paths and an output directory and
returns the path of the finished file (a .zip when there are several outputs).

These run inside a separate worker process (see jobs.py / runner.py), so a
damaged or hostile file can only hang or crash that process, never the server.
"""
from __future__ import annotations

import base64
import io
import math
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.errors import FileNotDecryptedError, PdfReadError
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from . import office
from .errors import UserError
from .formats import LABELS, TARGETS, kind_of

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:          # HEIC (iPhone photos) support is optional
    pass

Image.MAX_IMAGE_PIXELS = 120_000_000          # refuse decompression bombs
FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONTS = {"sans": "DejaVuSans", "sans-bold": "DejaVuSans-Bold", "serif": "DejaVuSerif",
         "serif-bold": "DejaVuSerif-Bold", "mono": "DejaVuSansMono"}
for _name in FONTS.values():
    pdfmetrics.registerFont(TTFont(_name, str(FONT_DIR / f"{_name}.ttf")))


# ---------------------------------------------------------------- helpers
def _zip(files: list[Path], out: Path) -> Path:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.name)
    return out


KIND_NAMES = {"document": "Word/text", "presentation": "PowerPoint", "spreadsheet": "Excel",
              "pdf": "PDF", "image": "Image", None: "These"}


def unique_name(name: str, used: set) -> str:
    """deck, deck -> deck, deck-2 so a zip never holds two files with one name."""
    candidate, n = name, 1
    while candidate.lower() in used:
        n += 1
        candidate = f"{name}-{n}"
    used.add(candidate.lower())
    return candidate


def copy_as(src: Path, dest: Path) -> Path:
    shutil.copyfile(src, dest)
    return dest


def _one_or_zip(files: list[Path], outdir: Path, zip_name: str) -> Path:
    return files[0] if len(files) == 1 else _zip(files, outdir / zip_name)


def _color(hex_color: str, default=(0, 0, 0)) -> tuple[float, float, float]:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(hex_color or ""))
    if not m:
        return default
    v = m.group(1)
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))


def open_pdf(path: Path, password: str | None = None) -> PdfReader:
    try:
        reader = PdfReader(str(path), strict=False)
    except (PdfReadError, ValueError, OSError) as e:
        raise UserError("This file is not a readable PDF.") from e
    if reader.is_encrypted:
        try:
            ok = reader.decrypt(password or "")
        except Exception:
            ok = 0
        if not ok:
            raise UserError("This PDF is password-protected. Use the Unlock tool first.")
    try:
        _ = len(reader.pages)
    except (FileNotDecryptedError, PdfReadError, Exception) as e:
        raise UserError("This PDF is damaged and cannot be read.") from e
    return reader


def check_pages(n: int, limit: int):
    if n > limit:
        raise UserError(f"This PDF has {n} pages; the limit for this tool is {limit}.")


def parse_ranges(spec: str, n: int) -> list[list[int]]:
    """'1-3, 5, 8-' -> [[0,1,2],[4],[7..n-1]] (1-based input, 0-based output)."""
    groups = []
    for part in re.split(r"[,\s;]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)|(\d+)", part)
        if not m:
            raise UserError(f"Could not understand the page range '{part}'. Use forms like 1-3, 5, 8-.")
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a = int(m.group(1) or 1)
            b = int(m.group(2) or n)
        if not (1 <= a <= b <= n):
            raise UserError(f"Page range '{part}' is outside 1-{n}.")
        groups.append(list(range(a - 1, b)))
    if not groups:
        raise UserError("Enter at least one page or range.")
    return groups


# ---------------------------------------------------------------- rendering
def render_pages(pdf: Path, outdir: Path, fmt: str, dpi: int, max_pages: int, stem: str) -> list[Path]:
    try:
        doc = pdfium.PdfDocument(str(pdf))
    except pdfium.PdfiumError as e:
        raise UserError("This PDF could not be opened (damaged or password-protected).") from e
    n = len(doc)
    check_pages(n, max_pages)
    files = []
    width = len(str(n))
    for i in range(n):
        img = doc[i].render(scale=dpi / 72).to_pil()
        out = outdir / f"{stem}-page-{str(i + 1).zfill(width)}.{fmt}"
        if fmt == "jpg":
            img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
        else:
            img.save(out, "PNG", optimize=True)
        files.append(out)
    doc.close()
    return files


# ---------------------------------------------------------------- conversion
def convert(src: Path, target: str, outdir: Path, *, stem: str, profile: Path, limits: dict,
            options: dict | None = None) -> Path:
    options = options or {}
    kind = kind_of(src.suffix.lstrip("."))
    if kind is None:
        raise UserError("This file type is not supported.")
    t = limits["office_timeout"]

    if kind in ("document", "presentation", "spreadsheet"):
        if target in ("jpg", "png"):
            pdf = office.convert(src, "pdf", outdir / "tmp", profile, t)
            files = render_pages(pdf, outdir, target, int(options.get("dpi", 150)), limits["max_pages"], stem)
            return _one_or_zip(files, outdir, f"{stem}-images.zip")
        if kind == "presentation" and target == "docx":
            return presentation_to_docx(src, outdir, stem, profile, limits, options.get("ppt_word", "layout"))
        result = office.convert(src, target, outdir / "lo", profile, t)
        return result.rename(outdir / f"{stem}.{target}")

    if kind == "pdf":
        reader = open_pdf(src)
        n = len(reader.pages)
        if target in ("jpg", "png"):
            files = render_pages(src, outdir, target, int(options.get("dpi", 150)), limits["max_pages"], stem)
            return _one_or_zip(files, outdir, f"{stem}-images.zip")
        if target in ("docx", "odt"):
            check_pages(n, limits["max_pages_docx"])
            docx = outdir / f"{stem}.docx"
            if options.get("remove_watermark"):
                from .watermark import remove_from_pdf
                src, _ = remove_from_pdf(src, outdir / "no-watermark.pdf",
                                         str(options.get("watermark_text", ""))[:200], must_find=False)
            pdf_to_docx(src, docx)
            if target == "docx":
                return docx
            return office.convert(docx, "odt", outdir / "lo", profile, t).rename(outdir / f"{stem}.odt")
        if target == "pptx":
            check_pages(n, limits["max_pages"])
            return pdf_to_pptx(src, reader, outdir / f"{stem}.pptx")
        if target == "xlsx":
            check_pages(n, limits["max_pages"])
            return pdf_to_xlsx(src, outdir / f"{stem}.xlsx")
        if target == "txt":
            check_pages(n, limits["max_pages"])
            return pdf_to_txt(src, outdir / f"{stem}.txt", outdir, options.get("lang", "eng"))

    if kind == "image":
        if target == "pdf":
            return images_to_pdf([src], outdir / f"{stem}.pdf", options)
        return image_to_image(src, target, outdir / f"{stem}.{target}")

    raise UserError(f"Converting .{src.suffix.lstrip('.')} to .{target} is not supported.")


def presentation_to_docx(src: Path, outdir: Path, stem: str, profile: Path, limits: dict, style: str) -> Path:
    """PowerPoint -> Word.
    layout:  every slide becomes a page that looks like the slide (via PDF).
    outline: slide titles, bullet points, tables, pictures and speaker notes as a
             normal, easy-to-edit Word document."""
    out = outdir / f"{stem}.docx"
    t = limits["office_timeout"]
    if style == "outline":
        if src.suffix.lower() != ".pptx":
            src = office.convert(src, "pptx", outdir / "lo-pptx", profile, t)
        return pptx_outline_to_docx(src, out, limits["max_pages"])
    pdf = office.convert(src, "pdf", outdir / "lo-pdf", profile, t)
    check_pages(len(open_pdf(pdf).pages), limits["max_pages_docx"])
    pdf_to_docx(pdf, out)
    return out


def pptx_outline_to_docx(src: Path, out: Path, max_slides: int) -> Path:
    from docx import Document
    from docx.shared import Inches, Pt
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
    try:
        prs = Presentation(str(src))
    except Exception as e:
        raise UserError("This presentation could not be opened.") from e
    slides = list(prs.slides)
    check_pages(len(slides), max_slides)
    doc = Document()
    doc.styles["Normal"].font.size = Pt(11)
    title_types = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}

    def is_title(shape):
        try:
            return shape.is_placeholder and shape.placeholder_format.type in title_types
        except Exception:
            return False

    def flatten(shapes):
        for sh in shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from flatten(sh.shapes)
            else:
                yield sh

    for n, slide in enumerate(slides, start=1):
        shapes = sorted(flatten(slide.shapes), key=lambda s: ((s.top or 0), (s.left or 0)))
        title = next((s.text_frame.text.strip() for s in shapes if is_title(s) and s.has_text_frame and s.text_frame.text.strip()), "")
        doc.add_heading(f"Slide {n}" + (f": {title}" if title else ""), level=1)
        for sh in shapes:
            if is_title(sh):
                continue
            if sh.has_text_frame:
                for para in sh.text_frame.paragraphs:
                    text = "".join(r.text for r in para.runs).strip()
                    if not text:
                        continue
                    level = min(para.level, 2)
                    style = "List Bullet" if level == 0 else f"List Bullet {level + 1}"
                    try:
                        p = doc.add_paragraph(style=style)
                    except KeyError:
                        p = doc.add_paragraph()
                    for r in para.runs:
                        if not r.text:
                            continue
                        run = p.add_run(r.text)
                        run.bold, run.italic, run.underline = r.font.bold, r.font.italic, r.font.underline
            elif getattr(sh, "has_table", False) and sh.has_table:
                rows = sh.table.rows
                cols = len(sh.table.columns)
                table = doc.add_table(rows=len(rows), cols=cols)
                table.style = "Table Grid"
                for i, row in enumerate(rows):
                    for j, cell in enumerate(row.cells):
                        if j < cols:
                            table.cell(i, j).text = cell.text
                doc.add_paragraph()
            elif sh.shape_type == MSO_SHAPE_TYPE.PICTURE or getattr(sh, "image", None) is not None:
                try:
                    blob = sh.image.blob
                    img = Image.open(io.BytesIO(blob))
                    img.load()
                    buf = io.BytesIO()
                    (img.convert("RGB") if img.mode not in ("RGB", "RGBA", "L") else img).save(buf, "PNG")
                    buf.seek(0)
                    width = min(6.0, (sh.width or Inches(6)) / 914400)
                    doc.add_picture(buf, width=Inches(max(width, 1.0)))
                except Exception:
                    continue           # images Word cannot hold (e.g. some vector formats) are skipped
        try:
            notes = slide.notes_slide.notes_text_frame.text.strip() if slide.has_notes_slide else ""
        except Exception:
            notes = ""
        if notes:
            p = doc.add_paragraph()
            r = p.add_run("Speaker notes: ")
            r.bold = True
            p.add_run(notes).italic = True
        if n < len(slides):
            doc.add_page_break()
    doc.save(str(out))
    return out


def pdf_to_docx(src: Path, out: Path):
    from pdf2docx import Converter       # imported here: it is slow to load
    import logging
    logging.getLogger().setLevel(logging.ERROR)
    try:
        cv = Converter(str(src))
        cv.convert(str(out), multi_processing=False)
        cv.close()
    except Exception as e:
        raise UserError("This PDF could not be converted to Word. It may be damaged or scanned.") from e
    if not out.exists():
        raise UserError("This PDF could not be converted to Word.")


def pdf_to_pptx(src: Path, reader: PdfReader, out: Path) -> Path:
    """Each PDF page becomes one slide (as a picture), with the page's text in the
    speaker notes so it stays searchable and copyable."""
    from pptx import Presentation
    from pptx.util import Emu
    doc = pdfium.PdfDocument(str(src))
    w_pt, h_pt = doc[0].get_size()
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(w_pt * 12700)), Emu(int(h_pt * 12700))
    blank = prs.slide_layouts[6]
    for i in range(len(doc)):
        page = doc[i]
        pw, ph = page.get_size()
        buf = io.BytesIO()
        page.render(scale=2).to_pil().convert("RGB").save(buf, "JPEG", quality=88)
        buf.seek(0)
        slide = prs.slides.add_slide(blank)
        scale = min(prs.slide_width / (pw * 12700), prs.slide_height / (ph * 12700))
        w, h = int(pw * 12700 * scale), int(ph * 12700 * scale)
        slide.shapes.add_picture(buf, (prs.slide_width - w) // 2, (prs.slide_height - h) // 2, w, h)
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            slide.notes_slide.notes_text_frame.text = text.strip()[:20000]
    doc.close()
    prs.save(out)
    return out


def pdf_to_xlsx(src: Path, out: Path) -> Path:
    """Tables found on each page go to a sheet per page; pages without tables
    keep their text, one line per row."""
    import pdfplumber
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    found_any = False
    with pdfplumber.open(str(src)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            ws = wb.create_sheet(f"Page {i}")
            tables = page.extract_tables() or []
            row = 1
            if tables:
                found_any = True
                for t_index, table in enumerate(tables):
                    if t_index:
                        row += 1
                    for cells in table:
                        for c, value in enumerate(cells, start=1):
                            ws.cell(row=row, column=c, value=_number_or_text(value))
                        row += 1
            else:
                for line in (page.extract_text() or "").splitlines():
                    ws.cell(row=row, column=1, value=line)
                    row += 1
            for col in ws.columns:
                width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(width + 2, 8), 60)
    if not wb.sheetnames:
        wb.create_sheet("Page 1")
    wb.properties.description = "tables found" if found_any else "no tables found; text exported"
    wb.save(out)
    return out


def _number_or_text(value):
    if value is None:
        return None
    s = str(value).strip()
    plain = s.replace(",", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", plain) and len(plain) < 16:
        return float(plain) if "." in plain else int(plain)
    return s


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def pdf_to_txt(src: Path, out: Path, workdir: Path, lang: str = "eng") -> Path:
    import pdfplumber
    parts = []
    with pdfplumber.open(str(src)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            parts.append(f"--- Page {i} ---\n{(page.extract_text() or '').strip()}")
    text = "\n\n".join(parts)
    if not re.sub(r"--- Page \d+ ---", "", text).strip():
        if not tesseract_available():
            raise UserError("This PDF has no selectable text (it is probably scanned), and OCR is not "
                            "installed on this server.")
        text = _ocr_text(src, workdir, lang)
    out.write_text(text, encoding="utf-8")
    return out


def _ocr_text(src: Path, workdir: Path, lang: str) -> str:
    pages = render_pages(src, workdir, "png", 300, 200, "ocr")
    chunks = []
    for i, img in enumerate(pages, start=1):
        r = subprocess.run(["tesseract", str(img), "stdout", "-l", _lang(lang)],
                           capture_output=True, text=True, timeout=120)
        chunks.append(f"--- Page {i} ---\n{r.stdout.strip()}")
    return "\n\n".join(chunks)


def _lang(lang: str) -> str:
    """Only allow installed language codes like 'eng' or 'eng+hin'."""
    if not re.fullmatch(r"[a-z_]{3,8}(\+[a-z_]{3,8}){0,3}", lang or ""):
        return "eng"
    try:
        installed = set(subprocess.run(["tesseract", "--list-langs"], capture_output=True,
                                       text=True, timeout=10).stdout.splitlines()[1:])
    except Exception:
        return "eng"
    return lang if all(p in installed for p in lang.split("+")) else "eng"


# ---------------------------------------------------------------- images
PAGE_SIZES = {"a4": (595.28, 841.89), "letter": (612, 792)}


def _load_image(path: Path) -> Image.Image:
    try:
        img = Image.open(path)
        img.load()
    except Image.DecompressionBombError as e:
        raise UserError(f"{path.name} is too large an image.") from e
    except Exception as e:
        raise UserError(f"{path.name} is not a readable image.") from e
    return ImageOps.exif_transpose(img)


def images_to_pdf(paths: list[Path], out: Path, options: dict) -> Path:
    """One page per image.  page_size: fit | a4 | letter; orientation: auto |
    portrait | landscape; margin in points."""
    size_opt = options.get("page_size", "fit")
    orient = options.get("orientation", "auto")
    margin = max(0.0, min(float(options.get("margin", 0) or 0), 100.0))
    c = canvas.Canvas(str(out))
    for p in paths:
        img = _load_image(p)
        if getattr(img, "n_frames", 1) > 1:
            img.seek(0)
        if img.mode not in ("RGB", "L"):
            bg = Image.new("RGB", img.size, "white")
            bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
            img = bg
        iw, ih = img.size
        if size_opt in PAGE_SIZES:
            pw, ph = PAGE_SIZES[size_opt]
            landscape = (orient == "landscape") or (orient == "auto" and iw > ih)
            if landscape:
                pw, ph = ph, pw
        else:
            dpi = img.info.get("dpi", (96, 96))[0] or 96
            pw, ph = iw * 72 / dpi + 2 * margin, ih * 72 / dpi + 2 * margin
        c.setPageSize((pw, ph))
        scale = min((pw - 2 * margin) / iw, (ph - 2 * margin) / ih)
        w, h = iw * scale, ih * scale
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92) if img.mode == "RGB" else img.save(buf, "PNG")
        buf.seek(0)
        c.drawImage(ImageReader(buf), (pw - w) / 2, (ph - h) / 2, w, h)
        c.showPage()
    c.save()
    return out


def image_to_image(src: Path, target: str, out: Path) -> Path:
    img = _load_image(src)
    if target == "jpg":
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, "white")
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        img.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    elif target == "png":
        img.save(out, "PNG", optimize=True)
    elif target == "webp":
        img.save(out, "WEBP", quality=90)
    else:
        raise UserError(f"Cannot convert an image to .{target}")
    return out


# ---------------------------------------------------------------- PDF tools
def merge(paths: list[Path], out: Path, max_pages: int) -> Path:
    writer = PdfWriter()
    total = 0
    for p in paths:
        reader = open_pdf(p)
        total += len(reader.pages)
        check_pages(total, max_pages)
        writer.append(reader)
    writer.write(str(out))
    return out


def split(src: Path, outdir: Path, stem: str, mode: str, ranges: str, max_pages: int) -> Path:
    reader = open_pdf(src)
    n = len(reader.pages)
    check_pages(n, max_pages)
    if mode == "every":
        groups = [[i] for i in range(n)]
    else:
        groups = parse_ranges(ranges, n)
    if mode == "extract":                       # all chosen pages into one file
        groups = [[i for g in groups for i in g]]
    files = []
    for g in groups:
        w = PdfWriter()
        for i in g:
            w.add_page(reader.pages[i])
        label = f"{g[0] + 1}" if len(g) == 1 else f"{g[0] + 1}-{g[-1] + 1}"
        name = f"{stem}-pages-{label}.pdf" if mode != "extract" else f"{stem}-extracted.pdf"
        path = outdir / name
        w.write(str(path))
        files.append(path)
    return _one_or_zip(files, outdir, f"{stem}-split.zip")


def organize(src: Path, out: Path, pages: list, max_pages: int) -> Path:
    """pages: [{"page": original 0-based index, "rotate": 0|90|180|270}, ...] in the
    new order.  Pages not listed are deleted; a page may appear twice (duplicate)."""
    reader = open_pdf(src)
    n = len(reader.pages)
    if not isinstance(pages, list) or not pages:
        raise UserError("Keep at least one page.")
    check_pages(len(pages), max_pages)
    writer = PdfWriter()
    for item in pages:
        try:
            idx, rot = int(item["page"]), int(item.get("rotate", 0))
        except (KeyError, TypeError, ValueError):
            raise UserError("Invalid page list.") from None
        if not 0 <= idx < n or rot % 90:
            raise UserError("Invalid page list.")
        page = writer.add_page(reader.pages[idx])
        if rot % 360:
            page.rotate(rot % 360)
    writer.write(str(out))
    return out


def compress(src: Path, out: Path, level: str) -> tuple[Path, dict]:
    """Re-encode large images at a lower resolution and quality, and pack the
    file structure.  Never returns a bigger file than the original."""
    quality, max_dpi = {"low": (85, 200), "medium": (70, 150), "high": (50, 100)}.get(level, (70, 150))
    try:
        pdf = pikepdf.open(str(src))
    except pikepdf.PasswordError:
        raise UserError("This PDF is password-protected. Use the Unlock tool first.") from None
    except Exception as e:
        raise UserError("This file is not a readable PDF.") from e
    seen = set()
    for page in pdf.pages:
        try:
            width_pt = float(page.mediabox[2]) - float(page.mediabox[0])
        except Exception:
            width_pt = 612
        for raw in _page_images(page):
            if raw.objgen in seen:
                continue
            seen.add(raw.objgen)
            try:
                _recompress_image(raw, quality, max_dpi, width_pt)
            except Exception:
                continue              # leave anything unusual untouched
    pdf.remove_unreferenced_resources()
    pdf.save(str(out), compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate,
             recompress_flate=True)
    before, after = src.stat().st_size, out.stat().st_size
    if after >= before:
        shutil.copyfile(src, out)
        after = before
    return out, {"before": before, "after": after}


def _page_images(page):
    getter = getattr(page, "get_images", None)
    images = getter() if getter else page.images
    return list(images.values())


def _recompress_image(raw, quality: int, max_dpi: int, page_width_pt: float):
    from pikepdf import PdfImage, Name
    if raw.get("/SMask") is not None or raw.get("/Mask") is not None or raw.get("/ImageMask"):
        return
    pimg = PdfImage(raw)
    if pimg.bits_per_component != 8 or pimg.colorspace not in ("/DeviceRGB", "/DeviceGray"):
        return
    img = pimg.as_pil_image()
    # assume the image spans at most the page width to estimate its resolution
    target_w = int(page_width_pt / 72 * max_dpi)
    if img.width > target_w:
        img = img.resize((target_w, max(1, round(img.height * target_w / img.width))), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("L" if pimg.colorspace == "/DeviceGray" else "RGB").save(buf, "JPEG", quality=quality, optimize=True)
    data = buf.getvalue()
    if len(data) >= len(raw.read_raw_bytes()):
        return
    raw.write(data, filter=Name.DCTDecode)
    raw.Width, raw.Height = img.width, img.height
    raw.ColorSpace = Name.DeviceGray if pimg.colorspace == "/DeviceGray" else Name.DeviceRGB
    raw.BitsPerComponent = 8
    for key in ("/DecodeParms", "/Decode"):
        if key in raw:
            del raw[key]


def protect(src: Path, out: Path, password: str) -> Path:
    if not password or len(password) < 4 or len(password) > 128:
        raise UserError("Choose a password of 4 to 128 characters.")
    try:
        pdf = pikepdf.open(str(src))
    except pikepdf.PasswordError:
        raise UserError("This PDF already has a password. Unlock it first.") from None
    except Exception as e:
        raise UserError("This file is not a readable PDF.") from e
    import secrets
    pdf.save(str(out), encryption=pikepdf.Encryption(user=password, owner=secrets.token_urlsafe(24), R=6))
    return out


def unlock(src: Path, out: Path, password: str) -> Path:
    try:
        pdf = pikepdf.open(str(src), password=password or "")
    except pikepdf.PasswordError:
        raise UserError("That password is not correct.") from None
    except Exception as e:
        raise UserError("This file is not a readable PDF.") from e
    pdf.save(str(out))
    return out


# --- overlays: draw in the page's displayed orientation, then map onto the page
def _display_box(page) -> tuple[float, float, float, float, int]:
    box = page.cropbox
    left, bottom = float(box.left), float(box.bottom)
    w, h = float(box.width), float(box.height)
    rot = (page.rotation or 0) % 360
    return left, bottom, w, h, rot


def _display_to_user(left, bottom, w, h, rot) -> Transformation:
    """Matrix that maps the displayed page (origin bottom-left, as seen on screen)
    to the page's own coordinate space, for /Rotate 0/90/180/270."""
    if rot == 90:
        m = (0, 1, -1, 0, w, 0)
    elif rot == 180:
        m = (-1, 0, 0, -1, w, h)
    elif rot == 270:
        m = (0, -1, 1, 0, 0, h)
    else:
        m = (1, 0, 0, 1, 0, 0)
    a, b, c, d, e, f = m
    return Transformation((a, b, c, d, e + left, f + bottom))


def _stamp(reader: PdfReader, draw_page, out: Path) -> Path:
    """draw_page(canvas, page_index, width, height) draws on the displayed page."""
    writer = PdfWriter(clone_from=reader)
    for i, page in enumerate(writer.pages):
        left, bottom, w, h, rot = _display_box(page)
        dw, dh = (h, w) if rot in (90, 270) else (w, h)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(dw, dh))
        drew = draw_page(c, i, dw, dh)
        c.showPage()
        c.save()
        if drew is False:
            continue
        overlay = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
        page.merge_transformed_page(overlay, _display_to_user(left, bottom, w, h, rot), over=True)
    writer.write(str(out))
    return out


def watermark(src: Path, out: Path, opts: dict) -> Path:
    text = str(opts.get("text", "")).strip()[:120]
    if not text:
        raise UserError("Enter the watermark text.")
    size = max(8.0, min(float(opts.get("size", 48)), 200.0))
    opacity = max(0.05, min(float(opts.get("opacity", 0.25)), 1.0))
    angle = float(opts.get("angle", 45)) % 360
    r, g, b = _color(opts.get("color", "#d32f2f"), (0.8, 0.2, 0.2))
    tiled = opts.get("layout") == "tiled"
    font = FONTS["sans-bold"]
    reader = open_pdf(src)

    def draw(c, _i, w, h):
        c.setFillColor(Color(r, g, b, alpha=opacity))
        c.setFont(font, size)
        tw = pdfmetrics.stringWidth(text, font, size)
        positions = [(w / 2, h / 2)]
        if tiled:
            step_x, step_y = tw + size * 3, size * 6
            positions = [(x, y) for y in _frange(0, h + step_y, step_y) for x in _frange(0, w + step_x, step_x)]
        for x, y in positions:
            c.saveState()
            c.translate(x, y)
            c.rotate(angle)
            c.drawString(-tw / 2, -size / 3, text)
            c.restoreState()

    return _stamp(reader, draw, out)


def _frange(a, b, step):
    x = a
    while x < b:
        yield x
        x += step


def page_numbers(src: Path, out: Path, opts: dict) -> Path:
    position = opts.get("position", "bottom-center")
    fmt = opts.get("format", "n")
    start = int(opts.get("start", 1))
    size = max(6.0, min(float(opts.get("size", 11)), 48.0))
    margin = max(10.0, min(float(opts.get("margin", 28)), 150.0))
    skip_first = bool(opts.get("skip_first", False))
    r, g, b = _color(opts.get("color", "#000000"))
    reader = open_pdf(src)
    total = len(reader.pages)
    font = FONTS["sans"]

    def draw(c, i, w, h):
        if skip_first and i == 0:
            return False
        n = start + i - (1 if skip_first else 0)
        last = start + total - 1 - (1 if skip_first else 0)
        label = {"n": f"{n}", "page-n": f"Page {n}", "n-of-total": f"{n} / {last}",
                 "page-n-of-total": f"Page {n} of {last}"}.get(fmt, f"{n}")
        tw = pdfmetrics.stringWidth(label, font, size)
        vert, horiz = (position.split("-") + ["center"])[:2]
        y = h - margin - size if vert == "top" else margin
        x = {"left": margin, "right": w - margin - tw}.get(horiz, (w - tw) / 2)
        c.setFillColorRGB(r, g, b)
        c.setFont(font, size)
        c.drawString(x, y, label)

    return _stamp(reader, draw, out)


def edit(src: Path, out: Path, ops: list) -> Path:
    """Apply additions drawn in the editor.  Every op has a 0-based "page" and
    coordinates as fractions (0-1) of the displayed page, measured from the top-left.

        text      x, y, text, size (pt), color, font (sans|serif|mono, optional -bold)
        image     x, y, w, h, data (data: URL of a PNG or JPEG)  - also used for signatures
        rect      x, y, w, h, fill, opacity, stroke, stroke_width  - highlight / whiteout / box
        ink       points [[x, y], ...], color, width (pt)
    """
    reader = open_pdf(src)
    if not isinstance(ops, list):
        raise UserError("Invalid edits.")
    if len(ops) > 2000:
        raise UserError("Too many edits in one go.")
    by_page: dict[int, list] = {}
    for op in ops:
        try:
            by_page.setdefault(int(op["page"]), []).append(op)
        except (KeyError, TypeError, ValueError):
            raise UserError("Invalid edits.") from None

    def draw(c, i, w, h):
        items = by_page.get(i)
        if not items:
            return False
        for op in items:
            _draw_op(c, op, w, h)

    return _stamp(reader, draw, out)


def _num(op, key, lo=-0.5, hi=1.5, default=0.0):
    try:
        v = float(op.get(key, default))
    except (TypeError, ValueError):
        raise UserError("Invalid edits.") from None
    if math.isnan(v) or not lo <= v <= hi:
        raise UserError("Invalid edits.")
    return v


def _draw_op(c, op, w, h):
    kind = op.get("type")
    if kind == "text":
        text = str(op.get("text", ""))[:5000]
        size = _num(op, "size", 4, 300, 14)
        font_key = op.get("font", "sans")
        font = FONTS.get(font_key, FONTS["sans"])
        x, y = _num(op, "x") * w, h - _num(op, "y") * h
        c.setFillColorRGB(*_color(op.get("color", "#000000")))
        c.setFont(font, size)
        # match the editor's CSS (line-height 1.2): baseline = half-leading + ascent
        ascent, descent = pdfmetrics.getAscentDescent(font, size)
        first = (1.2 * size - (ascent - descent)) / 2 + ascent
        for k, line in enumerate(text.split("\n")):
            c.drawString(x, y - first - 1.2 * size * k, line)
    elif kind == "image":
        data = str(op.get("data", ""))
        m = re.fullmatch(r"data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\s]+)", data)
        if not m or len(data) > 15_000_000:
            raise UserError("An added image could not be read.")
        try:
            img = Image.open(io.BytesIO(base64.b64decode(m.group(2))))
            img.load()
        except Exception:
            raise UserError("An added image could not be read.") from None
        x, y = _num(op, "x") * w, _num(op, "y") * h
        iw, ih = _num(op, "w", 0, 2) * w, _num(op, "h", 0, 2) * h
        c.drawImage(ImageReader(img), x, h - y - ih, iw, ih, mask="auto")
    elif kind == "rect":
        x, y = _num(op, "x") * w, _num(op, "y") * h
        rw, rh = _num(op, "w", 0, 2) * w, _num(op, "h", 0, 2) * h
        fill, stroke = op.get("fill"), op.get("stroke")
        opacity = _num(op, "opacity", 0, 1, 1)
        if fill:
            r, g, b = _color(fill, (1, 1, 1))
            c.setFillColor(Color(r, g, b, alpha=opacity))
        if stroke:
            r, g, b = _color(stroke)
            c.setStrokeColor(Color(r, g, b, alpha=opacity))
            c.setLineWidth(_num(op, "stroke_width", 0.1, 50, 1.5))
        c.rect(x, h - y - rh, rw, rh, fill=1 if fill else 0, stroke=1 if stroke else 0)
    elif kind == "ink":
        pts = op.get("points") or []
        if not isinstance(pts, list) or len(pts) < 2 or len(pts) > 20000:
            return
        r, g, b = _color(op.get("color", "#1a3fd6"))
        c.setStrokeColorRGB(r, g, b)
        c.setLineWidth(_num(op, "width", 0.2, 40, 2))
        c.setLineCap(1)
        c.setLineJoin(1)
        path = c.beginPath()
        for k, pt in enumerate(pts):
            px, py = _num({"v": pt[0]}, "v") * w, h - _num({"v": pt[1]}, "v") * h
            path.moveTo(px, py) if k == 0 else path.lineTo(px, py)
        c.drawPath(path, stroke=1, fill=0)
    else:
        raise UserError("Invalid edits.")


def ocr(src: Path, out: Path, workdir: Path, lang: str, max_pages: int) -> Path:
    """Scanned PDF -> searchable PDF (each page keeps its picture, with an invisible text layer)."""
    if not tesseract_available():
        raise UserError("OCR is not installed on this server.")
    images = render_pages(src, workdir, "png", 300, max_pages, "ocr")
    writer = PdfWriter()
    for img in images:
        base = img.with_suffix("")
        r = subprocess.run(["tesseract", str(img), str(base), "-l", _lang(lang), "pdf"],
                           capture_output=True, text=True, timeout=180)
        page_pdf = base.with_suffix(".pdf")
        if r.returncode != 0 or not page_pdf.exists():
            raise UserError("OCR failed on one of the pages.")
        writer.append(str(page_pdf))
    writer.write(str(out))
    return out


def remove_watermark(src: Path, outdir: Path, stem: str, text: str, profile: Path, limits: dict) -> tuple[Path, dict]:
    from . import watermark
    text = str(text or "")[:200]
    ext = src.suffix.lower().lstrip(".")
    if ext == "pdf":
        check_pages(len(open_pdf(src).pages), limits["max_pages"])
        return watermark.remove_from_pdf(src, outdir / f"{stem}-no-watermark.pdf", text)
    if ext == "doc":           # old Word format: convert to .docx first
        src = office.convert(src, "docx", outdir / "lo", profile, limits["office_timeout"])
    elif ext != "docx":
        raise UserError("Remove watermark works with PDF and Word (.docx, .doc) files.")
    return watermark.remove_from_docx(src, outdir / f"{stem}-no-watermark.docx", text)


def pdf_info(src: Path) -> dict:
    try:
        pdf = pikepdf.open(str(src))
        return {"pages": len(pdf.pages), "encrypted": False}
    except pikepdf.PasswordError:
        return {"pages": None, "encrypted": True}
    except Exception as e:
        raise UserError("This file is not a readable PDF.") from e
