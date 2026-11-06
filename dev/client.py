#!/usr/bin/env python3
"""
Mac-side client: hands operations to bridge.py running in Pythonista and waits for the result.

  client.py ping
  client.py write REMOTE LOCAL        # LOCAL of - reads from stdin
  client.py read REMOTE
  client.py list [REMOTE_DIR]
  client.py run REMOTE [ARGS...]      # run a .py file in Pythonista
  client.py run -c CODE
  client.py --device NAME pull        # update its clone from GitHub (asks there for a token the first time)
  client.py --device NAME pair        # get its token: tap Allow there, once for a Tailscale address
  client.py prompt TEXT [--model M]   # hand the task to the pycoder agent
  client.py op NAME JSON|@file.json   # any operation, arguments as JSON

Target (default: --device mac):
  --device NAME      mac, iphone, ... (address and token from .bridge/hosts/NAME.json)
  --host IP[:PORT]   a device by address (default port 8765), with the token from .bridge/token
  --timeout SECONDS  how long a run may take and the result is waited for (default 60 / 90)
The bridge makes a new token each time it starts.

REMOTE paths are relative to the pycoder repository (the folder that holds dev/).
Exit codes: 0 success, 1 operation failed, 2 bridge not running or timed out.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

BRIDGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.bridge')  # token, hosts
TOKEN_FILE = os.path.join(BRIDGE, 'token')
HOSTS = os.path.join(BRIDGE, 'hosts')
DEFAULT_PORT = 8765


def lan_address(host: str | None = None, device: str | None = None) -> tuple[str, int, str]:
    """(ip, port, token) of the bridge to talk to."""
    if device:
        try:
            with open(os.path.join(HOSTS, device + '.json'), encoding='utf-8') as f:
                info = json.load(f)
        except (OSError, ValueError):
            print(
                'no address known for %s: type bridge in its console, or use --host IP' % device,
                file=sys.stderr,
            )
            sys.exit(2)
        port = info.get('port', DEFAULT_PORT)
        ips = info.get('ips') or [info['ip']]
        for ip in ips:  # the first address where a server answers wins
            if _answers(ip, port):
                return ip, port, info.get('token') or read_token()
        print('%s is not reachable at %s (port %d)' % (device, ', '.join(ips), port), file=sys.stderr)
        sys.exit(2)
    ip, _, port = (host or '127.0.0.1').partition(':')
    return ip, int(port or DEFAULT_PORT), read_token()


def _answers(ip: str, port: int) -> bool:
    """Whether a server answers there. A connection alone doesn't say: a VPN can accept one for an
    address that has gone, and then reset it. The bridge refuses a GET, which is an answer."""
    try:
        with urllib.request.urlopen('http://%s:%d/' % (ip, port), timeout=2):
            return True
    except urllib.error.HTTPError:
        return True
    except OSError:
        return False


def read_token() -> str:
    try:
        return read_file(TOKEN_FILE).strip()
    except OSError:
        print('no token in %s: start bridge.py' % TOKEN_FILE, file=sys.stderr)
        sys.exit(2)


def send(target: tuple[str, int, str], op: str, args: dict[str, Any], timeout: int) -> dict[str, Any]:
    ip, port, token = target
    body = json.dumps({'op': op, 'args': args}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        'http://%s:%d/' % (ip, port),
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json', 'X-Bridge-Token': token},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            result: dict[str, Any] = json.loads(r.read().decode('utf-8'))
            return result
    except urllib.error.HTTPError as e:
        error: dict[str, Any] = json.loads(e.read().decode('utf-8') or '{}') or {
            'ok': False,
            'output': str(e),
        }
        return error
    except (urllib.error.URLError, OSError) as e:
        print('cannot reach bridge at %s:%d: %s' % (ip, port, getattr(e, 'reason', e)), file=sys.stderr)
        sys.exit(2)


def pair(device: str) -> int:
    """Ask another device's bridge for its token: an alert there asks the person to allow it. Needed
    after each start of that bridge, as devices share no folder the token could travel through."""
    path = os.path.join(HOSTS, device + '.json')
    ip, port, _ = lan_address(device=device)
    req = urllib.request.Request('http://%s:%d/pair' % (ip, port), data=b'{}', method='POST')
    print('Asking %s (tap Allow there if it asks)…' % device)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            token = json.loads(r.read().decode('utf-8'))['token']
    except urllib.error.HTTPError as e:
        print(json.loads(e.read().decode('utf-8') or '{}').get('output', e), file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as e:
        print('cannot reach bridge at %s:%d: %s' % (ip, port, getattr(e, 'reason', e)), file=sys.stderr)
        return 2
    with open(path, encoding='utf-8') as f:
        info = json.load(f)
    info['token'] = token
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(info, f)
    os.chmod(path, 0o600)
    print('paired with %s' % device)
    return 0


def read_file(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    target = {'device': 'mac'}
    for flag in ('--host', '--device'):
        if flag in argv:
            i = argv.index(flag)
            target = {flag[2:]: argv[i + 1]}
            del argv[i : i + 2]
    wait = None  # --timeout <seconds>: how long to wait for the answer (a long `run`)
    if '--timeout' in argv:
        i = argv.index('--timeout')
        wait = int(argv[i + 1])
        del argv[i : i + 2]
    cmd, rest = argv[0], argv[1:]
    timeout = 120
    if cmd == 'pair':
        return pair(target.get('device') or 'mac')
    if cmd == 'pull':  # the script is sent, so a clone too old to have it can still update itself
        pull = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pull.py')
        res = send(lan_address(**target), 'run', {'code': read_file(pull), 'timeout': 170}, 180)
        print(res.get('output', ''))
        return 0 if res.get('ok') else 1
    if cmd == 'ping':
        op, args = 'ping', {}
    elif cmd == 'write':
        remote, local = rest
        content = sys.stdin.read() if local == '-' else read_file(local)
        op, args = 'write', {'path': remote, 'content': content}
    elif cmd == 'read':
        op, args = 'read', {'path': rest[0]}
    elif cmd == 'list':
        op, args = 'list', {'path': rest[0] if rest else '.'}
    elif cmd == 'run':
        if rest[0] == '-c':
            op, args = 'run', {'code': rest[1]}
        else:
            op, args = 'run', {'path': rest[0], 'args': rest[1:]}
        timeout = 90
    elif cmd == 'prompt':
        args = {'text': rest[0]}
        if '--model' in rest:
            args['model'] = rest[rest.index('--model') + 1]
        op, timeout = 'prompt', 1800
    elif cmd == 'op':
        raw = rest[1]
        if raw.startswith('@'):
            raw = read_file(raw[1:])
        op, args = rest[0], json.loads(raw)
        timeout = 1800 if op == 'prompt' else 120
    else:
        print(__doc__)
        return 2
    if wait and op == 'run':
        args['timeout'] = max(1, wait - 10)  # the script's own limit, inside the wait for its answer
    res = send(lan_address(**target), op, args, wait or timeout)
    print(res.get('output', ''))
    if not res.get('ok'):
        if res.get('traceback'):
            print(res['traceback'], file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
