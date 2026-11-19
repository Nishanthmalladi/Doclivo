# Doclivo: FastAPI + LibreOffice + Tesseract in one image.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data HOME=/tmp

# LibreOffice for Office files; fonts so documents keep their look
# (Carlito/Caladea match Calibri/Cambria, Noto covers Indian scripts);
# Tesseract for OCR of scanned PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        fonts-dejavu-core fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea fonts-noto-core \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-tel tesseract-ocr-tam \
        tesseract-ocr-kan tesseract-ocr-mal tesseract-ocr-mar tesseract-ocr-ben tesseract-ocr-guj \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY web ./web

RUN useradd --system --uid 10001 --home-dir /data doclivo && mkdir -p /data && chown doclivo /data
USER doclivo

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT', '8000')}/healthz\", timeout=4)"
# Hosting platforms such as Render tell the app which port to use in $PORT.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 30"]
