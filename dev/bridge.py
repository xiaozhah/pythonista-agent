"""
bridge — lets Claude Code on the Mac write files and run code through Pythonista itself.

Why: while a file is open in the Pythonista editor, Pythonista saves its stale editor buffer back to disk,
overwriting new content written from outside (Mac / iCloud). Writing from inside the Pythonista process
and refreshing the editor right after makes it show the new content, so nothing conflicts.

Usage: type `bridge` in Pythonista's console. It serves from a thread of its own, so the console
stays free; `bridge stop` ends it, and `bridge restart` starts it with the code on disk now.

It serves HTTP on port 8765 on this device only (127.0.0.1). To reach it from another device, list
where it should also listen in .bridge/listen, one per line: `tailscale` (this device's Tailscale
address), `lan` (every address it has) or an IP address.
Every request must carry the token in the X-Bridge-Token header. The token is new at each start,
in .bridge/token (readable only by you) and in .bridge/hosts/<device>.json, next to the addresses
the client uses to find this device. Nothing in .bridge/ goes into git.
"""

import hmac
import ipaddress
import json
import os
import queue
import secrets
import socket
import sys
import threading
import time
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

try:
    import console

    IN_PYTHONISTA = True
except ImportError:
    IN_PYTHONISTA = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # this file is in dev/
BRIDGE = os.path.join(ROOT, '.bridge')
TOKEN_FILE = os.path.join(BRIDGE, 'token')
HOSTS = os.path.join(BRIDGE, 'hosts')
LISTEN_FILE = os.path.join(BRIDGE, 'listen')
TRUSTED_FILE = os.path.join(BRIDGE, 'trusted')  # addresses that get the token without asking, one per line
TAILNET = ipaddress.ip_network('100.64.0.0/10')
SETTINGS_FILE = os.path.join(BRIDGE, 'settings.json')  # the prompt agent's own settings
LOOPBACK = '127.0.0.1'
PORT = 8765
MAX_BODY = 20 * 1024 * 1024
AWAKE_EVERY = 5  # seconds
STOP_WAIT = 5  # seconds
RUNNING = '_pycoder_bridge'


def say(text: str, color: str | None = None) -> None:
    rgb = {
        'dim': (0.55, 0.55, 0.55),
        'green': (0.2, 0.65, 0.3),
        'red': (0.85, 0.25, 0.25),
        'magenta': (0.7, 0.35, 0.8),
    }.get(color or '')
    if IN_PYTHONISTA and rgb:
        console.set_color(*rgb)
        print(text)
        console.set_color()
    else:
        print(text)


def atomic_write(path: str, text: str, private: bool = False) -> None:
    """Write via a temporary file; `private` files (holding the token) are readable only by you."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp-bridge'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with open(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def resolve(path: str) -> str:
    root = os.path.realpath(ROOT)
    full = os.path.realpath(os.path.join(root, path))
    if os.path.commonpath([root, full]) != root:
        raise ValueError('Path is outside Documents: %s' % path)
    return full


def sync_editor(full: str, content: str) -> None:
    """Make the Pythonista editor show the new content.

    reload_files() refreshes background tabs but not the active one, and Pythonista
    saves the active buffer when you tap Run, so that tab's text is replaced directly.
    """
    if not IN_PYTHONISTA:
        return
    try:
        import editor

        if os.path.realpath(editor.get_path() or '') == full:
            text = editor.get_text() or ''
            if text != content:
                editor.replace_text(0, len(text), content)
        editor.reload_files()
    except Exception as e:
        say('  (editor sync failed: %s)' % e, 'red')


def keep_awake() -> Any:
    """Stop macOS from suspending Pythonista while it sits in the background."""
    if not IN_PYTHONISTA:
        return None
    try:
        from objc_util import ObjCClass, ns

        info = ObjCClass('NSProcessInfo').processInfo()
        # NSActivityUserInitiatedAllowingIdleSystemSleep | NSActivityLatencyCritical
        return info.beginActivityWithOptions_reason_(0x00EFFFFF | 0xFF00000000, ns('pycoder bridge'))
    except Exception as e:
        say('  (keep-awake failed: %s)' % e, 'red')
        return None


def read_text(full: str) -> str:
    with open(full, encoding='utf-8') as f:
        return f.read()


def device_name() -> str:
    """'mac' for Pythonista running on a Mac, otherwise 'iphone' / 'ipad'."""
    if not IN_PYTHONISTA:
        return 'desktop'
    try:
        from objc_util import ObjCClass

        if ObjCClass('NSProcessInfo').processInfo().isiOSAppOnMac():
            return 'mac'
        return str(ObjCClass('UIDevice').currentDevice().model()).lower().replace(' ', '')
    except Exception:
        return 'unknown'


def lan_ips() -> list[str]:
    """IPv4 addresses other devices might reach, Wi-Fi/LAN first, VPNs like Tailscale (100.x) last.

    Asks the routing table which local address would be used for a few targets; no packet is sent.
    """
    found = []
    for target in ('192.168.1.1', '10.0.0.1', '172.16.0.1', '8.8.8.8', '100.100.100.100'):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            ip = s.getsockname()[0]
            if not ip.startswith('127.') and ip not in found:
                found.append(ip)
        except OSError:
            pass
        finally:
            s.close()
    found.sort(key=lambda ip: ip.startswith('100.'))
    return found or ['127.0.0.1']


def listen_addresses(ips: list[str]) -> list[str]:
    """Where to listen besides 127.0.0.1, from .bridge/listen; without that file, the Tailscale
    addresses (a private, authenticated network). Loopback alone isn't enough: in the iPad app on a
    Mac, macOS can't reach the app's 127.0.0.1."""
    try:
        words = read_text(LISTEN_FILE).split()
    except OSError:
        words = ['tailscale']
    found: list[str] = []
    for word in words:
        if word == 'lan':
            found += ips
        elif word == 'tailscale':
            found += [ip for ip in ips if ip.startswith('100.')]
        else:
            found.append(word)
    return [ip for ip in dict.fromkeys(found) if ip != LOOPBACK and not ip.startswith('127.')]


def new_token() -> str:
    """A fresh token for this run: one that leaked earlier opens nothing now. .bridge/ keeps
    itself out of git, so the token never reaches a commit."""
    token = secrets.token_urlsafe(24)
    atomic_write(os.path.join(BRIDGE, '.gitignore'), '*\n')
    atomic_write(TOKEN_FILE, token + '\n', private=True)
    return token


# ---------------------------------------------------------------- Operations


def op_ping() -> str:
    return 'pong · Python %s · %s' % (sys.version.split()[0], 'Pythonista' if IN_PYTHONISTA else 'desktop')


def op_write(path: str, content: str) -> str:
    full = resolve(path)
    existed = os.path.isfile(full)
    atomic_write(full, content)
    sync_editor(full, content)
    return '%s %s (%d lines)' % ('Overwrote' if existed else 'Created', path, len(content.splitlines()))


def op_edit(path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
    full = resolve(path)
    text = read_text(full)
    n = text.count(old_str)
    if not old_str or n == 0:
        raise ValueError('old_str not found')
    if n > 1 and not replace_all:
        raise ValueError('old_str appears %d times, not unique' % n)
    text = text.replace(old_str, new_str) if replace_all else text.replace(old_str, new_str, 1)
    atomic_write(full, text)
    sync_editor(full, text)
    return 'Edited %s (%d replacement(s))' % (path, n if replace_all else 1)


def op_read(path: str) -> str:
    return read_text(resolve(path))


def op_list(path: str = '.') -> str:
    base = resolve(path)
    return '\n'.join(
        n + ('/' if os.path.isdir(os.path.join(base, n)) else '')
        for n in sorted(os.listdir(base))
        if not n.startswith('.')
    )


def load_pycoder() -> Any:
    """Import pycoder fresh every time so the latest version on disk is used."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    for name in [n for n in sys.modules if n == 'pycoder' or n.startswith('pycoder.')]:
        del sys.modules[name]
    import pycoder.app.controller

    return pycoder


def op_run(
    code: str | None = None, path: str | None = None, args: list[str] | None = None, timeout: int = 60
) -> str:
    load_pycoder()
    from pycoder.state.workspace import Workspace
    from pycoder.tools.python_runner import run_code

    return run_code(Workspace(ROOT), code, path, args, timeout)


_controller: Any = None  # kept across requests so a prompt conversation continues


def op_prompt(text: str, model: str | None = None, new: bool = False) -> str:
    """Hand the task to the pycoder agent in Pythonista and return its final text reply."""
    global _controller
    if _controller is None or new:
        load_pycoder()
        from pycoder.app.controller import Controller
        from pycoder.frontends.console.frontend import ConsoleFrontend

        # tool output goes to the bridge console. Nobody is there to answer questions, and whoever
        # holds the token can run any code (op_run) anyway, so this agent never asks: bypass, in
        # settings of its own so the user's own mode and model stay as they are
        _controller = Controller(ConsoleFrontend(), root=ROOT, settings_file=SETTINGS_FILE)
        _controller.set_setting('mode', 'bypass')
        _controller.connect()
    from pycoder import config

    if model:
        _controller.set_model(config.resolve_model(model) or _controller.settings.model)
    result = _controller.run_turn(text)
    return str(result.text or '(%s, no text reply)' % result.status)


OPS: dict[str, Callable[..., str]] = {
    'ping': op_ping,
    'write': op_write,
    'edit': op_edit,
    'read': op_read,
    'list': op_list,
    'run': op_run,
    'prompt': op_prompt,
}


def handle(req: dict[str, Any]) -> dict[str, Any]:
    name, args = str(req.get('op')), req.get('args') or {}
    fn = OPS.get(name)
    if fn is None:
        return {'ok': False, 'output': 'Unknown operation %s' % name}
    label = args.get('path') or (args.get('text') or args.get('code') or '')[:50].replace('\n', ' ')
    say('⏺ %s %s' % (name, label), 'magenta')
    try:
        output = fn(**args)
        say('  ✓ ' + str(output).splitlines()[0][:100] if output else '  ✓', 'green')
        return {'ok': True, 'output': output}
    except KeyboardInterrupt:
        raise
    except Exception as e:
        say('  ✗ %s: %s' % (type(e).__name__, e), 'red')
        return {'ok': False, 'output': '%s: %s' % (type(e).__name__, e), 'traceback': traceback.format_exc()}


# ---------------------------------------------------------------- LAN server

# HTTP threads only queue requests; the main loop runs them one at a time,
# so file writes, editor calls and run_python never overlap.
_jobs: queue.Queue[tuple[dict[str, Any], threading.Event, dict[str, Any]]] = queue.Queue()


_pairing = threading.Lock()  # one question on screen at a time


def ask_to_pair(who: str) -> bool:
    """Whether the person at this device gives `who` the token. Devices share no folder (each has its
    own clone), so this is how another device gets it: a person says yes, on the device itself."""
    if not IN_PYTHONISTA:
        return False
    message = f"{who} asks for this bridge's token, which lets it run any code here. Did you ask for this?"
    if can_remember(who):
        message += ' This address will not be asked about again.'
    try:
        return bool(console.alert('Pair with bridge', message, 'Allow') == 1)
    except KeyboardInterrupt:  # Cancel
        return False


def can_remember(who: str) -> bool:
    """A Tailscale address is one device, proved by its key. On a LAN an address can pass to another."""
    return ipaddress.ip_address(who) in TAILNET


def is_trusted(who: str) -> bool:
    try:
        return who in read_text(TRUSTED_FILE).split()
    except OSError:
        return False


def trust(who: str) -> None:
    if can_remember(who) and not is_trusted(who):
        try:
            known = read_text(TRUSTED_FILE)
        except OSError:
            known = ''
        atomic_write(TRUSTED_FILE, known + who + '\n', private=True)


def make_handler(token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path == '/pair':
                return self._pair()
            if not hmac.compare_digest(self.headers.get('X-Bridge-Token', ''), token):
                return self._reply(403, {'ok': False, 'output': 'bad token'})
            try:
                size = int(self.headers.get('Content-Length', 0))
                if size > MAX_BODY:
                    return self._reply(413, {'ok': False, 'output': 'request too large'})
                req = json.loads(self.rfile.read(size).decode('utf-8'))
            except ValueError:
                return self._reply(400, {'ok': False, 'output': 'invalid JSON'})
            done, box = threading.Event(), cast(dict[str, Any], {})
            _jobs.put((req, done, box))
            done.wait()
            self._reply(200, box['res'])

        def _pair(self) -> None:
            if not _pairing.acquire(blocking=False):
                return self._reply(429, {'ok': False, 'output': 'already asking on the device'})
            try:
                who = self.client_address[0]
                allowed = is_trusted(who) or ask_to_pair(who)
                if allowed:
                    trust(who)
            finally:
                _pairing.release()
            if not allowed:
                return self._reply(403, {'ok': False, 'output': 'not allowed on the device'})
            self._reply(200, {'ok': True, 'token': token, 'output': 'paired'})

        def _reply(self, status: int, obj: dict[str, Any]) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # keep the console for operations only

    return Handler


def start_servers(token: str, addresses: list[str]) -> list[ThreadingHTTPServer]:
    """One server on 127.0.0.1 and one on each configured address (each one that can be bound)."""
    servers = []
    for address in [LOOPBACK, *addresses]:
        try:
            server = ThreadingHTTPServer((address, PORT), make_handler(token))
        except OSError as e:
            say('Not listening on %s: %s' % (address, e), 'red')
            continue
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
    return servers


def publish_address(device: str, ips: list[str], token: str) -> None:
    """Leave this device's addresses and token in .bridge/hosts so the Mac client can find it."""
    try:
        atomic_write(
            os.path.join(HOSTS, device + '.json'),
            json.dumps({'device': device, 'ips': ips, 'port': PORT, 'token': token, 'time': time.time()}),
            private=True,
        )
    except OSError:
        pass


# ---------------------------------------------------------------- Main loop


def serve(stopping: threading.Event) -> None:
    if IN_PYTHONISTA:
        console.set_idle_timer_disabled(True)  # keep an iPhone/iPad from auto-locking
    activity = keep_awake()  # noqa: F841 (must stay referenced while the loop runs)
    # record a crash here too, and say what the last one left: a device may run only the bridge
    load_pycoder()
    from pycoder.launch import watch_for_crashes

    for note in watch_for_crashes():
        say(note, 'red')
    device, token = device_name(), new_token()
    servers = start_servers(token, listen_addresses(lan_ips()))
    if not servers:
        return
    # the client tries them in order: another device's address first, this device's own last
    ips = sorted((str(s.server_address[0]) for s in servers), key=lambda ip: ip == LOOPBACK)
    say('bridge started on %s, waiting for Claude Code... (bridge stop quits)' % device, 'magenta')
    say('Listening on: ' + '  '.join('http://%s:%d' % (ip, PORT) for ip in ips), 'magenta')
    if ips == [LOOPBACK]:
        say('Only this device can reach it; for others, write tailscale in .bridge/listen', 'dim')
    publish_address(device, ips, token)
    try:
        awake = 0.0
        while not stopping.is_set():
            if IN_PYTHONISTA and time.time() - awake > AWAKE_EVERY:
                # iOS suspends the bridge if the device locks; Pythonista allows auto-lock again each
                # time a script ends, so this is set again and again
                console.set_idle_timer_disabled(True)
                awake = time.time()
            try:
                req, done, box = _jobs.get(timeout=0.5)  # timeout keeps stopping responsive
            except queue.Empty:
                continue
            box['res'] = handle(req)
            done.set()
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        if IN_PYTHONISTA:
            console.set_idle_timer_disabled(False)
        say('bridge stopped', 'dim')


def running() -> tuple[threading.Thread, threading.Event] | None:
    """The bridge of this process, kept on sys: each `bridge` command loads this file afresh."""
    found = sys.__dict__.get(RUNNING)
    return found if found is not None and found[0].is_alive() else None


def start() -> None:
    if running() is not None:
        say('bridge is already running (bridge restart loads new code)', 'dim')
        return
    stopping = threading.Event()
    thread = threading.Thread(target=serve, args=(stopping,), daemon=True)
    sys.__dict__[RUNNING] = (thread, stopping)
    thread.start()


def stop() -> None:
    found = running()
    if found is None:
        say('bridge is not running', 'dim')
        return
    thread, stopping = found
    stopping.set()
    thread.join(STOP_WAIT)
    if thread.is_alive():
        say('bridge will stop when the request it is on ends', 'dim')
