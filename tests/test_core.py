from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from calmtechrss.api_config import load_api_config
from calmtechrss.db import Database
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
    def test_api_config_loads_model_settings(self) -> None:
        config = load_api_config("config/api.yml")

        self.assertEqual(config.llm.api_key_env, "OPENAI_API_KEY")
        self.assertTrue(config.llm.model)
        self.assertTrue(config.embedding.model)

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


if __name__ == "__main__":
    unittest.main()
