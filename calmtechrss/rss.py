from __future__ import annotations

from datetime import datetime, time, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET


def generate_feed(
    output_dir: str | Path,
    site_base_url: str,
    issue_date: str,
    title: str = "Calm Tech RSS",
    description: str = "平静、客观、克制的中文科技日报。",
) -> str:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = site_base_url.rstrip("/")
    issue_url = f"{base}/issues/{issue_date}.html"
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = base
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = "zh-CN"
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"{issue_date} 科技简报"
    ET.SubElement(item, "link").text = issue_url
    ET.SubElement(item, "guid").text = issue_url
    pub_dt = datetime.combine(datetime.fromisoformat(issue_date).date(), time(8, 0), timezone.utc)
    ET.SubElement(item, "pubDate").text = format_datetime(pub_dt, usegmt=True)
    ET.SubElement(item, "description").text = "今日科技简报，包括 AI、研究、开源和开发者工具动态。"
    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    path = output / "feed.xml"
    tree.write(path, encoding="utf-8", xml_declaration=True)
    ET.parse(path)
    return str(path)


def validate_feed(path: str | Path) -> None:
    root = ET.parse(path).getroot()
    if root.tag != "rss":
        raise ValueError("feed root is not rss")
    channel = root.find("channel")
    if channel is None or channel.find("item") is None:
        raise ValueError("feed has no channel item")

