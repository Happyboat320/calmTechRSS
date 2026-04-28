from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .cluster import cluster_articles
from .config import load_sources
from .db import Database
from .env import load_env
from .fetcher import fetch_articles
from .llm import LLMClient, PROMPT_VERSION
from .render import render_issue
from .rss import generate_feed

LOGGER = logging.getLogger(__name__)


def run_pipeline(
    sources_path: str | Path,
    db_path: str | Path,
    output_dir: str | Path,
    site_base_url: str,
    issue_date: str | None = None,
    candidate_hours: int = 48,
) -> None:
    load_env()
    issue_date = issue_date or date.today().isoformat()
    since = datetime.now(timezone.utc) - timedelta(hours=candidate_hours)
    sources = load_sources(sources_path)
    db = Database(db_path)
    try:
        db.init()
        db.upsert_sources(sources)
        fetched = fetch_articles(sources, since)
        saved = db.upsert_articles(fetched)
        LOGGER.info("fetched=%s saved_or_seen=%s", len(fetched), len(saved))

        candidates = db.get_articles_since(since)
        llm = LLMClient()
        translation_model = llm.model if llm.enabled else "source-text"
        for article in candidates:
            cached = db.get_translation(article, translation_model)
            if cached:
                values = cached
            else:
                values = llm.translate_article(article)
                db.save_translation(article, translation_model, values)
            article.translated_title, article.translated_summary, article.translated_content = values

        events = cluster_articles(candidates)
        db.upsert_events(events)
        selected_hashes = set(llm.pick_event_hashes(events, limit=5))
        selected_events = [event for event in events if event.event_hash in selected_hashes][:5]
        if len(selected_events) < 3:
            selected_events = events[: min(5, len(events))]

        rewrites = []
        rewrite_model = llm.model if llm.enabled else "fallback"
        for event in selected_events:
            cached_rewrite = db.get_rewrite(event.event_hash, PROMPT_VERSION, rewrite_model)
            rewrite = cached_rewrite or llm.rewrite_event(event)
            if cached_rewrite is None:
                db.save_rewrite(event.event_hash, PROMPT_VERSION, rewrite_model, rewrite)
            rewrites.append((event, rewrite))

        html_path = render_issue(output_dir, issue_date, rewrites, site_base_url)
        generate_feed(output_dir, site_base_url, issue_date)
        db.save_issue(issue_date, selected_events, html_path)
    finally:
        db.close()
