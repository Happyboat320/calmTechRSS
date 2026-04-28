from __future__ import annotations

import json
from pathlib import Path

from .models import Event
from .text import truncate


def write_clusters_json(output_dir: str | Path, issue_date: str, events: list[Event]) -> str:
    clusters_dir = Path(output_dir) / "clusters"
    clusters_dir.mkdir(parents=True, exist_ok=True)
    path = clusters_dir / f"{issue_date}.json"
    payload = {
        "issue_date": issue_date,
        "event_count": len(events),
        "events": [
            {
                "event_hash": event.event_hash,
                "score": round(event.score, 6),
                "article_count": len(event.articles),
                "sources": sorted({article.source_name for article in event.articles}),
                "titles": [article.title for article in event.articles],
                "articles": [
                    {
                        "title": article.title,
                        "url": article.url,
                        "source_name": article.source_name,
                        "source_category": article.source_category,
                        "published_at_utc": article.published_at_utc.isoformat(),
                        "summary": truncate(article.summary, 700),
                        "content": truncate(article.content, 1200),
                        "url_hash": article.url_hash,
                        "content_hash": article.content_hash,
                    }
                    for article in event.articles
                ],
            }
            for event in events
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)

