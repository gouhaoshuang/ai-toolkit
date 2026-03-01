# config.py — 全局配置

# ── 目标期刊/会议 ──────────────────────────────────────────────────
DEFAULT_VENUE_ID = "5ea1c5c1edb6e7d53c00e7ad"  # Design Automation Conference (DAC)
DEFAULT_VENUE_NAME = "Design Automation Conference"

# ── API 配置 ────────────────────────────────────────────────────────
API_BASE_URL = "https://datacenter.aminer.cn/venue/magic"
API_ACTION = "venuePro.GetRecentVenueAndPublication"
PAGE_SIZE = 20  # 每次请求论文数量（建议 ≤ 20）

# ── 请求头（模拟浏览器）────────────────────────────────────────────
REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.aminer.cn/",
    "Origin": "https://www.aminer.cn",
}

# ── 限速与重试 ──────────────────────────────────────────────────────
REQUEST_DELAY = 0.8  # 每次请求间隔（秒）
MAX_RETRIES = 3  # 最大重试次数
RETRY_BACKOFF = 2.0  # 重试指数退避基数（秒）
REQUEST_TIMEOUT = 30  # 单次请求超时（秒）

# ── 输出配置 ────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
JSON_FILENAME = "papers.json"
CSV_FILENAME = "papers.csv"
DB_FILENAME = "papers.db"
PROGRESS_FILE = "progress.json"
