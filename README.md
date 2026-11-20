📄 Doclivo

I got tired of converter sites that want a login, or cap you at 2 conversions a day. So I built my own.

Doclivo converts Word, PowerPoint, Excel, PDF and images into pretty much any format you need, and has a bunch of PDF tools on top. It's free, there's no sign-up, and your files get deleted as soon as you download the result.

🔗 Try it: https://doclivo.onrender.com

⏳ It runs on Render's free plan, so if nobody's used it for a while the first load takes about a minute to wake up. After that it's quick.

🔄 What it converts
From	To
📝 Word (doc, docx, odt, rtf, txt, html)	PDF, Word, ODT, RTF, Text, HTML, JPG, PNG
📊 PowerPoint (ppt, pptx, odp)	PDF, Word, PPT, ODP, JPG, PNG
📈 Excel (xls, xlsx, ods, csv)	PDF, Excel, ODS, CSV
📕 PDF	Word, PowerPoint, Excel, Text, JPG, PNG
🖼️ Images (jpg, png, webp, heic...)	PDF, JPG, PNG, WebP

PowerPoint → Word has two modes: keep the slides looking like slides, or turn them into a clean document with headings, bullet points, tables and your speaker notes. The second one is great for making notes out of lecture slides 📚

📦 Lots of files at once

Drop up to 15 files (mix of PPTs, Word docs, PDFs, whatever) and pick one format. You get everything back in a single zip. If a file can't be converted to that format, it tells you before you start, and lists it in a NOT-CONVERTED.txt inside the zip so nothing silently goes missing.

🛠️ PDF tools

Pages

🔗 Merge PDFs
✂️ Split by page range
🗂️ Organize: drag pages around, rotate, duplicate, delete
🔃 Rotate

Editing

✏️ Add text, images, highlights, boxes, freehand drawing
🩹 White-out (cover something and type over it)
✍️ Sign: draw it with your mouse/finger or upload a photo of your signature
💧 Add a watermark
🚫 Remove a watermark (works on PDFs and Word files)
🔢 Page numbers

Size & security

🗜️ Compress (got a 21 MB PDF down to 646 KB in testing)
🔒 Password protect
🔓 Unlock
🔍 OCR for scanned PDFs (on the local version)

The editor and page organizer show your PDF right in the browser, so nothing gets uploaded until you hit Save.

🧱 How it's built
your browser  ──►  FastAPI server  ──►  separate worker process
(HTML/CSS/JS,       (checks files,       (LibreOffice, pdf2docx,
 pdf.js preview)     queue, cleanup)       pypdf, pikepdf...)

Every conversion runs in its own process with a time limit. So if someone uploads a broken or weird file, only that job dies and the site keeps running.

Stack: Python · FastAPI · LibreOffice (headless) · pdf2docx · pypdf · pikepdf · pypdfium2 · pdfplumber · python-docx · python-pptx · openpyxl · Pillow · ReportLab · pdf.js · plain JavaScript (no framework) · Docker · Render

💻 Run it yourself

You'll need Python 3.10+ and LibreOffice.

bash
# on a Mac
brew install --cask libreoffice

cd doclivo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000

Then open http://127.0.0.1:8000 🎉

Want OCR too? brew install tesseract tesseract-lang and restart.

Tests: there are 63 of them.

bash
pip install -r requirements-dev.txt
python -m pytest -q
🚀 Deploying

Render (free) — this repo is already set up as a Render Blueprint. New → Blueprint → pick this repo → set the Blueprint path to doclivo/render.yaml → Apply. First build takes 10-20 min because LibreOffice is big.

Free plan means 512 MB of RAM, so it handles one job at a time and files up to 15 MB each. I tested a 10-file batch under a real 512 MB limit and it peaked at about 230 MB, so there's room.

Own server — there's a docker-compose.yml + Caddy setup in the doclivo folder that gives you HTTPS automatically. Just set your domain in .env and run docker compose up -d --build.

🔐 Privacy
Files go into a temp folder and get deleted right after you download the result
No accounts, no cookies, no analytics
Upload size and file type are checked before anything gets processed
Rate limited per visitor so one person can't hog the server
⚠️ Things it can't do (yet)
PDF → Word works well on normal documents, but fancy layouts like magazines or forms can shift around a bit
PDF → PowerPoint turns each page into an image slide, because PDFs don't actually store slide info
Editing existing PDF text isn't supported. You can white it out and type over it though
Watermark removal won't work if the watermark is part of a scanned image (it's literally baked into the picture)
Some Microsoft-only stuff like SmartArt or macros gets simplified when converting

📜 License

AGPL-3.0. The PDF → Word part uses PyMuPDF which is AGPL, so the full source has to stay public. That's what this repo is.

Made by @Nishanthmalladi ⭐ Star the repo if it helped you out!
