"""Local-only invariants: temporary fixtures, fake credentials, no live API calls."""

import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import course_notes as notes


class CourseNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "transcript.txt").write_text("原理介绍\n组内采样\n构造经验\n训练闭环\n", encoding="utf-8")
        (self.root / "code.py").write_text("x = 1\nprint(x)\n", encoding="utf-8")
        (self.root / "slides.pdf").write_bytes(b"%PDF-1.4\nfixture")
        (self.root / "curve.png").write_bytes(b"\x89PNG\r\nfixture")
        self.config = {
            "title": "测试课程", "transcript": "transcript.txt",
            "api": {"env_file": "", "container": ""},
            "parts": [
                {"title": "原理与采样", "lines": [1, 2],
                 "code": [{"path": "code.py", "lines": [[1, 2]]}], "files": ["slides.pdf"]},
                {"title": "训练闭环", "lines": [3, 4], "files": ["curve.png"]},
            ],
        }
        self.output = self.root / "run"
        self.config_file = self.root / "course.json"
        self.fake_key = "fixture-credential-never-use-on-a-real-endpoint"
        # Even a mistakenly unmocked send cannot reach any network or real credential source.
        network = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        credentials = patch.object(notes, "load_key", return_value=self.fake_key)
        self.mock_key = credentials.start()
        self.addCleanup(credentials.stop)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def prepare(self):
        self.config_file.write_text(json.dumps(self.config, ensure_ascii=False), encoding="utf-8")
        self.plan_file = notes.prepare(self.config_file, self.output)
        return notes.read_plan(self.plan_file)

    def response(self, api, key, body, finish="stop"):
        self.assertEqual(key, self.fake_key)
        number = "1" if "第 1/2" in body["messages"][0]["content"][0]["text"] else "2"
        return 200, json.dumps({
            "id": "fixture-" + number, "model": "fixture-model",
            "choices": [{"finish_reason": finish,
                         "message": {"content": "# 单节标题\n\n## 内容\n\n正文 " + number + "\n\n```python\n# 保留代码注释\nprint(1)\n```\n"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }, ensure_ascii=False)

    def test_prepare_freezes_materials_and_builds_pdf_and_image_inputs(self):
        root, plan, _ = self.prepare()
        self.mock_key.assert_not_called()
        prompt = (root / plan["parts"][0]["prompt"]).read_text()
        self.assertIn("```python\nx = 1\nprint(x)\n```", prompt)
        self.assertNotIn("区分讲师", prompt)
        (self.root / "slides.pdf").unlink()
        (self.root / "code.py").unlink()
        first = notes.build_body(root, plan, plan["parts"][0])
        second = notes.build_body(root, plan, plan["parts"][1])
        pdf = first["messages"][0]["content"][1]
        picture = second["messages"][0]["content"][1]
        self.assertEqual(pdf["type"], "file")
        self.assertEqual(base64.b64decode(pdf["file"]["file_data"].split(",", 1)[1]), b"%PDF-1.4\nfixture")
        self.assertEqual(picture["type"], "image_url")
        self.assertTrue(picture["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_rejects_missing_or_overlapping_lines_before_creating_output(self):
        for lines in ([3, 3], [2, 4]):
            self.config["parts"][1]["lines"] = lines
            with self.assertRaises(ValueError):
                self.prepare()
            self.assertFalse(self.output.exists())

    def test_generation_needs_confirmation_and_unchanged_prepared_material(self):
        root, plan, _ = self.prepare()
        with self.assertRaises(ValueError):
            notes.generate(self.plan_file)
        prompt = root / plan["parts"][0]["prompt"]
        prompt.write_text(prompt.read_text() + "changed")
        with self.assertRaises(ValueError):
            notes.generate(self.plan_file, confirmed=True)
        self.mock_key.assert_not_called()

    def test_resume_skips_complete_parts_and_merge_preserves_code(self):
        self.prepare()
        with patch.object(notes, "send", side_effect=self.response) as transport:
            run = notes.generate(self.plan_file, confirmed=True)
            self.assertEqual(transport.call_count, 2)
            notes.generate(self.plan_file, confirmed=True)
            self.assertEqual(transport.call_count, 2)
        originals = {x["file"]: (self.output / x["file"]).read_bytes() for x in run["attempts"]}
        final = notes.merge(self.plan_file).read_text()
        self.assertIn("```python\n# 保留代码注释\nprint(1)\n```", final)
        self.assertEqual(sum(line.startswith("# ") for line in final.splitlines()), 3)  # title plus 2 code comments
        for relative, data in originals.items():
            self.assertEqual((self.output / relative).read_bytes(), data)
        with self.assertRaises(ValueError):
            notes.merge(self.plan_file)

    def test_truncation_is_not_complete_and_retry_is_bounded(self):
        self.prepare()
        with patch.object(notes, "send", side_effect=lambda api, key, body: self.response(api, key, body, "length")) as transport:
            notes.generate(self.plan_file, confirmed=True)
            with self.assertRaises(ValueError):
                notes.merge(self.plan_file)
            self.assertFalse((self.output / "课程笔记.md").exists())
            notes.generate(self.plan_file, confirmed=True)
            self.assertEqual(transport.call_count, 2)
            notes.generate(self.plan_file, confirmed=True, retry_failed=True)
            self.assertEqual(transport.call_count, 4)
            notes.generate(self.plan_file, confirmed=True, retry_failed=True)
            self.assertEqual(transport.call_count, 4)

    def test_error_response_is_redacted_and_never_merged(self):
        self.prepare()
        error = json.dumps({"error": {"message": "invalid " + self.fake_key}})
        with patch.object(notes, "send", return_value=(401, error)):
            notes.generate(self.plan_file, confirmed=True)
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(self.fake_key.encode(), path.read_bytes())
        with self.assertRaises(ValueError):
            notes.merge(self.plan_file)

    def test_interrupted_request_is_not_resent_automatically(self):
        root, plan, plan_hash = self.prepare()
        run = notes.read_run(root, plan_hash)
        run["pending"] = [{"part": 1, "attempt": 1}]
        notes.write_json(root / "run.json", run)
        with patch.object(notes, "send") as transport:
            with self.assertRaises(ValueError):
                notes.generate(self.plan_file, confirmed=True, retry_failed=True)
            transport.assert_not_called()

    def test_remote_endpoint_cannot_reuse_local_credentials_by_default(self):
        with self.assertRaises(ValueError):
            notes.api_config({"base_url": "https://example.invalid/v1"})
        api = notes.api_config({"base_url": "https://example.invalid/v1", "key_env": "EXAMPLE_KEY",
                                "env_file": "", "container": ""})
        self.assertEqual(api["key_env"], "EXAMPLE_KEY")
        with self.assertRaises(ValueError):
            notes.api_config({"api_key": "not-allowed"})

    def test_material_hash_and_unclosed_code_block_prevent_bad_merge(self):
        self.prepare()
        with patch.object(notes, "send", side_effect=self.response):
            run = notes.generate(self.plan_file, confirmed=True)
        selected = self.output / run["attempts"][0]["file"]
        selected.write_text("changed")
        with self.assertRaises(ValueError):
            notes.merge(self.plan_file)
        with self.assertRaises(ValueError):
            notes.format_part("# title\n\n```python\nprint(1)\n")


if __name__ == "__main__":
    unittest.main()
