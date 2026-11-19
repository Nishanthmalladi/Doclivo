# Doclivo

A free file converter and PDF editor for the web. Works in any modern browser on
phones, tablets and computers.

**Convert** Word, PowerPoint, Excel, PDF and images in every direction:

| From | To |
|---|---|
| Word (.doc .docx .odt .rtf .txt .html) | PDF, Word, Word 97, ODT, RTF, Text, HTML, JPG, PNG |
| PowerPoint (.ppt .pptx .odp) | PDF, Word (slide look or clean document), PowerPoint, PPT 97, ODP, JPG, PNG |
| Excel (.xls .xlsx .ods .csv) | PDF, Excel, XLS 97, ODS, CSV |
| PDF | Word, ODT, PowerPoint, Excel, Text, JPG, PNG |
| Images (.jpg .png .webp .gif .bmp .tiff .heic) | PDF (one or many images), JPG, PNG, WebP |

**Many files at once:** drop up to 15 files of any kind (the `MAX_FILES` setting) and pick a format. Every file that can become that format is converted and they all come back in one zip; files already in that format are included as they are; anything that can't be converted is listed in `NOT-CONVERTED.txt` inside the zip, and the page tells you beforehand which ones those are.

**PDF tools:** merge, split, organize pages (reorder, rotate, duplicate, delete),
rotate, edit (text, pictures, highlight, white-out, boxes, freehand drawing),
sign (draw or upload), add watermark, remove watermark (PDF and Word), page numbers,
compress, protect with a password, unlock, and OCR (make a scanned PDF searchable).
PDF to Word can also remove the watermark on the way.

Files are processed in a temporary folder and deleted as soon as the result is sent.

## How it works

```
Browser (web/)  ──upload──►  FastAPI (app/main.py)  ──►  worker process (app/jobs.py)
pdf.js previews              limits, rate limits,         LibreOffice, pdf2docx, pypdf,
for organize/edit            queue, clean-up              pikepdf, pdfium, Tesseract
```

Each job runs in its own process with a time limit, so a damaged or hostile file
can't take the site down. At most `WORKERS` jobs run at once; the rest wait in a
short queue.

## Run it on a Mac

```bash
brew install --cask libreoffice          # Office conversions
brew install tesseract tesseract-lang    # optional: OCR for scanned PDFs
cd doclivo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000.

If `pip install` fails on a very new Python, install a slightly older one and use it
for the virtual environment: `brew install python@3.12`, then `python3.12 -m venv .venv`.

### Share it from your Mac (temporary public link)

Start the app with the Cloudflare setting so rate limits see each visitor:

```bash
PROXY=cloudflare uvicorn app.main:app --port 8000
```

In a second terminal:

```bash
cloudflared tunnel --url http://localhost:8000
```

Share the `https://….trycloudflare.com` link it prints. It works while your Mac is
awake and both terminals are running; the link changes each time.

## Put it online for free on Render

`render.yaml` and `Dockerfile.render` are ready for Render's free plan.

1. Put this folder in a **public** GitHub repository (GitHub Desktop: File > Add Local
   Repository > create > Publish, with "Keep this code private" unticked).
2. Sign in at render.com with your GitHub account.
3. **New > Blueprint**, choose the repository, and click **Apply**.
4. When asked for `SOURCE_URL`, paste your GitHub repository's address.
5. Wait for the first build (10-20 minutes). Your site is at the `https://….onrender.com`
   address Render shows.

Free plan limits: 512 MB memory and a small share of a CPU, so one job runs at a time (a
10-file batch is one job) and conversions are slower than on your own computer. Files up to
15 MB each, 40 MB per upload. Tested under a real 512 MB limit: a 10-file mixed batch peaks
at about 230 MB. The site
sleeps after 15 minutes without visitors; the next visitor waits about a minute while it
wakes up. OCR is left out to save memory. Every push to GitHub redeploys automatically.

## Run it as a real website (always on)

You need a Linux server with at least 2 GB of RAM (any VPS such as AWS Lightsail,
DigitalOcean or Hetzner), Docker, and a domain name.

1. Point your domain's DNS **A record** at the server's IP address.
2. On the server:
   ```bash
   git clone <your repository> doclivo && cd doclivo
   cp .env.example .env        # set DOMAIN and SOURCE_URL
   docker compose up -d --build
   ```
3. Visit `https://your-domain`. Caddy gets the HTTPS certificate automatically.

Update later with `git pull && docker compose up -d --build`.

Sizing: one conversion can use up to about 1 GB of memory, so set `WORKERS` to roughly
the server's RAM in GB minus one.

## Settings

All in `.env` (see `.env.example`): file and page limits, `WORKERS`, `JOB_TIMEOUT`,
per-visitor rate limits, `PROXY` (`none`, `xff` behind Caddy/nginx, `cloudflare`
behind Cloudflare), `SITE_NAME` and `SOURCE_URL`.

## Security measures

- Upload size enforced while receiving; requests over the limit are cut off.
- File types checked by extension and file signature; uploaded file names are never used as paths.
- Every job in a separate process with a hard time limit; LibreOffice is killed with it.
- Temporary folders deleted after each response and swept every 10 minutes.
- Per-visitor rate limits and a bounded queue: visitors see "busy" instead of the server falling over.
- Strict Content-Security-Policy (no inline scripts or styles), no cookies, no tracking.
- Docker: non-root user, read-only filesystem except `/data` and `/tmp`, memory and process limits.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

63 tests: every conversion path, each PDF tool, watermark removal (and proof that
ordinary documents are left untouched), edits on rotated pages, bad input, size limits,
passwords, clean-up and rate limits. Sample files are generated on the
first run.

## Known limits

- **PDF to Word** rebuilds the page as editable Word content. Simple documents come
  out well; complex layouts (multi-column magazines, forms) can shift. Scanned PDFs
  come out as pictures, so run OCR first.
- **PDF to PowerPoint** makes one slide per page as a picture, with the page text in the
  speaker notes. PDFs don't contain slide structure to rebuild.
- **Edit PDF** adds things on top of the page. To change existing text, cover it with
  white-out and type the new text over it. Editing a PDF's original text in place is
  not supported.
- Text typed in the editor supports Latin, Greek and Cyrillic letters. Indian scripts
  typed in the editor may not join correctly.
- **Remove watermark** removes watermarks that are separate from the page content:
  ones labelled as watermarks, angled/see-through/light text repeated across pages,
  see-through logos, and Word's own watermarks. A watermark that is part of a scanned
  picture can't be removed. Only use it on documents you own or have permission to change.
- Office conversions use LibreOffice. Most documents look the same; some Microsoft-only
  features (SmartArt, certain animations, macros) are simplified or dropped.

## Licence

AGPL-3.0, because PDF to Word uses PyMuPDF. Running a public site means offering its
source code to visitors, so set `SOURCE_URL`. See `LICENSE`.
