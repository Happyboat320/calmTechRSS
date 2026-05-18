from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from calmtechrss.api_config import load_api_config
from calmtechrss.api_config import LLMSettings
from calmtechrss.cluster import ExistingCluster, cluster_text, incremental_cluster_articles, merge_new_articles
from calmtechrss.config import load_sources
from calmtechrss.db import Database
from calmtechrss.export import write_clusters_json
from calmtechrss.fulltext import enrich_articles_with_fulltext
from calmtechrss.llm import EventJudgeClient, LLMClient, fallback_rewrite
from calmtechrss.models import Article, Event
from calmtechrss.render import (
    article_paragraphs,
    render_cluster_log,
    render_index,
    render_issue,
    render_original_pages,
)
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


def json_vector(values: list[float]) -> np.ndarray:
    return np.array(values, dtype=float)


class CoreTest(unittest.TestCase):
    def test_plan_sources_are_configured(self) -> None:
        sources = load_sources("config/sources.yml")
        names = {source.name for source in sources}

        self.assertEqual(len(sources), 14)
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
                "AI Era",
                "量子位",
                "AIBase News",
                "QQ Tech",
            },
        )

    def test_api_config_loads_model_settings(self) -> None:
        config = load_api_config("config/api.yml")

        self.assertEqual(config.llm.api_key_env, "OPENAI_API_KEY")
        self.assertTrue(config.llm.model)
        self.assertEqual(config.embedding.model, "intfloat/multilingual-e5-small")
        self.assertEqual(config.embedding.device, "cpu")
        self.assertEqual(config.pipeline.max_workers, 4)
        self.assertEqual(config.llm.timeout_seconds, 180)
        self.assertEqual(config.llm.max_retries, 5)
        self.assertEqual(config.judge.model, "deepseek-v4-flash")

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
            feed_path = generate_feed(output_dir, "https://example.com", "2026-04-28", selected=[(event, rewrite)])

            self.assertTrue(Path(html_path).exists())
            self.assertTrue(Path(feed_path).exists())
            self.assertIn("AI tooling update", Path(feed_path).read_text(encoding="utf-8"))
            validate_feed(feed_path)

    def test_original_pages_and_cluster_log_render(self) -> None:
        with TemporaryDirectory() as temp_dir:
            event = make_event()
            rewrite = fallback_rewrite(event)
            output_dir = Path(temp_dir) / "site"
            links = render_original_pages(
                output_dir,
                "2026-05-18",
                [(event, rewrite)],
                "https://example.com/calmTechRSS",
            )
            log_url = render_cluster_log(
                output_dir,
                "2026-05-18",
                [event],
                [event],
                [event],
                "https://example.com/calmTechRSS",
                {"new_clusters": 1},
            )
            html_path = render_issue(
                output_dir,
                "2026-05-18",
                [(event, rewrite)],
                "https://example.com/calmTechRSS",
                original_links=links,
                log_url=log_url,
            )
            html = Path(html_path).read_text(encoding="utf-8")

            self.assertIn("https://example.com/calmTechRSS/issues/2026-05-18-e1", links["e1"])
            self.assertTrue((output_dir / "issues" / "2026-05-18-e1" / "index.html").exists())
            self.assertTrue((output_dir / "issues" / "2026-05-18-log" / "index.html").exists())
            self.assertIn("本日原文归档", html)
            self.assertIn("本次聚类日志", html)
            log_html = (output_dir / "issues" / "2026-05-18-log" / "index.html").read_text(
                encoding="utf-8"
            )
            self.assertIn("今日新增", log_html)
            self.assertIn("最终分数", log_html)

    def test_article_paragraphs_formats_flat_text(self) -> None:
        paragraphs = article_paragraphs(
            "第一句话。第二句话。第三句话。"
            + "This is a longer English sentence. Another sentence follows. " * 8
        )

        self.assertGreater(len(paragraphs), 1)

    def test_feed_keeps_multiple_issue_items(self) -> None:
        with TemporaryDirectory() as temp_dir:
            event = make_event()
            rewrite = fallback_rewrite(event)
            output_dir = Path(temp_dir) / "site"
            feed_path = generate_feed(
                output_dir,
                "https://example.com",
                "2026-04-29",
                issues=[
                    ("2026-04-29", [(event, rewrite)]),
                    ("2026-04-28", [(event, rewrite)]),
                ],
            )
            html = Path(feed_path).read_text(encoding="utf-8")

            self.assertIn("2026-04-29 科技简报", html)
            self.assertIn("2026-04-28 科技简报", html)

    def test_index_renders_feed_link(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = render_index(temp_dir, "2026-04-29", "https://example.com/calmTechRSS")
            html = Path(path).read_text(encoding="utf-8")

            self.assertIn("https://example.com/calmTechRSS/feed.xml", html)
            self.assertIn("https://example.com/calmTechRSS/issues/2026-04-29.html", html)

    def test_clusters_json_exports_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            event = make_event()
            path = write_clusters_json(temp_dir, "2026-04-28", [event])
            payload = json.loads(Path(path).read_text(encoding="utf-8"))

            self.assertEqual(payload["issue_date"], "2026-04-28")
            self.assertEqual(payload["event_count"], 1)
            self.assertEqual(payload["events"][0]["event_hash"], "e1")
            self.assertFalse(payload["events"][0]["is_new"])
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
        self.assertFalse(updated[0].is_new)
        self.assertEqual({article.url_hash for article in updated[0].articles}, {"h1", "h2"})

    def test_incremental_cluster_uses_event_judge(self) -> None:
        existing_article = make_event().articles[0]
        initial = incremental_cluster_articles([existing_article], [], embedding_model="hashing")
        new_article = Article(
            title="AI tooling update",
            url="https://example.com/c",
            source_name="Example 3",
            source_category="media",
            published_at_utc=datetime.now(timezone.utc),
            summary="A concise update about AI tooling.",
            content="",
            source_article_id="c",
            url_hash="h3",
            content_hash="c3",
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
            event_judge=lambda article, group: False,
            max_judge_workers=2,
        )

        self.assertEqual(len(updated), 1)
        self.assertTrue(updated[0].is_new)
        self.assertNotEqual(updated[0].event_hash, initial[0].event_hash)

    def test_new_class_merge_requires_all_embedding_models(self) -> None:
        event = make_event()
        left = event.articles[0]
        right = Article(
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

        groups = merge_new_articles(
            [
                (left, {"m1": json_vector([1, 0]), "m2": json_vector([1, 0])}),
                (right, {"m1": json_vector([1, 0]), "m2": json_vector([0, 1])}),
            ],
            threshold=0.8,
        )

        self.assertEqual(len(groups), 2)

    def test_llm_retries_timeout(self) -> None:
        import httpx

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"choices": [{"message": {"content": "{\"ok\": true}"}}]}

        calls = {"count": 0}

        def fake_post(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] < 3:
                raise httpx.TimeoutException("timeout")
            return Response()

        client = LLMClient(
            LLMSettings(api_key="test", timeout_seconds=180, max_retries=5)
        )
        with patch("httpx.post", side_effect=fake_post):
            self.assertEqual(client._chat_json("test"), {"ok": True})

        self.assertEqual(calls["count"], 3)

    def test_event_judge_returns_model_decision(self) -> None:
        class CapturingJudge(EventJudgeClient):
            def __init__(self) -> None:
                super().__init__(LLMSettings(api_key="test", model="deepseek-v4-flash"))
                self.prompt = ""

            def _chat_json(self, prompt: str) -> dict:
                self.prompt = prompt
                return {"same_event": True}

        judge = CapturingJudge()
        self.assertTrue(judge.same_event(make_event().articles[0], make_event().articles))
        self.assertIn("同一个具体事件", judge.prompt)

    def test_fulltext_enrichment_updates_content_before_clustering(self) -> None:
        class Response:
            headers = {"content-type": "text/html; charset=utf-8"}
            text = "<html><article><p>" + ("Full article body. " * 80) + "</p></article></html>"
            url = "https://example.com/a"

            def raise_for_status(self) -> None:
                return None

        event = make_event()
        article = event.articles[0]
        with patch("httpx.get", return_value=Response()):
            enrich_articles_with_fulltext([article], max_workers=1)

        self.assertIn("Full article body", article.content)
        self.assertNotEqual(article.content_hash, "c1")
        self.assertIn("Full article body", cluster_text(article))

    def test_rewrite_uses_event_article_content(self) -> None:
        class CapturingClient(LLMClient):
            def __init__(self) -> None:
                super().__init__(LLMSettings(api_key="test"))
                self.prompt = ""

            def _chat_json(self, prompt: str) -> dict:
                self.prompt = prompt
                return {
                    "title": "AI 工具更新",
                    "summary": "一个主要 AI 工具发布了面向开发者的更新，重点是改进工作流集成和日常使用体验。",
                    "sources": [{"name": "Example", "url": "https://example.com/a"}],
                    "uncertainty": "",
                }

        event = make_event()
        event.articles[0].content = "Full article body " * 300
        client = CapturingClient()
        rewrite = client.rewrite_event(event)

        self.assertEqual(rewrite.title, "AI 工具更新")
        self.assertIn('"content": "Full article body', client.prompt)
        self.assertIn("summary 80-150 字", client.prompt)
        self.assertIn("不逐篇复述、不逐段概括、不扩写", client.prompt)

    def test_fulltext_enrichment_keeps_feed_content_on_failure(self) -> None:
        event = make_event()
        with patch("httpx.get", side_effect=Exception("network blocked")):
            enrich_articles_with_fulltext(event.articles, max_workers=1)

        self.assertEqual(event.articles[0].content, "")
        self.assertEqual(event.articles[0].summary, "A concise update about AI tooling.")


if __name__ == "__main__":
    unittest.main()
