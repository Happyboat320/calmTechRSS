from __future__ import annotations

import argparse
import logging
import os

from .db import Database
from .env import load_env
from .rss import validate_feed


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="calmtechrss")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    add_common(run_parser)
    run_parser.add_argument("--date", dest="issue_date")
    run_parser.add_argument("--candidate-hours", type=int, default=24)

    init_parser = subparsers.add_parser("init-db")
    init_parser.add_argument("--db", default=os.getenv("DATABASE_PATH", "data/calmtechrss.sqlite3"))

    validate_parser = subparsers.add_parser("validate-feed")
    validate_parser.add_argument("--feed", default=os.path.join(os.getenv("OUTPUT_DIR", "site"), "feed.xml"))

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")

    if args.command == "run":
        from .pipeline import run_pipeline

        run_pipeline(
            sources_path=args.sources,
            api_config_path=args.api_config,
            db_path=args.db,
            output_dir=args.output,
            site_base_url=args.site_base_url,
            issue_date=args.issue_date,
            candidate_hours=args.candidate_hours,
        )
    elif args.command == "init-db":
        db = Database(args.db)
        try:
            db.init()
        finally:
            db.close()
    elif args.command == "validate-feed":
        validate_feed(args.feed)


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sources", default=os.getenv("SOURCES_PATH", "config/sources.yml"))
    parser.add_argument("--api-config", default=os.getenv("API_CONFIG_PATH", "config/api.yml"))
    parser.add_argument("--db", default=os.getenv("DATABASE_PATH", "data/calmtechrss.sqlite3"))
    parser.add_argument("--output", default=os.getenv("OUTPUT_DIR", "site"))
    parser.add_argument("--site-base-url", default=os.getenv("SITE_BASE_URL", "https://example.com"))
