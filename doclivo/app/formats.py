"""Which inputs can become which outputs.  The website builds its menus from this."""
from __future__ import annotations

DOCUMENT = {"doc", "docx", "odt", "rtf", "txt", "html", "htm"}
PRESENTATION = {"ppt", "pptx", "odp", "pps", "ppsx"}
SPREADSHEET = {"xls", "xlsx", "ods", "csv"}
PDF = {"pdf"}
IMAGE = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic", "heif"}

TARGETS = {
    "document": ["pdf", "docx", "doc", "odt", "rtf", "txt", "html", "jpg", "png"],
    "presentation": ["pdf", "docx", "pptx", "ppt", "odp", "jpg", "png"],
    "spreadsheet": ["pdf", "xlsx", "xls", "ods", "csv"],
    "pdf": ["docx", "odt", "pptx", "xlsx", "txt", "jpg", "png"],
    "image": ["pdf", "jpg", "png", "webp"],
}

LABELS = {
    "pdf": "PDF", "docx": "Word (.docx)", "doc": "Word 97-2003 (.doc)", "odt": "OpenDocument Text (.odt)",
    "rtf": "Rich Text (.rtf)", "txt": "Plain text (.txt)", "html": "Web page (.html)",
    "pptx": "PowerPoint (.pptx)", "ppt": "PowerPoint 97-2003 (.ppt)", "odp": "OpenDocument Slides (.odp)",
    "xlsx": "Excel (.xlsx)", "xls": "Excel 97-2003 (.xls)", "ods": "OpenDocument Sheet (.ods)",
    "csv": "CSV (.csv)", "jpg": "JPG images", "png": "PNG images", "webp": "WebP image",
}

MIME = {
    "pdf": "application/pdf", "zip": "application/zip", "txt": "text/plain; charset=utf-8",
    "html": "text/html; charset=utf-8", "csv": "text/csv; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword", "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint", "odp": "application/vnd.oasis.opendocument.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel", "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp",
}


def kind_of(ext: str) -> str | None:
    ext = ext.lower()
    for name, group in (("document", DOCUMENT), ("presentation", PRESENTATION),
                        ("spreadsheet", SPREADSHEET), ("pdf", PDF), ("image", IMAGE)):
        if ext in group:
            return name
    return None


def needs_office(kind: str, target: str) -> bool:
    """True when LibreOffice is involved in this conversion."""
    return kind in ("document", "presentation", "spreadsheet") or (kind == "pdf" and target == "odt")
