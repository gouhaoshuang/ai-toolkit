---
name: pappercatch
description: AMiner 学术论文爬虫。给定一个 AMiner 期刊/会议的 venue_id，批量抓取全部论文元数据（标题、作者、摘要、年份、DOI 等），输出 JSON / CSV / SQLite 三种格式，支持断点续传、自动限速与重试。
---

# PapperCatch Skill 使用指南

## 技能概述

本 Skill 完全自包含，所有爬虫代码均在此目录内。  
**工作目录必须切换到本 Skill 目录才能正确运行。**

### Skill 目录位置

本 Skill 位于项目的 `{项目根目录}/skills/pappercatch/` 目录下。  
使用前请先用 `cd` 命令切换到该目录（见下方步骤）。

---

## 前置条件

使用前确认已安装依赖（只需执行一次）：

```powershell
# 切换到本 Skill 所在目录（路径因项目位置而异）
cd <本Skill目录的绝对路径>
pip install -r requirements.txt
```

依赖项：`requests>=2.31.0`、`tqdm>=4.66.0`

---

## 如何获取 venue_id

1. 在浏览器打开 AMiner 期刊/会议页面，例如：  
   `https://www.aminer.cn/open/journal/detail/5ea1c5c1edb6e7d53c00e7ad`
2. URL 最后一段即为 `venue_id`：`5ea1c5c1edb6e7d53c00e7ad`
3. 常用 venue_id 速查见 `examples/known_venues.md`
4. 如果 `examples/known_venues.md` 中没有用户想要搜索的会议、期刊的 venue_id ，提示用户访问 AMiner 网站，获取对应的 venue_id。

---

## 标准使用流程

### 步骤 0：与用户确认抓取目标

**用户触发**：用户表达想抓取某个期刊/会议的论文信息。

**AI 需要向用户依次确认以下信息：**

1. **目标期刊/会议名称**
   - 询问用户想抓取哪个期刊或会议的论文
   - 查询 `examples/known_venues.md`，判断是否已有对应的 `venue_id`
   - 若已有 → 告知用户并直接使用；若没有 → 提示用户访问以下页面自行查找并提供 `venue_id`：  
     `https://www.aminer.cn/open/journal/detail/<venue_id>`

2. **抓取数量**
   - 询问用户希望抓取多少篇（填写具体数字，或回答"全部"）
   - 全部 → 使用 `--limit 0`（默认）；指定数量 → 使用 `--limit N`

3. **输出格式**（可选，默认 `all`）
   - 是否需要特定格式：`json` / `csv` / `db` / `all`
   - 若用户无偏好，使用默认值 `all`（同时生成三种格式）

4. **是否重新开始**（可选，默认续传）
   - 若用户之前已有抓取进度，询问是否从断点继续，还是从头重新抓取

**确认示例对话：**

> 用户："帮我抓取 ICCAD 的论文"  
> AI："好的，ICCAD 的 venue_id 是 `5ea1d155edb6e7d53c00fca6`。请问需要抓取多少篇？全部还是指定数量？"  
> 用户："先抓 500 篇试试"  
> AI："明白，将抓取 ICCAD 前 500 篇论文，输出格式为 JSON/CSV/SQLite 三种，开始执行。"

### 步骤 1：切换到 Skill 目录

```powershell
# 切换到本 Skill 所在目录（路径因项目位置而异）
cd <本Skill目录的绝对路径>
```

### 步骤 2：运行爬虫

```powershell
# 全量抓取（默认：Design Automation Conference，全部格式输出）
python main.py

# 指定 venue_id 和会议名称
python main.py --venue-id <venue_id> --venue-name "会议名称"

# 仅抓取前 N 篇（测试用）
python main.py --limit 100

# 从头重新抓取（忽略断点）
python main.py --reset
```

### 步骤 3：查看输出

输出文件按会议/期刊名称自动分子目录，保存在 `output/<venue_name>/` 下：

```
output/
├── Design Automation Conference/   ← 按会议名称自动创建
│   ├── papers.json                 — 完整论文数据（JSON 数组）
│   ├── papers.csv                  — 可直接用 Excel 打开（UTF-8-BOM）
│   ├── papers.db                   — SQLite 数据库
│   ├── progress.json               — 断点续传进度记录
│   └── crawler.log                 — 本次运行日志
├── ICCAD/
│   └── ...
└── NeurIPS/
    └── ...
```

> 会议名称中的非法字符（`\ / : * ? " < > |`）会自动替换为 `_`。

---

## 完整命令参数

| 参数           | 说明                                    | 默认值                            |
| -------------- | --------------------------------------- | --------------------------------- |
| `--venue-id`   | AMiner venue_id                         | `5ea1c5c1edb6e7d53c00e7ad`（DAC） |
| `--venue-name` | 期刊/会议名称（写入数据用）             | `Design Automation Conference`    |
| `--output-dir` | 输出目录路径                            | `output`                          |
| `--format`     | 输出格式：`json` / `csv` / `db` / `all` | `all`                             |
| `--limit`      | 最多抓取篇数，0 = 全部                  | `0`                               |
| `--delay`      | 请求间隔（秒），建议 ≥ 0.5              | `0.8`                             |
| `--reset`      | 忽略断点，从头开始                      | -                                 |

---

## 常见工作流

### 工作流 A：对新期刊做全量抓取

```powershell
# 确保当前目录已切换到本 Skill 目录
python main.py --venue-id <venue_id> --venue-name "ICCAD" --output-dir "output_iccad"
```

### 工作流 B：断点续传（程序中断后恢复）

```powershell
# 直接重新运行，程序自动从上次断点继续
python main.py
```

### 工作流 C：仅输出 CSV（供 Excel 分析）

```powershell
python main.py --format csv
```

### 工作流 D：查询 SQLite 数据

```powershell
python -c "
import sqlite3
conn = sqlite3.connect('output/papers.db')
# 查询有摘要的论文数量
print(conn.execute(\"SELECT COUNT(*) FROM papers WHERE abstract != ''\").fetchone())
# 按年份统计
for row in conn.execute('SELECT year, COUNT(*) FROM papers GROUP BY year ORDER BY year DESC LIMIT 10'):
    print(row)
"
```

### 工作流 E：验证输出数据

```powershell
python -c "
import json
papers = json.load(open('output/papers.json', encoding='utf-8'))
print(f'总篇数: {len(papers)}')
print(f'有摘要: {sum(1 for p in papers if p[\"abstract\"])} 篇')
print(f'示例: {papers[5][\"title\"]}')
"
```

---

## 输出数据字段

完整字段说明见 `resources/data_schema.md`。

| 字段             | 类型      | 说明                                 |
| ---------------- | --------- | ------------------------------------ |
| `publication_id` | str       | AMiner 论文唯一 ID                   |
| `title`          | str       | 论文标题                             |
| `authors`        | list[str] | 作者姓名列表                         |
| `year`           | int       | 发表年份                             |
| `abstract`       | str       | 摘要（部分论文 AMiner 无数据则为空） |
| `venue`          | str       | 期刊/会议名称                        |
| `doi`            | str       | DOI / ISSN 号                        |
| `citation_count` | int       | 引用次数                             |
| `urls`           | list[str] | 外部链接                             |
| `crawled_at`     | str       | 抓取时间戳（ISO 8601）               |

---

## 注意事项

> [!NOTE]
> **关于摘要为空**：AMiner 列表 API 对 `offset=0`（第一页）的前几篇论文有时不返回摘要字段，这是 AMiner 数据库本身的缺失，非爬虫问题。从第二页（`offset=20`）起，摘要数据完整。

> [!NOTE]
> **关于 total 未知**：AMiner 列表 API 不直接返回论文总数，爬虫以"返回空列表"为终止信号，进度条无法显示百分比，属正常现象。

> [!CAUTION]
> 不要将 `--delay` 设置低于 `0.3` 秒，否则可能触发服务器限流（HTTP 429）。

---

## 代码结构

```
pappercatch/
├── SKILL.md              # 本文件（AI 使用手册）
├── config.py             # 全局配置（API 地址、默认参数）
├── main.py               # 主入口（命令行界面 + 流程编排）
├── requirements.txt      # Python 依赖
├── crawler/
│   ├── aminer_client.py  # AMiner API 客户端（分页+重试+限速）
│   ├── parser.py         # Paper 数据模型 + API 响应解析
│   └── progress.py       # 断点续传进度管理
├── storage/
│   ├── json_writer.py    # JSON 写入（JSONL 临时 → 最终合并）
│   ├── csv_writer.py     # CSV 写入（UTF-8-BOM）
│   └── db_writer.py      # SQLite 写入（INSERT OR IGNORE）
├── examples/
│   └── known_venues.md   # 常用 venue_id 速查表
└── resources/
    └── data_schema.md    # 输出数据字段详细说明
```
