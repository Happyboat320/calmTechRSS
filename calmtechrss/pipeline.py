from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .api_config import load_api_config
from .cluster import ExistingCluster, incremental_cluster_articles, llm_cluster_articles
from .config import load_sources
from .db import Database
from .env import load_env
from .export import write_clusters_json
from .fetcher import fetch_articles
from .fulltext import enrich_articles_with_fulltext
from .llm import EventJudgeClient, LLMClient, PROMPT_VERSION
from .render import (
    prune_issue_pages,
    render_cluster_log,
    render_index,
    render_issue,
    render_original_pages,
)
from .rss import generate_feed

LOGGER = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
LAST_FETCH_KEY = "last_fetch_at_utc"


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
    run_started_utc = datetime.now(timezone.utc)
    issue_date = issue_date or datetime.now(LOCAL_TZ).date().isoformat()
    api_config = load_api_config(api_config_path)
    sources = load_sources(sources_path)
    db = Database(db_path)
    try:
        db.init()
        since, window_reason = resolve_fetch_window(db, run_started_utc, candidate_hours)
        db.upsert_sources(sources)
        fetched = fetch_articles(
            sources,
            since,
            max_workers=api_config.pipeline.max_workers,
            until_utc=run_started_utc,
        )
        fetched = enrich_articles_with_fulltext(
            fetched,
            max_workers=api_config.pipeline.max_workers,
        )
        saved = db.upsert_articles(fetched)
        LOGGER.info("fetched=%s saved_or_seen=%s", len(fetched), len(saved))

        candidates = db.get_unassigned_articles_between(since, run_started_utc)
        llm = LLMClient(api_config.llm)
        judge = EventJudgeClient(api_config.judge.resolved(api_config.llm))

        if llm.enabled:
            changed_events = llm_cluster_articles(
                candidates,
                llm_client=llm,
                max_articles=api_config.llm.max_articles,
            )
            new_events = changed_events
        else:
            existing_clusters = [
                ExistingCluster(event_hash=event_hash, articles=articles, centroid=[], vectors=centroid)
                for event_hash, articles, centroid in db.get_existing_clusters()
            ]
            changed_events = incremental_cluster_articles(
                candidates,
                existing_clusters=existing_clusters,
                embedding_model=api_config.embedding.model,
                embedding_models=api_config.embedding.models,
                embedding_device=api_config.embedding.device,
                embedding_batch_size=api_config.embedding.batch_size,
                embedding_cpu_threads=api_config.embedding.cpu_threads,
                embedding_max_chars=api_config.embedding.max_chars,
                similarity_threshold=api_config.embedding.similarity_threshold,
                event_judge=judge.same_event if judge.enabled else None,
                max_judge_workers=api_config.pipeline.max_workers,
            )
            new_events = [event for event in changed_events if event.is_new]
            ranked_hashes = llm.rank_new_events(new_events, limit=5)
            rank_bonus = {event_hash: 6 - index for index, event_hash in enumerate(ranked_hashes, 1)}
            for event in new_events:
                event.score = 1 + rank_bonus.get(event.event_hash, 0)

        db.upsert_events(changed_events)

        events = db.get_events_with_articles_between(since, run_started_utc)
        new_event_hashes = {event.event_hash for event in changed_events if event.is_new}
        for event in events:
            event.is_new = event.event_hash in new_event_hashes
        clusters_json_path = write_clusters_json(output_dir, issue_date, events)
        LOGGER.info("clusters_json=%s event_count=%s", clusters_json_path, len(events))
        selected_events = sorted(
            new_events,
            key=lambda event: event.score,
            reverse=True,
        )[:5]
        LOGGER.info("selected_new_events=%s", len(selected_events))

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

        original_links = render_original_pages(output_dir, issue_date, rewrites, site_base_url)
        log_url = render_cluster_log(
            output_dir,
            issue_date,
            events,
            changed_events,
            selected_events,
            site_base_url,
            stats={
                "fetched": len(fetched),
                "saved_or_seen": len(saved),
                "candidates": len(candidates),
                "changed_clusters": len(changed_events),
                "new_clusters": len(new_events),
                "selected_clusters": len(selected_events),
                "clusters_json": clusters_json_path,
                "fetch_window_start": since.isoformat(),
                "fetch_window_end": run_started_utc.isoformat(),
                "fetch_window_reason": window_reason,
            },
        )
        html_path = render_issue(
            output_dir,
            issue_date,
            rewrites,
            site_base_url,
            original_links=original_links,
            log_url=log_url,
        )
        db.save_issue(issue_date, selected_events, html_path)
        issue_entries = db.get_issue_entries(10, PROMPT_VERSION, rewrite_model)
        generate_feed(output_dir, site_base_url, issue_date, selected=rewrites, issues=issue_entries)
        render_index(output_dir, issue_date, site_base_url)
        prune_issue_pages(output_dir, keep=5)
        db.set_metadata_datetime(LAST_FETCH_KEY, run_started_utc)
    finally:
        db.close()


def resolve_fetch_window(
    db: Database,
    run_started_utc: datetime,
    candidate_hours: int,
) -> tuple[datetime, str]:
    fallback_since = run_started_utc - timedelta(hours=candidate_hours)
    if os.getenv("GITHUB_EVENT_NAME") == "push":
        return fallback_since, f"push 运行，使用最近 {candidate_hours} 小时"
    last_fetch_at = db.get_metadata_datetime(LAST_FETCH_KEY)
    if last_fetch_at is None:
        return fallback_since, f"没有上次抓取记录，使用最近 {candidate_hours} 小时"
    if last_fetch_at >= run_started_utc:
        return fallback_since, f"上次抓取时间异常，使用最近 {candidate_hours} 小时"
    return last_fetch_at, "从上次抓取时间开始"
