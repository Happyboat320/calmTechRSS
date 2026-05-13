from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from html.parser import HTMLParser
from typing import Any

import httpx


USER_AGENT = "CalmTechRSS-FulltextExperiment/0.1"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_stack: list[str] = []
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}:
            self.skip_stack.append(tag)
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_stack and self.skip_stack[-1] == tag:
            self.skip_stack.pop()
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        data = normalize(data)
        if not data:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.skip_stack:
            return
        if len(data) >= 20:
            self.text_parts.append(data)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def extract_with_trafilatura(html: str, url: str) -> tuple[str, str] | None:
    try:
        import trafilatura
    except ModuleNotFoundError:
        return None
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False)
    if not text:
        return None
    return "", normalize(text)


def extract_with_parser(html: str) -> tuple[str, str]:
    parser = TextExtractor()
    parser.feed(html)
    title = normalize(" ".join(parser.title_parts))
    text = normalize("\n".join(parser.text_parts))
    return title, text


def fetch_fulltext(url: str, timeout: float = 30.0) -> dict[str, Any]:
    response = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=timeout,
    )
    response.raise_for_status()
    html = response.text
    extracted = extract_with_trafilatura(html, str(response.url))
    if extracted is None:
        title, text = extract_with_parser(html)
        extractor = "html.parser"
    else:
        title, text = extracted
        extractor = "trafilatura"
    return {
        "url": str(response.url),
        "status_code": response.status_code,
        "title": title,
        "text": text,
        "text_length": len(text),
        "extractor": extractor,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-text", type=int, default=4000)
    args = parser.parse_args()

    try:
        result = fetch_fulltext(args.url, timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"url": args.url, "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    if args.max_text >= 0:
        result["text"] = result["text"][: args.max_text]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

