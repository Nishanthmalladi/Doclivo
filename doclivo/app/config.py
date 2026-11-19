"""Settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    max_file_mb: int = _int("MAX_FILE_MB", 50)
    max_total_mb: int = _int("MAX_TOTAL_MB", 150)
    max_files: int = _int("MAX_FILES", 30)
    max_pages: int = _int("MAX_PAGES", 300)
    max_pages_docx: int = _int("MAX_PAGES_DOCX", 100)
    job_timeout: int = _int("JOB_TIMEOUT", 180)
    office_timeout: int = _int("OFFICE_TIMEOUT", 150)
    workers: int = _int("WORKERS", 2)
    queue_wait: int = _int("QUEUE_WAIT", 60)
    rate_per_minute: int = _int("RATE_PER_MINUTE", 20)
    rate_per_hour: int = _int("RATE_PER_HOUR", 200)
    # how to find the visitor's address: none (direct), xff (behind Caddy/nginx),
    # cloudflare (behind Cloudflare or a cloudflared tunnel)
    proxy: str = os.environ.get("PROXY", "none").lower()
    source_url: str = os.environ.get("SOURCE_URL", "")
    site_name: str = os.environ.get("SITE_NAME", "Doclivo")


settings = Settings()
