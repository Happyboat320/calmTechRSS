from __future__ import annotations

from pathlib import Path

import yaml

from .models import Source


def load_sources(path: str | Path) -> list[Source]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sources = []
    for item in raw.get("sources", []):
        source = Source(
            name=str(item["name"]),
            url=str(item["url"]),
            type=str(item.get("type", "rss")),
            category=str(item.get("category", "media")),
            active=bool(item.get("active", True)),
            weight=float(item.get("weight", 1.0)),
        )
        if source.active:
            sources.append(source)
    return sources

