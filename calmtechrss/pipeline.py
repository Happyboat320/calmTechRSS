from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .api_config import load_api_config
from .cluster import ExistingCluster, incremental_cluster_articles
from .config import load_sources
from .db import Database
from .env import load_env
from .export import write_clusters_json
from .fetcher import fetch_articles
from .llm import LLMClient, PROMPT_VERSION
from .render import render_index, render_issue
from .rss import generate_feed

LOGGER = logging.getLogger(__name__)


def run_pipeline(
    sources_path: str | Path,
    api_config_path: str | Path,
    db_path: str | Path,
    output_dir: str | Path,
    site_base_url: str,
    issue_date: str | None = None,
    candidate_hours: int = 24,
) -> None:
    load_env()
    issue_date = issue_date or date.today().isoformat()
    since = datetime.now(timezone.utc) - timedelta(hours=candidate_hours)
    api_config = load_api_config(api_config_path)
    sources = load_sources(sources_path)
    db = Database(db_path)
    try:
        db.init()
        db.upsert_sources(sources)
        fetched = fetch_articles(sources, since, max_workers=api_config.pipeline.max_workers)
        saved = db.upsert_articles(fetched)
        LOGGER.info("fetched=%s saved_or_seen=%s", len(fetched), len(saved))

        candidates = db.get_unassigned_articles_since(since)
        llm = LLMClient(api_config.llm)
        existing_clusters = [
            ExistingCluster(event_hash=event_hash, articles=articles, centroid=centroid)
            for event_hash, articles, centroid in db.get_existing_clusters()
        ]
        changed_events = incremental_cluster_articles(
            candidates,
            existing_clusters=existing_clusters,
            embedding_model=api_config.embedding.model,
            embedding_device=api_config.embedding.device,
            embedding_batch_size=api_config.embedding.batch_size,
            embedding_cpu_threads=api_config.embedding.cpu_threads,
        )
        db.upsert_events(changed_events)
        events = db.get_events_with_recent_articles(since)
        clusters_json_path = write_clusters_json(output_dir, issue_date, events)
        LOGGER.info("clusters_json=%s event_count=%s", clusters_json_path, len(events))
        selected_hashes = set(llm.pick_event_hashes(events, limit=5))
        selected_events = [event for event in events if event.event_hash in selected_hashes][:5]
        if len(selected_events) < 3:
            selected_events = events[: min(5, len(events))]

        rewrites_by_hash = {}
        rewrite_model = llm.model if llm.enabled else "fallback"
        missing_events = []
        for event in selected_events:
            cached_rewrite = db.get_rewrite(event.event_hash, PROMPT_VERSION, rewrite_model)
            if cached_rewrite is None:
                missing_events.append(event)
            else:
                rewrites_by_hash[event.event_hash] = cached_rewrite

        if missing_events:
            workers = min(api_config.pipeline.max_workers, len(missing_events))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_event = {
                    executor.submit(llm.rewrite_event, event): event for event in missing_events
                }
                for future in as_completed(future_to_event):
                    event = future_to_event[future]
                    rewrite = future.result()
                    db.save_rewrite(event.event_hash, PROMPT_VERSION, rewrite_model, rewrite)
                    rewrites_by_hash[event.event_hash] = rewrite

        rewrites = [(event, rewrites_by_hash[event.event_hash]) for event in selected_events]

        html_path = render_issue(output_dir, issue_date, rewrites, site_base_url)
        generate_feed(output_dir, site_base_url, issue_date)
        render_index(output_dir, issue_date, site_base_url)
        db.save_issue(issue_date, selected_events, html_path)
    finally:
        db.close()
