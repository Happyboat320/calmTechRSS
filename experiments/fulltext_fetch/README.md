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

