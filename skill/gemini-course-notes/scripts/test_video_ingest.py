#!/usr/bin/env python3
"""Offline unit tests for video_ingest.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import video_ingest as vi


class TestVideoIngest(unittest.TestCase):
    def test_detect_platform(self) -> None:
        self.assertEqual(vi.detect_platform("https://www.youtube.com/watch?v=abc"), "youtube")
        self.assertEqual(vi.detect_platform("https://youtu.be/abc"), "youtube")
        self.assertEqual(vi.detect_platform("https://www.bilibili.com/video/BV17YHY6LEPN/"), "bilibili")
        self.assertEqual(vi.detect_platform("https://b23.tv/xyz"), "bilibili")
        self.assertEqual(vi.detect_platform("https://example.com/v"), "other")

    def test_resolve_cookies_priority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cdir = Path(td)
            self.assertIsNone(vi.resolve_cookies_path("bilibili", cookies_dir=cdir))
            generic = cdir / "cookies.txt"
            generic.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            self.assertEqual(vi.resolve_cookies_path("bilibili", cookies_dir=cdir), generic)
            bili = cdir / "bilibili.txt"
            bili.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            self.assertEqual(vi.resolve_cookies_path("bilibili", cookies_dir=cdir), bili)
            self.assertEqual(vi.resolve_cookies_path("youtube", cookies_dir=cdir), generic)

    def test_cookie_error_detection(self) -> None:
        self.assertTrue(vi.looks_like_cookie_error("ERROR: Sign in to confirm you're not a bot."))
        self.assertTrue(vi.looks_like_cookie_error("HTTP Error 412: Precondition Failed"))
        self.assertFalse(vi.looks_like_cookie_error("Network timeout"))

    def test_select_free_gpu_picks_most_free(self) -> None:
        fake_stdout = (
            "0, NVIDIA L40, 2048, 46068, 95\n"
            "1, NVIDIA L40, 44000, 46068, 0\n"
            "2, NVIDIA L40, 18000, 46068, 30\n"
        )

        def fake_runner(_cmd: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(_cmd, 0, stdout=fake_stdout, stderr="")

        gpu = vi.select_free_gpu(min_free_mb=6144, runner=fake_runner)
        self.assertEqual(gpu["index"], 1)
        self.assertEqual(gpu["memory_free_mb"], 44000)

    def test_select_free_gpu_stops_when_all_full(self) -> None:
        fake_stdout = (
            "0, NVIDIA L40, 1200, 46068, 99\n"
            "1, NVIDIA L40, 3500, 46068, 92\n"
        )

        def fake_runner(_cmd: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(_cmd, 0, stdout=fake_stdout, stderr="")

        with self.assertRaises(vi.NoFreeGPUError) as ctx:
            vi.select_free_gpu(min_free_mb=6144, runner=fake_runner)
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertIn("GPU 0", str(ctx.exception))
        self.assertIn("GPU 1", str(ctx.exception))

    def test_parse_vtt_dedups_rolling_captions(self) -> None:
        vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000
<c>Hello world</c>

00:00:03.000 --> 00:00:05.000
Hello world this is a test

00:00:05.000 --> 00:00:07.000
this is a test and more
"""
        segs = vi.parse_vtt_or_srt(vtt)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["text"], "Hello world this is a test")
        self.assertEqual(segs[1]["text"], "and more")

    def test_choose_subtitle_track(self) -> None:
        info = {
            "language": "en",
            "subtitles": {"fr": [{}], "en": [{}]},
            "automatic_captions": {"zh-Hans": [{}], "en-orig": [{}]},
        }
        self.assertEqual(vi.choose_subtitle_track(info), ("manual", "en"))

        info_auto_only = {
            "language": "en",
            "subtitles": {},
            "automatic_captions": {"zh-Hans": [{}], "en-orig": [{}]},
        }
        self.assertEqual(vi.choose_subtitle_track(info_auto_only), ("auto", "en-orig"))
        self.assertIsNone(vi.choose_subtitle_track(info_auto_only, allow_auto=False))

    def test_line_ranges_and_nearest_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            segs = [
                {"start": 0.0, "end": 5.0, "text": "line one"},
                {"start": 5.0, "end": 12.0, "text": "line two"},
                {"start": 12.0, "end": 20.0, "text": "line three"},
            ]
            stats = vi.write_transcript_outputs(out_dir, segs, duration_sec=20.0)
            self.assertEqual(stats["line_count"], 3)
            ranges = vi.line_ranges_to_time_ranges(out_dir / "transcript_timed.jsonl", "1-2,3-3")
            self.assertEqual(ranges, [(0.0, 12.0), (12.0, 20.0)])
            entries = [
                json.loads(line)
                for line in (out_dir / "transcript_timed.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(vi.find_nearest_line(entries, 7.5), 2)

    def test_deduplicate_frames(self) -> None:
        cands = [
            {"timestamp": 1.0, "dhash": 0b0000000000000000, "path": Path("a.png")},
            {"timestamp": 2.0, "dhash": 0b1111111111111111, "path": Path("b.png")},  # too close in time
            {"timestamp": 8.0, "dhash": 0b0000000000000011, "path": Path("c.png")},  # hamming=2 < 8
            {"timestamp": 15.0, "dhash": 0b1111111111110000, "path": Path("d.png")},  # distinct
            {"timestamp": 25.0, "dhash": 0b0000111100001111, "path": Path("e.png")},  # distinct
        ]
        kept = vi.deduplicate_frames(cands, min_interval=4.0, hash_distance=8, max_frames=2)
        self.assertEqual([c["path"].name for c in kept], ["a.png", "e.png"])

    def test_extract_links(self) -> None:
        desc = "Code: https://github.com/org/repo, slides: https://arxiv.org/abs/2401.00001."
        self.assertEqual(
            vi.extract_links_from_description(desc),
            ["https://github.com/org/repo", "https://arxiv.org/abs/2401.00001"],
        )

    def test_bilibili_bypasses_proxy_by_default(self) -> None:
        bili_cmd = vi._yt_dlp_base_cmd(platform="bilibili")
        self.assertIn("--proxy", bili_cmd)
        self.assertEqual(bili_cmd[bili_cmd.index("--proxy") + 1], "")
        yt_cmd = vi._yt_dlp_base_cmd(platform="youtube")
        self.assertNotIn("--proxy", yt_cmd)
        custom_cmd = vi._yt_dlp_base_cmd(platform="bilibili", proxy="http://127.0.0.1:7890")
        self.assertEqual(custom_cmd[custom_cmd.index("--proxy") + 1], "http://127.0.0.1:7890")


if __name__ == "__main__":
    unittest.main()
