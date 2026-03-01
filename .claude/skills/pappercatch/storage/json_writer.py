# storage/json_writer.py — 将论文追加写入 JSON 文件

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crawler.parser import Paper


class JsonWriter:
    """
    采用「JSON Lines + 最终合并」策略：
    - 抓取过程中，每批论文以追加形式写入 .jsonl 临时文件（安全，不会因崩溃丢数据）。
    - flush() 时将所有行合并成标准 JSON 数组文件。
    """

    def __init__(self, output_path: str):
        self._final_path = output_path
        self._temp_path = output_path + ".tmp.jsonl"

    def open(self, resume: bool = True) -> None:
        """
        打开临时文件。
        resume=True  → 追加模式（断点续传）
        resume=False → 截断模式（重新开始）
        """
        os.makedirs(os.path.dirname(self._final_path) or ".", exist_ok=True)
        mode = "a" if resume else "w"
        self._file = open(self._temp_path, mode, encoding="utf-8")

    def write_batch(self, papers: list["Paper"]) -> None:
        """将一批论文逐行追加写入临时文件"""
        for paper in papers:
            line = json.dumps(paper.to_dict(), ensure_ascii=False)
            self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        """关闭临时文件"""
        if hasattr(self, "_file") and not self._file.closed:
            self._file.close()

    def flush(self) -> int:
        """
        将 .jsonl 合并为标准 JSON 数组文件。
        返回合并后的论文总数。
        """
        self.close()

        if not os.path.exists(self._temp_path):
            return 0

        all_papers: list[dict] = []
        with open(self._temp_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        all_papers.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        with open(self._final_path, "w", encoding="utf-8") as f:
            json.dump(all_papers, f, ensure_ascii=False, indent=2)

        return len(all_papers)
