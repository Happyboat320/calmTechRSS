from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import feedparser
import httpx
from dateutil import parser as date_parser

from .models import Article, Source
from .text import clean_url, normalize_whitespace, sha256_text, strip_html

LOGGER = logging.getLogger(__name__)


def fetch_articles(sources: list[Source], since_utc: datetime, max_workers: int = 4) -> list[Article]:
    articles: list[Article] = []
    workers = max(1, min(max_workers, len(sources) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_source, source, since_utc) for source in sources]
        for future in as_completed(futures):
            articles.extend(future.result())
    return articles


def fetch_source(source: Source, since_utc: datetime) -> list[Article]:
    headers = {"User-Agent": "CalmTechRSS/0.1 (+https://example.com)"}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=20.0) as client:
        try:
            response = client.get(source.url)
            response.raise_for_status()
            return parse_feed(response.text, source, since_utc)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("source failed: %s: %s", source.name, exc)
    return []


def parse_feed(feed_text: str, source: Source, since_utc: datetime) -> list[Article]:
    parsed = feedparser.parse(feed_text)
    articles: list[Article] = []
    for entry in parsed.entries:
        title = normalize_whitespace(getattr(entry, "title", ""))
        link = clean_url(getattr(entry, "link", ""))
        if not title or not link:
            continue
        published_at = parse_entry_time(entry)
        if published_at < since_utc:
            continue
        summary = strip_html(getattr(entry, "summary", ""))
        content = extract_content(entry)
        if not summary and not content:
            continue
        source_article_id = normalize_whitespace(getattr(entry, "id", "")) or link
        content_hash = sha256_text("\n".join([title, summary, content]))
        articles.append(
            Article(
                title=title,
                url=link,
                source_name=source.name,
                source_category=source.category,
                published_at_utc=published_at,
                summary=summary,
                content=content,
                source_article_id=source_article_id,
                url_hash=sha256_text(link),
                content_hash=content_hash,
                source_weight=source.weight,
            )
        )
    return articles


def parse_entry_time(entry: object) -> datetime:
    for key in ("published", "updated", "created"):
        value = getattr(entry, key, None)
        if value:
            try:
                parsed = date_parser.parse(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return datetime.now(timezone.utc)


def extract_content(entry: object) -> str:
    content_items = getattr(entry, "content", None) or []
    if content_items:
        value = getattr(content_items[0], "value", "") or content_items[0].get("value", "")
        return strip_html(value)
    return ""
