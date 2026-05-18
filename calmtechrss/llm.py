from __future__ import annotations

import json
import logging

from .api_config import LLMSettings
from .models import Article, Event, Rewrite
from .text import remove_clickbait, truncate

LOGGER = logging.getLogger(__name__)
PROMPT_VERSION = "rewrite-v4-precluster-fulltext"


class LLMClient:
    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or LLMSettings()
        self.api_key = self.settings.resolved_api_key
        self.base_url = self.settings.base_url.rstrip("/")
        self.model = self.settings.model

    @property
    def enabled(self) -> bool:
        return self.settings.enabled and bool(self.api_key)

    def pick_event_hashes(self, events: list[Event], limit: int = 5) -> list[str]:
        if not self.enabled or len(events) <= 5:
            return [event.event_hash for event in events[:limit]]
        catalog = []
        for event in events:
            titles = [a.title for a in event.articles]
            catalog.append(
                {
                    "event_hash": event.event_hash,
                    "score": round(event.score, 3),
                    "sources": sorted({a.source_name for a in event.articles}),
                    "titles": titles,
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

    def rank_new_events(self, events: list[Event], limit: int = 5) -> list[str]:
        if not self.enabled or len(events) <= limit:
            return [event.event_hash for event in events[:limit]]
        catalog = []
        for event in events:
            first = event.articles[0]
            catalog.append(
                {
                    "event_hash": event.event_hash,
                    "title": first.title,
                    "summary": truncate(first.summary, 700),
                }
            )
        prompt = (
            "你是克制的科技日报编辑。请只根据候选类第一篇文章的标题和摘要，"
            "选出 5 条对计算机专业工作者最重要的信息，并按重要性从高到低排序。"
            "避免过窄的 patch release、营销稿、重复列表页。"
            "只返回严格 JSON：{\"event_hashes\":[\"...\"]}。\n\n"
            + json.dumps(catalog, ensure_ascii=False)
        )
        try:
            data = self._chat_json(prompt)
            hashes = [str(item) for item in data.get("event_hashes", [])]
            allowed = {event.event_hash for event in events}
            selected = [item for item in hashes if item in allowed]
            if selected:
                return selected[:limit]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("new event ranking failed: %s", exc)
        return [event.event_hash for event in events[:limit]]

    def rewrite_event(self, event: Event) -> Rewrite:
        if not self.enabled:
            return fallback_rewrite(event)
        payload = []
        for article in event.articles:
            payload.append(
                {
                    "source": article.source_name,
                    "url": article.url,
                    "title": article.title,
                    "summary": truncate(article.summary, 900),
                    "content": truncate(article.content, 3000),
                }
            )
        prompt = (
            "基于以下来源，写一条中文科技日报事件。要求：只基于来源内容；不添加外部信息；"
            "语气平静、客观、克制；不要使用夸张词；不确定信息写入 uncertainty。"
            "每个来源包含标题、RSS 摘要和正文；正文可能是抓取到的原文，也可能是 RSS 自带内容。"
            "即使输入包含长原文，也只提炼事件本身，不逐篇复述、不逐段概括、不扩写。"
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
        return fallback_rewrite(event, uncertainty="LLM 重写失败，当前条目使用来源摘要生成。")

    def _chat_json(self, prompt: str) -> dict:
        import httpx

        response = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
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
                break
            except httpx.TimeoutException:
                if attempt >= self.settings.max_retries:
                    raise
                LOGGER.warning(
                    "chat completion timed out; retrying attempt %s/%s",
                    attempt + 1,
                    self.settings.max_retries,
                )
        if response is None:
            raise RuntimeError("chat completion did not return a response")
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)


class EventJudgeClient(LLMClient):
    @property
    def enabled(self) -> bool:
        return self.settings.enabled and bool(self.api_key)

    def same_event(self, article: Article, existing_articles: list[Article]) -> bool:
        if not self.enabled:
            return True
        payload = {
            "new_article": judge_article_payload(article),
            "existing_event": [judge_article_payload(item) for item in existing_articles[:5]],
        }
        prompt = (
            "判断 new_article 和 existing_event 是否在报道同一个具体事件。"
            "同一个事件要求核心主体、动作和时间背景一致；同一公司或同一领域的不同新闻不是同一个事件。"
            "跨中英文标题或摘要表达相同含义时可以判为同一个事件。"
            "只返回严格 JSON：{\"same_event\":true 或 false}。\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        try:
            data = self._chat_json(prompt)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("event judge failed for %s: %s", article.url, exc)
            return False
        return bool(data.get("same_event", False))


def validate_sources(raw: object, event: Event) -> list[dict[str, str]]:
    valid_urls = {article.url: article.source_name for article in event.articles}
    sources: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("url") in valid_urls:
                sources.append({"name": str(item.get("name") or valid_urls[item["url"]]), "url": item["url"]})
    return sources or [{"name": a.source_name, "url": a.url} for a in event.articles[:5]]


def judge_article_payload(article: Article) -> dict[str, str]:
    return {
        "source": article.source_name,
        "title": article.title,
        "summary": truncate(article.summary, 500),
        "content": truncate(article.content, 900),
        "url": article.url,
    }


def fallback_rewrite(
    event: Event,
    uncertainty: str = "未配置 LLM API，当前条目使用来源摘要生成。",
) -> Rewrite:
    articles = sorted(event.articles, key=lambda a: a.source_weight, reverse=True)
    primary = articles[0]
    title = remove_clickbait(primary.title)
    fragments = [
        primary.summary,
        primary.content,
    ]
    summary = truncate(next((item for item in fragments if item), title), 150)
    return Rewrite(
        title=truncate(title, 64),
        summary=remove_clickbait(summary),
        sources=[{"name": a.source_name, "url": a.url} for a in articles[:5]],
        uncertainty=uncertainty,
    )
