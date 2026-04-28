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

