# storage/csv_writer.py — 将论文追加写入 CSV 文件

from __future__ import annotations

import csv
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crawler.parser import Paper

# CSV 列顺序与标题
CSV_FIELDS = [
    ("publication_id", "论文ID"),
    ("title", "标题"),
    ("authors", "作者"),
    ("year", "年份"),
    ("abstract", "摘要"),
    ("venue", "期刊/会议"),
    ("doi", "DOI"),
    ("citation_count", "引用数"),
    ("urls", "链接"),
    ("crawled_at", "抓取时间"),
]


class CsvWriter:
    """将论文批量追加写入 CSV 文件，使用 UTF-8-BOM 编码（Excel 可直接打开）。"""

    def __init__(self, output_path: str):
        self._path = output_path
        self._file = None
        self._writer = None

    def open(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        file_exists = os.path.exists(self._path) and os.path.getsize(self._path) > 0
        self._file = open(self._path, "a", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(
            self._file,
            fieldnames=[f for f, _ in CSV_FIELDS],
            extrasaction="ignore",
        )
        if not file_exists:
            # 写入中文表头（第一行）
            header_map = {f: label for f, label in CSV_FIELDS}
            self._writer.writerow(header_map)

    def write_batch(self, papers: list["Paper"]) -> None:
        for paper in papers:
            row = paper.to_dict()
            # 列表字段转为分号分隔字符串
            row["authors"] = "; ".join(row.get("authors") or [])
            row["urls"] = "; ".join(row.get("urls") or [])
            self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()
