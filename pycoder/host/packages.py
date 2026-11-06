"""Install pure-Python packages from PyPI without pip or StaSh.

A wheel tagged py3-none-any is just a zip of Python files, so installing it means downloading,
checking its sha256 and unzipping it into Pythonista's site-packages-3 folder. Packages with
compiled code have no such wheel and can't run on iOS anyway.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import io
import os
import re
import sys
import zipfile
from collections.abc import Callable
from typing import Any

from .. import config

PYPI = 'https://pypi.org/pypi'
_REQUIREMENT = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$')

HttpGet = Callable[[str], Any]  # returns an object with .json() and .content, raising on HTTP errors


class PackageError(Exception):
    pass


def site_packages() -> str:
    """Where packages go: Pythonista's site-packages-3, or .pycoder/site-packages elsewhere."""
    for path in sys.path:
        if path.rstrip('/').endswith('site-packages-3'):
            return path
    path = os.path.join(config.DATA_DIR, 'site-packages')
    if path not in sys.path:
        sys.path.append(path)
    return path


def normalize(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def parse_requirement(text: str) -> tuple[str, str, str]:
    """'pkg[extra]>=1.0; marker' -> (name, version spec, marker)."""
    requirement, _, marker = text.partition(';')
    m = _REQUIREMENT.match(requirement)
    if not m:
        raise PackageError(f'Cannot parse requirement {text!r}')
    return m.group(1), m.group(3).strip().strip('()'), marker.strip()


def marker_applies(marker: str) -> bool:
    """Evaluate the environment markers that matter here; extras and other platforms are skipped."""
    if not marker:
        return True
    if 'extra' in marker:
        return False
    m = re.fullmatch(r'python_version\s*(<=|>=|<|>|==|!=)\s*["\']([\d.]+)["\']', marker)
    if m:
        current = sys.version_info[:2]
        wanted = tuple(int(p) for p in m.group(2).split('.'))[:2]
        return {
            '<': current < wanted,
            '<=': current <= wanted,
            '>': current > wanted,
            '>=': current >= wanted,
            '==': current == wanted,
            '!=': current != wanted,
        }[m.group(1)]
    return False  # sys_platform, implementation, ...: not worth guessing


def installed_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        pass
    try:  # bundled Pythonista packages often have no metadata; an importable module counts
        module = importlib.import_module(normalize(name).replace('-', '_'))
    except Exception:
        return None
    return str(getattr(module, '__version__', 'unknown'))


def version_key(version: str) -> tuple[int, ...] | None:
    """The numeric release part of a version ('1.5.0rc1' -> (1, 5, 0)); None if it has none."""
    m = re.match(r'\s*v?(\d+(?:\.\d+)*)', version)
    return tuple(int(p) for p in m.group(1).split('.')) if m else None


def _pad(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)), b + (0,) * (width - len(b))


def satisfies(version: str, spec: str) -> bool:
    """Whether `version` meets a specifier such as '>=1.5,<2' (release numbers only; enough here)."""
    if not spec.strip():
        return True
    have = version_key(version)
    if have is None:
        return False
    for clause in spec.split(','):
        m = re.match(r'\s*(~=|===|==|!=|>=|<=|>|<)\s*([\w.*+!-]+)\s*$', clause)
        if not m:
            continue
        op, wanted = m.groups()
        if wanted.endswith('.*'):
            prefix = version_key(wanted[:-2]) or ()
            matched = have[: len(prefix)] == prefix
            if (op == '==') != matched:
                return False
            continue
        want = version_key(wanted)
        if want is None:
            continue
        a, b = _pad(have, want)
        ok = {
            '==': a == b,
            '===': a == b,
            '!=': a != b,
            '>=': a >= b,
            '<=': a <= b,
            '>': a > b,
            '<': a < b,
            '~=': a >= b and have[: max(1, len(want) - 1)] == want[: max(1, len(want) - 1)],
        }[op]
        if not ok:
            return False
    return True


def install(
    requirement: str,
    http_get: HttpGet | None = None,
    log: Callable[[str], None] = print,
    target: str | None = None,
    _seen: set[str] | None = None,
) -> list[str]:
    """Install a package and its missing dependencies; returns 'name version' for each one installed."""
    get = http_get or _requests_get
    target = target or site_packages()
    seen = _seen if _seen is not None else set()
    name, spec, _ = parse_requirement(requirement)
    if normalize(name) in seen:
        return []
    seen.add(normalize(name))

    pinned = spec[2:].strip() if spec.startswith('==') and '*' not in spec else None
    info = get(f'{PYPI}/{name}/{pinned}/json' if pinned else f'{PYPI}/{name}/json').json()
    version, wheel = _choose_release(info, '' if pinned else spec)
    if wheel is None:
        raise PackageError(
            f'{name} {version} has no pure-Python wheel; it needs compiled code, which iOS cannot load'
        )

    installed: list[str] = []
    for dependency in info['info'].get('requires_dist') or []:
        dep_name, dep_spec, marker = parse_requirement(dependency)
        if not marker_applies(marker):
            continue
        have = installed_version(dep_name)
        # Pythonista bundles some packages in old versions; install a newer one alongside when needed
        if have is None or not satisfies(have, dep_spec):
            installed += install(dependency.partition(';')[0], get, log, target, seen)

    log('downloading {}'.format(wheel['filename']))
    data = get(wheel['url']).content
    if hashlib.sha256(data).hexdigest() != wheel['digests']['sha256']:
        raise PackageError('Checksum mismatch for {}'.format(wheel['filename']))
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(target)
        top_level = {
            n.split('/')[0].removesuffix('.py') for n in archive.namelist() if '.dist-info/' not in n
        }
    importlib.invalidate_caches()
    _forget_modules(top_level)
    installed.append(f'{name} {version}')
    return installed


def _forget_modules(names: set[str]) -> None:
    """Drop already-imported copies (Pythonista keeps modules between runs) so the new ones load."""
    for module in list(sys.modules):
        if module.split('.')[0] in names:
            del sys.modules[module]


def _choose_release(info: dict[str, Any], spec: str) -> tuple[str, dict[str, Any] | None]:
    """The newest stable release meeting `spec` that has a pure-Python wheel (the latest if no spec)."""
    latest = str(info['info']['version'])
    if not spec or satisfies(latest, spec):
        return latest, _pure_wheel(info['urls'])
    releases: dict[str, list[dict[str, Any]]] = info.get('releases') or {}
    candidates = [
        v for v in releases if re.fullmatch(r'[\d.]+', v) and satisfies(v, spec) and _pure_wheel(releases[v])
    ]
    if not candidates:
        return latest, None
    best = max(candidates, key=lambda v: version_key(v) or ())
    return best, _pure_wheel(releases[best])


def _pure_wheel(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    for f in files:
        if f.get('packagetype') == 'bdist_wheel' and re.search(
            r'-py(2\.)?py3-none-any\.whl$|-py3-none-any\.whl$', f['filename']
        ):
            return f
    return None


def _requests_get(url: str) -> Any:
    import requests

    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        raise PackageError(f'Not found on PyPI: {url}')
    response.raise_for_status()
    return response
