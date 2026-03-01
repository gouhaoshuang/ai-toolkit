# crawler/progress.py — 断点续传：记录和恢复抓取进度

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict


@dataclass
class Progress:
    venue_id: str
    last_offset: int = 0  # 上次已完成的偏移量
    total: int = 0  # API 返回的论文总数
    saved_count: int = 0  # 已成功写入的论文数


class ProgressManager:
    """负责加载 / 保存爬取进度到磁盘，实现断点续传。"""

    def __init__(self, progress_path: str):
        self._path = progress_path

    def load(self, venue_id: str) -> Progress:
        """加载已有进度；若文件不存在或 venue_id 不匹配则返回全新进度。"""
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("venue_id") == venue_id:
                    return Progress(
                        **{
                            k: v
                            for k, v in data.items()
                            if k in Progress.__dataclass_fields__
                        }
                    )
            except Exception:
                pass

        return Progress(venue_id=venue_id)

    def save(self, progress: Progress) -> None:
        """将当前进度写入磁盘。"""
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(asdict(progress), f, ensure_ascii=False, indent=2)

    def reset(self, venue_id: str) -> Progress:
        """重置进度（强制重新抓取）。"""
        p = Progress(venue_id=venue_id)
        self.save(p)
        return p
