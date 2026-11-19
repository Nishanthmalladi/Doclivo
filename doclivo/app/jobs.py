"""Worker process entry point.  The server starts  python -m app.jobs  for each
job, writes a JSON spec to stdin and reads a JSON result from stdout.  Running
each job in its own process means a hostile or broken file can at worst hang or
crash this process, which the server kills after the time limit."""
from __future__ import annotations

import json
import sys
import traceback
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")


def run(spec: dict) -> dict:
    from . import engine
    from .errors import UserError
    op = spec["op"]
    inputs = [Path(p) for p in spec.get("inputs", [])]
    outdir = Path(spec["outdir"])
    stem = spec.get("stem", "file")
    opts = spec.get("options", {})
    limits = spec["limits"]
    profile = Path(spec.get("profile", outdir / "profile"))
    max_pages = limits["max_pages"]
    meta: dict = {}

    if op == "convert":
        target = spec["target"]
        kinds = {engine.kind_of(p.suffix.lstrip(".")) for p in inputs}
        if target == "pdf" and kinds == {"image"} and opts.get("combine", True):
            path = engine.images_to_pdf(inputs, outdir / f"{stem}.pdf", opts)
        elif len(inputs) == 1:
            path = engine.convert(inputs[0], target, outdir, stem=stem, profile=profile,
                                  limits=limits, options=opts)
        else:
            # Several files: convert each on its own; one bad file must not sink the
            # others.  Files already in the target format are passed through as they are.
            results, problems, used = [], [], set()
            for k, (src, name) in enumerate(zip(inputs, spec["stems"])):
                name = engine.unique_name(name, used)
                sub = outdir / f"item-{k}"
                sub.mkdir()
                ext = src.suffix.lstrip(".").lower()
                kind = engine.kind_of(ext)
                try:
                    if ext == target or (ext == "jpeg" and target == "jpg"):
                        results.append(engine.copy_as(src, sub / f"{name}.{target}"))
                    elif target not in engine.TARGETS.get(kind, []):
                        raise UserError(f"{engine.KIND_NAMES[kind]} files cannot be turned into "
                                        f"{engine.LABELS.get(target, target)}.")
                    else:
                        results.append(engine.convert(src, target, sub, stem=name, profile=profile,
                                                      limits=limits, options=opts))
                except UserError as e:
                    problems.append(f"{name}.{ext}: {e}")
            if not results:
                raise UserError("None of the files could be converted. " + " ".join(problems))
            path = engine._zip(results, outdir / f"{stem}-converted.zip")
            meta = {"converted": len(results), "failed": len(problems)}
            if problems:
                (outdir / "notes.txt").write_text("Files that could not be converted:\n" + "\n".join(problems))
                import zipfile
                with zipfile.ZipFile(path, "a") as z:
                    z.write(outdir / "notes.txt", "NOT-CONVERTED.txt")
    elif op == "merge":
        path = engine.merge(inputs, outdir / f"{stem}-merged.pdf", max_pages)
    elif op == "split":
        path = engine.split(inputs[0], outdir, stem, opts.get("mode", "ranges"), opts.get("ranges", ""), max_pages)
    elif op == "organize":
        path = engine.organize(inputs[0], outdir / f"{stem}-organized.pdf", opts.get("pages"), max_pages)
    elif op == "compress":
        path, meta = engine.compress(inputs[0], outdir / f"{stem}-compressed.pdf", opts.get("level", "medium"))
    elif op == "protect":
        path = engine.protect(inputs[0], outdir / f"{stem}-protected.pdf", opts.get("password", ""))
    elif op == "unlock":
        path = engine.unlock(inputs[0], outdir / f"{stem}-unlocked.pdf", opts.get("password", ""))
    elif op == "watermark":
        path = engine.watermark(inputs[0], outdir / f"{stem}-watermarked.pdf", opts)
    elif op == "page-numbers":
        path = engine.page_numbers(inputs[0], outdir / f"{stem}-numbered.pdf", opts)
    elif op == "edit":
        path = engine.edit(inputs[0], outdir / f"{stem}-edited.pdf", opts.get("ops"))
    elif op == "remove-watermark":
        path, meta = engine.remove_watermark(inputs[0], outdir, stem, opts.get("text", ""), profile, limits)
    elif op == "ocr":
        work = outdir / "ocr"
        work.mkdir()
        path = engine.ocr(inputs[0], outdir / f"{stem}-searchable.pdf", work, opts.get("lang", "eng"), max_pages)
    else:
        raise ValueError(f"unknown op {op}")
    return {"path": str(path), "meta": meta}


def main():
    from .errors import UserError
    try:
        result = run(json.loads(sys.stdin.read()))
        print(json.dumps(result))
    except UserError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(2)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": "Something went wrong while processing this file. "
                                   "It may be damaged or use features we cannot handle."}))
        sys.exit(3)


if __name__ == "__main__":
    main()
