Doclivo

Free online file converter and PDF editor. Convert Word, PowerPoint, Excel, PDF and images in any direction, up to 15 files at once, then merge, split, sign, edit, watermark, compress or protect PDFs. No account, no tracking, and every file is deleted the moment the result is sent back.

Live site: https://doclivo.onrender.com (first visit after a quiet period takes about a minute while the free server wakes up)

What it does
Convert
From	To
Word (.doc .docx .odt .rtf .txt .html)	PDF, Word, Word 97, ODT, RTF, Text, HTML, JPG, PNG
PowerPoint (.ppt .pptx .odp)	PDF, Word (slide-look or clean document), PowerPoint, PPT 97, ODP, JPG, PNG
Excel (.xls .xlsx .ods .csv)	PDF, Excel, XLS 97, ODS, CSV
PDF	Word, ODT, PowerPoint, Excel, Text, JPG, PNG
Images (.jpg .png .webp .gif .bmp .tiff .heic)	PDF (one or many images), JPG, PNG, WebP

Batches: drop up to 15 files of mixed types and choose one format. Everything that can become that format is converted and returned in a single zip; files already in that format are included unchanged; anything that can't be converted is listed in NOT-CONVERTED.txt inside the zip, and the page tells you which ones before you start.

PDF tools
Group	Tools
Arrange pages	Merge, Split, Organize (reorder, rotate, duplicate, delete with live thumbnails), Rotate
Mark up	Edit (text, pictures, highlight, white-out, boxes, freehand drawing), Sign (draw or upload), Add watermark, Remove watermark (PDF and Word), Page numbers
Shrink and secure	Compress, Protect with password, Unlock, OCR for scanned PDFs (when installed)

Previews for Organize, Rotate, Edit and Sign are drawn in your browser with pdf.js; the file is only uploaded when you press Save.

How it works
Browser (web/)  ──upload──►  FastAPI server (app/main.py)  ──►  worker process (app/jobs.py)
pdf.js previews              size & type checks, rate limits,     LibreOffice, pdf2docx, pypdf,
vanilla JavaScript           queue, automatic clean-up           pikepdf, pdfium, Pillow, Tesseract

Every job runs in its own process with a hard time limit, so a damaged or hostile file can't take the site down. A fixed number of jobs run at once and the rest wait in a short queue. Temporary folders are deleted after each response and swept every 10 minutes.

Built with

Python, FastAPI, Uvicorn, LibreOffice (headless), pdf2docx, pypdf, pikepdf, pypdfium2, pdfplumber, python-docx, python-pptx, openpyxl, Pillow, ReportLab, Tesseract OCR, pdf.js, plain HTML/CSS/JavaScript, Docker.

Repository layout
doclivo/
  app/            Python server: API, conversion engine, PDF tools, watermark removal
  web/            website: pages, styles, editor, pdf.js
  tests/          63 automated tests (pytest)
  Dockerfile.render   image used by Render's free plan
  Dockerfile      full image with OCR, for your own server
  docker-compose.yml + Caddyfile   always-on deployment with automatic HTTPS
  render.yaml     Render Blueprint
  requirements.txt
Run it locally

Needs Python 3.10+ and LibreOffice (brew install --cask libreoffice on a Mac). Tesseract is optional, for OCR.

bash
cd doclivo
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000

Open http://127.0.0.1:8000.

Run the tests with pip install -r requirements-dev.txt then python -m pytest -q. Sample files are generated on the first run.

Deploy

Render (free): this repository is set up as a Render Blueprint. New → Blueprint → choose the repository → Blueprint path doclivo/render.yaml → Apply. Set the SOURCE_URL environment variable to this repository's address. The free plan gives 512 MB of memory and a small share of a CPU, so one job runs at a time, files are limited to 15 MB, and the site sleeps after 15 minutes without visitors.

Your own server: cd doclivo, copy .env.example to .env, set DOMAIN, then docker compose up -d --build. Caddy obtains the HTTPS certificate automatically.

All limits (file size, pages, workers, rate limits, timeouts) are environment variables; see doclivo/.env.example.

Security and privacy
Upload size is enforced while receiving; oversized requests are cut off.
File types are checked by extension and by file signature; uploaded names never become paths.
Each job is a separate process with a timeout; LibreOffice is killed along with it.
Per-visitor rate limits and a bounded queue, so busy periods degrade gracefully.
Strict Content-Security-Policy, no cookies, no analytics.
Docker image runs as a non-root user on a read-only filesystem.
Known limits
PDF → Word rebuilds pages as editable content; complex layouts (multi-column pages, forms) can shift. Scanned PDFs come out as pictures; run OCR first.
PDF → PowerPoint makes one picture slide per page, with the page text in the speaker notes, because PDFs hold no slide structure.
Edit PDF adds things on top of a page. To change existing text, white it out and type over it.
Remove watermark handles watermarks that are separate from the page content (labelled watermarks, angled or see-through repeated text, faint logos, Word's own watermarks). A watermark baked into a scanned image can't be removed. Use it only on documents you own or may change.
Office conversions rely on LibreOffice; a few Microsoft-only features (SmartArt, some animations, macros) are simplified or dropped.
Licence

AGPL-3.0. PDF → Word depends on PyMuPDF, which is AGPL-licensed, so anyone running Doclivo as a public service must offer its source code; this repository is that offer. See doclivo/LICENSE for bundled third-party licences (pdf.js, Archivo, DejaVu).
