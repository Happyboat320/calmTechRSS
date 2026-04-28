# Calm Tech RSS

Calm Tech RSS 会从可信科技 RSS / Atom 源抓取内容，去重、聚类并筛选 3-5 条值得关注的事件，生成克制、客观的中文科技日报，同时发布静态 HTML 和每天只新增一个条目的 RSS Feed。

系统按可重复运行设计：文章 URL、翻译结果、事件重写和每日简报都会缓存在 SQLite 中，重复执行不会重复入库，也会尽量避免重复调用 LLM。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -m calmtechrss run --date 2026-04-28
```

输出位置：

- `site/issues/YYYY-MM-DD.html`
- `site/feed.xml`
- `data/calmtechrss.sqlite3`

## 配置文件

RSS 源配置在 `config/sources.yml`：

```yaml
sources:
  - name: OpenAI Blog
    url: https://openai.com/news/rss.xml
    type: rss
    category: official
    active: true
    weight: 1.5
```

API、聊天模型和向量模型配置在 `config/api.yml`。仓库只提交 `config/api.example.yml` 模板，真实 `config/api.yml` 会被 Git 忽略：

```yaml
llm:
  enabled: true
  base_url: https://api.openai.com/v1
  api_key_env: OPENAI_API_KEY
  api_key: ""
  model: gpt-4.1-mini
  temperature: 0.2
  timeout_seconds: 60

embedding:
  model: intfloat/multilingual-e5-small
  device: cpu
  batch_size: 32
  cpu_threads: 4

pipeline:
  max_workers: 4
```

建议把密钥放在 `.env` 或运行环境中，不要直接写入仓库：

```bash
OPENAI_API_KEY=你的密钥
```

如果没有配置 API key，程序会使用本地降级摘要，完整生成流程仍然可以运行。`sentence-transformers` 或模型不可用时，语义聚类会回退到确定性的本地哈希向量。GitHub Actions 环境默认按 CPU 运行 `intfloat/multilingual-e5-small`，并发抓取数默认是 4。

## 常用命令

```bash
python3 -m calmtechrss run
python3 -m calmtechrss init-db
python3 -m calmtechrss validate-feed
```

常用参数：

- `--sources config/sources.yml`
- `--api-config config/api.yml`
- `--db data/calmtechrss.sqlite3`
- `--output site`
- `--site-base-url https://example.com`
- `--date YYYY-MM-DD`
- `--candidate-hours 24`

## 可选向量依赖

如果希望使用 `intfloat/multilingual-e5-small` 做语义聚类，需要安装可选依赖：

```bash
pip install ".[embeddings]"
```

不安装也可以运行，只是会使用轻量级哈希向量作为降级方案。

## 部署

仓库包含 GitHub Actions 工作流，会每天运行一次生成任务，并把 `site/` 作为 GitHub Pages artifact 上传。Actions 会安装 CPU 版 Torch 和 `sentence-transformers`，使用 `config/api.example.yml` 中的 `device: cpu`、`cpu_threads: 4` 和 `max_workers: 4`。

部署前至少需要设置：

- `OPENAI_API_KEY`：可选，不设置时使用本地降级摘要
- `SITE_BASE_URL`：建议设置为实际站点地址，否则 RSS 链接会指向默认示例地址

如果需要更换 API 服务商、模型或向量模型，修改 `config/api.yml` 即可。
