from __future__ import annotations

import json
import logging

from .api_config import LLMSettings
from .models import Article, Event, Rewrite
from .text import has_cjk, remove_clickbait, truncate

LOGGER = logging.getLogger(__name__)
PROMPT_VERSION = "rewrite-v1"


class LLMClient:
    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or LLMSettings()
        self.api_key = self.settings.resolved_api_key
        self.base_url = self.settings.base_url.rstrip("/")
        self.model = self.settings.model

    @property
    def enabled(self) -> bool:
        return self.settings.enabled and bool(self.api_key)

    def translate_article(self, article: Article) -> tuple[str, str, str]:
        if not self.enabled or has_cjk(article.title + article.summary + article.content):
            return article.title, article.summary, article.content
        prompt = (
            "Translate the following RSS article fields into concise Chinese. "
            "Keep product names and links unchanged. Return strict JSON with keys "
            "title, summary, content.\n\n"
            f"Title: {article.title}\nSummary: {article.summary}\nContent: {truncate(article.content, 1800)}"
        )
        try:
            data = self._chat_json(prompt)
            return (
                str(data.get("title") or article.title),
                str(data.get("summary") or article.summary),
                str(data.get("content") or article.content),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("translation failed for %s: %s", article.url, exc)
            return article.title, article.summary, article.content

    def pick_event_hashes(self, events: list[Event], limit: int = 5) -> list[str]:
        if not self.enabled or len(events) <= 5:
            return [event.event_hash for event in events[:limit]]
        catalog = []
        for event in events[:30]:
            titles = [a.translated_title or a.title for a in event.articles]
            catalog.append(
                {
                    "event_hash": event.event_hash,
                    "score": round(event.score, 3),
                    "sources": sorted({a.source_name for a in event.articles}),
                    "titles": titles[:5],
                }
            )
        prompt = (
            "你是克制的科技日报编辑。请从候选事件中选出 3-5 条值得计算机专业工作者了解、"
            "且不过于细分领域的事件。避免 patch release、营销稿、重复列表页。"
            "只返回严格 JSON：{\"event_hashes\":[\"...\"]}。\n\n"
            + json.dumps(catalog, ensure_ascii=False)
        )
        try:
            data = self._chat_json(prompt)
            hashes = [str(x) for x in data.get("event_hashes", [])]
            allowed = {event.event_hash for event in events}
            selected = [item for item in hashes if item in allowed]
            if 3 <= len(selected) <= 5:
                return selected
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("event selection failed: %s", exc)
        return [event.event_hash for event in events[:limit]]

    def rewrite_event(self, event: Event) -> Rewrite:
        if not self.enabled:
            return fallback_rewrite(event)
        payload = []
        for article in event.articles[:8]:
            payload.append(
                {
                    "source": article.source_name,
                    "url": article.url,
                    "title": article.translated_title or article.title,
                    "summary": truncate(article.translated_summary or article.summary, 700),
                    "content": truncate(article.translated_content or article.content, 1200),
                }
            )
        prompt = (
            "基于以下来源，写一条中文科技日报事件。要求：只基于来源内容；不添加外部信息；"
            "语气平静、客观、克制；不要使用夸张词；不确定信息写入 uncertainty。"
            "返回严格 JSON，字段为 title、summary、sources、uncertainty。summary 80-150 字。"
            "\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        try:
            data = self._chat_json(prompt)
            rewrite = Rewrite(
                title=remove_clickbait(str(data["title"])),
                summary=remove_clickbait(str(data["summary"])),
                sources=validate_sources(data.get("sources"), event),
                uncertainty=str(data.get("uncertainty", "")),
            )
            if rewrite.title and rewrite.summary:
                return rewrite
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("rewrite failed for %s: %s", event.event_hash, exc)
        return fallback_rewrite(event)

    def _chat_json(self, prompt: str) -> dict:
        import httpx

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.settings.temperature,
                "response_format": {"type": "json_object"},
            },
            timeout=self.settings.timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)


def validate_sources(raw: object, event: Event) -> list[dict[str, str]]:
    valid_urls = {article.url: article.source_name for article in event.articles}
    sources: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("url") in valid_urls:
                sources.append({"name": str(item.get("name") or valid_urls[item["url"]]), "url": item["url"]})
    return sources or [{"name": a.source_name, "url": a.url} for a in event.articles[:5]]


def fallback_rewrite(event: Event) -> Rewrite:
    articles = sorted(event.articles, key=lambda a: a.source_weight, reverse=True)
    primary = articles[0]
    title = remove_clickbait(primary.translated_title or primary.title)
    fragments = [
        primary.translated_summary or primary.summary,
        primary.translated_content or primary.content,
    ]
    summary = truncate(next((item for item in fragments if item), title), 150)
    return Rewrite(
        title=truncate(title, 64),
        summary=remove_clickbait(summary),
        sources=[{"name": a.source_name, "url": a.url} for a in articles[:5]],
        uncertainty="未配置 LLM API，当前条目使用来源摘要生成。",
    )
