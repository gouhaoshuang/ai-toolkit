# crawler/aminer_client.py — AMiner API 客户端（分页 + 重试 + 限速）

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

import requests

import config
from crawler.parser import Paper, parse_papers, extract_total

logger = logging.getLogger(__name__)

# AMiner 页面 JS 显示论文总数，但 API 不直接提供；此处用硬编码备用值
# 真正终止条件是「API 返回空列表」
_FALLBACK_TOTAL = 999_999


class AMinerClient:
    """
    封装对 AMiner datacenter API 的分页请求。
    支持自动重试、指数退避、请求限速。
    """

    def __init__(
        self,
        venue_id: str = config.DEFAULT_VENUE_ID,
        venue_name: str = config.DEFAULT_VENUE_NAME,
        page_size: int = config.PAGE_SIZE,
        sort: str = "time",
        delay: float = config.REQUEST_DELAY,
        max_retries: int = config.MAX_RETRIES,
        timeout: int = config.REQUEST_TIMEOUT,
    ):
        self.venue_id = venue_id
        self.venue_name = venue_name
        self.page_size = page_size
        self.sort = sort
        self.delay = delay
        self.max_retries = max_retries
        self.timeout = timeout

        self._session = requests.Session()
        self._session.headers.update(config.REQUEST_HEADERS)

    # ── 内部方法 ────────────────────────────────────────────────────

    def _build_payload(self, offset: int) -> list[dict]:
        return [
            {
                "action": config.API_ACTION,
                "parameters": {
                    "offset": offset,
                    "size": self.page_size,
                    "venue_id": self.venue_id,
                    "sort": self.sort,
                },
            }
        ]

    def _post_with_retry(self, offset: int) -> Any:
        """发送单次 POST 请求，失败时指数退避重试。"""
        payload = self._build_payload(offset)
        url = f"{config.API_BASE_URL}?a=__{config.API_ACTION}__"

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.HTTPError as e:
                logger.warning(
                    f"[offset={offset}] HTTP错误 (尝试 {attempt}/{self.max_retries}): {e}"
                )
            except requests.exceptions.ConnectionError as e:
                logger.warning(
                    f"[offset={offset}] 连接错误 (尝试 {attempt}/{self.max_retries}): {e}"
                )
            except requests.exceptions.Timeout:
                logger.warning(
                    f"[offset={offset}] 请求超时 (尝试 {attempt}/{self.max_retries})"
                )
            except json.JSONDecodeError as e:
                logger.warning(
                    f"[offset={offset}] JSON解析错误 (尝试 {attempt}/{self.max_retries}): {e}"
                )

            if attempt < self.max_retries:
                backoff = config.RETRY_BACKOFF**attempt
                logger.info(f"  → {backoff:.1f}s 后重试…")
                time.sleep(backoff)

        logger.error(f"[offset={offset}] 已达最大重试次数，跳过此批次。")
        return None

    # ── 公开方法 ────────────────────────────────────────────────────

    def fetch_total(self) -> int:
        """
        获取论文总数。
        AMiner 列表 API 不直接提供 total，此处先请求第一页，
        如果 API 不返回 total 字段则返回 -1 表示"可分页但总数未知"。
        返回 0 表示连接失败。
        """
        raw = self._post_with_retry(offset=0)
        if raw is None:
            return 0
        total = extract_total(raw)
        if total == 0:
            papers = parse_papers(raw, venue_name=self.venue_name)
            if papers:
                # 返回 -1 表示"可以分页但总数未知"
                return -1
        return total

    def fetch_page(self, offset: int) -> list[Paper]:
        """获取指定偏移量的一页论文"""
        raw = self._post_with_retry(offset=offset)
        if raw is None:
            return []
        return parse_papers(raw, venue_name=self.venue_name)

    def iter_all_papers(
        self,
        start_offset: int = 0,
        limit: int = 0,
    ) -> Iterator[tuple[list[Paper], int]]:
        """
        迭代器：逐页获取所有论文。

        Yields:
            (papers_in_page, current_offset)

        Args:
            start_offset: 从哪个偏移量开始（断点续传用）
            limit:        最多抓取多少篇（0 = 全部）
        """
        offset = start_offset
        fetched = 0

        while True:
            papers = self.fetch_page(offset)
            if not papers:
                logger.info(f"offset={offset} 返回空结果，抓取完成。")
                break

            yield papers, offset

            fetched += len(papers)
            offset += self.page_size

            # 达到用户指定上限
            if limit > 0 and fetched >= limit:
                logger.info(f"已达到指定上限 {limit} 篇，停止。")
                break

            time.sleep(self.delay)
