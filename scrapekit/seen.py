"""Seen-id helpers: persist only after listings merge succeeds."""

from __future__ import annotations

import json
from pathlib import Path


def load_seen(path: Path | str) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(x) for x in data)
    except (json.JSONDecodeError, OSError):
        pass
    return set()


def save_seen(path: Path | str, seen: set[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def commit_seen(path: Path | str, new_ids: list[str] | set[str]) -> int:
    """Union new ids into seen file. Returns number newly added."""
    seen = load_seen(path)
    before = len(seen)
    for i in new_ids:
        if i:
            seen.add(str(i))
    if len(seen) != before:
        save_seen(path, seen)
    return len(seen) - before
