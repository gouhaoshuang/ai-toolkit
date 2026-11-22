#!/usr/bin/env python3
"""Video ingestion helper for gemini-course-notes (YouTube & Bilibili).

Intended to run in the local `agent` conda environment:
  /data/ghs/miniconda3/envs/agent/bin/python scripts/video_ingest.py fetch <URL> --out <dir>
  /data/ghs/miniconda3/envs/agent/bin/python scripts/video_ingest.py frames <dir> [options]
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

DEFAULT_COOKIES_DIR = Path.home() / ".config" / "gemini-course-notes"
DEFAULT_ASR_MODEL = "large-v3-turbo"
DEFAULT_MIN_FREE_VRAM_MB = 6144

COOKIE_ERROR_PATTERNS = (
    "sign in to confirm",
    "not a bot",
    "use --cookies",
    "cookies-from-browser",
    "login required",
    "requires login",
    "http error 412",
    "需要登录",
    "大会员",
    "请先登录",
    "account is required",
    "members-only",
    "private video",
)

URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]{}]+")
VTT_TAG_RE = re.compile(r"<[^>]+>")
TS_VTT_RE = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})"
)
SHOWINFO_PTS_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


class IngestError(RuntimeError):
    exit_code = 1


class CookieRequiredError(IngestError):
    exit_code = 2

    def __init__(self, platform: str, detail: str) -> None:
        self.platform = platform
        self.detail = detail
        super().__init__(
            f"{platform} 视频需要登录态 cookies 才能继续获取。原始错误: {detail}"
        )


class NoFreeGPUError(IngestError):
    exit_code = 3

    def __init__(self, gpus: list[dict[str, Any]], min_free_mb: int) -> None:
        self.gpus = gpus
        self.min_free_mb = min_free_mb
        lines = [
            f"当前没有空闲显存 >= {min_free_mb} MiB 的 GPU，已停止 ASR 转写以避免挤占其他任务："
        ]
        for gpu in gpus:
            lines.append(
                f"  GPU {gpu['index']} ({gpu['name']}): "
                f"空闲 {gpu['memory_free_mb']} MiB / 总计 {gpu['memory_total_mb']} MiB, "
                f"利用率 {gpu['utilization_pct']}%"
            )
        super().__init__("\n".join(lines))


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    return "other"


def resolve_cookies_path(
    platform: str,
    explicit_path: str | None = None,
    cookies_dir: Path = DEFAULT_COOKIES_DIR,
) -> Path | None:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not path.is_file():
            raise IngestError(f"指定的 cookies 文件不存在: {path}")
        return path
    candidates = [cookies_dir / f"{platform}.txt", cookies_dir / "cookies.txt"]
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def looks_like_cookie_error(stderr: str) -> bool:
    lower = stderr.lower()
    return any(pat in lower for pat in COOKIE_ERROR_PATTERNS)


def format_timestamp(seconds: float, force_hours: bool = False) -> str:
    total = max(0, int(round(seconds)))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0 or force_hours:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def format_timestamp_filename(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    if hrs > 0:
        return f"{hrs:02d}h{mins:02d}m{secs:02d}s"
    return f"{mins:02d}m{secs:02d}s"


def parse_time_str(text: str) -> float:
    text = text.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise IngestError(f"无法解析时间格式: {text!r}（支持 秒 / MM:SS / HH:MM:SS）")


def parse_time_ranges(ranges_str: str) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    for item in ranges_str.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" not in item:
            raise IngestError(f"时间范围格式应为 start-end，收到: {item!r}")
        left, right = item.split("-", 1)
        start = parse_time_str(left)
        end = parse_time_str(right)
        if end <= start:
            raise IngestError(f"时间范围结束必须大于开始: {item!r}")
        ranges.append((start, end))
    return ranges


def extract_links_from_description(description: str) -> list[str]:
    if not description:
        return []
    seen: set[str] = set()
    links: list[str] = []
    for match in URL_RE.findall(description):
        cleaned = match.rstrip(".,;:!?，。；：！？")
        if cleaned not in seen:
            seen.add(cleaned)
            links.append(cleaned)
    return links


def query_gpus(
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> list[dict[str, Any]]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.free,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    if runner is None:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    else:
        proc = runner(cmd)
    if proc.returncode != 0:
        raise IngestError(f"无法查询 GPU 状态 (nvidia-smi): {proc.stderr.strip()}")
    gpus: list[dict[str, Any]] = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            gpus.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "memory_free_mb": int(float(parts[2])),
                    "memory_total_mb": int(float(parts[3])),
                    "utilization_pct": int(float(parts[4])),
                }
            )
        except ValueError:
            continue
    return gpus


def select_free_gpu(
    min_free_mb: int = DEFAULT_MIN_FREE_VRAM_MB,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    gpus = query_gpus(runner=runner)
    if not gpus:
        raise IngestError("未检测到可用 NVIDIA GPU。")
    eligible = [g for g in gpus if g["memory_free_mb"] >= min_free_mb]
    if not eligible:
        raise NoFreeGPUError(gpus, min_free_mb)
    eligible.sort(key=lambda g: (-g["memory_free_mb"], g["utilization_pct"], g["index"]))
    return eligible[0]


def _yt_dlp_base_cmd(
    platform: str = "other",
    proxy: str | None = None,
    cookies: Path | None = None,
) -> list[str]:
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings"]
    if proxy is not None:
        cmd.extend(["--proxy", proxy])
    elif platform == "bilibili":
        # Domestic site: bypass overseas terminal proxy by default unless user passed --proxy
        cmd.extend(["--proxy", ""])
    if cookies:
        cmd.extend(["--cookies", str(cookies)])
    return cmd


def _run_yt_dlp(
    args: list[str],
    platform: str,
    proxy: str | None = None,
    cookies: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = _yt_dlp_base_cmd(platform=platform, proxy=proxy, cookies=cookies) + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if looks_like_cookie_error(err):
            raise CookieRequiredError(platform, err.splitlines()[-1] if err else "需要 cookies")
        raise IngestError(f"yt-dlp 执行失败: {err}")
    return proc


def _clean_caption_text(raw: str) -> str:
    text = VTT_TAG_RE.sub("", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _ts_groups_to_seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return (int(h) if h else 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _dedup_caption_segments(
    raw_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse rolling/overlapping YouTube VTT auto-caption duplicates."""
    cleaned: list[dict[str, Any]] = []
    for seg in raw_segments:
        text = seg["text"].strip()
        if not text:
            continue
        start = float(seg["start"])
        end = float(seg["end"])
        if not cleaned:
            cleaned.append({"start": start, "end": end, "text": text})
            continue
        prev = cleaned[-1]
        prev_text = prev["text"]
        if text == prev_text:
            prev["end"] = max(prev["end"], end)
            continue
        # Rolling caption: new cue starts with previous cue text (extending it)
        if text.startswith(prev_text) and len(text) > len(prev_text):
            prev["text"] = text
            prev["end"] = max(prev["end"], end)
            continue
        # Rolling caption: previous cue ends with new cue text (already captured)
        if prev_text.endswith(text) and (start - prev["end"]) <= 2.0:
            prev["end"] = max(prev["end"], end)
            continue
        # Partial line overlap: strip overlapping prefix from new text
        overlap_stripped = _strip_overlap(prev_text, text)
        if not overlap_stripped:
            prev["end"] = max(prev["end"], end)
            continue
        cleaned.append({"start": start, "end": end, "text": overlap_stripped})
    return cleaned


def _strip_overlap(prev: str, curr: str) -> str:
    max_len = min(len(prev), len(curr))
    best = 0
    for k in range(max_len, 3, -1):
        if prev.endswith(curr[:k]):
            best = k
            break
    if best > 0:
        return curr[best:].strip()
    return curr


def parse_vtt_or_srt(content: str) -> list[dict[str, Any]]:
    raw_segments: list[dict[str, Any]] = []
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    n = len(lines)
    while i < n:
        match = TS_VTT_RE.search(lines[i])
        if not match:
            i += 1
            continue
        start = _ts_groups_to_seconds(match.group(1), match.group(2), match.group(3), match.group(4))
        end = _ts_groups_to_seconds(match.group(5), match.group(6), match.group(7), match.group(8))
        i += 1
        text_lines: list[str] = []
        while i < n and lines[i].strip() != "":
            cleaned = _clean_caption_text(lines[i])
            if cleaned:
                text_lines.append(cleaned)
            i += 1
        if text_lines:
            joined = " ".join(text_lines)
            raw_segments.append({"start": start, "end": end, "text": joined})
    return _dedup_caption_segments(raw_segments)


def parse_json3(content: str) -> list[dict[str, Any]]:
    data = json.loads(content)
    raw_segments: list[dict[str, Any]] = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = _clean_caption_text("".join(s.get("utf8", "") for s in segs))
        if not text:
            continue
        start = float(event.get("tStartMs", 0)) / 1000.0
        dur = float(event.get("dDurationMs", 0)) / 1000.0
        raw_segments.append({"start": start, "end": start + max(dur, 0.1), "text": text})
    return _dedup_caption_segments(raw_segments)


def parse_subtitle_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json3":
        return parse_json3(text)
    return parse_vtt_or_srt(text)


def choose_subtitle_track(
    info: dict[str, Any],
    allow_auto: bool = True,
) -> tuple[str, str] | None:
    """Return (kind, lang_code) where kind is 'manual' or 'auto', or None."""
    video_lang = (info.get("language") or "").strip().lower()

    def rank_langs(available: dict[str, Any], is_auto: bool) -> list[str]:
        keys = [k for k in available.keys() if k.lower() != "live_chat"]
        if not keys:
            return []
        preferred: list[str] = []
        if video_lang:
            for k in keys:
                kl = k.lower()
                if kl == f"{video_lang}-orig" or kl == video_lang or kl.startswith(f"{video_lang}-"):
                    preferred.append(k)
        # For auto captions, never pick translated captions into another language
        if is_auto:
            for k in keys:
                if k.lower().endswith("-orig") and k not in preferred:
                    preferred.insert(0, k)
            if video_lang and preferred:
                return preferred
            for fallback in ("zh-Hans", "zh-CN", "zh", "ai-zh", "en-orig", "en", "en-US"):
                for k in keys:
                    if k.lower() == fallback.lower() and k not in preferred:
                        preferred.append(k)
            return preferred

        # Manual subtitles: prefer native language, then Chinese/English
        for fallback in ("zh-Hans", "zh-CN", "zh", "zh-Hant", "en", "en-US", "en-GB"):
            for k in keys:
                if k.lower() == fallback.lower() and k not in preferred:
                    preferred.append(k)
        for k in keys:
            if k not in preferred:
                preferred.append(k)
        return preferred

    manual = info.get("subtitles") or {}
    manual_ranked = rank_langs(manual, is_auto=False)
    if manual_ranked:
        return ("manual", manual_ranked[0])

    if allow_auto:
        auto = info.get("automatic_captions") or {}
        auto_ranked = rank_langs(auto, is_auto=True)
        if auto_ranked:
            return ("auto", auto_ranked[0])

    return None


def write_transcript_outputs(
    out_dir: Path,
    segments: list[dict[str, Any]],
    duration_sec: float = 0.0,
) -> dict[str, Any]:
    force_hours = duration_sec >= 3600 or any(s["end"] >= 3600 for s in segments)
    raw_lines: list[str] = []
    timed_lines: list[str] = []
    jsonl_lines: list[str] = []

    for idx, seg in enumerate(segments, start=1):
        text = re.sub(r"\s+", " ", seg["text"]).strip()
        if not text:
            continue
        start = round(float(seg["start"]), 3)
        end = round(float(seg["end"]), 3)
        line_no = len(raw_lines) + 1
        raw_lines.append(text)
        ts_str = format_timestamp(start, force_hours=force_hours)
        timed_lines.append(f"[{ts_str}] {text}")
        jsonl_lines.append(
            json.dumps(
                {"line": line_no, "start": start, "end": end, "text": text},
                ensure_ascii=False,
            )
        )

    (out_dir / "transcript_raw.txt").write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    (out_dir / "transcript_timed.txt").write_text("\n".join(timed_lines) + "\n", encoding="utf-8")
    (out_dir / "transcript_timed.jsonl").write_text("\n".join(jsonl_lines) + "\n", encoding="utf-8")
    return {
        "line_count": len(raw_lines),
        "char_count": sum(len(x) for x in raw_lines),
    }


def transcribe_with_faster_whisper(
    audio_path: Path,
    model_name: str,
    gpu_info: dict[str, Any],
    language: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from faster_whisper import WhisperModel  # type: ignore

    model = WhisperModel(
        model_name,
        device="cuda",
        device_index=int(gpu_info["index"]),
        compute_type="float16",
    )
    kwargs: dict[str, Any] = {
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 500},
        "beam_size": 5,
    }
    if language:
        kwargs["language"] = language
    seg_iter, info = model.transcribe(str(audio_path), **kwargs)
    segments: list[dict[str, Any]] = []
    for seg in seg_iter:
        text = seg.text.strip()
        if text:
            segments.append({"start": float(seg.start), "end": float(seg.end), "text": text})
    asr_meta = {
        "model": model_name,
        "language": getattr(info, "language", None),
        "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        "gpu": gpu_info,
    }
    return segments, asr_meta


def cmd_fetch(args: argparse.Namespace) -> int:
    url = args.url.strip()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    platform = detect_platform(url)
    cookies = resolve_cookies_path(platform, explicit_path=args.cookies)

    # 1. Fetch metadata
    meta_proc = _run_yt_dlp(
        ["--dump-single-json", "--no-playlist", url],
        platform=platform,
        proxy=args.proxy,
        cookies=cookies,
    )
    info = json.loads(meta_proc.stdout)
    duration_sec = float(info.get("duration") or 0.0)
    description = info.get("description") or ""
    chapters = [
        {
            "title": ch.get("title") or "",
            "start_time": float(ch.get("start_time") or 0.0),
            "end_time": float(ch.get("end_time") or 0.0),
        }
        for ch in (info.get("chapters") or [])
    ]

    segments: list[dict[str, Any]] = []
    transcript_source = ""
    transcript_lang = info.get("language") or ""
    asr_meta: dict[str, Any] | None = None

    # 2. Try subtitles first unless --force-asr
    if not args.force_asr:
        chosen = choose_subtitle_track(info, allow_auto=not args.no_auto_subs)
        if chosen is not None:
            kind, lang = chosen
            sub_dir = out_dir / "raw_subtitles"
            sub_dir.mkdir(parents=True, exist_ok=True)
            sub_flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
            try:
                _run_yt_dlp(
                    [
                        "--skip-download",
                        "--no-playlist",
                        sub_flag,
                        "--sub-langs",
                        lang,
                        "--sub-format",
                        "json3/vtt/srt/best",
                        "-o",
                        str(sub_dir / "subtitle.%(ext)s"),
                        url,
                    ],
                    platform=platform,
                    proxy=args.proxy,
                    cookies=cookies,
                )
                sub_files = sorted(
                    p for p in sub_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in {".json3", ".vtt", ".srt"}
                )
                if sub_files:
                    segments = parse_subtitle_file(sub_files[0])
                    if segments:
                        transcript_source = f"{kind}_subtitle"
                        transcript_lang = lang
            except CookieRequiredError:
                raise
            except IngestError as exc:
                print(f"[warn] 字幕下载失败，将尝试本地 ASR 兜底: {exc}", file=sys.stderr)

    # 3. Fallback to local GPU faster-whisper ASR
    if not segments:
        gpu_info = select_free_gpu(min_free_mb=args.min_free_vram_mb)
        audio_dir = out_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_tpl = str(audio_dir / "audio.%(ext)s")
        _run_yt_dlp(
            [
                "--no-playlist",
                "-f",
                "bestaudio/best",
                "-o",
                audio_tpl,
                url,
            ],
            platform=platform,
            proxy=args.proxy,
            cookies=cookies,
        )
        audio_files = sorted(p for p in audio_dir.iterdir() if p.is_file() and not p.name.endswith(".part"))
        if not audio_files:
            raise IngestError("音频下载完成但未找到音频文件。")
        audio_path = audio_files[0]
        segments, asr_meta = transcribe_with_faster_whisper(
            audio_path=audio_path,
            model_name=args.asr_model,
            gpu_info=gpu_info,
            language=args.asr_language,
        )
        if not segments:
            raise IngestError("faster-whisper 转写结果为空。")
        transcript_source = "faster_whisper"
        transcript_lang = asr_meta.get("language") or transcript_lang
        if not args.keep_audio:
            shutil.rmtree(audio_dir, ignore_errors=True)

    stats = write_transcript_outputs(out_dir, segments, duration_sec=duration_sec)

    meta = {
        "url": url,
        "webpage_url": info.get("webpage_url") or url,
        "platform": platform,
        "id": info.get("id") or "",
        "title": info.get("title") or "",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "upload_date": info.get("upload_date") or "",
        "duration_sec": duration_sec,
        "duration_str": format_timestamp(duration_sec),
        "language": info.get("language") or "",
        "chapters": chapters,
        "description": description,
        "extracted_links": extract_links_from_description(description),
        "available_manual_subtitles": sorted((info.get("subtitles") or {}).keys()),
        "available_auto_subtitles": sorted((info.get("automatic_captions") or {}).keys()),
        "cookies_used": bool(cookies),
        "transcript_source": transcript_source,
        "transcript_language": transcript_lang,
        "transcript_lines": stats["line_count"],
        "transcript_chars": stats["char_count"],
        "asr": asr_meta,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = {
        "out_dir": str(out_dir),
        "title": meta["title"],
        "platform": platform,
        "duration": meta["duration_str"],
        "chapters_count": len(chapters),
        "extracted_links_count": len(meta["extracted_links"]),
        "transcript_source": transcript_source,
        "transcript_language": transcript_lang,
        "transcript_lines": stats["line_count"],
        "transcript_chars": stats["char_count"],
        "asr_gpu": asr_meta["gpu"]["index"] if asr_meta else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def line_ranges_to_time_ranges(
    timed_jsonl_path: Path,
    line_ranges_str: str,
) -> list[tuple[float, float]]:
    entries: dict[int, dict[str, Any]] = {}
    for raw in timed_jsonl_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        obj = json.loads(raw)
        entries[int(obj["line"])] = obj
    if not entries:
        raise IngestError(f"时间戳索引为空: {timed_jsonl_path}")
    max_line = max(entries.keys())
    ranges: list[tuple[float, float]] = []
    for item in line_ranges_str.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" not in item:
            raise IngestError(f"行号范围格式应为 start-end，收到: {item!r}")
        a_str, b_str = item.split("-", 1)
        a, b = int(a_str), int(b_str)
        if a < 1 or b < a or b > max_line:
            raise IngestError(f"行号范围越界: {item!r}（有效 1-{max_line}）")
        start_sec = float(entries[a]["start"])
        end_sec = float(entries[b]["end"])
        if end_sec <= start_sec:
            end_sec = start_sec + 1.0
        ranges.append((start_sec, end_sec))
    return ranges


def compute_dhash(image_path: Path, hash_size: int = 8) -> int:
    import cv2  # type: ignore

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise IngestError(f"无法读取图像: {image_path}")
    resized = cv2.resize(img, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    bits = 0
    for val in diff.flatten():
        bits = (bits << 1) | int(bool(val))
    return bits


def hamming_distance(h1: int, h2: int) -> int:
    return (h1 ^ h2).bit_count()


def deduplicate_frames(
    candidates: list[dict[str, Any]],
    min_interval: float = 4.0,
    hash_distance: int = 8,
    max_frames: int = 24,
) -> list[dict[str, Any]]:
    """Deduplicate candidate frames with timestamp + dHash Hamming distance."""
    kept: list[dict[str, Any]] = []
    for cand in sorted(candidates, key=lambda c: c["timestamp"]):
        if not kept:
            kept.append(cand)
            continue
        prev = kept[-1]
        if cand["timestamp"] - prev["timestamp"] < min_interval:
            continue
        if hamming_distance(cand["dhash"], prev["dhash"]) < hash_distance:
            continue
        kept.append(cand)

    if len(kept) <= max_frames:
        return kept

    # Evenly downsample while always preserving first and last frame
    if max_frames <= 1:
        return kept[:1]
    indices = [
        round(i * (len(kept) - 1) / (max_frames - 1))
        for i in range(max_frames)
    ]
    selected: list[dict[str, Any]] = []
    seen_idx: set[int] = set()
    for idx in indices:
        if idx not in seen_idx:
            seen_idx.add(idx)
            selected.append(kept[idx])
    return selected


def find_nearest_line(timed_entries: list[dict[str, Any]], timestamp: float) -> int | None:
    if not timed_entries:
        return None
    best_line = int(timed_entries[0]["line"])
    best_dist = abs(float(timed_entries[0]["start"]) - timestamp)
    for entry in timed_entries:
        start = float(entry["start"])
        end = float(entry["end"])
        if start <= timestamp <= end:
            return int(entry["line"])
        dist = min(abs(start - timestamp), abs(end - timestamp))
        if dist < best_dist:
            best_dist = dist
            best_line = int(entry["line"])
    return best_line


def _extract_candidates_ffmpeg(
    video_path: Path,
    tmp_dir: Path,
    scene_threshold: float,
    sample_interval: float,
    offset_sec: float = 0.0,
) -> list[dict[str, Any]]:
    vf = (
        f"select='gt(scene,{scene_threshold})+isnan(prev_selected_t)"
        f"+gte(t-prev_selected_t,{sample_interval})',showinfo"
    )
    pattern = str(tmp_dir / "cand_%05d.png")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(video_path),
        "-vf",
        vf,
        "-vsync",
        "vfr",
        pattern,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise IngestError(f"ffmpeg 抽帧失败: {proc.stderr[-500:]}")
    pts_list = [float(m.group(1)) for m in SHOWINFO_PTS_RE.finditer(proc.stderr)]
    pngs = sorted(tmp_dir.glob("cand_*.png"))
    candidates: list[dict[str, Any]] = []
    for idx, png in enumerate(pngs):
        ts = offset_sec + (pts_list[idx] if idx < len(pts_list) else float(idx) * sample_interval)
        candidates.append(
            {
                "path": png,
                "timestamp": round(ts, 2),
                "dhash": compute_dhash(png),
            }
        )
    return candidates


def cmd_frames(args: argparse.Namespace) -> int:
    video_dir = Path(args.video_dir).expanduser().resolve()
    meta_path = video_dir / "meta.json"
    if not meta_path.is_file():
        raise IngestError(f"未找到 meta.json，请先运行 fetch: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    url = meta["url"]
    platform = meta.get("platform") or detect_platform(url)
    duration_sec = float(meta.get("duration_sec") or 0.0)
    cookies = resolve_cookies_path(platform, explicit_path=args.cookies)

    timed_entries: list[dict[str, Any]] = []
    timed_jsonl = video_dir / "transcript_timed.jsonl"
    if timed_jsonl.is_file():
        for raw in timed_jsonl.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                timed_entries.append(json.loads(raw))

    ranges: list[tuple[float, float]] = []
    if args.ranges:
        ranges.extend(parse_time_ranges(args.ranges))
    if args.line_ranges:
        if not timed_jsonl.is_file():
            raise IngestError(f"使用 --line-ranges 需要 {timed_jsonl}")
        ranges.extend(line_ranges_to_time_ranges(timed_jsonl, args.line_ranges))

    frames_dir = video_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    # Clean old extracted frames if re-running
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()

    fmt = f"bestvideo[height<={args.max_height}][ext=mp4]/best[height<={args.max_height}]/best"
    dl_dir = video_dir / "_video_tmp"
    dl_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[dict[str, Any]] = []

    try:
        with tempfile.TemporaryDirectory(prefix="course_frames_") as cand_tmp:
            cand_root = Path(cand_tmp)
            if ranges:
                # Download each requested section individually if supported, else fallback to full video
                section_ok = True
                for r_idx, (start_s, end_s) in enumerate(ranges, start=1):
                    sec_tpl = str(dl_dir / f"sec_{r_idx}.%(ext)s")
                    try:
                        _run_yt_dlp(
                            [
                                "--no-playlist",
                                "-f",
                                fmt,
                                "--download-sections",
                                f"*{start_s:.1f}-{end_s:.1f}",
                                "-o",
                                sec_tpl,
                                url,
                            ],
                            platform=platform,
                            proxy=args.proxy,
                            cookies=cookies,
                        )
                    except CookieRequiredError:
                        raise
                    except IngestError:
                        section_ok = False
                        break
                    sec_files = sorted(
                        p for p in dl_dir.glob(f"sec_{r_idx}.*") if not p.name.endswith(".part")
                    )
                    if not sec_files:
                        section_ok = False
                        break
                    sub_tmp = cand_root / f"sec_{r_idx}"
                    sub_tmp.mkdir(parents=True, exist_ok=True)
                    candidates.extend(
                        _extract_candidates_ffmpeg(
                            video_path=sec_files[0],
                            tmp_dir=sub_tmp,
                            scene_threshold=args.scene_threshold,
                            sample_interval=args.sample_interval,
                            offset_sec=start_s,
                        )
                    )
                if not section_ok:
                    candidates.clear()
                    ranges_filter = ranges
                else:
                    ranges_filter = []
            else:
                ranges_filter = []

            if not candidates:
                video_tpl = str(dl_dir / "video.%(ext)s")
                _run_yt_dlp(
                    ["--no-playlist", "-f", fmt, "-o", video_tpl, url],
                    platform=platform,
                    proxy=args.proxy,
                    cookies=cookies,
                )
                vid_files = sorted(
                    p for p in dl_dir.glob("video.*") if not p.name.endswith(".part")
                )
                if not vid_files:
                    raise IngestError("视频下载完成但未找到视频文件。")
                full_tmp = cand_root / "full"
                full_tmp.mkdir(parents=True, exist_ok=True)
                all_cands = _extract_candidates_ffmpeg(
                    video_path=vid_files[0],
                    tmp_dir=full_tmp,
                    scene_threshold=args.scene_threshold,
                    sample_interval=args.sample_interval,
                    offset_sec=0.0,
                )
                if ranges_filter:
                    candidates = [
                        c
                        for c in all_cands
                        if any(s <= c["timestamp"] <= e for s, e in ranges_filter)
                    ]
                else:
                    candidates = all_cands

            selected = deduplicate_frames(
                candidates,
                min_interval=args.min_interval,
                hash_distance=args.hash_distance,
                max_frames=args.max_frames,
            )

            force_hours = duration_sec >= 3600
            manifest_frames: list[dict[str, Any]] = []
            for idx, item in enumerate(selected, start=1):
                ts = item["timestamp"]
                fname = f"frame_{idx:03d}_{format_timestamp_filename(ts)}.png"
                dest = frames_dir / fname
                shutil.copy2(item["path"], dest)
                manifest_frames.append(
                    {
                        "index": idx,
                        "file": f"frames/{fname}",
                        "timestamp": ts,
                        "timestamp_str": format_timestamp(ts, force_hours=force_hours),
                        "line": find_nearest_line(timed_entries, ts),
                    }
                )
    finally:
        if not args.keep_video:
            shutil.rmtree(dl_dir, ignore_errors=True)

    manifest = {
        "video_dir": str(video_dir),
        "title": meta.get("title") or "",
        "ranges": ranges,
        "candidates_count": len(candidates),
        "frames_count": len(manifest_frames),
        "frames": manifest_frames,
    }
    (frames_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "frames_dir": str(frames_dir),
                "candidates_count": len(candidates),
                "frames_count": len(manifest_frames),
                "manifest": str(frames_dir / "manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="YouTube/Bilibili video ingestion for gemini-course-notes."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="拉取视频元信息并获取带时间戳逐字稿（字幕优先，GPU ASR 兜底）")
    p_fetch.add_argument("url", help="YouTube 或 Bilibili 视频链接")
    p_fetch.add_argument("--out", required=True, help="输出目录（建议放在课程工作目录的 sources/video）")
    p_fetch.add_argument("--proxy", default=None, help="可选代理地址；默认继承终端环境变量")
    p_fetch.add_argument("--cookies", default=None, help="可选 cookies.txt 路径；默认自动检测 ~/.config/gemini-course-notes/")
    p_fetch.add_argument("--force-asr", action="store_true", help="跳过字幕，直接使用本地 GPU faster-whisper 转写")
    p_fetch.add_argument("--no-auto-subs", action="store_true", help="不使用平台自动字幕（仅人工字幕，否则走本地 ASR）")
    p_fetch.add_argument("--asr-model", default=DEFAULT_ASR_MODEL, help=f"faster-whisper 模型（默认 {DEFAULT_ASR_MODEL}）")
    p_fetch.add_argument("--asr-language", default=None, help="可选指定 ASR 语言代码（如 zh / en），默认自动检测")
    p_fetch.add_argument("--min-free-vram-mb", type=int, default=DEFAULT_MIN_FREE_VRAM_MB, help=f"选择空闲 GPU 所需最小空闲显存 MiB（默认 {DEFAULT_MIN_FREE_VRAM_MB}）")
    p_fetch.add_argument("--keep-audio", action="store_true", help="ASR 完成后保留临时下载的音频文件")
    p_fetch.set_defaults(func=cmd_fetch)

    p_frames = sub.add_parser("frames", help="按需动态抽取 PPT / 关键帧截图（去重并附带时间戳与行号）")
    p_frames.add_argument("video_dir", help="fetch 生成的视频素材目录")
    p_frames.add_argument("--ranges", default=None, help="逗号分隔的时间段，如 00:05:00-00:15:00,00:25:00-00:35:00")
    p_frames.add_argument("--line-ranges", default=None, help="逗号分隔的逐字稿行号段，如 1-50,120-180")
    p_frames.add_argument("--max-frames", type=int, default=24, help="最多保留的关键帧数量（默认 24）")
    p_frames.add_argument("--scene-threshold", type=float, default=0.08, help="ffmpeg 场景变化阈值（默认 0.08）")
    p_frames.add_argument("--sample-interval", type=float, default=30.0, help="保底周期采样间隔秒数（默认 30.0）")
    p_frames.add_argument("--min-interval", type=float, default=4.0, help="相邻保留帧的最小时间间隔秒数（默认 4.0）")
    p_frames.add_argument("--hash-distance", type=int, default=8, help="相邻保留帧的最小 dHash 汉明距离（默认 8）")
    p_frames.add_argument("--max-height", type=int, default=720, help="下载视频最大高度像素（默认 720）")
    p_frames.add_argument("--proxy", default=None, help="可选代理地址")
    p_frames.add_argument("--cookies", default=None, help="可选 cookies.txt 路径")
    p_frames.add_argument("--keep-video", action="store_true", help="抽帧后保留临时视频文件")
    p_frames.set_defaults(func=cmd_frames)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except IngestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
