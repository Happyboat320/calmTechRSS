from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    type: str
    category: str
    active: bool = True
    weight: float = 1.0


@dataclass
class Article:
    title: str
    url: str
    source_name: str
    source_category: str
    published_at_utc: datetime
    summary: str
    content: str
    source_article_id: str
    url_hash: str
    content_hash: str
    source_weight: float = 1.0
    id: int | None = None
    translated_title: str | None = None
    translated_summary: str | None = None
    translated_content: str | None = None


@dataclass
class Event:
    event_hash: str
    articles: list[Article]
    score: float = 0.0
    id: int | None = None
    centroid: list[float] | None = None


@dataclass
class Rewrite:
    title: str
    summary: str
    sources: list[dict[str, str]]
    uncertainty: str = ""


@dataclass
class Issue:
    issue_date: str
    events: list[tuple[Event, Rewrite]] = field(default_factory=list)
    html_path: str = ""
