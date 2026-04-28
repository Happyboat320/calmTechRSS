from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import urlsplit, urlunsplit


CLICKBAIT_WORDS = [
    "震惊",
    "重磅",
    "炸裂",
    "颠覆",
    "疯狂",
    "杀疯了",
    "史诗级",
    "革命性",
    "划时代",
]


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return normalize_whitespace(value)


def normalize_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clean_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, ""))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value or ""))


def remove_clickbait(value: str) -> str:
    result = value
    for word in CLICKBAIT_WORDS:
        result = result.replace(word, "")
    return normalize_whitespace(result)


def truncate(value: str, limit: int) -> str:
    value = normalize_whitespace(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"

