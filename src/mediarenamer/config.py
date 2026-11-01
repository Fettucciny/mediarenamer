"""User settings stored in ~/.mediarenamer/config.json (API keys, preferences)."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_FILE = Path.home() / ".mediarenamer" / "config.json"
DEFAULTS = {
    "tmdb_api_key": "",
    "prefer_original_titles": False,
    "recursive": True,
    "output_dir": "",
    "tv_scheme": "plex",        # 'plex' | 'simple'
    "movie_scheme": "filebot",  # 'filebot' | 'simple'
    "rename_folders": True,     # rename a dropped folder to 'Title (Year) {tmdb-ID}'
    "recent_paths": [],
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def apply_env(cfg: dict) -> None:
    """Export settings the providers read from the environment, without
    overriding values the user already set there."""
    if cfg.get("tmdb_api_key") and not os.environ.get("TMDB_API_KEY"):
        os.environ["TMDB_API_KEY"] = cfg["tmdb_api_key"]
