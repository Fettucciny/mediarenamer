"""Command-line interface. `match` is always a dry run; `apply` renames; `undo` reverts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .journal import apply_ops, undo_last
from .match import MatchResult, match_all
from .parse import COMPANION_EXTS, VIDEO_EXTS, parse_file
from .plan import build_plan


def scan(root: Path, recursive: bool) -> list:
    exts = VIDEO_EXTS | COMPANION_EXTS
    it = root.rglob("*") if recursive else root.glob("*")
    files = sorted(p for p in it if p.is_file() and p.suffix.casefold() in exts)
    return [parse_file(p, root) for p in files]


def print_results(results: list[MatchResult], verbose: bool) -> None:
    for r in sorted(results, key=lambda r: str(r.file.path)):
        name = r.file.path.name
        if r.status == "UNMATCHED":
            reason = r.trace[-1] if r.trace else "no evidence"
            print(f"[UNMATCHED] {name}\n            reason: {reason}")
        else:
            target = r.new_name or "(name unchanged)"
            tag = f"{r.status} {r.confidence:.2f}"
            print(f"[{tag}] {name}\n{' ' * (len(tag) + 3)}-> {target}")
        if verbose:
            for line in r.trace:
                print(f"    | {line}")


def main(argv: list[str] | None = None) -> int:
    # Windows consoles often default to cp1252; show names are Unicode.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="mediarenamer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("match", "apply"):
        p = sub.add_parser(name)
        p.add_argument("path", type=Path)
        p.add_argument("-r", "--recursive", action="store_true")
        p.add_argument("-v", "--verbose", action="store_true")
        p.add_argument("--kind", choices=["auto", "tv", "movie"], default="auto")
        p.add_argument("--season", type=int, default=None,
                       help="force the season for bare episode numbers")
        p.add_argument("--output", type=Path, default=None,
                       help="organize into this directory instead of renaming in place")
        if name == "apply":
            p.add_argument("--yes", action="store_true", help="skip confirmation")
            p.add_argument("--accept-review", action="store_true",
                           help="also apply REVIEW-band matches")
    sub.add_parser("undo")

    args = ap.parse_args(argv)

    if args.cmd == "undo":
        n, errs = undo_last()
        print(f"undone: {n} file(s)")
        for e in errs:
            print(f"  ! {e}", file=sys.stderr)
        return 0 if not errs else 1

    root = args.path.resolve()
    if not root.exists():
        print(f"path not found: {root}", file=sys.stderr)
        return 2
    files = scan(root, args.recursive)
    if not files:
        print("no media files found")
        return 0
    results = match_all(files, kind=args.kind, season=args.season)
    threshold = "REVIEW" if (args.cmd == "apply" and args.accept_review) else "AUTO"
    accepted = [r for r in results
                if r.status == "AUTO" or (threshold == "REVIEW" and r.status == "REVIEW")]
    ops = build_plan(accepted, output=args.output)
    # annotate new names on everything matched (for display), not just accepted
    build_plan([r for r in results if r.status != "UNMATCHED" and r.new_name is None],
               output=args.output)
    print_results(results, args.verbose)

    auto = sum(1 for r in results if r.status == "AUTO")
    review = sum(1 for r in results if r.status == "REVIEW")
    un = sum(1 for r in results if r.status == "UNMATCHED")
    print(f"\n{auto} auto, {review} review, {un} unmatched; {len(ops)} rename(s) planned")

    if args.cmd == "match":
        print("dry run — use 'apply' to rename")
        return 0
    if not ops:
        return 0
    if not args.yes:
        reply = input(f"apply {len(ops)} rename(s)? [y/N] ").strip().casefold()
        if reply not in ("y", "yes"):
            print("aborted")
            return 1
    n, errs = apply_ops(ops)
    print(f"renamed: {n} file(s)  (undo with 'mediarenamer undo')")
    for e in errs:
        print(f"  ! {e}", file=sys.stderr)
    return 0 if not errs else 1
