# Calm Tech RSS 实现计划

生成日期：2026-04-28

## 项目背景和目的

科技新闻信息源分散，RSS 订阅容易产生大量重复、低价值或标题党内容。这个项目的目标是做一个自动化科技简报系统：每天抓取可信科技源，去重、聚类、筛选后生成一篇中文科技日报，并通过 RSS 发布。

输出形式：

- 每天生成一篇 HTML 简报。
- RSS 中每天只新增一个 item，指向当天简报页面。
- 每篇简报包含 3-5 条重点事件。
- 每条事件保留来源链接。

核心目标：

- 降低订阅噪声。
- 聚合同一事件的多来源报道。
- 用平静、客观、克制的中文重写。
- 不补充来源中没有的信息。
- 支持定时自动运行。
- 支持重复执行，避免重复入库、重复生成、重复调用 LLM。

## 项目具体实现逻辑和流程

整体流程：（这个很重要！）

```text
读取 RSS 源配置
  → 抓取 RSS / Atom
  → 解析文章
  → 统一 UTC 时间
  → 过滤最近 24 小时内容
  → 清洗无效文章（有效：至少有正文或摘要其中之一）
  → 向量聚类去重（转换成向量，尝试将每一条的向量归到之前的类中，剩余的再聚类）
  → 写入 SQLite
  → 选出 3-5 条事件（使用LLM，传入所有的标题，让LLM给出3-5条面向计算机专业工作站值得说，并且不是过于细分领域的事件）
  → LLM 客观重写(将那一类的所有标题摘要正文，输入LLM，输出中文重写)
  → 生成 HTML 简报（包括重写的内容和链接）
  → 生成 RSS feed.xml
  → 发布到静态站点
```

信息源配置使用 YAML，字段建议：

```yaml
sources:
  - name: OpenAI Blog
    url: https://openai.com/news/rss.xml
    type: rss
    category: official
    active: true
    weight: 1.5
```

文章标准字段：

```text
title
url
source_name
source_category
published_at_utc
summary
content
source_article_id
url_hash
content_hash
```

数据存储使用 SQLite，建议至少包含：

- `sources`：信息源配置。
- `articles`：原始文章，按 `url_hash` 唯一去重。
- `article_translations`：翻译缓存，按 `article_id + content_hash + model` 去重。
- `events`：聚类后的新闻事件，按事件内文章 hash 集合生成 `event_hash`。
- `event_rewrites`：LLM 重写缓存，按 `event_hash + prompt_version + model` 去重。
- `issues`：每日简报，按日期唯一。

抓取逻辑：

- 使用 `httpx` 请求 RSS。
- 使用 `feedparser` 解析 RSS / Atom。
- 单个源失败只记录日志，不中断整体任务。
- 设置 User-Agent、timeout 和重定向。
- 优先使用 `published` 时间，其次使用 `updated`。
- 无标题、无链接、无摘要/正文的文章直接丢弃。

时间处理：

- 所有时间统一转为 UTC。
- 简报建议使用最近 36-48 小时作为候选窗口，而不是只看当天。
- 这样可以减少时区、RSS 延迟、定时任务不准时带来的漏报。

翻译逻辑：

- 将标题、摘要、正文统一翻译为中文，便于聚类和重写。
- 中文源可跳过翻译或只做规范化。
- 翻译失败时回退原文。
- 翻译结果必须持久化缓存，避免重复消耗 API。

聚类逻辑：

- 聚类文本建议使用：

```text
translated_title + "\n" + translated_summary[:400] + "\n" + translated_content[:600]
```

- 使用 `intfloat/multilingual-e5-small` 生成向量。
- 用余弦相似度判断是否同一事件。
- 相似度 `>= 0.90` 直接合并。
- 相似度 `0.86-0.90` 可结合标题关键词、来源和时间再判断。
- 每个聚类生成一个事件。

排序逻辑：

- 官方源优先。
- 多来源报道优先。
- 时间更近优先。
- 文章数量更多优先。
- 控制类别平衡，避免全是论文或全是 release。
- 降低 patch release、营销稿、重复列表页权重。

重写逻辑：

- 每个事件输入多篇来源文章。
- LLM 输出严格 JSON。
- 输出字段建议：

```json
{
  "title": "简洁客观的中文标题",
  "summary": "80-150 字中文摘要",
  "sources": [
    {"name": "OpenAI Blog", "url": "https://..."}
  ],
  "uncertainty": ""
}
```

重写要求：

- 只基于来源内容。
- 不添加外部信息。
- 不使用夸张词。
- 不把推测写成事实。
- 保留来源链接。
- 对不确定信息明确说明。

生成逻辑：

- HTML：生成 `site/issues/YYYY-MM-DD.html`。
- RSS：生成 `site/feed.xml`。
- RSS 一天一个 item，不是一条新闻一个 item。
- RSS item 的 `guid` 使用当天 HTML 页面 URL。

RSS item 示例：

```xml
<item>
  <title>2026-04-28 科技简报</title>
  <link>https://example.com/issues/2026-04-28.html</link>
  <guid>https://example.com/issues/2026-04-28.html</guid>
  <pubDate>Tue, 28 Apr 2026 08:00:00 GMT</pubDate>
  <description>今日科技简报，包括 AI、研究、开源和开发者工具动态。</description>
</item>
```

## 项目使用技术栈

- Python 3.11+：主流程和数据处理。
- SQLite：本地持久化存储。
- httpx：HTTP 请求。
- feedparser：RSS / Atom 解析。
- python-dateutil：时间解析。
- PyYAML：读取信息源配置。
- python-dotenv：本地环境变量。
- sentence-transformers：文本向量。
- intfloat/multilingual-e5-small：中英文语义聚类模型。
- numpy：向量相似度计算。
- Jinja2：HTML 模板渲染。
- xml.etree.ElementTree 或 feedgen：RSS 生成。
- OpenAI-compatible Chat Completions API：翻译和重写。
- GitHub Actions：定时运行。
- GitHub Pages / Cloudflare Pages：静态页面和 RSS 托管。

## 项目注意点

- 文章按 `url_hash` 去重。

- 事件按文章 hash 集合生成 `event_hash`。

- 翻译和重写结果必须缓存。

- 单个 RSS 源失败不能中断整体流程。

- LLM 输出必须做 JSON 解析和字段校验。

- RSS 生成后必须做 XML 校验。

- 禁止标题党和夸张表达，例如：震惊、重磅、炸裂、颠覆、疯狂、杀疯了、史诗级、革命性、划时代。

- 不要把 GitHub Actions 当长期服务，只作为定时批处理器。

- 不建议将微信公众号抓取作为核心依赖，稳定性和合规风险都较高。

- 非 RSS 网页抓取后续再做，不应影响 RSS MVP。

- `SITE_BASE_URL` 必须和实际托管路径一致，否则 RSS 链接会错误。

- 对 GitHub Releases 需要降噪，否则容易被低价值 patch 版本占满。

- 对 arXiv 需要控制数量，否则论文源会压过新闻源。

  

## RSS情况

建议第一版只接入稳定 RSS / Atom 源。网页抓取和公众号抓取放到后续扩展。

### 可用官方源

| 名称 | 类型 | 链接 | 备注 |
|---|---|---|---|
| OpenAI Blog | RSS | `https://openai.com/news/rss.xml` | 官方 RSS |
| Anthropic News | RSSHub | `https://rsshub.bestblogs.dev/anthropic/news` | 第三方 RSSHub |
| Google DeepMind Blog | RSS | `https://deepmind.google/blog/rss.xml` | 官方 RSS |
| Microsoft AI Blog | RSS | `https://blogs.microsoft.com/ai/feed/` | 官方 RSS |
| NVIDIA Blog | RSS | `https://blogs.nvidia.com/feed/` | 官方 RSS |
| Hugging Face Blog | RSS | `https://huggingface.co/blog/feed.xml` | 官方 RSS |

### 可用媒体源

| 名称 | 类型 | 链接 | 备注 |
|---|---|---|---|
| The Verge | RSS | `https://www.theverge.com/rss/index.xml` | 全站 RSS，需过滤 AI/科技内容 |
| TechCrunch AI | RSS | `https://techcrunch.com/category/artificial-intelligence/feed/` | AI 分类 |
| VentureBeat AI | RSS | `https://venturebeat.com/category/ai/feed` | AI 分类 |
| MIT Technology Review AI | RSS | `https://www.technologyreview.com/topic/artificial-intelligence/feed/` | AI 主题 |
| 量子位 | RSS | `https://www.qbitai.com/feed` | 中文 AI 媒体 |
| InfoQ 中文 | RSS | `https://www.infoq.cn/feed` | 中文技术媒体 |

### 可用研究源

| 名称 | 类型 | 链接 | 备注 |
|---|---|---|---|
| arXiv cs.CL | RSS | `https://export.arxiv.org/rss/cs.CL` | NLP / LLM |
| arXiv cs.AI | RSS | `https://export.arxiv.org/rss/cs.AI` | AI |
| arXiv cs.LG | RSS | `https://export.arxiv.org/rss/cs.LG` | 机器学习 |

### 可用开源源

| 名称 | 类型 | 链接 | 备注 |
|---|---|---|---|
| transformers releases | Atom | `https://github.com/huggingface/transformers/releases.atom` | Hugging Face Transformers |
| PyTorch releases | Atom | `https://github.com/pytorch/pytorch/releases.atom` | PyTorch |
| LangChain releases | Atom | `https://github.com/langchain-ai/langchain/releases.atom` | LangChain |
| llama.cpp releases | Atom | `https://github.com/ggml-org/llama.cpp/releases.atom` | llama.cpp |
| Open WebUI releases | Atom | `https://github.com/open-webui/open-webui/releases.atom` | Open WebUI |
| vLLM releases | Atom | `https://github.com/vllm-project/vllm/releases.atom` | vLLM |

### 暂不作为核心 RSS 的源

| 名称 | 链接 | 原因 |
|---|---|---|
| Meta AI Blog | `https://about.fb.com/news/` | 无稳定 RSS，适合后续网页抓取 |
| Qwen Blog | `https://qwen.ai/blog/` | 无公开 RSS |
| DeepSeek | `https://deepseek.com/` | 无博客/新闻 RSS |
| 百度文心 | `https://wenxin.baidu.com/` | 无公开 RSS |
| 火山方舟 | `https://www.volcengine.com/product/ark` | 无公开 RSS |
| 腾讯混元 | `https://hunyuan.tencent.com/` | 无公开 RSS |
| 智谱 AI | `https://zhipuai.cn/` | 无公开 RSS |
| Kimi | `https://kimi.moonshot.cn/` | 无公开 RSS |
| 机器之心 | `https://www.jiqizhixin.com/` | 无公开 RSS，公众号依赖较强 |
| 新智元 | `https://www.ainewstoday.com/` | 官网不稳定，公众号依赖较强 |
| Hugging Face Papers | `https://huggingface.co/papers/feed.xml` | RSS 访问可能返回 401 |
| Papers with Code | `https://paperswithcode.com/` | 无公开 RSS |
| GitHub Trending | `https://github.com/trending?since=daily` | 不是 RSS，需要 HTML 抓取 |

## LLM API使用

准备使用opencode go的模型。需要给出.env设置api。

``` 
模型	模型 ID	端点	AI SDK 包
DeepSeek V4 Pro	deepseek-v4-pro	https://opencode.ai/zen/go/v1/chat/completions	@ai-sdk/openai-compatible
```
