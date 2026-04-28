from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Article, Event, Rewrite, Source


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sources (
  name TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  type TEXT NOT NULL,
  category TEXT NOT NULL,
  active INTEGER NOT NULL,
  weight REAL NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_category TEXT NOT NULL,
  published_at_utc TEXT NOT NULL,
  summary TEXT NOT NULL,
  content TEXT NOT NULL,
  source_article_id TEXT NOT NULL,
  url_hash TEXT NOT NULL UNIQUE,
  content_hash TEXT NOT NULL,
  source_weight REAL NOT NULL DEFAULT 1.0,
  created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_translations (
  article_id INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  translated_title TEXT NOT NULL,
  translated_summary TEXT NOT NULL,
  translated_content TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  PRIMARY KEY (article_id, content_hash, model)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_hash TEXT NOT NULL UNIQUE,
  article_hashes_json TEXT NOT NULL,
  score REAL NOT NULL,
  created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_rewrites (
  event_hash TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  model TEXT NOT NULL,
  rewrite_json TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  PRIMARY KEY (event_hash, prompt_version, model)
);

CREATE TABLE IF NOT EXISTS issues (
  issue_date TEXT PRIMARY KEY,
  event_hashes_json TEXT NOT NULL,
  html_path TEXT NOT NULL,
  created_at_utc TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def init(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_sources(self, sources: list[Source]) -> None:
        self.conn.executemany(
            """
            INSERT INTO sources (name, url, type, category, active, weight, updated_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              url=excluded.url,
              type=excluded.type,
              category=excluded.category,
              active=excluded.active,
              weight=excluded.weight,
              updated_at_utc=excluded.updated_at_utc
            """,
            [
                (s.name, s.url, s.type, s.category, int(s.active), s.weight, utc_now())
                for s in sources
            ],
        )
        self.conn.commit()

    def upsert_articles(self, articles: list[Article]) -> list[Article]:
        saved: list[Article] = []
        for article in articles:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO articles (
                  title, url, source_name, source_category, published_at_utc, summary,
                  content, source_article_id, url_hash, content_hash, source_weight, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article.title,
                    article.url,
                    article.source_name,
                    article.source_category,
                    article.published_at_utc.isoformat(),
                    article.summary,
                    article.content,
                    article.source_article_id,
                    article.url_hash,
                    article.content_hash,
                    article.source_weight,
                    utc_now(),
                ),
            )
            row = self.conn.execute(
                "SELECT id FROM articles WHERE url_hash = ?", (article.url_hash,)
            ).fetchone()
            article.id = int(row["id"])
            saved.append(article)
        self.conn.commit()
        return saved

    def get_articles_since(self, since_utc: datetime) -> list[Article]:
        rows = self.conn.execute(
            """
            SELECT * FROM articles
            WHERE published_at_utc >= ?
            ORDER BY published_at_utc DESC
            """,
            (since_utc.isoformat(),),
        ).fetchall()
        return [row_to_article(row) for row in rows]

    def get_translation(self, article: Article, model: str) -> tuple[str, str, str] | None:
        if article.id is None:
            return None
        row = self.conn.execute(
            """
            SELECT translated_title, translated_summary, translated_content
            FROM article_translations
            WHERE article_id = ? AND content_hash = ? AND model = ?
            """,
            (article.id, article.content_hash, model),
        ).fetchone()
        if row:
            return row["translated_title"], row["translated_summary"], row["translated_content"]
        return None

    def save_translation(self, article: Article, model: str, values: tuple[str, str, str]) -> None:
        if article.id is None:
            return
        self.conn.execute(
            """
            INSERT OR IGNORE INTO article_translations (
              article_id, content_hash, model, translated_title, translated_summary,
              translated_content, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (article.id, article.content_hash, model, values[0], values[1], values[2], utc_now()),
        )
        self.conn.commit()

    def upsert_events(self, events: list[Event]) -> None:
        for event in events:
            hashes = sorted(a.url_hash for a in event.articles)
            self.conn.execute(
                """
                INSERT INTO events (event_hash, article_hashes_json, score, created_at_utc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(event_hash) DO UPDATE SET
                  article_hashes_json=excluded.article_hashes_json,
                  score=excluded.score
                """,
                (event.event_hash, json.dumps(hashes), event.score, utc_now()),
            )
            row = self.conn.execute(
                "SELECT id FROM events WHERE event_hash = ?", (event.event_hash,)
            ).fetchone()
            event.id = int(row["id"])
        self.conn.commit()

    def get_rewrite(self, event_hash: str, prompt_version: str, model: str) -> Rewrite | None:
        row = self.conn.execute(
            """
            SELECT rewrite_json FROM event_rewrites
            WHERE event_hash = ? AND prompt_version = ? AND model = ?
            """,
            (event_hash, prompt_version, model),
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["rewrite_json"])
        return Rewrite(**data)

    def save_rewrite(
        self, event_hash: str, prompt_version: str, model: str, rewrite: Rewrite
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO event_rewrites (
              event_hash, prompt_version, model, rewrite_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_hash,
                prompt_version,
                model,
                json.dumps(rewrite.__dict__, ensure_ascii=False),
                utc_now(),
            ),
        )
        self.conn.commit()

    def save_issue(self, issue_date: str, events: list[Event], html_path: str) -> None:
        self.conn.execute(
            """
            INSERT INTO issues (issue_date, event_hashes_json, html_path, created_at_utc)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(issue_date) DO UPDATE SET
              event_hashes_json=excluded.event_hashes_json,
              html_path=excluded.html_path
            """,
            (
                issue_date,
                json.dumps([event.event_hash for event in events]),
                html_path,
                utc_now(),
            ),
        )
        self.conn.commit()


def row_to_article(row: sqlite3.Row) -> Article:
    return Article(
        id=int(row["id"]),
        title=row["title"],
        url=row["url"],
        source_name=row["source_name"],
        source_category=row["source_category"],
        published_at_utc=datetime.fromisoformat(row["published_at_utc"]),
        summary=row["summary"],
        content=row["content"],
        source_article_id=row["source_article_id"],
        url_hash=row["url_hash"],
        content_hash=row["content_hash"],
        source_weight=float(row["source_weight"]),
    )

