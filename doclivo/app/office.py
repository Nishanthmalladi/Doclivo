"""Headless LibreOffice for Office <-> PDF and Office <-> Office conversions."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path

from .errors import UserError

FILTERS = {
    # target -> --convert-to argument (LibreOffice picks the right export for the input type)
    "pdf": "pdf",
    "docx": "docx:MS Word 2007 XML", "doc": "doc:MS Word 97", "odt": "odt", "rtf": "rtf",
    "txt": "txt:Text (encoded):UTF8", "html": "html:XHTML Writer File:UTF8",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML", "ppt": "ppt:MS PowerPoint 97", "odp": "odp",
    "xlsx": "xlsx:Calc MS Excel 2007 XML", "xls": "xls:MS Excel 97", "ods": "ods",
    # 44=comma, 34=double quote, 76=UTF-8, 1=first line
    "csv": 'csv:Text - txt - csv (StarCalc):44,34,76,1',
}
MAC_PATHS = [
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice"),
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
]


def soffice_path() -> str | None:
    env = os.environ.get("SOFFICE_PATH")
    if env and Path(env).exists():
        return env
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in MAC_PATHS if Path(p).exists()), None)


def convert(src: Path, target: str, outdir: Path, profile: Path, timeout: int,
            infilter: str | None = None) -> Path:
    exe = soffice_path()
    if not exe:
        raise UserError("Office conversions are not available on this server (LibreOffice is not installed).")
    if target not in FILTERS:
        raise UserError(f"LibreOffice cannot produce .{target}")
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo",
           "--nofirststartwizard", f"-env:UserInstallation={profile.resolve().as_uri()}"]
    if infilter:
        cmd.append(f"--infilter={infilter}")
    cmd += ["--convert-to", FILTERS[target], "--outdir", str(outdir), str(src)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True, env={**os.environ, "HOME": str(profile)})
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise UserError("The conversion took too long and was stopped. Try a smaller file.")
    result = outdir / f"{src.stem}.{target}"
    if not result.exists() or result.stat().st_size == 0:
        raise UserError("This file could not be converted. It may be damaged, password-protected "
                        "or in an unsupported format.")
    return result
