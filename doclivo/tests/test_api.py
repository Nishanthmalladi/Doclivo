"""HTTP-level tests: limits, validation and the full request path."""
import io
import os
from pathlib import Path

import pytest

os.environ.setdefault("RATE_PER_MINUTE", "1000")
os.environ.setdefault("MAX_FILE_MB", "30")
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

F = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def up(name, field="file"):
    return (field, (name, (F / name).read_bytes()))


def test_capabilities(client):
    caps = client.get("/api/capabilities").json()
    assert "docx" in caps["targets"]["pdf"] and caps["limits"]["max_file_mb"] == 30


def test_convert_pdf_to_word(client):
    r = client.post("/api/convert", files=[up("text.pdf", "files")], data={"target": "docx"})
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('"text.docx"')
    assert r.content[:2] == b"PK"


def test_images_become_one_pdf(client):
    r = client.post("/api/convert", files=[up("photo.jpg", "files"), up("logo.png", "files")], data={"target": "pdf"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_unsupported_target(client):
    r = client.post("/api/convert", files=[up("photo.jpg", "files")], data={"target": "docx"})
    assert r.status_code == 400 and "cannot be converted" in r.json()["error"]


def test_fake_pdf_rejected(client):
    r = client.post("/api/pdf/compress", files=[("file", ("x.pdf", b"hello"))])
    assert r.status_code == 400 and "does not look like" in r.json()["error"]


def test_pdf_tools_only_take_pdfs(client):
    r = client.post("/api/pdf/split", files=[up("photo.jpg")])
    assert r.status_code == 400 and "only works with PDF" in r.json()["error"]


def test_too_large(client):
    big = b"%PDF" + b"0" * (31 * 1024 * 1024)
    r = client.post("/api/pdf/compress", files=[("file", ("big.pdf", big))])
    assert r.status_code == 400 and "larger than" in r.json()["error"]


def test_body_limit_stops_huge_uploads(client):
    r = client.post("/api/pdf/merge", content=b"x", headers={"content-length": str(10 ** 10), "content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413


def test_wrong_password_message(client):
    locked = client.post("/api/pdf/protect", files=[up("text.pdf")], data={"options": '{"password": "abcd1234"}'})
    assert locked.status_code == 200
    r = client.post("/api/pdf/unlock", files=[("file", ("l.pdf", locked.content))], data={"options": '{"password": "zzzz"}'})
    assert r.status_code == 422 and r.json()["error"] == "That password is not correct."


def test_compress_reports_sizes(client):
    r = client.post("/api/pdf/compress", files=[up("heavy.pdf")], data={"options": '{"level": "high"}'})
    assert r.status_code == 200 and int(r.headers["x-after"]) < int(r.headers["x-before"])


def test_job_folders_are_cleaned_up(client):
    client.post("/api/convert", files=[up("text.pdf", "files")], data={"target": "txt"})
    assert list(main.JOBS.iterdir()) == []


def test_security_headers_and_unknown_api(client):
    r = client.get("/")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/api/nope").status_code == 404


def test_rate_limit():
    limiter = main.RateLimiter()
    cap = min(main.settings.rate_per_minute, main.settings.rate_per_hour)
    allowed = [limiter.allow("1.2.3.4") for _ in range(cap + 1)]
    assert allowed[-1] is False and all(allowed[:-1])
    assert limiter.allow("5.6.7.8")             # other visitors are unaffected


def test_remove_watermark_pdf_and_word(client):
    r = client.post("/api/remove-watermark", files=[up("wm-tiled.pdf")])
    assert r.status_code == 200 and int(r.headers["x-removed"]) > 0
    assert r.headers["content-disposition"].endswith('"wm-tiled-no-watermark.pdf"')
    r = client.post("/api/remove-watermark", files=[up("wm.docx")])
    assert r.status_code == 200 and r.content[:2] == b"PK"
    r = client.post("/api/remove-watermark", files=[up("photo.jpg")])
    assert r.status_code == 400 and ".docx" in r.json()["error"]
    r = client.post("/api/remove-watermark", files=[up("text.pdf")])
    assert r.status_code == 422 and "couldn't find" in r.json()["error"]


def test_ten_mixed_files_in_one_go_to_pdf(client):
    """10 files of different kinds, converted together: everything comes back in one zip,
    files already in the target format are passed through, names never clash."""
    import io, zipfile
    names = ["deck.pptx", "report.docx", "sheet.xlsx", "photo.jpg", "text.pdf"] * 2
    r = client.post("/api/convert", files=[up(n, "files") for n in names], data={"target": "pdf"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["x-converted"] == "10" and r.headers["x-failed"] == "0"
    listing = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(listing) == 10 and len(set(listing)) == 10
    assert "deck.pdf" in listing and "deck-2.pdf" in listing and "text.pdf" in listing


def test_mixed_batch_to_word_skips_what_cannot_become_word(client):
    import io, zipfile
    names = ["deck.pptx", "report.docx", "sheet.xlsx", "photo.jpg", "text.pdf"]
    r = client.post("/api/convert", files=[up(n, "files") for n in names], data={"target": "docx"})
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert r.headers["x-converted"] == "3" and r.headers["x-failed"] == "2"
    note = z.read("NOT-CONVERTED.txt").decode()
    assert "Excel files cannot be turned into Word" in note and "Image files cannot" in note
    assert "/tmp" not in note and "jobs/" not in note          # no server paths


def test_batch_with_nothing_convertible(client):
    r = client.post("/api/convert", files=[up("photo.jpg", "files"), up("logo.png", "files")], data={"target": "docx"})
    assert r.status_code == 400 and "None of these files" in r.json()["error"]


def test_too_many_files(client):
    files = [up("text.pdf", "files")] * (main.settings.max_files + 1)
    r = client.post("/api/convert", files=files, data={"target": "docx"})
    assert r.status_code == 400 and "at most" in r.json()["error"]
