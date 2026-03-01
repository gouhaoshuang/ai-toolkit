#!/usr/bin/env python3
# main.py — PapperCatch 主入口：命令行界面 + 爬取流程编排

from __future__ import annotations

import argparse
import logging
import os
import re
import sys

from tqdm import tqdm

import config
from crawler.aminer_client import AMinerClient
from crawler.progress import ProgressManager
from storage.json_writer import JsonWriter
from storage.csv_writer import CsvWriter
from storage.db_writer import DbWriter

# ── 日志（仅 stdout，FileHandler 在 main() 拿到输出目录后再添加）──────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def sanitize_dirname(name: str) -> str:
    """将会议/期刊名称转为合法目录名：替换 Windows/Unix 不允许的字符。"""
    # 替换不合法字符：\ / : * ? " < > |
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


# ── 命令行参数 ───────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pappercatch",
        description="PapperCatch — AMiner 论文爬虫",
    )
    p.add_argument(
        "--venue-id",
        default=config.DEFAULT_VENUE_ID,
        help=f"AMiner venue_id（默认：{config.DEFAULT_VENUE_ID}）",
    )
    p.add_argument(
        "--venue-name",
        default=config.DEFAULT_VENUE_NAME,
        help=f"期刊/会议名称（默认：{config.DEFAULT_VENUE_NAME}）",
    )
    p.add_argument(
        "--output-dir",
        default=config.OUTPUT_DIR,
        help=f"输出目录（默认：{config.OUTPUT_DIR}）",
    )
    p.add_argument(
        "--format",
        choices=["json", "csv", "db", "all"],
        default="all",
        help="输出格式（默认：all，同时生成 JSON/CSV/SQLite）",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多抓取论文数量，0 表示全部（默认：0）",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="忽略已有进度，从头开始重新抓取",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=config.REQUEST_DELAY,
        help=f"请求间隔秒数（默认：{config.REQUEST_DELAY}）",
    )
    return p


# ── 主流程 ───────────────────────────────────────────────────────────
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # 实际输出目录 = <output_dir>/<venue_name>/
    venue_subdir = sanitize_dirname(args.venue_name)
    output_dir = os.path.join(args.output_dir, venue_subdir)
    os.makedirs(output_dir, exist_ok=True)

    # 日志文件写入会议子目录
    file_handler = logging.FileHandler(
        os.path.join(output_dir, "crawler.log"), mode="a", encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    logging.getLogger().addHandler(file_handler)

    # 各输出文件路径
    json_path = os.path.join(output_dir, config.JSON_FILENAME)
    csv_path = os.path.join(output_dir, config.CSV_FILENAME)
    db_path = os.path.join(output_dir, config.DB_FILENAME)
    progress_path = os.path.join(output_dir, config.PROGRESS_FILE)

    fmt = args.format

    # ── 初始化各模块 ────────────────────────────────────────────────
    client = AMinerClient(
        venue_id=args.venue_id,
        venue_name=args.venue_name,
        delay=args.delay,
    )
    prog_mgr = ProgressManager(progress_path)

    # ── 断点续传 or 重置 ────────────────────────────────────────────
    if args.reset:
        progress = prog_mgr.reset(args.venue_id)
        logger.info("🔄 已重置进度，从头开始。")
    else:
        progress = prog_mgr.load(args.venue_id)
        if progress.last_offset > 0:
            logger.info(
                f"⏩ 检测到上次进度：已抓取 {progress.saved_count} 篇，"
                f"从 offset={progress.last_offset} 继续。"
            )

    # ── 获取总量 ────────────────────────────────────────────────────
    # fetch_total() 返回：正数=已知总数；-1=API不提供总数但可分页；0=连接失败
    if progress.total == 0:
        logger.info("🔍 正在验证 API 连通性…")
        progress.total = client.fetch_total()
        if progress.total == 0:
            logger.error("❌ 无法连接 API，请检查网络或 venue_id。")
            sys.exit(1)
        elif progress.total == -1:
            logger.info("📚 API 不提供论文总数，将持续翻页直到返回空列表。")
        else:
            logger.info(f"📚 论文总数：{progress.total:,} 篇")
        prog_mgr.save(progress)

    # 进度条上限
    if args.limit > 0:
        total_to_fetch: int | None = args.limit
    elif progress.total > 0:
        total_to_fetch = progress.total
    else:
        total_to_fetch = None  # 未知总数，进度条不显示上限

    # ── 初始化存储 ──────────────────────────────────────────────────
    writers = []
    jw: JsonWriter | None = None
    cw: CsvWriter | None = None
    dw: DbWriter | None = None

    resume = not args.reset  # reset=True 时不续传

    if fmt in ("json", "all"):
        jw = JsonWriter(json_path)
        jw.open(resume=resume)
        writers.append(jw)

    if fmt in ("csv", "all"):
        cw = CsvWriter(csv_path)
        cw.open()
        writers.append(cw)

    if fmt in ("db", "all"):
        dw = DbWriter(db_path)
        dw.open()
        writers.append(dw)

    # ── 进度条 ──────────────────────────────────────────────────────
    pbar = tqdm(
        total=total_to_fetch,
        initial=progress.saved_count,
        unit="篇",
        desc="抓取论文",
        ncols=80,
    )

    logger.info(f"🚀 开始抓取（格式：{fmt}，输出目录：{output_dir}）")
    print()

    try:
        for papers, offset in client.iter_all_papers(
            start_offset=progress.last_offset,
            limit=args.limit,
        ):
            if not papers:
                continue

            # 写入所有格式
            for w in writers:
                w.write_batch(papers)

            # 更新进度
            progress.last_offset = offset + config.PAGE_SIZE
            progress.saved_count += len(papers)
            prog_mgr.save(progress)

            pbar.update(len(papers))

    except KeyboardInterrupt:
        logger.info("\n⏸  用户中断。进度已保存，下次运行将从断点继续。")
    finally:
        pbar.close()
        # 在关闭前先记录 db 数量
        db_count = dw.count() if dw is not None else 0
        for w in writers:
            w.close()

    # ── 最终合并 / 汇报 ─────────────────────────────────────────────
    if jw is not None:
        count = jw.flush()
        logger.info(f"✅ JSON 已保存：{json_path}（共 {count:,} 篇）")

    if cw is not None:
        logger.info(f"✅ CSV  已保存：{csv_path}")

    if dw is not None:
        logger.info(f"✅ SQLite 已保存：{db_path}（共 {db_count:,} 篇）")

    logger.info(f"\n🎉 抓取完成！共获取 {progress.saved_count:,} 篇论文。")


if __name__ == "__main__":
    main()
