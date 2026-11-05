"""Local diagnostic JSON-lines client. Never exposes the Unix socket over HTTP."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import socket
import stat
import sys

MAX_RESPONSE = 32 * 1024 * 1024


def request(path, payload, timeout=180):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('Expected a private mode-0600 Unix socket')
    if info.st_uid != __import__('os').getuid():
        raise ValueError('Socket belongs to another OS user')
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() + b'\n'
    if len(raw) > 65536:
        raise ValueError('Request exceeds 64 KiB')
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(raw)
        data = bytearray()
        while b'\n' not in data:
            chunk = connection.recv(65536)
            if not chunk:
                raise ValueError('Incomplete response; query the original operation ID')
            data.extend(chunk)
            if len(data) > MAX_RESPONSE:
                raise ValueError('Response exceeds 32 MiB')
    result = json.loads(bytes(data).split(b'\n', 1)[0])
    if not isinstance(result, dict):
        raise ValueError('Expected an object response')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--request', help='JSON object; omit to read stdin')
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error('timeout must be 1..300 seconds')
    try:
        payload = json.loads(args.request) if args.request is not None else json.load(sys.stdin)
        result = request(args.socket, payload, args.timeout)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('ok') is True else 1
    except (ValueError, OSError) as error:
        print(json.dumps({'ok': False, 'errorType': type(error).__name__,
                          'message': 'Request failed; verify health or recover the original operation ID.'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
