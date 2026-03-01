# crawler/parser.py — 解析 AMiner API 响应，转换为统一数据模型

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Paper:
    """一篇论文的数据模型"""

    publication_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int = 0
    abstract: str = ""
    venue: str = ""
    doi: str = ""
    urls: list[str] = field(default_factory=list)
    citation_count: int = 0
    crawled_at: str = field(
        default_factory=lambda: datetime.datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        return asdict(self)


def _extract_authors(raw_authors: list[dict] | None) -> list[str]:
    """从作者列表中提取姓名"""
    if not raw_authors:
        return []
    names = []
    for a in raw_authors:
        name = a.get("name") or a.get("Name") or ""
        if name:
            names.append(name.strip())
    return names


def _extract_urls(raw: dict) -> list[str]:
    """尝试从多个可能字段提取 PDF/外链"""
    urls: list[str] = []
    for key in ("urls", "url", "pdf_url", "pdf", "links"):
        val = raw.get(key)
        if isinstance(val, list):
            urls.extend(str(u) for u in val if u)
        elif isinstance(val, str) and val:
            urls.append(val)
    return list(dict.fromkeys(urls))  # 去重保序


def parse_papers(api_response: Any, venue_name: str = "") -> list[Paper]:
    """
    解析 API 返回的原始数据，返回 Paper 列表。

    AMiner API 实际响应结构：
    {
      "data": [
        {
          "succeed": true,
          "items": [ {...}, ... ],
          "meta": { "context": "...", "time": "..." }
        }
      ]
    }
    """
    papers: list[Paper] = []

    # 兼容 dict 和 list 两种顶层格式
    if isinstance(api_response, dict):
        data_list = api_response.get("data") or []
    elif isinstance(api_response, list):
        data_list = api_response
    else:
        return papers

    if not data_list:
        return papers

    result = data_list[0]
    if not isinstance(result, dict):
        return papers
    if not result.get("succeed"):
        return papers

    publications = result.get("items") or result.get("publications") or []

    for pub in publications:
        if not isinstance(pub, dict):
            continue

        pid = pub.get("publication_id") or pub.get("id") or pub.get("_id") or ""
        title = (pub.get("title") or "").strip()
        if not title:
            continue

        paper = Paper(
            publication_id=str(pid),
            title=title,
            authors=_extract_authors(pub.get("authors")),
            year=int(pub.get("year") or 0),
            abstract=(pub.get("abstract") or "").strip(),
            venue=pub.get("venue_name") or pub.get("venue") or venue_name,
            doi=(pub.get("doi") or pub.get("issn") or "").strip(),
            urls=_extract_urls(pub),
            citation_count=int(pub.get("n_citation") or pub.get("citation_count") or 0),
        )
        papers.append(paper)

    return papers


def extract_total(api_response: Any) -> int:
    """
    从响应中提取论文总数。
    AMiner 的列表 API 不直接返回 total，返回 0 表示需要用翻页方式判断结束。
    """
    try:
        if isinstance(api_response, dict):
            data_list = api_response.get("data") or []
        else:
            data_list = api_response
        return int(data_list[0].get("total") or 0)
    except (KeyError, IndexError, TypeError, ValueError):
        return 0
