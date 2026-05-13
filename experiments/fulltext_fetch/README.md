# 全文抓取实验

这个目录用于独立测试“从 RSS entry 的链接抓取网页正文”，不接入主项目流水线。

## 使用方式

```bash
.venv/bin/python experiments/fulltext_fetch/fetch_fulltext.py https://example.com/article
```

输出为 JSON，包含：

- `url`
- `status_code`
- `title`
- `text`
- `text_length`
- `extractor`

## 抽取策略

脚本会优先使用 `trafilatura`。如果当前环境没有安装，则回退到标准库 `html.parser` 的粗略正文抽取。

安装可选依赖：

```bash
.venv/bin/python -m pip install trafilatura
```

这个实验目录不会修改数据库，也不会影响 `calmtechrss` 主流程。

## 用无头浏览器测试

如果普通 HTTP 请求被站点拒绝，且本机有 Chrome/Chromium，可以尝试公开页面的无头浏览器渲染：

```bash
.venv/bin/python experiments/fulltext_fetch/fetch_with_browser.py https://example.com/article
```

脚本使用 Chrome 的 `--headless --dump-dom` 获取渲染后的 DOM，再用 `trafilatura` 抽取正文。它只用于访问公开页面，不处理登录、验证码、Cloudflare challenge 或其它访问控制。

## 批量测试当前 RSS 源

```bash
.venv/bin/python experiments/fulltext_fetch/test_sources_fulltext.py --per-source 2 --candidate-hours 72
```

脚本会读取 `config/sources.yml` 的 active 源，先抓 RSS，再对每个源最多抽样 2 篇原文链接做全文抽取测试。

报告输出到：

```text
experiments/fulltext_fetch/fulltext_report.json
```

该报告是本地测试产物，不提交到 Git。
