"""Doclivo web server (FastAPI).

Run locally:   uvicorn app.main:app --port 8000
Every upload is processed in a throw-away folder that is deleted as soon as the
result has been sent (and swept after 30 minutes if anything goes wrong)."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import engine, formats, office
from .config import settings
from .errors import UserError
from .runner import Busy, JobFailed, Runner

mimetypes.add_type("text/javascript", ".mjs")
WEB = Path(__file__).resolve().parent.parent / "web"
JOBS = settings.data_dir / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.site_name, docs_url=None, redoc_url=None, openapi_url=None)
runner: Runner | None = None

CSP = ("default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self'; "
       "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


# ------------------------------------------------------------------ middleware
class BodyLimit:
    """Stops reading an upload as soon as it passes the total size limit, so a
    huge upload cannot fill the disk or memory."""

    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        length = headers.get(b"content-length")
        if length and length.isdigit() and int(length) > self.limit:
            return await _too_large(send)
        seen = 0

        async def limited():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, limited, send)
        except _TooLarge:
            await _too_large(send)


class _TooLarge(Exception):
    pass


async def _too_large(send):
    body = json.dumps({"error": f"Upload is too large. The limit is {settings.max_total_mb} MB in total."}).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


app.add_middleware(BodyLimit, limit=settings.max_total_mb * 1024 * 1024 + 1024 * 1024)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


class RateLimiter:
    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        last_minute = sum(1 for t in q if now - t < 60)
        if last_minute >= settings.rate_per_minute or len(q) >= settings.rate_per_hour:
            return False
        q.append(now)
        return True


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    """Only trust forwarding headers when PROXY says one is in front of us;
    otherwise anyone could fake them to dodge the rate limit."""
    if settings.proxy == "cloudflare" and request.headers.get("cf-connecting-ip"):
        return request.headers["cf-connecting-ip"].strip()
    if settings.proxy in ("xff", "cloudflare") and request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


# ------------------------------------------------------------------ lifecycle
@app.on_event("startup")
async def startup():
    global runner
    runner = Runner(settings.workers, settings.data_dir, settings.job_timeout, settings.queue_wait)
    lo = office.soffice_path()
    print(f"\n  LibreOffice : {lo or 'NOT FOUND - Word/PowerPoint/Excel conversions are switched off'}")
    print(f"  OCR         : {'Tesseract found' if engine.tesseract_available() else 'not installed (optional)'}")
    if not lo:
        print("  Fix on a Mac: brew install --cask libreoffice, open LibreOffice once, then restart this server.")
    print()
    asyncio.get_event_loop().create_task(_sweeper())


async def _sweeper():
    """Remove any job folder older than 30 minutes (normally they are deleted at once)."""
    while True:
        cutoff = time.time() - 1800
        for d in JOBS.iterdir():
            try:
                if d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except FileNotFoundError:
                pass
        await asyncio.sleep(600)


# ------------------------------------------------------------------ uploads
MAGIC = {
    "pdf": [b"%PDF"],
    "zip": [b"PK\x03\x04"],                      # docx pptx xlsx odt odp ods
    "ole": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],  # doc ppt xls
    "rtf": [b"{\\rtf"],
}
ZIP_EXT = {"docx", "pptx", "xlsx", "odt", "odp", "ods", "ppsx"}
OLE_EXT = {"doc", "ppt", "xls", "pps"}


def safe_stem(filename: str) -> str:
    stem = Path(filename or "file").stem
    stem = re.sub(r"[^\w\-. ]+", "", stem, flags=re.UNICODE).strip(" .")
    stem = re.sub(r"\s+", "-", stem)[:60]
    return stem or "file"


def ext_of(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def _check_magic(ext: str, head: bytes, name: str):
    if ext == "pdf":
        ok = b"%PDF" in head[:1024]
    elif ext in ZIP_EXT:
        ok = head.startswith(b"PK\x03\x04")
    elif ext in OLE_EXT:
        ok = head.startswith(MAGIC["ole"][0]) or head.startswith(b"PK\x03\x04")   # misnamed .doc is common
    elif ext == "rtf":
        ok = head.lstrip().startswith(b"{\\rtf")
    else:
        ok = True                               # text formats and images are checked when opened
    if not ok:
        raise UserError(f"{name} does not look like a real .{ext} file.")


async def save_uploads(files: list[UploadFile], job: Path, allowed: set[str] | None = None) -> tuple[list[Path], list[str]]:
    if not files:
        raise UserError("Choose a file first.")
    if len(files) > settings.max_files:
        raise UserError(f"You can upload at most {settings.max_files} files at once.")
    paths, stems = [], []
    limit = settings.max_file_mb * 1024 * 1024
    for k, f in enumerate(files):
        ext = ext_of(f.filename)
        if formats.kind_of(ext) is None:
            raise UserError(f"{f.filename or 'This file'}: this file type is not supported.")
        if allowed is not None and ext not in allowed:
            names = " or ".join(sorted(f".{a}" for a in allowed))
            raise UserError(f"{f.filename}: this tool only works with {'PDF' if allowed == {'pdf'} else names} files.")
        dest = job / f"input-{k}.{'jpg' if ext == 'jpeg' else ext}"
        size = 0
        with open(dest, "wb") as out:
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise UserError(f"{f.filename} is larger than {settings.max_file_mb} MB.")
                out.write(chunk)
        if size == 0:
            raise UserError(f"{f.filename} is empty.")
        with open(dest, "rb") as fh:
            _check_magic(ext, fh.read(2048), f.filename)
        paths.append(dest)
        stems.append(safe_stem(f.filename))
    return paths, stems


def limits() -> dict:
    return {"max_pages": settings.max_pages, "max_pages_docx": settings.max_pages_docx,
            "office_timeout": settings.office_timeout}


async def process(request: Request, files: list[UploadFile], spec: dict, allowed: set[str] | None = None):
    """Shared path for every tool: rate limit, save, run, return the file, clean up."""
    if not limiter.allow(client_ip(request)):
        return error("Too many requests from your network. Please wait a minute and try again.", 429)
    job = JOBS / uuid.uuid4().hex
    job.mkdir()
    cleanup = BackgroundTask(shutil.rmtree, job, ignore_errors=True)
    try:
        paths, stems = await save_uploads(files, job, allowed)
        outdir = job / "out"
        outdir.mkdir()
        result = await runner.run({**spec, "inputs": [str(p) for p in paths], "outdir": str(outdir),
                                   "stem": stems[0], "stems": stems, "limits": limits()})
    except UserError as e:
        shutil.rmtree(job, ignore_errors=True)
        return error(str(e))
    except JobFailed as e:
        shutil.rmtree(job, ignore_errors=True)
        return error(str(e), 422)
    except Busy:
        shutil.rmtree(job, ignore_errors=True)
        return error("The server is busy right now. Please try again in a minute.", 503)
    except Exception:
        shutil.rmtree(job, ignore_errors=True)
        raise
    path = Path(result["path"])
    if not path.is_file() or job not in path.parents:
        shutil.rmtree(job, ignore_errors=True)
        return error("Processing failed.", 500)
    ext = path.suffix.lstrip(".")
    headers = {f"X-{k.title()}": str(v) for k, v in result.get("meta", {}).items()}
    headers["Access-Control-Expose-Headers"] = ", ".join(headers) or "Content-Disposition"
    return FileResponse(path, media_type=formats.MIME.get(ext, "application/octet-stream"),
                        filename=path.name, headers=headers, background=cleanup)


def parse_json(value: str, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise UserError("Invalid options.") from None


# ------------------------------------------------------------------ API
@app.get("/healthz")
async def health():
    return {"ok": True}


@app.get("/api/capabilities")
async def capabilities():
    ocr_langs = []
    if engine.tesseract_available():
        proc = await asyncio.create_subprocess_exec("tesseract", "--list-langs",
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        ocr_langs = [l.strip() for l in out.decode().splitlines()[1:] if l.strip() and l.strip() not in ("osd", "equ")]
    return {
        "site_name": settings.site_name, "source_url": settings.source_url,
        "targets": formats.TARGETS, "labels": formats.LABELS,
        "kinds": {k: sorted(v) for k, v in (("document", formats.DOCUMENT), ("presentation", formats.PRESENTATION),
                                             ("spreadsheet", formats.SPREADSHEET), ("pdf", formats.PDF),
                                             ("image", formats.IMAGE))},
        "office": office.soffice_path() is not None, "ocr": bool(ocr_langs), "ocr_langs": ocr_langs,
        "limits": {"max_file_mb": settings.max_file_mb, "max_total_mb": settings.max_total_mb,
                   "max_files": settings.max_files, "max_pages": settings.max_pages,
                   "max_pages_docx": settings.max_pages_docx},
    }


@app.post("/api/convert")
async def convert(request: Request, files: list[UploadFile] = File(...), target: str = Form(...),
                  options: str = Form("")):
    target = target.lower()
    try:
        opts = parse_json(options, {})
        kinds = {formats.kind_of(ext_of(f.filename)) for f in files}
        if None in kinds:
            raise UserError("One of the files is a type we cannot convert.")
        if target not in formats.LABELS:
            raise UserError(f"Unknown format .{target}.")
        possible = any(target in formats.TARGETS[k] or ext_of(f.filename).replace("jpeg", "jpg") == target
                       for k, f in zip((formats.kind_of(ext_of(f.filename)) for f in files), files))
        if len(files) == 1 and target not in formats.TARGETS[next(iter(kinds))]:
            raise UserError(f"{next(iter(kinds)).capitalize()} files cannot be converted to .{target}.")
        if not possible:
            raise UserError(f"None of these files can be converted to .{target}.")
        if not office.soffice_path() and any(formats.needs_office(k, target) for k in kinds):
            raise UserError("Office conversions are not available on this server.")
    except UserError as e:
        return error(str(e))
    return await process(request, files, {"op": "convert", "target": target, "options": _clean(opts)})


def _clean(opts):
    return opts if isinstance(opts, dict) else {}


PDF_ONLY = {"pdf"}


@app.post("/api/pdf/merge")
async def merge(request: Request, files: list[UploadFile] = File(...)):
    if len(files) < 2:
        return error("Choose at least two PDFs to merge.")
    return await process(request, files, {"op": "merge"}, PDF_ONLY)


async def _single(request, file, op, options):
    try:
        opts = _clean(parse_json(options, {}))
    except UserError as e:
        return error(str(e))
    return await process(request, [file], {"op": op, "options": opts}, PDF_ONLY)


@app.post("/api/pdf/{tool}")
async def pdf_tool(tool: str, request: Request, file: UploadFile = File(...), options: str = Form("")):
    if tool not in {"split", "organize", "compress", "protect", "unlock", "watermark", "page-numbers", "edit", "ocr"}:
        return error("Unknown tool.", 404)
    if tool == "ocr" and not engine.tesseract_available():
        return error("OCR is not available on this server.")
    return await _single(request, file, tool, options)


@app.post("/api/remove-watermark")
async def remove_watermark(request: Request, file: UploadFile = File(...), options: str = Form("")):
    if ext_of(file.filename) == "doc" and not office.soffice_path():
        return error("Old .doc files need LibreOffice, which is not installed on this server. Save it as .docx and try again.")
    return await _single_any(request, file, "remove-watermark", options, {"pdf", "docx", "doc"})


async def _single_any(request, file, op, options, allowed):
    try:
        opts = _clean(parse_json(options, {}))
    except UserError as e:
        return error(str(e))
    return await process(request, [file], {"op": op, "options": opts}, allowed)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return error("Not found", 404)
    return FileResponse(WEB / "index.html")      # client-side routes


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
