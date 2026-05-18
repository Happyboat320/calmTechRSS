from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .models import Event, Rewrite


def render_issue(
    output_dir: str | Path,
    issue_date: str,
    selected: list[tuple[Event, Rewrite]],
    site_base_url: str,
    original_links: dict[str, str] | None = None,
    log_url: str = "",
) -> str:
    output = Path(output_dir)
    issues_dir = output / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=PackageLoader("calmtechrss", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("issue.html.j2")
    html = template.render(
        issue_date=issue_date,
        events=selected,
        generated_at=datetime.now(timezone.utc),
        site_base_url=site_base_url.rstrip("/"),
        original_links=original_links or {},
        log_url=log_url,
    )
    path = issues_dir / f"{issue_date}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


def render_original_pages(
    output_dir: str | Path,
    issue_date: str,
    selected: list[tuple[Event, Rewrite]],
    site_base_url: str,
) -> dict[str, str]:
    output = Path(output_dir)
    issues_dir = output / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)
    base = site_base_url.rstrip("/")
    links: dict[str, str] = {}
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for event, rewrite in selected:
        slug = f"{issue_date}-{event.event_hash[:8]}"
        page_dir = issues_dir / slug
        page_dir.mkdir(parents=True, exist_ok=True)
        links[event.event_hash] = f"{base}/issues/{slug}"
        article_html = []
        for article in event.articles:
            content = article.content or article.summary
            article_html.append(
                f"""
                <article>
                  <h2>{escape(article.title)}</h2>
                  <p class="meta"><a href="{escape(article.url, quote=True)}">{escape(article.source_name)} 原始链接</a></p>
                  <p>{escape(article.summary)}</p>
                  <p class="body">{escape(content)}</p>
                </article>
                """
            )
        html = base_page(
            title=f"{issue_date} 原文 - {rewrite.title}",
            body=f"""
            <header>
              <h1>{escape(rewrite.title)}</h1>
              <p class="meta">原文归档。生成时间：{generated_at}</p>
              <p><a href="{base}/issues/{issue_date}.html">返回当日简报</a></p>
            </header>
            {''.join(article_html)}
            """,
        )
        (page_dir / "index.html").write_text(html, encoding="utf-8")
    return links


def render_cluster_log(
    output_dir: str | Path,
    issue_date: str,
    events: list[Event],
    changed_events: list[Event],
    selected_events: list[Event],
    site_base_url: str,
    stats: dict[str, int | str],
) -> str:
    output = Path(output_dir)
    slug = f"{issue_date}-log"
    page_dir = output / "issues" / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    base = site_base_url.rstrip("/")
    changed_hashes = {event.event_hash for event in changed_events}
    selected_hashes = {event.event_hash for event in selected_events}
    rows = []
    for event in events:
        labels = []
        if event.event_hash in selected_hashes:
            labels.append("selected")
        if event.is_new:
            labels.append("new")
        elif event.event_hash in changed_hashes:
            labels.append("existing")
        articles = "".join(
            f'<li><a href="{escape(article.url, quote=True)}">{escape(article.title)}</a> '
            f'<span class="meta">{escape(article.source_name)}</span></li>'
            for article in event.articles
        )
        rows.append(
            f"""
            <section>
              <h2>{escape(event.event_hash[:12])} {' '.join(labels)}</h2>
              <p class="meta">score={event.score:.3f}; articles={len(event.articles)}</p>
              <ul>{articles}</ul>
            </section>
            """
        )
    stat_items = "".join(
        f"<li>{escape(str(key))}: {escape(str(value))}</li>" for key, value in stats.items()
    )
    html = base_page(
        title=f"{issue_date} 聚类日志",
        body=f"""
        <header>
          <h1>{issue_date} 聚类日志</h1>
          <p class="meta">本页记录本次运行中的聚类、入选和基础统计。</p>
          <p><a href="{base}/issues/{issue_date}.html">返回当日简报</a></p>
        </header>
        <section>
          <h2>运行统计</h2>
          <ul>{stat_items}</ul>
        </section>
        {''.join(rows)}
        """,
    )
    (page_dir / "index.html").write_text(html, encoding="utf-8")
    return f"{base}/issues/{slug}"


def prune_issue_pages(output_dir: str | Path, keep: int = 5) -> None:
    issues_dir = Path(output_dir) / "issues"
    if not issues_dir.exists():
        return
    pages = sorted(issues_dir.glob("????-??-??-*.html"), key=lambda path: path.stem, reverse=True)
    for page in pages[keep:]:
        page.unlink(missing_ok=True)
    dirs = [
        path
        for path in issues_dir.glob("????-??-??-*")
        if path.is_dir() and not path.name.endswith("-log")
    ]
    keep_dates = sorted({path.name[:10] for path in dirs}, reverse=True)[:keep]
    for path in dirs:
        if path.name[:10] not in keep_dates:
            remove_tree(path)


def render_index(output_dir: str | Path, issue_date: str, site_base_url: str) -> str:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = site_base_url.rstrip("/")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Calm Tech RSS</title>
  <link rel="alternate" type="application/rss+xml" title="Calm Tech RSS" href="{base}/feed.xml">
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.65;
      color: #202124;
      background: #f7f7f4;
    }}
    main {{
      max-width: 720px;
      margin: 0 auto;
      padding: 56px 20px;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 2rem;
      letter-spacing: 0;
    }}
    a {{
      color: #225ea8;
      text-underline-offset: 3px;
    }}
    .links {{
      display: flex;
      gap: 18px;
      flex-wrap: wrap;
      margin-top: 24px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Calm Tech RSS</h1>
    <p>平静、客观、克制的中文科技日报。</p>
    <div class="links">
      <a href="{base}/issues/{issue_date}.html">最新简报</a>
      <a href="{base}/feed.xml">RSS Feed</a>
    </div>
  </main>
</body>
</html>
"""
    path = output / "index.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


def base_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #202124;
      background: #f7f7f4;
    }}
    body {{ margin: 0; line-height: 1.65; }}
    main {{ max-width: 900px; margin: 0 auto; padding: 48px 20px 72px; }}
    header {{ border-bottom: 1px solid #d8d8d2; margin-bottom: 32px; padding-bottom: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 2rem; font-weight: 650; letter-spacing: 0; }}
    h2 {{ margin: 0 0 10px; font-size: 1.2rem; line-height: 1.35; letter-spacing: 0; }}
    article, section {{ padding: 20px 0; border-bottom: 1px solid #e1e1dc; }}
    p {{ margin: 0 0 14px; }}
    ul {{ margin: 8px 0 0; padding-left: 20px; }}
    a {{ color: #225ea8; text-decoration-thickness: 1px; text-underline-offset: 3px; }}
    .meta {{ color: #64645f; font-size: 0.95rem; }}
    .body {{ white-space: pre-wrap; color: #3f4245; }}
  </style>
</head>
<body>
  <main>{body}</main>
</body>
</html>
"""


def remove_tree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            remove_tree(child)
        else:
            child.unlink(missing_ok=True)
    path.rmdir()
