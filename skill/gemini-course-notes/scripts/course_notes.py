#!/usr/bin/env python3
"""Prepare course materials offline, explicitly generate parts, then merge offline."""

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


DEFAULT_API = {
    "base_url": "http://127.0.0.1:2048/v1",
    "model": "gemini-4-argon",
    "concurrency": 2,
    "max_tokens": 32768,
    "timeout": 600,
    "key_env": "COURSE_NOTES_API_KEY",
    "env_file": "/data/ghs/services/aistudio2api/data/.env",
    "key_name": "PROXY_API_KEY",
    "container": "aistudio2api",
    "container_env_file": "/data/.env",
}
MEDIA = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def emit(data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def span(value, length, label):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} requires [start, end]")
    start, end = [positive(x, label) for x in value]
    if start > end or end > length:
        raise ValueError(f"{label} is outside the source")
    return start, end


def source_path(base, value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def api_config(settings):
    if not isinstance(settings, dict) or set(settings) - set(DEFAULT_API):
        raise ValueError("Unsupported api setting; raw API keys/passwords do not belong in course.json")
    api = {**DEFAULT_API, **settings}
    for field in ("base_url", "key_env", "key_name", "env_file", "container", "container_env_file"):
        if not isinstance(api[field], str):
            raise ValueError(f"{field} must be a string")
    parsed = urlsplit(api["base_url"])
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("base_url must be an HTTP(S) URL without credentials, query or fragment")
    if not local:
        if (parsed.scheme != "https" or not settings.get("key_env")
                or api["env_file"] or api["container"]):
            raise ValueError("Remote endpoints require HTTPS, explicit key_env, and empty env_file/container")
    for field in ("concurrency", "max_tokens", "timeout"):
        positive(api[field], field)
    if api["concurrency"] > 4:
        raise ValueError("Use concurrency 1–4 after checking actual service capacity")
    if not isinstance(api["model"], str) or not api["model"].strip():
        raise ValueError("A model name is required")
    api["base_url"] = api["base_url"].rstrip("/")
    return api


def text_resource(base, item, code=False):
    spec = {"path": item} if isinstance(item, str) else item
    path = source_path(base, spec["path"])
    text = path.read_text(encoding="utf-8")
    ranges = spec.get("lines")
    chunks = [(path.name, text)]
    if ranges is not None:
        if not isinstance(ranges, list) or not ranges:
            raise ValueError("Resource lines must be a nonempty list of ranges")
        lines = text.splitlines()
        chunks = []
        for item_range in ranges:
            start, end = span(item_range, len(lines), path.name)
            chunks.append((f"{path.name}（第 {start}–{end} 行）", "\n".join(lines[start - 1:end])))
    rendered = []
    for caption, text in chunks:
        if code:
            fence = "`" * max(3, max((len(x) + 1 for x in re.findall(r"`+", text)), default=3))
            language = {".py": "python", ".js": "javascript", ".ts": "typescript",
                        ".sh": "bash", ".json": "json"}.get(path.suffix.lower(), "text")
            text = f"{fence}{language}\n{text.rstrip()}\n{fence}"
        rendered.append(f"### {caption}\n\n{text.rstrip()}")
    return "\n\n".join(rendered)


def prepare(config_path, out):
    config_path = Path(config_path).resolve()
    base = config_path.parent
    config = json.loads(config_path.read_text(encoding="utf-8"))
    api = api_config(config.get("api", {}))
    title = config.get("title", "课程笔记")
    if not isinstance(title, str) or not title.strip() or "\n" in title:
        raise ValueError("title must be a single nonempty line")
    source = source_path(base, config["transcript"])
    transcript = source.read_text(encoding="utf-8")
    lines = transcript.splitlines()
    parts = config.get("parts", [])
    if not lines or not isinstance(parts, list) or not parts:
        raise ValueError("A nonempty transcript and parts list are required")
    next_line = 1
    for part in parts:
        start, end = span(part["lines"], len(lines), "transcript range")
        if start != next_line:
            raise ValueError("Parts must be contiguous, nonoverlapping and cover all transcript lines")
        next_line = end + 1
        if not isinstance(part.get("title"), str) or not part["title"].strip() or "\n" in part["title"]:
            raise ValueError("Each part needs a single-line title")
    if next_line != len(lines) + 1:
        raise ValueError("Parts do not cover the whole transcript")
    outline = "；".join(f"{i}. {part['title']}" for i, part in enumerate(parts, 1))
    prepared = []
    materials = {}
    for number, part in enumerate(parts, 1):
        start, end = part["lines"]
        prompt = ("请根据下面的课程录音稿和配套资料，整理成详细、易懂的 Markdown 课程笔记。"
                  f"这是全课第 {number}/{len(parts)} 部分：{part['title']}。请充分讲解本节内容。\n\n"
                  f"全课提纲：{outline}。\n\n## 课程录音稿\n\n"
                  + "\n".join(lines[start - 1:end]))
        code = [text_resource(base, item, code=True) for item in part.get("code", [])]
        text = [text_resource(base, item) for item in part.get("text", [])]
        if code:
            prompt += "\n\n## 配套代码\n\n" + "\n\n".join(code)
        if text:
            prompt += "\n\n## 其他资料\n\n" + "\n\n".join(text)
        attachments = []
        for item in part.get("files", []):
            path = source_path(base, item)
            mime = MEDIA.get(path.suffix.lower())
            if not mime:
                raise ValueError(f"Convert {path.name} to PDF, PNG, JPEG or WebP first")
            content = path.read_bytes()
            relative = "materials/" + digest(content)[:20] + "-" + path.name
            materials[relative] = content
            attachments.append({"path": relative, "mime": mime, "sha256": digest(content)})
        if attachments:
            prompt += "\n\n配套附件：" + "、".join(Path(item["path"]).name[21:] for item in attachments) + "。"
        prompt += "\n"
        prepared.append({"id": number, "title": part["title"], "lines": part["lines"],
                         "prompt": f"prompts/{number:02d}.md", "prompt_sha256": digest(prompt.encode()),
                         "attachments": attachments, "_text": prompt})
    # Validate/read everything before creating the destination; never overwrite a previous run.
    original = (source_path(base, config["original_transcript"]).read_bytes()
                if config.get("original_transcript") else None)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "prompts").mkdir()
    (out / "materials").mkdir()
    for part in prepared:
        (out / part["prompt"]).write_text(part.pop("_text"), encoding="utf-8")
    for relative, content in materials.items():
        (out / relative).write_bytes(content)
    (out / "录音稿_发送版.txt").write_text(transcript, encoding="utf-8")
    if original is not None:
        (out / "录音稿_原始.txt").write_bytes(original)
    plan = {"version": 1, "prepared_at": now(), "title": title, "api": api,
            "transcript_sha256": digest(transcript.encode()), "parts": prepared}
    write_json(out / "plan.json", plan)
    emit({"status": "prepared_offline", "plan": str(out / "plan.json"), "parts": len(parts)})
    return out / "plan.json"


def read_plan(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    plan = json.loads(data)
    if plan.get("version") != 1:
        raise ValueError("Unsupported plan version")
    api_config(plan["api"])
    return path.parent, plan, digest(data)


def checked_file(root, relative, expected):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Prepared paths must remain inside the run directory")
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError("Prepared material changed; create and confirm a new plan")
    return data


def build_body(root, plan, part):
    prompt = checked_file(root, part["prompt"], part["prompt_sha256"]).decode("utf-8")
    content = [{"type": "text", "text": prompt}]
    for attachment in part["attachments"]:
        data = checked_file(root, attachment["path"], attachment["sha256"])
        uri = "data:" + attachment["mime"] + ";base64," + base64.b64encode(data).decode()
        if attachment["mime"] == "application/pdf":
            content.append({"type": "file", "file": {
                "filename": Path(attachment["path"]).name[21:], "file_data": uri}})
        else:
            content.append({"type": "image_url", "image_url": {"url": uri}})
    return {"model": plan["api"]["model"], "messages": [{"role": "user", "content": content}],
            "max_tokens": plan["api"]["max_tokens"], "stream": False}


def parse_env_key(text, name):
    for line in text.splitlines():
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key.strip() == name:
            values = shlex.split(value, comments=True, posix=True)
            if len(values) == 1 and values[0].strip():
                return values[0].split(",", 1)[0].strip()
    return None


def load_key(api):
    value = os.environ.get(api["key_env"])
    if value and value.strip():
        return value.strip()
    if api["env_file"]:
        try:
            value = parse_env_key(Path(api["env_file"]).read_text(encoding="utf-8"), api["key_name"])
            if value:
                return value
        except (OSError, ValueError):
            pass
    if api["container"]:
        try:
            result = subprocess.run(
                ["docker", "exec", api["container"], "cat", api["container_env_file"]],
                capture_output=True, text=True, timeout=20, check=True,
            )
            value = parse_env_key(result.stdout, api["key_name"])
            if value:
                return value
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    raise ValueError("No usable API key; inspect the configured credential source without printing its contents")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(api, key, body):
    request = Request(api["base_url"] + "/chat/completions", data=json.dumps(body).encode(),
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    local = urlsplit(api["base_url"]).hostname in {"127.0.0.1", "localhost", "::1"}
    handlers = [NoRedirect()]
    if local:
        handlers.append(ProxyHandler({}))
    opener = build_opener(*handlers)
    try:
        with opener.open(request, timeout=api["timeout"]) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def read_run(root, plan_hash):
    path = root / "run.json"
    if path.exists():
        run = json.loads(path.read_text(encoding="utf-8"))
        if run["plan_sha256"] != plan_hash:
            raise ValueError("The plan differs from this run; create a new run directory")
        return run
    return {"started_at": now(), "plan_sha256": plan_hash, "attempts": []}


def generate(path, confirmed=False, retry_failed=False):
    if not confirmed:
        raise ValueError("User confirmation is required; use --confirmed only after obtaining it")
    root, plan, plan_hash = read_plan(path)
    run = read_run(root, plan_hash)
    if run.get("pending"):
        raise ValueError("A previous request has unknown completion status; inspect the pending record before resending")
    jobs = []
    for part in plan["parts"]:
        previous = [item for item in run["attempts"] if item["part"] == part["id"]]
        if previous and previous[-1]["status"] == "complete":
            checked_file(root, previous[-1]["file"], previous[-1]["saved_sha256"])
            continue
        if previous and (not retry_failed or len(previous) >= 2):
            continue
        attempt = len(previous) + 1
        stem = f"{part['id']:02d}_attempt{attempt}"
        if any((root / relative).exists() for relative in
               (f"responses/{stem}.txt", f"generated/{stem}.md")):
            raise ValueError("Unrecorded attempt artifacts exist; inspect them before resending")
        jobs.append((part, build_body(root, plan, part), attempt))
    if not jobs:
        emit({"status": "nothing_to_send", "note": "Complete parts skipped; failures require explicit retry and have at most two attempts"})
        return run
    key = load_key(plan["api"])
    for folder in ("generated", "responses"):
        (root / folder).mkdir(exist_ok=True)
    run["pending"] = [{"part": job[0]["id"], "attempt": job[2]} for job in jobs]
    write_json(root / "run.json", run)

    def execute(job):
        part, body, attempt = job
        stem = f"{part['id']:02d}_attempt{attempt}"
        record = {"part": part["id"], "attempt": attempt, "started_at": now()}
        started = time.monotonic()
        emit({"status": "sending", "part": part["id"], "attempt": attempt})
        try:
            status, text = send(plan["api"], key, body)
            text = text.replace(key, "[REDACTED]")
            record["http_status"] = status
            raw = f"responses/{stem}.txt"
            with (root / raw).open("x", encoding="utf-8") as output:
                output.write(text)
            record["raw_response"] = raw
            data = json.loads(text)
            record.update(usage=data.get("usage"), response_model=data.get("model"),
                          provider_model=data.get("provider_model"), response_id=data.get("id"))
            if status != 200 or data.get("error") or not data.get("choices"):
                record.update(status="error", error=data.get("error", "No usable choices"))
            else:
                choice = data["choices"][0]
                answer = choice.get("message", {}).get("content")
                if isinstance(answer, list):
                    answer = "".join(item.get("text", "") for item in answer
                                     if item.get("type") in {"text", "output_text"})
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("No final answer text")
                filename = f"generated/{stem}.md"
                saved = answer + ("" if answer.endswith("\n") else "\n")
                with (root / filename).open("x", encoding="utf-8") as output:
                    output.write(saved)
                record.update(status="complete" if choice.get("finish_reason") == "stop" else "incomplete",
                              finish_reason=choice.get("finish_reason"), file=filename,
                              saved_sha256=digest(saved.encode()), answer_sha256=digest(answer.encode()),
                              characters=len(answer))
        except Exception as error:
            record.update(status="error", error=str(error).replace(key, "[REDACTED]"))
        record.update(ended_at=now(), elapsed_seconds=round(time.monotonic() - started, 2))
        emit({"status": record["status"], "part": record["part"], "elapsed_seconds": record["elapsed_seconds"]})
        return record

    with concurrent.futures.ThreadPoolExecutor(max_workers=plan["api"]["concurrency"]) as executor:
        futures = [executor.submit(execute, job) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            run["attempts"].append(result)
            run["pending"].remove({"part": result["part"], "attempt": result["attempt"]})
            write_json(root / "run.json", run)
    run["updated_at"] = now()
    write_json(root / "run.json", run)
    return run


def format_part(text):
    lines = text.splitlines()
    result = []
    fence = None
    dropped_title = False
    for line in lines:
        marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if marker:
            value = marker[1]
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence) and not marker[2].strip():
                fence = None
            result.append(line)
            continue
        if fence is None:
            heading = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading:
                if len(heading[1]) == 1 and not dropped_title:
                    dropped_title = True
                    continue
                line = "#" * min(6, max(3, len(heading[1]) + 1)) + " " + heading[2]
                if result and result[-1].strip():
                    result.append("")
                result.extend([line, ""])
                continue
        result.append(line)
    if fence is not None:
        raise ValueError("Unclosed code block; inspect the part before merging")
    return "\n".join(result).strip()


def merge(path):
    root, plan, plan_hash = read_plan(path)
    run = read_run(root, plan_hash)
    notes = ["# " + plan["title"]]
    for part in plan["parts"]:
        attempts = [item for item in run["attempts"] if item["part"] == part["id"]]
        if not attempts or attempts[-1]["status"] != "complete":
            raise ValueError(f"Part {part['id']} is missing or incomplete; no complete notes produced")
        latest = attempts[-1]
        text = checked_file(root, latest["file"], latest["saved_sha256"]).decode("utf-8")
        notes.append(f"## 第 {part['id']} 部分：{part['title']}\n\n" + format_part(text))
    target, summary = root / "课程笔记.md", root / "运行记录.md"
    if target.exists() or summary.exists():
        raise ValueError("Merged output already exists; preserve it and review changes explicitly")
    rows = ["# 课程笔记运行记录", "", f"模型：`{plan['api']['model']}`；并发：{plan['api']['concurrency']}。", "",
            "| 部分 | 尝试 | 状态 | 耗时（秒） | 输入 Token | 完成 Token | 总 Token |",
            "|---:|---:|---|---:|---:|---:|---:|"]
    for record in run["attempts"]:
        usage = record.get("usage") or {}
        rows.append(f"| {record['part']} | {record['attempt']} | {record['status']} | {record['elapsed_seconds']} | "
                    f"{usage.get('prompt_tokens', '未报告')} | {usage.get('completion_tokens', '未报告')} | "
                    f"{usage.get('total_tokens', '未报告')} |")
    reported = sum((item.get("usage") or {}).get("total_tokens", 0) for item in run["attempts"])
    rows.extend(["", f"已报告总用量：{reported} Token；未报告的失败请求用量未知。", "",
                 "总量直接使用接口返回值，不重复加上思考 Token。原始正文与响应未改写。", "",
                 "自动合并只统一标题层级；内容去重、章节衔接、公式、图片及链接仍需 Codex 审阅。", ""])
    target.write_text("\n\n---\n\n".join(notes) + "\n", encoding="utf-8")
    summary.write_text("\n".join(rows), encoding="utf-8")
    emit({"status": "merged_offline", "notes": str(target), "summary": str(summary)})
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Offline preparation; no credential access or network")
    prep.add_argument("config")
    prep.add_argument("--out", required=True)
    gen = commands.add_parser("generate", help="Call the configured model after user confirmation")
    gen.add_argument("plan")
    gen.add_argument("--confirmed", action="store_true")
    gen.add_argument("--retry-failed", action="store_true")
    join = commands.add_parser("merge", help="Offline merge; requires all parts complete")
    join.add_argument("plan")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.config, args.out)
        elif args.command == "generate":
            run = generate(args.plan, args.confirmed, args.retry_failed)
            root, plan, unused = read_plan(args.plan)
            last = {item["part"]: item for item in run["attempts"]}
            return 0 if all(last.get(part["id"], {}).get("status") == "complete" for part in plan["parts"]) else 1
        else:
            merge(args.plan)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
