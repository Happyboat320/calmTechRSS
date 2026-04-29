# Calm Tech RSS

Calm Tech RSS 会从可信科技 RSS / Atom 源抓取内容，去重、聚类并筛选 3-5 条值得关注的事件，生成克制、客观的中文科技日报，同时发布静态 HTML 和每天只新增一个条目的 RSS Feed。

系统按可重复运行设计：文章 URL、事件重写和每日简报都会缓存在 SQLite 中，重复执行不会重复入库，也会尽量避免重复调用 LLM。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -m calmtechrss run --date 2026-04-28
```

输出位置：

- `site/index.html`
- `site/issues/YYYY-MM-DD.html`
- `site/feed.xml`
- `site/clusters/YYYY-MM-DD.json`
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
  timeout_seconds: 180

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

## LLM 调用流程

主流程不会逐篇翻译文章。LLM 只在两类任务中调用：

- 事件选择：把所有聚类后的事件及其全部标题传给模型，要求返回 3-5 个 `event_hash`。
- 事件重写：只对选中的 3-5 个事件调用模型，每个请求包含该事件内文章的标题、摘要、正文片段和来源链接。

每次运行会把聚类结果写入 `site/clusters/YYYY-MM-DD.json`，用于核查聚类数量、每类文章和传给事件选择步骤的标题。

## 增量聚类

数据库会持久化事件类和文章归属：

- `articles` 按 `url_hash` 去重，重复运行不会重复插入同一链接。
- `events` 保存事件类、文章集合和向量中心。
- `event_articles` 保存文章属于哪个事件类。

每次运行时，程序只处理候选窗口内尚未归属事件的文章。新文章会先和已有事件类的向量中心比较；相似度足够高时归入已有类，并更新该类的文章集合和向量中心。无法归入已有类的文章，才会在剩余集合中重新聚类并创建新事件类。本期简报从最近窗口内有文章的事件类中选择 3-5 条。

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

部署步骤：

1. 推送仓库到 GitHub。
2. 在仓库 `Settings -> Pages` 中，把 Build and deployment 的 Source 设为 `GitHub Actions`。
3. 在 `Settings -> Secrets and variables -> Actions` 中添加需要的 Secrets。
4. 确认 `SITE_BASE_URL` 是最终站点地址，例如 `https://用户名.github.io/仓库名`。如果不设置，Actions 会默认使用当前仓库的项目页地址。
5. 到 `Actions -> Daily digest` 手动运行一次，确认生成和部署成功。

建议设置：

- `OPENAI_API_KEY`：可选，不设置时使用本地降级摘要
- `SITE_BASE_URL`：建议设置为实际站点地址，否则 RSS 链接会指向默认示例地址

如果需要更换 API 服务商、模型或向量模型，本地修改 `config/api.yml`；GitHub Actions 使用提交到仓库的 `config/api.example.yml`，因此部署环境的非密钥配置需要同步改这个模板文件。

项目页部署后可以打开：

- 首页：`https://用户名.github.io/仓库名/`
- RSS：`https://用户名.github.io/仓库名/feed.xml`

RSS 阅读器应订阅 `feed.xml` 的完整地址，而不是订阅项目页首页。

`SITE_BASE_URL` 需要设置为项目页根地址，不要写到 `feed.xml`：

```text
https://用户名.github.io/仓库名
```

RSS item 会指向当天 HTML 简报，同时在 `description` 和 `content:encoded` 中包含 3-5 条简报内容，方便 RSS 阅读器直接预览。

## 历史页面和 RSS

GitHub Actions 会恢复并保存 `site/issues/` 缓存，因此历史 HTML 简报会继续部署：

```text
https://用户名.github.io/仓库名/issues/YYYY-MM-DD.html
```

`feed.xml` 不保留历史 item，每次运行只输出当天这一条。这样 RSS 阅读器每天只收到一条新简报，但旧的 HTML 页面仍可通过原链接访问。
