# 输出数据字段说明

本文档描述 PapperCatch 爬虫输出的 `papers.json` / `papers.csv` / `papers.db` 中每个字段的含义。

## 字段列表

| 字段名           | 类型         | 说明                                                    | 可能为空               |
| ---------------- | ------------ | ------------------------------------------------------- | ---------------------- |
| `publication_id` | string       | AMiner 平台分配的论文唯一 ID                            | 否                     |
| `title`          | string       | 论文标题                                                | 否                     |
| `authors`        | list[string] | 作者姓名列表，按论文原始顺序排列                        | 否（可为空列表）       |
| `year`           | integer      | 论文发表年份（如 `2025`）                               | 可能为 `0`（数据缺失） |
| `abstract`       | string       | 论文摘要全文                                            | **可能为空**（见说明） |
| `venue`          | string       | 所属期刊/会议名称                                       | 否                     |
| `doi`            | string       | DOI 或 ISSN 号                                          | 可能为空               |
| `citation_count` | integer      | 被引用次数                                              | 可能为 `0`             |
| `urls`           | list[string] | 外部链接（PDF、主页等）                                 | 可能为空列表           |
| `crawled_at`     | string       | 数据抓取时间，ISO 8601 格式（如 `2026-03-01T13:47:35`） | 否                     |

---

## 关于 `abstract` 为空的说明

**原因**：AMiner 列表 API 的第一页（`offset=0`）对极少数论文不返回摘要字段，这是 AMiner 数据库本身的数据缺失，并非爬虫问题。  
**影响范围**：通常为每批次最前面几篇（约 2～5 篇），其余论文摘要完整。  
**解决方案**：接受空字段，或通过 AMiner 论文详情页手动补充（需浏览器）。

---

## CSV 格式特殊说明

在 CSV 文件中：

- `authors` 字段：多个作者用 `; ` 分隔，例如：`Alice; Bob; Charlie`
- `urls` 字段：多个链接用 `; ` 分隔
- 编码：UTF-8-BOM（Microsoft Excel 可直接打开不乱码）

---

## SQLite 表结构

```sql
CREATE TABLE papers (
    publication_id TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    authors        TEXT,   -- JSON 数组，如 ["Alice", "Bob"]
    year           INTEGER,
    abstract       TEXT,
    venue          TEXT,
    doi            TEXT,
    citation_count INTEGER DEFAULT 0,
    urls           TEXT,   -- JSON 数组，如 ["https://..."]
    crawled_at     TEXT
);

-- 已建立索引
CREATE INDEX idx_year  ON papers(year);
CREATE INDEX idx_venue ON papers(venue);
```

### 常用 SQL 查询示例

```sql
-- 按年份统计论文数量
SELECT year, COUNT(*) AS count FROM papers GROUP BY year ORDER BY year DESC;

-- 查找有摘要的论文
SELECT title, abstract FROM papers WHERE abstract != '' LIMIT 10;

-- 搜索特定关键词（标题）
SELECT title, year, authors FROM papers WHERE title LIKE '%neural%';

-- 高引用论文
SELECT title, citation_count FROM papers ORDER BY citation_count DESC LIMIT 20;
```
