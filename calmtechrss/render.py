from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .models import Event, Rewrite


def render_issue(
    output_dir: str | Path,
    issue_date: str,
    selected: list[tuple[Event, Rewrite]],
    site_base_url: str,
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
    )
    path = issues_dir / f"{issue_date}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


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
