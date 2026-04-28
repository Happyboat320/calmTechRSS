from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from calmtechrss.api_config import load_api_config
from calmtechrss.cluster import ExistingCluster, incremental_cluster_articles
from calmtechrss.config import load_sources
from calmtechrss.db import Database
from calmtechrss.export import write_clusters_json
from calmtechrss.llm import fallback_rewrite
from calmtechrss.models import Article, Event
from calmtechrss.render import render_issue
from calmtechrss.rss import generate_feed, validate_feed


def make_event() -> Event:
    article = Article(
        title="AI tooling update",
        url="https://example.com/a",
        source_name="Example",
        source_category="official",
        published_at_utc=datetime.now(timezone.utc),
        summary="A concise update about AI tooling.",
        content="",
        source_article_id="a",
        url_hash="h1",
        content_hash="c1",
        source_weight=1.0,
    )
    return Event(event_hash="e1", articles=[article], score=1.0)


class CoreTest(unittest.TestCase):
    def test_plan_sources_are_configured(self) -> None:
        sources = load_sources("config/sources.yml")
        names = {source.name for source in sources}

        self.assertEqual(len(sources), 12)
        self.assertEqual(
            names,
            {
                "OpenAI Blog",
                "Anthropic News",
                "Google DeepMind Blog",
                "Microsoft AI Blog",
                "NVIDIA Blog",
                "Hugging Face Blog",
                "The Verge",
                "TechCrunch AI",
                "VentureBeat AI",
                "MIT Technology Review AI",
                "量子位",
                "InfoQ 中文",
            },
        )

    def test_api_config_loads_model_settings(self) -> None:
        config = load_api_config("config/api.yml")

        self.assertEqual(config.llm.api_key_env, "OPENAI_API_KEY")
        self.assertTrue(config.llm.model)
        self.assertEqual(config.embedding.model, "intfloat/multilingual-e5-small")
        self.assertEqual(config.embedding.device, "cpu")
        self.assertEqual(config.pipeline.max_workers, 4)

    def test_database_initializes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "calmtechrss.sqlite3")
            try:
                db.init()
            finally:
                db.close()

    def test_render_and_feed_validate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            event = make_event()
            rewrite = fallback_rewrite(event)
            output_dir = Path(temp_dir) / "site"
            html_path = render_issue(output_dir, "2026-04-28", [(event, rewrite)], "https://example.com")
            feed_path = generate_feed(output_dir, "https://example.com", "2026-04-28")

            self.assertTrue(Path(html_path).exists())
            self.assertTrue(Path(feed_path).exists())
            validate_feed(feed_path)

    def test_clusters_json_exports_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            event = make_event()
            path = write_clusters_json(temp_dir, "2026-04-28", [event])
            payload = json.loads(Path(path).read_text(encoding="utf-8"))

            self.assertEqual(payload["issue_date"], "2026-04-28")
            self.assertEqual(payload["event_count"], 1)
            self.assertEqual(payload["events"][0]["event_hash"], "e1")
            self.assertEqual(payload["events"][0]["titles"], ["AI tooling update"])

    def test_incremental_cluster_assigns_to_existing_event(self) -> None:
        existing_article = make_event().articles[0]
        initial = incremental_cluster_articles([existing_article], [], embedding_model="hashing")
        new_article = Article(
            title="AI tooling update",
            url="https://example.com/b",
            source_name="Example 2",
            source_category="media",
            published_at_utc=datetime.now(timezone.utc),
            summary="A concise update about AI tooling.",
            content="",
            source_article_id="b",
            url_hash="h2",
            content_hash="c2",
            source_weight=1.0,
        )

        updated = incremental_cluster_articles(
            [new_article],
            [
                ExistingCluster(
                    event_hash=initial[0].event_hash,
                    articles=initial[0].articles,
                    centroid=initial[0].centroid or [],
                )
            ],
            embedding_model="hashing",
        )

        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0].event_hash, initial[0].event_hash)
        self.assertEqual({article.url_hash for article in updated[0].articles}, {"h1", "h2"})


if __name__ == "__main__":
    unittest.main()
