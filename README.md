# Calm Tech RSS

Calm Tech RSS fetches trusted technology RSS/Atom sources, deduplicates and clusters related articles, selects 3-5 worthwhile events, rewrites them into a restrained Chinese daily digest, and publishes static HTML plus a one-item-per-day RSS feed.

The pipeline is designed to be repeatable. Article URLs, translations, event rewrites, and daily issues are cached in SQLite so reruns do not duplicate content or API calls.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m calmtechrss run --date 2026-04-28
```

Outputs are written to:

- `site/issues/YYYY-MM-DD.html`
- `site/feed.xml`
- `data/calmtechrss.sqlite3`

For LLM rewriting, set `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`. Without an API key, the app uses deterministic local summaries so the full publishing flow still works.

For semantic embeddings, install the optional package:

```bash
pip install ".[embeddings]"
```

Without `sentence-transformers`, deterministic hashing vectors are used as a lightweight fallback.

## Commands

```bash
python -m calmtechrss run
python -m calmtechrss init-db
python -m calmtechrss validate-feed
```

Useful options:

- `--sources config/sources.yml`
- `--db data/calmtechrss.sqlite3`
- `--output site`
- `--site-base-url https://example.com`
- `--date YYYY-MM-DD`
- `--candidate-hours 48`

## Deployment

The included GitHub Actions workflow runs the digest daily and uploads the generated `site/` directory as a Pages artifact. Set repository secrets for LLM use if needed:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `SITE_BASE_URL`

