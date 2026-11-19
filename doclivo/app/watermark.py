"""Finding and removing watermarks from PDF and Word files.

PDF.  A watermark is not a separate thing in a PDF; it is drawing instructions
mixed in with the page.  We remove only what we can identify confidently:

  1. Content the PDF itself labels as a watermark (Acrobat and many tools mark it
     as an "Artifact" of subtype Watermark, or put it on a layer named Watermark).
  2. Watermark annotations.
  3. Text that looks like a watermark: drawn at an angle, see-through or very
     light, and repeated on most pages (or the exact text the person typed in).
  4. See-through pictures repeated on most pages (logo watermarks).

Only the drawing of those items is removed; colour and position settings stay,
so the rest of the page is untouched.

Word.  Word keeps watermarks in the page headers as a shape whose name contains
"WaterMark".  We remove those shapes (and, if the person typed the text, any
header shape with that text).
"""
from __future__ import annotations

import io
import math
import re
import zipfile
from collections import Counter
from pathlib import Path

import pikepdf
from lxml import etree

from .errors import UserError

# PDF operators that paint something (removed inside a watermark) ...
PAINT = {"Tj", "TJ", "'", '"', "Do", "sh", "BI", "INLINE IMAGE",
         "m", "l", "c", "v", "y", "h", "re", "f", "F", "f*", "B", "B*", "b", "b*", "S", "s", "n", "W", "W*"}
TEXT_SHOW = {"Tj", "TJ", "'", '"'}
MAX_DEPTH = 6


def norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def _mul(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2,
            e * a2 + f * c2 + e2, e * b2 + f * d2 + f2)


def _nums(ops):
    try:
        return tuple(float(x) for x in ops)
    except (TypeError, ValueError):
        return None


class _Fonts:
    """Turns the bytes in a text operator back into characters."""

    def __init__(self):
        self.cache = {}

    def decoder(self, font):
        if font is None:
            return lambda raw: raw.decode("latin-1", "ignore")
        key = font.objgen if font.is_indirect else id(font)
        if key in self.cache:
            return self.cache[key]
        two_byte = font.get("/Subtype") == "/Type0"
        mapping = {}
        tu = font.get("/ToUnicode")
        if tu is not None:
            try:
                from pdfminer.cmapdb import CMapParser, FileUnicodeMap
                cmap = FileUnicodeMap()
                CMapParser(cmap, io.BytesIO(tu.read_bytes())).run()
                mapping = dict(cmap.cid2unichr)
            except Exception:
                mapping = {}

        def decode(raw: bytes) -> str:
            if two_byte:
                codes = [int.from_bytes(raw[i:i + 2], "big") for i in range(0, len(raw) - 1, 2)]
            else:
                codes = list(raw)
            if mapping:
                return "".join(mapping.get(c, "") for c in codes)
            return "".join(chr(c) for c in codes if c < 0x110000) if not two_byte else ""

        self.cache[key] = decode
        return decode


def _ocg_is_watermark(oc) -> bool:
    try:
        if oc is None:
            return False
        name = str(oc.get("/Name", ""))
        if "watermark" in name.lower():
            return True
        for ocg in oc.get("/OCGs", []) or []:        # an OCMD that groups layers
            if "watermark" in str(ocg.get("/Name", "")).lower():
                return True
    except Exception:
        return False
    return False


def _is_watermark_mark(tag, props, resources) -> bool:
    """Marked content that the PDF itself labels as a watermark."""
    if isinstance(props, pikepdf.Name):
        try:
            props = resources.Properties[props]
        except (KeyError, AttributeError, TypeError):
            props = None
    if not isinstance(props, pikepdf.Dictionary):
        return False
    if tag == "/Artifact" and str(props.get("/Subtype", "")) == "/Watermark":
        return True
    if tag == "/OC":
        return _ocg_is_watermark(props)
    return False


class _Walker:
    """Walks a page's drawing instructions, keeping track of position, angle and
    transparency.  In 'scan' mode it records watermark candidates; in 'clean'
    mode it rewrites the instructions without the parts chosen for removal."""

    def __init__(self, pdf, fonts, drop_text: set[str], user_text: str, drop_images: set):
        self.pdf, self.fonts = pdf, fonts
        self.drop_text, self.user_text, self.drop_images = drop_text, user_text, drop_images
        self.found = Counter()          # what was removed
        self.text_keys: Counter = Counter()      # scan: candidate text -> times seen on this page
        self.faint_images: set = set()
        self.cleaned_forms: set = set()

    page_area = 1.0

    def _area(self, xo, sub, m) -> float:
        """Share of the page covered by an image or drawing placed with matrix m."""
        try:
            if sub == "/Image":
                w = h = 1.0
            else:
                x0, y0, x1, y1 = (float(v) for v in xo.BBox)
                w, h = abs(x1 - x0), abs(y1 - y0)
            return abs(m[0] * m[3] - m[1] * m[2]) * w * h / self.page_area
        except Exception:
            return 0.0

    def _user_match(self, key: str) -> bool:
        t = self.user_text
        return bool(t) and bool(key) and key.replace(t, "") == "" and t in key

    def walk(self, stream_owner, resources, state, depth, clean: bool):
        try:
            ops = pikepdf.parse_content_stream(stream_owner)
        except Exception:
            return None
        out = []
        ctm, alpha, light = state
        stack = []
        marks = []                       # one bool per open marked-content section: drop?
        font = None
        tm = (1, 0, 0, 1, 0, 0)
        block = None                     # instructions inside BT..ET
        fill_gray = None

        def dropping():
            return any(marks)

        for ins in ops:
            op = str(ins.operator)
            operands = list(ins.operands) if hasattr(ins, "operands") else []
            if op == "q":
                stack.append((ctm, alpha, light, fill_gray))
            elif op == "Q" and stack:
                ctm, alpha, light, fill_gray = stack.pop()
            elif op == "cm":
                m = _nums(operands)
                if m and len(m) == 6:
                    ctm = _mul(m, ctm)
            elif op == "gs" and operands:
                try:
                    g = resources.ExtGState[operands[0]]
                    if "/ca" in g:
                        alpha = float(g.ca)
                except Exception:
                    pass
            elif op in ("g", "rg", "k", "sc", "scn"):
                vals = _nums([x for x in operands if not isinstance(x, pikepdf.Name)])
                if vals:
                    if op == "k" and len(vals) == 4:
                        fill_gray = 1 - min(1, vals[3] + sum(vals[:3]) / 3)
                    else:
                        fill_gray = sum(vals[:3]) / min(len(vals), 3)
                light = fill_gray is not None and fill_gray > 0.7
            elif op in ("BDC", "BMC"):
                tag = str(operands[0]) if operands else ""
                props = operands[1] if len(operands) > 1 else None
                is_wm = _is_watermark_mark(tag, props, resources)
                if is_wm and not dropping():
                    self.found["marked"] += 1
                marks.append(is_wm)
            elif op == "EMC" and marks:
                marks.pop()

            if op == "BT":
                block = {"ins": [ins], "text": [], "angles": [], "faint": False, "light": False}
                tm = (1, 0, 0, 1, 0, 0)
                continue
            if block is not None:
                if op == "Tf" and operands:
                    try:
                        font = resources.Font[operands[0]]
                    except Exception:
                        font = None
                elif op == "Tm":
                    m = _nums(operands)
                    if m and len(m) == 6:
                        tm = m
                if op in TEXT_SHOW:
                    decode = self.fonts.decoder(font)
                    parts = []
                    for x in operands:
                        if isinstance(x, pikepdf.String):
                            parts.append(decode(bytes(x)))
                        elif isinstance(x, pikepdf.Array):
                            parts += [decode(bytes(s)) for s in x if isinstance(s, pikepdf.String)]
                    block["text"].append("".join(parts))
                    full = _mul(tm, ctm)
                    block["angles"].append(math.degrees(math.atan2(full[1], full[0])) % 360)
                    block["faint"] |= alpha < 0.95
                    block["light"] |= bool(light)
                block["ins"].append(ins)
                if op != "ET":
                    continue
                # finished a text block: decide about it
                key = norm("".join(block["text"]))
                rotated = any(min(a % 90, 90 - a % 90) > 3 for a in block["angles"])
                looks = key and len(key) >= 2 and (rotated or block["faint"] or block["light"])
                remove = dropping() or (key and (key in self.drop_text or self._user_match(key)))
                if not clean and looks and not dropping():
                    self.text_keys[key] += 1
                if clean and remove and key and not dropping():
                    self.found["text"] += 1
                for b in block["ins"]:
                    bop = str(b.operator)
                    if clean and (remove or dropping()) and bop in TEXT_SHOW:
                        continue
                    out.append(b)
                block = None
                continue

            if op == "Do" and operands:
                try:
                    xo = resources.XObject[operands[0]]
                except Exception:
                    xo = None
                if xo is not None:
                    sub = str(xo.get("/Subtype", ""))
                    if _ocg_is_watermark(xo.get("/OC")) and not dropping():
                        self.found["marked"] += 1
                        if clean:
                            continue
                    fm = _nums(xo.get("/Matrix", [1, 0, 0, 1, 0, 0])) if sub == "/Form" else None
                    inner = _mul(fm, ctm) if fm and len(fm) == 6 else ctm
                    # a see-through picture or drawing that covers a good part of the page
                    if not clean and alpha < 0.95 and sub in ("/Image", "/Form") and self._area(xo, sub, inner) >= 0.05:
                        self.faint_images.add(xo.objgen)
                    if clean and xo.objgen in self.drop_images and not dropping():
                        self.found["images"] += 1
                        continue
                    if sub == "/Form" and depth < MAX_DEPTH and not dropping():
                        res = xo.get("/Resources", resources)
                        if clean:
                            if xo.objgen not in self.cleaned_forms:
                                self.cleaned_forms.add(xo.objgen)
                                data = self.walk(xo, res, (inner, alpha, light), depth + 1, True)
                                if data is not None:
                                    xo.write(data)
                        else:
                            self.walk(xo, res, (inner, alpha, light), depth + 1, False)

            if clean and dropping() and op in PAINT:
                continue
            out.append(ins)
        if clean:
            return pikepdf.unparse_content_stream(out)
        return None


def remove_from_pdf(src: Path, out: Path, user_text: str = "", must_find: bool = True) -> tuple[Path, dict]:
    try:
        pdf = pikepdf.open(str(src))
    except pikepdf.PasswordError:
        raise UserError("This PDF is password-protected. Use the Unlock tool first.") from None
    except Exception as e:
        raise UserError("This file is not a readable PDF.") from e
    pages = list(pdf.pages)
    if not pages:
        raise UserError("This PDF has no pages.")
    fonts = _Fonts()
    ident = ((1, 0, 0, 1, 0, 0), 1.0, False)
    user = norm(user_text or "")

    # pass 1: what looks like a watermark, and on how many pages
    text_pages: Counter = Counter()
    text_rot_single = set()
    image_pages: Counter = Counter()
    def area(page):
        try:
            b = page.mediabox
            return max(1.0, abs(float(b[2]) - float(b[0])) * abs(float(b[3]) - float(b[1])))
        except Exception:
            return 612 * 792

    for page in pages:
        w = _Walker(pdf, fonts, set(), user, set())
        w.page_area = area(page)
        page.contents_coalesce()
        w.walk(page, page.obj.get("/Resources", pikepdf.Dictionary()), ident, 0, False)
        for k, n in w.text_keys.items():
            text_pages[k] += 1
            if n >= 2:                 # repeated on the same page (tiled watermark)
                text_rot_single.add(k)
        for img in w.faint_images:
            image_pages[img] += 1

    need = max(2, math.ceil(0.6 * len(pages)))
    drop_text = {k for k, n in text_pages.items() if n >= need} | text_rot_single
    if len(pages) == 1:
        drop_text |= set(text_pages)          # one page: an angled/see-through/light text is the watermark
    drop_images = {k for k, n in image_pages.items() if n >= need or len(pages) == 1}

    # pass 2: rewrite
    w = _Walker(pdf, fonts, drop_text, user, drop_images)
    for page in pages:
        data = w.walk(page, page.obj.get("/Resources", pikepdf.Dictionary()), ident, 0, True)
        if data is not None:
            page.obj.Contents = pdf.make_stream(data)
        annots = page.obj.get("/Annots")
        if annots is not None:
            keep = [a for a in annots if str(a.get("/Subtype", "")) != "/Watermark"]
            if len(keep) != len(annots):
                w.found["annotations"] += len(annots) - len(keep)
                page.obj.Annots = pdf.make_indirect(pikepdf.Array(keep))

    total = sum(w.found.values())
    if must_find and total == 0:
        raise UserError("We couldn't find a watermark in this PDF. If you know its exact text, type it in and try again. "
                        "Watermarks that are part of a scanned picture can't be removed.")
    pdf.remove_unreferenced_resources()
    pdf.save(str(out))
    return out, {"removed": total}


# ------------------------------------------------------------------ Word
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}
W_R = f"{{{NS['w']}}}r"


def _run_of(el):
    while el is not None and el.tag != W_R:
        el = el.getparent()
    return el


def remove_from_docx(src: Path, out: Path, user_text: str = "") -> tuple[Path, dict]:
    user = norm(user_text or "")
    try:
        zin = zipfile.ZipFile(src)
    except zipfile.BadZipFile:
        raise UserError("This is not a readable Word (.docx) file.") from None
    if sum(i.file_size for i in zin.infolist()) > 400 * 1024 * 1024:
        raise UserError("This Word file is too large once unpacked.")
    removed = 0
    parts = {}
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    for info in zin.infolist():
        data = zin.read(info)
        if re.fullmatch(r"word/(header\d*|footer\d*|document)\.xml", info.filename):
            try:
                root = etree.fromstring(data, parser)
            except etree.XMLSyntaxError:
                parts[info] = data
                continue
            targets = []
            for shape in root.iter(f"{{{NS['v']}}}shape"):
                ident = (shape.get("id", "") + " " + shape.get(f"{{{NS['o']}}}spid", "")).lower()
                textpath = shape.find("v:textpath", NS)
                text = norm(textpath.get("string", "")) if textpath is not None else ""
                if "watermark" in ident or (user and text and text.replace(user, "") == ""):
                    targets.append(shape)
            for doc_pr in root.iter(f"{{{NS['wp']}}}docPr"):
                if "watermark" in (doc_pr.get("name", "") + doc_pr.get("descr", "")).lower():
                    targets.append(doc_pr)
            seen = set()
            for t in targets:
                run = _run_of(t)
                if run is not None and id(run) not in seen and run.getparent() is not None:
                    seen.add(id(run))
                    run.getparent().remove(run)
                    removed += 1
            data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        parts[info] = data
    if removed == 0:
        raise UserError("We couldn't find a watermark in this Word file. Word watermarks are added with "
                        "Design > Watermark; text typed or pasted into the page itself is ordinary content.")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in parts.items():
            zout.writestr(info, data)
    return out, {"removed": removed}
