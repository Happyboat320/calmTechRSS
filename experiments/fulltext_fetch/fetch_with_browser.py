from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from fetch_fulltext import extract_with_parser, extract_with_trafilatura, normalize


def find_browser() -> str:
    for name in ("google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("No Chrome/Chromium executable found")


def fetch_dom_with_chrome(url: str, timeout: float = 45.0) -> str:
    browser = find_browser()
    with tempfile.TemporaryDirectory() as profile_dir:
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-dev-shm-usage",
            "--user-data-dir=" + profile_dir,
            "--dump-dom",
            url,
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    if completed.returncode != 0:
        stderr = normalize(completed.stderr)
        raise RuntimeError(f"browser exited with {completed.returncode}: {stderr[:500]}")
    return completed.stdout


def extract_from_browser(url: str, timeout: float = 45.0) -> dict[str, Any]:
    html = fetch_dom_with_chrome(url, timeout=timeout)
    extracted = extract_with_trafilatura(html, url)
    if extracted is None:
        title, text = extract_with_parser(html)
        extractor = "browser+html.parser"
    else:
        title, text = extracted
        extractor = "browser+trafilatura"
    return {
        "url": url,
        "title": title,
        "text": text,
        "text_length": len(text),
        "extractor": extractor,
        "html_length": len(html),
        "looks_blocked": looks_blocked(html, text),
    }


def looks_blocked(html: str, text: str) -> bool:
    lowered = (html[:20000] + "\n" + text[:2000]).lower()
    markers = [
        "forbidden",
        "access denied",
        "cf-challenge",
        "enable javascript",
        "verify you are human",
        "captcha",
    ]
    return any(marker in lowered for marker in markers)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-text", type=int, default=4000)
    parser.add_argument("--save-html")
    args = parser.parse_args()

    try:
        html = fetch_dom_with_chrome(args.url, timeout=args.timeout)
        if args.save_html:
            Path(args.save_html).write_text(html, encoding="utf-8")
        extracted = extract_with_trafilatura(html, args.url)
        if extracted is None:
            title, text = extract_with_parser(html)
            extractor = "browser+html.parser"
        else:
            title, text = extracted
            extractor = "browser+trafilatura"
        result = {
            "url": args.url,
            "title": title,
            "text": text[: args.max_text] if args.max_text >= 0 else text,
            "text_length": len(text),
            "extractor": extractor,
            "html_length": len(html),
            "looks_blocked": looks_blocked(html, text),
        }
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"url": args.url, "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

