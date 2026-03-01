# storage/db_writer.py — 将论文写入 SQLite 数据库

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crawler.parser import Paper

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS papers (
    publication_id TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    authors        TEXT,          -- JSON 数组字符串
    year           INTEGER,
    abstract       TEXT,
    venue          TEXT,
    doi            TEXT,
    citation_count INTEGER DEFAULT 0,
    urls           TEXT,          -- JSON 数组字符串
    crawled_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_year  ON papers(year);
CREATE INDEX IF NOT EXISTS idx_venue ON papers(venue);
"""

INSERT_SQL = """
INSERT OR IGNORE INTO papers
    (publication_id, title, authors, year, abstract, venue, doi, citation_count, urls, crawled_at)
VALUES
    (:publication_id, :title, :authors, :year, :abstract, :venue, :doi, :citation_count, :urls, :crawled_at)
"""


class DbWriter:
    """将论文写入 SQLite 数据库，支持断点续传（INSERT OR IGNORE）。"""

    def __init__(self, db_path: str):
        self._path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.executescript(CREATE_TABLE_SQL)
        self._conn.commit()

    def write_batch(self, papers: list["Paper"]) -> None:
        import json

        rows = []
        for p in papers:
            d = p.to_dict()
            d["authors"] = json.dumps(d["authors"], ensure_ascii=False)
            d["urls"] = json.dumps(d["urls"], ensure_ascii=False)
            rows.append(d)
        self._conn.executemany(INSERT_SQL, rows)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def count(self) -> int:
        """返回数据库中已有论文数量"""
        if not self._conn:
            return 0
        cur = self._conn.execute("SELECT COUNT(*) FROM papers")
        return cur.fetchone()[0]
