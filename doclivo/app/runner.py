"""Runs jobs in worker processes, a limited number at a time.

Each of the N slots owns a LibreOffice profile directory, so LibreOffice runs
never share state and the profile is reused (much faster than a fresh one)."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Busy(Exception):
    pass


class JobFailed(Exception):
    pass


class Runner:
    def __init__(self, slots: int, data_dir: Path, job_timeout: int, wait_timeout: int):
        self.job_timeout, self.wait_timeout = job_timeout, wait_timeout
        self.profiles = [data_dir / "profiles" / f"slot-{i}" for i in range(slots)]
        for p in self.profiles:
            p.mkdir(parents=True, exist_ok=True)
        self.free: asyncio.Queue[int] = asyncio.Queue()
        for i in range(slots):
            self.free.put_nowait(i)
        self.waiting = 0
        self.max_waiting = slots * 8

    async def run(self, spec: dict) -> dict:
        if self.waiting >= self.max_waiting:
            raise Busy()
        self.waiting += 1
        try:
            slot = await asyncio.wait_for(self.free.get(), self.wait_timeout)
        except asyncio.TimeoutError:
            raise Busy() from None
        finally:
            self.waiting -= 1
        try:
            return await self._execute({**spec, "profile": str(self.profiles[slot])})
        finally:
            self.free.put_nowait(slot)

    async def _execute(self, spec: dict) -> dict:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "app.jobs", cwd=str(ROOT),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True,
            env={**os.environ, "PYTHONWARNINGS": "ignore"})
        try:
            out, err = await asyncio.wait_for(proc.communicate(json.dumps(spec).encode()), self.job_timeout)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)       # also kills LibreOffice children
            except ProcessLookupError:
                pass
            await proc.wait()
            raise JobFailed("This file took too long to process and was stopped. Try a smaller file.") from None
        lines = out.decode(errors="replace").strip().splitlines()
        try:
            result = json.loads(lines[-1]) if lines else {}
        except json.JSONDecodeError:
            result = {}
        if proc.returncode != 0 or "path" not in result:
            if proc.returncode == 3 and err:
                print(err.decode(errors="replace")[-3000:], file=sys.stderr)
            raise JobFailed(result.get("error") or "Processing failed. The file may be damaged.")
        return result
