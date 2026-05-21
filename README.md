# Calm Tech RSS

Calm Tech RSS 会从可信科技 RSS / Atom 源抓取内容，去重、聚类并筛选 5 条值得关注的事件，生成克制、客观的中文科技日报，同时发布静态 HTML 和每日 RSS Feed。

系统按可重复运行设计：文章 URL、抓取后的正文、事件重写和每日简报都会缓存在 SQLite 中，重复执行不会重复入库，也会尽量避免重复调用 LLM。

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
- `site/issues/YYYY-MM-DD-事件哈希/index.html`
- `site/issues/YYYY-MM-DD-log/index.html`
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
  base_url: https://right.codes/deepseek
  api_key_env: OPENAI_API_KEY
  model: deepseek-v4-pro
  temperature: 0.1
  timeout_seconds: 180
  max_retries: 5

judge:
  enabled: true
  model: deepseek-v4-flash
  temperature: 0.0
  timeout_seconds: 180
  max_retries: 5

embedding:
  model: intfloat/multilingual-e5-small
  models:
    - intfloat/multilingual-e5-small
    - sentence-transformers/all-MiniLM-L6-v2
  device: cpu
  batch_size: 32
  cpu_threads: 4
  max_chars: 2000
  similarity_threshold: 0.8

pipeline:
  max_workers: 4
```

建议把密钥放在 `.env` 或运行环境中，不要直接写入仓库：

```bash
OPENAI_API_KEY=你的密钥
```

如果没有配置 API key，程序会使用本地降级摘要，完整生成流程仍然可以运行。`sentence-transformers` 或模型不可用时，语义聚类会回退到确定性的本地哈希向量。GitHub Actions 环境默认按 CPU 并行运行两个向量模型，并发抓取数默认是 4。

## 主流程

主流程不会逐篇翻译文章。LLM 只对今日新增类做重要性排序，并对最终入选类做重写。

- 读取 RSS 源配置，并发抓取 RSS / Atom。
- 解析文章，统一 UTC 时间，过滤候选窗口内内容。push 首次构建使用最近 24 小时；每日增量运行使用上次成功抓取时间到本次运行开始时间。
- 清洗无效文章：至少需要标题、链接，以及摘要或正文之一。
- 在入库和聚类之前尝试抓取每篇文章的网页正文；抓取成功时写入 `articles.content` 并更新 `content_hash`，失败时保留 RSS 自带内容。
- 使用“标题 + 摘要 + 内容”并行做双模型向量化，超长文本只取最前面的片段。
- 写入 SQLite，并增量归入历史事件类或新建事件类。
- 聚类时只有两个向量模型对同一候选类的相似度都大于阈值才允许合并。
- 事件选择：只从本次新建的事件类中选择；先把每类第一篇文章的标题和摘要交给 LLM 排序，再按重要性加分，取最终分数最高的 5 个。
- 事件重写：只对选中的新增事件类调用 LLM，每个请求包含该事件类内所有文章的标题、摘要、正文片段和来源链接。

每次运行会把聚类结果写入 `site/clusters/YYYY-MM-DD.json`，并生成 `issues/YYYY-MM-DD-log/` 聚类日志页。每个入选类的原文归档单独写入 `issues/YYYY-MM-DD-事件哈希/`。

## 增量聚类

数据库会持久化事件类和文章归属：

- `articles` 按 `url_hash` 去重，重复运行不会重复插入同一链接。
- `events` 保存事件类、文章集合和向量中心。
- `event_articles` 保存文章属于哪个事件类。

每次运行时，程序只处理候选窗口内尚未归属事件的文章。每个事件类使用第一篇文章的向量作为固定中心，后续文章归入时不会把中心改成均值。

新文章的归类流程：

- 先和所有历史类中心向量比较；两个模型相似度都大于 `0.8` 时才进入已有类候选。
- 对已有类候选并行调用判别模型判断“是不是同一个具体事件”，通过后才归入相似度最高的已有类。
- 剩余文章每篇先单独成类，再按同样的双模型阈值反复合并，直到无法继续合并。
- 每个类用第一篇文章的双模型向量表示，不用均值中心。

判别模型使用 `judge` 配置，默认沿用 `llm` 的 `base_url`、`api_key_env` 和密钥，只把模型名设为 `deepseek-v4-flash`。它有独立 prompt，只返回是否同一事件。这样跨中英文报道可以先靠向量召回，再由判别模型确认主体、动作和时间背景是否一致。

## RSS 和全文抓取观察

以下是 2026-05-13 本地测试时的观察，用于判断各源在当前抓取策略下提供的信息量。站点策略可能变化，主流程会在全文抓取失败时自动回退到 RSS 摘要或 RSS 自带内容。

| 来源 | RSS 状态 | RSS 内容结构 | 文章页全文抓取观察 |
| --- | --- | --- | --- |
| OpenAI Blog | 可下载，RSS 文件较大 | RSS 中包含较多条目和内容片段 | 文章页直接 HTTP 和无头浏览器都遇到站点验证/JavaScript 与 cookies 提示，当前不稳定，通常依赖 RSS 内容 |
| Google DeepMind Blog | 可下载 | RSS / 站点公开内容较完整 | 公开页面可通过浏览器渲染获取正文或列表内容 |
| Hugging Face Blog | 可下载 | RSS 文件较大，通常包含较多正文信息 | 适合用 RSS 内容和文章页正文互补 |
| TechCrunch AI | 可下载 | AI 分类 RSS，通常以摘要为主 | 文章页是否可抽取取决于页面结构和访问限制 |
| MIT Technology Review AI | 可下载 | AI 主题 RSS，通常以摘要为主 | 文章页可能有访问限制，失败时回退 RSS 摘要 |
| 量子位 | 可下载；普通 `curl -I` 曾返回 403，但带 User-Agent 的 GET 正常 | WordPress RSS 2.0；每条 item 有 `title`、`link`、`dc:creator`、`pubDate`、`category`、`guid`、`description`，没有实际 `content:encoded` 正文 | 可以抓取文章页正文。最近一次测试从文章页抽取到约 1200 字正文，因此主流程会在聚类前把正文写入 `articles.content` |
| AIBase News | 最近一次样本下载返回 403 | 无法稳定拿到 RSS 样本 | 当前可能需要依赖源站可用性或后续更换源地址 |

量子位的 RSS 摘要很短，例如 `description` 只有一句话；但文章链接页目前可以抽取正文。因此在当前逻辑下，量子位会先由 RSS 提供标题、链接、发布时间和摘要，再在入库前尝试抓取文章页全文，成功后用“标题 + 摘要 + 正文”参与聚类和重写。

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

仓库包含 GitHub Actions 工作流，会在每天 UTC+8 06:00 运行生成任务，并把 `site/` 作为 GitHub Pages artifact 上传。Actions 会安装 CPU 版 Torch 和 `sentence-transformers`，使用 `config/api.example.yml` 中的 `device: cpu`、`cpu_threads: 4` 和 `max_workers: 4`。

部署步骤：

1. 推送仓库到 GitHub。
2. 在仓库 `Settings -> Pages` 中，把 Build and deployment 的 Source 设为 `GitHub Actions`。
3. 在 `Settings -> Secrets and variables -> Actions` 中添加需要的 Secrets。
4. 确认 `SITE_BASE_URL` 是最终站点地址，例如 `https://用户名.github.io/仓库名`。如果不设置，Actions 会默认使用当前仓库的项目页地址。
5. 到 `Actions -> Daily digest` 手动运行一次，确认生成和部署成功。

工作流会在以下情况运行：

- push 到 `main`：不恢复数据库缓存，相当于清空数据库后重新生成。
- 每天定时任务：恢复并保存 `data/` 数据库缓存，用于从上次成功抓取时间继续增量入库和增量聚类。
- 手动 `workflow_dispatch`：不恢复数据库缓存，行为和 push 一样。

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

RSS item 会指向当天 HTML 简报，同时在 `description` 和 `content:encoded` 中包含最多 5 条简报内容，方便 RSS 阅读器直接预览。

## 历史页面和 RSS

GitHub Actions 会恢复并保存 `site/issues/` 缓存，因此历史 HTML 简报会继续部署：

```text
https://用户名.github.io/仓库名/issues/YYYY-MM-DD.html
```

`site/issues/` 只保留最近 5 天网页归档，RSS `feed.xml` 保留最近 10 天 item。原文页和当日聚类日志也位于 `site/issues/` 下：

```text
https://用户名.github.io/仓库名/issues/YYYY-MM-DD-事件哈希
https://用户名.github.io/仓库名/issues/YYYY-MM-DD-log
```
