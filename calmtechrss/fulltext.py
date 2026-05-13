from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from html.parser import HTMLParser

import httpx

from .models import Article
from .text import sha256_text

LOGGER = logging.getLogger(__name__)

USER_AGENT = "CalmTechRSS/0.1 (+https://github.com/)"
MIN_FULLTEXT_LENGTH = 500


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_stack: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}:
            self.skip_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_stack and self.skip_stack[-1] == tag:
            self.skip_stack.pop()

    def handle_data(self, data: str) -> None:
        if self.skip_stack:
            return
        data = normalize(data)
        if len(data) >= 20:
            self.text_parts.append(data)


def enrich_articles_with_fulltext(
    articles: list[Article],
    max_workers: int = 4,
    timeout: float = 12.0,
) -> list[Article]:
    if not articles:
        return articles
    workers = max(1, min(max_workers, len(articles)))
    enriched = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_article = {
            executor.submit(fetch_article_fulltext, article.url, timeout): article
            for article in articles
        }
        for future in as_completed(future_to_article):
            article = future_to_article[future]
            fulltext = future.result()
            if not fulltext:
                continue
            article.content = fulltext
            article.content_hash = sha256_text("\n".join([article.title, article.summary, article.content]))
            enriched += 1
    LOGGER.info("fulltext_enriched=%s total=%s", enriched, len(articles))
    return articles


def fetch_article_fulltext(url: str, timeout: float = 12.0) -> str:
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=timeout,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("fulltext fetch failed for %s: %s", url, exc)
        return ""

    content_type = response.headers.get("content-type", "")
    if content_type and "html" not in content_type.lower():
        return ""

    html = response.text
    if looks_blocked(html):
        return ""

    text = extract_text(html, str(response.url))
    if len(text) < MIN_FULLTEXT_LENGTH or looks_blocked(text):
        return ""
    return text


def extract_text(html: str, url: str) -> str:
    extracted = extract_with_trafilatura(html, url)
    if extracted:
        return extracted
    parser = TextExtractor()
    parser.feed(html)
    return normalize("\n".join(parser.text_parts))


def extract_with_trafilatura(html: str, url: str) -> str:
    try:
        import trafilatura
    except ModuleNotFoundError:
        return ""
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False)
    return normalize(text or "")


def looks_blocked(text: str) -> bool:
    lowered = text[:20000].lower()
    markers = [
        "403 forbidden",
        "access denied",
        "cf-challenge",
        "enable javascript",
        "verify you are human",
        "captcha",
    ]
    return any(marker in lowered for marker in markers)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()
