"""Apply rename operations with a persistent journal, and undo the last batch."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .plan import Op

JOURNAL = Path.home() / ".mediarenamer" / "journal.jsonl"


def apply_ops(ops: list[Op]) -> tuple[int, list[str]]:
    done: list[dict] = []
    errors: list[str] = []
    for op in ops:
        try:
            op.dst.parent.mkdir(parents=True, exist_ok=True)
            if op.dst.exists() and op.dst != op.src:
                errors.append(f"exists, skipped: {op.dst}")
                continue
            op.src.rename(op.dst)
            done.append({"from": str(op.src), "to": str(op.dst)})
        except OSError as e:
            errors.append(f"{op.src}: {e}")
    if done:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "ops": done}) + "\n")
    return len(done), errors


def undo_last() -> tuple[int, list[str]]:
    if not JOURNAL.is_file():
        return 0, ["no journal found"]
    lines = JOURNAL.read_text(encoding="utf-8").splitlines()
    if not lines:
        return 0, ["journal is empty"]
    batch = json.loads(lines[-1])
    errors: list[str] = []
    undone = 0
    for op in reversed(batch["ops"]):
        src, dst = Path(op["to"]), Path(op["from"])
        try:
            if not src.exists():
                errors.append(f"missing, cannot undo: {src}")
                continue
            if dst.exists():
                errors.append(f"original name taken, cannot undo: {dst}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            undone += 1
            try:
                src.parent.rmdir()   # drop a movie folder the apply created, if now empty
            except OSError:
                pass
        except OSError as e:
            errors.append(f"{src}: {e}")
    JOURNAL.write_text("\n".join(lines[:-1]) + ("\n" if len(lines) > 1 else ""),
                       encoding="utf-8")
    return undone, errors
