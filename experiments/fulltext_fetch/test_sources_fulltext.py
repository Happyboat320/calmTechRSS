from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calmtechrss.config import load_sources
from calmtechrss.fetcher import fetch_articles

from fetch_fulltext import fetch_fulltext


def test_sources(
    sources_path: str,
    per_source: int,
    candidate_hours: int,
    timeout: float,
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=candidate_hours)
    sources = load_sources(sources_path)
    articles = fetch_articles(sources, since, max_workers=4)
    by_source: dict[str, list[Any]] = {}
    for article in articles:
        by_source.setdefault(article.source_name, []).append(article)

    source_results = []
    for source in sources:
        items = []
        for article in by_source.get(source.name, [])[:per_source]:
            try:
                fulltext = fetch_fulltext(article.url, timeout=timeout)
                items.append(
                    {
                        "title": article.title,
                        "url": article.url,
                        "status": "ok",
                        "rss_summary_length": len(article.summary),
                        "rss_content_length": len(article.content),
                        "fulltext_length": fulltext["text_length"],
                        "extractor": fulltext["extractor"],
                        "preview": fulltext["text"][:240],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                items.append(
                    {
                        "title": article.title,
                        "url": article.url,
                        "status": "error",
                        "error": str(exc),
                        "rss_summary_length": len(article.summary),
                        "rss_content_length": len(article.content),
                    }
                )
        ok_count = sum(1 for item in items if item["status"] == "ok")
        source_results.append(
            {
                "source": source.name,
                "url": source.url,
                "fetched_articles": len(by_source.get(source.name, [])),
                "tested_articles": len(items),
                "ok": ok_count,
                "errors": len(items) - ok_count,
                "items": items,
            }
        )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources_path": sources_path,
        "candidate_hours": candidate_hours,
        "per_source": per_source,
        "total_sources": len(sources),
        "total_rss_articles": len(articles),
        "sources": source_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="config/sources.yml")
    parser.add_argument("--per-source", type=int, default=2)
    parser.add_argument("--candidate-hours", type=int, default=72)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", default="experiments/fulltext_fetch/fulltext_report.json")
    args = parser.parse_args()

    report = test_sources(
        sources_path=args.sources,
        per_source=args.per_source,
        candidate_hours=args.candidate_hours,
        timeout=args.timeout,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary(report), ensure_ascii=False, indent=2))
    print(f"report={output}")


def summary(report: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for source in report["sources"]:
        lengths = [
            item["fulltext_length"]
            for item in source["items"]
            if item["status"] == "ok"
        ]
        sources.append(
            {
                "source": source["source"],
                "fetched_articles": source["fetched_articles"],
                "tested_articles": source["tested_articles"],
                "ok": source["ok"],
                "errors": source["errors"],
                "max_fulltext_length": max(lengths) if lengths else 0,
            }
        )
    return {
        "total_sources": report["total_sources"],
        "total_rss_articles": report["total_rss_articles"],
        "sources": sources,
    }


if __name__ == "__main__":
    main()
