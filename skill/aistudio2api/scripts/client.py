#!/usr/bin/env python3
"""Non-streaming, loopback-only AIStudio2API client; credentials never enter argv."""
import argparse
import json
import math
import os
import stat
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

BASE_URL = 'http://127.0.0.1:2048/v1'
DEFAULT_CONFIG = Path.home() / '.config/aistudio2api/client.json'


class ClientError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_key():
    """Prefer an injected environment secret; otherwise read a private user file."""
    key = os.environ.get('AISTUDIO2API_API_KEY', '').strip()
    if not key:
        path = Path(os.environ.get('AISTUDIO2API_CONFIG', str(DEFAULT_CONFIG))).expanduser()
        try:
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, encoding='utf-8') as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise ClientError('Client config must be a regular file owned by this user with mode 0600 (or 0400).')
                data = json.load(handle)
            key = data.get('api_key', '') if isinstance(data, dict) else ''
        except (OSError, ValueError):
            raise ClientError('Cannot read private client config. See references/client-usage.md; do not read the root service .env or request a sudo password.') from None
    if not isinstance(key, str) or not key.strip() or '\n' in key or '\r' in key:
        raise ClientError('Client API key is missing or invalid; provision the private client config.')
    return key.strip()


def request_json(path, key, payload=None, timeout=120):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(BASE_URL + path, data=body, headers={
        'Authorization': 'Bearer ' + key,
        'Content-Type': 'application/json',
    })
    # Never send a proxy token through environment HTTP proxies or redirects.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    started = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as response:
            status = response.status
            value = json.load(response)
    except HTTPError as exc:
        # Report only structured error details, not headers, cookies or HTML pages.
        detail = ''
        try:
            failure = json.loads(exc.read(65536))
            error = failure.get('error', {}) if isinstance(failure, dict) else {}
            if isinstance(error, dict):
                detail = str(error.get('code', '')) + ': ' + str(error.get('message', ''))
        except (ValueError, OSError):
            pass
        safe_detail = detail.replace(key, '[REDACTED]')[:500]
        raise ClientError(f'HTTP {exc.code} {safe_detail}'.strip()) from None
    except (URLError, TimeoutError, OSError):
        raise ClientError('Local API connection failed or timed out; no automatic retry. A timed-out generation may still consume quota.') from None
    except ValueError:
        raise ClientError('Local API returned invalid JSON.') from None
    return value, status, round(time.monotonic() - started, 2)


def read_text(path):
    try:
        return Path(path).read_text(encoding='utf-8')
    except (OSError, ValueError):
        raise ClientError('Cannot read a requested UTF-8 input file.') from None


def build_payload(args):
    if args.request_file:
        if args.prompt is not None or args.prompt_file or args.context:
            raise ClientError('--request-file cannot be combined with prompt or context arguments.')
        try:
            payload = json.loads(read_text(args.request_file))
        except ValueError:
            raise ClientError('Request file must contain valid JSON.') from None
        if not isinstance(payload, dict) or not isinstance(payload.get('messages'), list) or not payload['messages']:
            raise ClientError('Request JSON must contain a nonempty messages array.')
        if payload.get('stream'):
            raise ClientError('This helper supports non-streaming requests only.')
        if payload.get('model', args.model) != args.model:
            raise ClientError('Request model differs from --model; refusing silent substitution.')
        payload.setdefault('max_tokens', args.max_tokens)
    else:
        if (args.prompt is None) == (args.prompt_file is None):
            raise ClientError('Provide exactly one of --prompt or --prompt-file.')
        prompt = args.prompt if args.prompt is not None else read_text(args.prompt_file)
        for filename in args.context:
            prompt += '\n\n--- Reference: ' + str(Path(filename)) + ' ---\n' + read_text(filename)
        if not prompt.strip():
            raise ClientError('Prompt is empty.')
        payload = {'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': args.max_tokens}
    payload['model'] = args.model
    payload['stream'] = False
    return payload


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    models = commands.add_parser('models', help='List model IDs; does not prove generation availability.')
    models.add_argument('--timeout', type=float, default=30)
    chat = commands.add_parser('chat', help='Generate once with an exact model ID; never switches or retries.')
    chat.add_argument('--model', required=True)
    chat.add_argument('--prompt', help='Short non-secret user prompt.')
    chat.add_argument('--prompt-file', help='UTF-8 prompt file.')
    chat.add_argument('--context', action='append', default=[], help='UTF-8 reference file; repeat to append multiple files.')
    chat.add_argument('--request-file', help='Complete OpenAI messages/tools JSON; metadata is preserved.')
    chat.add_argument('--max-tokens', type=int, default=4096)
    chat.add_argument('--timeout', type=float, default=180)
    chat.add_argument('--output', help='Write a new UTF-8 result file; refuses to overwrite.')
    chat.add_argument('--json', action='store_true', help='Return the full response JSON, including tool-call metadata.')
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be positive and finite.')
    if args.command == 'chat' and (args.max_tokens <= 0 or not args.model.strip()):
        parser.error('--max-tokens must be positive and --model nonempty.')
    return args


def main():
    args = parse_args()
    if args.command == 'models':
        result, status, elapsed = request_json('/models', load_key(), timeout=args.timeout)
        if not isinstance(result, dict) or not isinstance(result.get('data'), list):
            raise ClientError('Unexpected model-list response.')
        print(json.dumps([item.get('id') for item in result['data'] if isinstance(item, dict)], ensure_ascii=False, indent=2))
        print(json.dumps({'http_status': status, 'elapsed_seconds': elapsed}), file=sys.stderr)
        return
    payload = build_payload(args)
    if args.output and (Path(args.output).exists() or Path(args.output).is_symlink()):
        raise ClientError('Output already exists; choose a new path (checked before sending).')
    if args.output and not Path(args.output).parent.is_dir():
        raise ClientError('Output parent directory does not exist (checked before sending).')
    result, status, elapsed = request_json('/chat/completions', load_key(), payload, args.timeout)
    try:
        choice = result['choices'][0]
        message = choice['message']
    except (KeyError, IndexError, TypeError):
        raise ClientError('Generation returned no valid assistant message.') from None
    metadata = {'http_status': status, 'requested_model': args.model, 'returned_model': result.get('model'),
                'elapsed_seconds': elapsed, 'finish_reason': choice.get('finish_reason'), 'usage': result.get('usage')}
    print(json.dumps(metadata, ensure_ascii=False), file=sys.stderr)
    if args.json:
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        if message.get('tool_calls') or message.get('function_call'):
            raise ClientError('Response contains tool calls; use --json to preserve their metadata (generation already completed).')
        text = message.get('content')
        if not isinstance(text, str) or not text.strip():
            raise ClientError('Generation returned no text (generation already completed).')
    if args.output:
        try:
            with open(args.output, 'x', encoding='utf-8') as handle:
                handle.write(text)
                if not text.endswith('\n'):
                    handle.write('\n')
        except OSError:
            raise ClientError('Cannot create output file (generation already completed).') from None
        print('Saved response to ' + str(Path(args.output).resolve()), file=sys.stderr)
    else:
        print(text)


if __name__ == '__main__':
    try:
        main()
    except ClientError as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        sys.exit(1)
