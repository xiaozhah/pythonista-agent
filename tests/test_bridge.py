"""dev/bridge.py: where it listens and its per-start token."""

from __future__ import annotations

import importlib.util
import os
import stat
from typing import Any

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def bridge(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    spec = importlib.util.spec_from_file_location('bridge_under_test', os.path.join(ROOT, 'dev', 'bridge.py'))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = str(tmp_path / '.bridge')
    monkeypatch.setattr(module, 'BRIDGE', folder)
    monkeypatch.setattr(module, 'TOKEN_FILE', os.path.join(folder, 'token'))
    monkeypatch.setattr(module, 'LISTEN_FILE', os.path.join(folder, 'listen'))
    monkeypatch.setattr(module, 'TRUSTED_FILE', os.path.join(folder, 'trusted'))
    monkeypatch.setattr(module, 'PORT', 0)  # any free port: a real bridge may be running
    return module


def test_a_new_private_token_at_each_start(bridge: Any) -> None:
    first, second = bridge.new_token(), bridge.new_token()
    assert first != second
    assert bridge.read_text(bridge.TOKEN_FILE).strip() == second
    assert stat.S_IMODE(os.stat(bridge.TOKEN_FILE).st_mode) == 0o600
    assert bridge.read_text(os.path.join(bridge.BRIDGE, '.gitignore')) == '*\n'  # never committed


def test_it_listens_only_on_this_device_unless_told(bridge: Any) -> None:
    ips = ['192.168.1.5', '100.64.1.2']
    assert bridge.listen_addresses(ips) == ['100.64.1.2']  # no listen file: Tailscale only
    bridge.atomic_write(bridge.LISTEN_FILE, 'tailscale\n')
    assert bridge.listen_addresses(ips) == ['100.64.1.2']
    bridge.atomic_write(bridge.LISTEN_FILE, 'lan 10.0.0.9 127.0.0.1\n')
    assert bridge.listen_addresses(ips) == ['192.168.1.5', '100.64.1.2', '10.0.0.9']
    servers = bridge.start_servers('t', [])
    try:
        assert [s.server_address[0] for s in servers] == ['127.0.0.1']
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


def test_a_token_is_handed_over_only_when_the_person_allows(
    bridge: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import urllib.error
    import urllib.request

    servers = bridge.start_servers('secret', [])
    port = servers[0].server_address[1]

    def post(path: str) -> tuple[int, dict[str, Any]]:
        req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=b'{}', method='POST')
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        monkeypatch.setattr(bridge, 'ask_to_pair', lambda who: False)
        status, reply = post('/pair')
        assert status == 403
        assert 'token' not in reply
        assert post('/')[0] == 403  # everything else still needs the token
        monkeypatch.setattr(bridge, 'ask_to_pair', lambda who: who == '127.0.0.1')
        assert post('/pair')[1]['token'] == 'secret'
        monkeypatch.setattr(bridge, 'ask_to_pair', lambda who: False)
        assert post('/pair')[0] == 403  # this isn't an address to remember: it is asked about each time
        monkeypatch.setattr(bridge, 'can_remember', lambda who: True)
        bridge.trust('127.0.0.1')
        assert post('/pair')[1]['token'] == 'secret'  # now it isn't asked about
    finally:
        servers[0].shutdown()
        servers[0].server_close()


def test_only_a_tailscale_address_is_remembered(bridge: Any) -> None:
    bridge.trust('192.168.1.5')
    assert not bridge.is_trusted('192.168.1.5')
    bridge.trust('100.64.1.2')
    bridge.trust('100.64.1.2')
    assert bridge.is_trusted('100.64.1.2')
    assert bridge.read_text(bridge.TRUSTED_FILE).split() == ['100.64.1.2']
