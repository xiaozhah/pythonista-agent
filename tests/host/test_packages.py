"""Installing pure-Python packages from PyPI, and where git tokens may go."""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from typing import Any

import pytest

from pycoder.host import packages, vcs


def make_wheel(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


class FakePypi:
    def __init__(self, packages_: dict[str, tuple[str, list[str], bytes | None]]) -> None:
        self.packages = packages_  # name -> (version, requires_dist, wheel bytes or None for compiled-only)
        self.urls: list[str] = []

    def __call__(self, url: str) -> Any:
        self.urls.append(url)
        if url.endswith('.whl'):
            return type('R', (), {'content': self.packages[url.split('/')[-1].split('-')[0]][2]})()
        name = url.split('/pypi/')[1].split('/')[0]
        version, requires, wheel = self.packages[name]
        files = []
        if wheel is not None:
            files.append(
                {
                    'packagetype': 'bdist_wheel',
                    'filename': f'{name}-{version}-py3-none-any.whl',
                    'url': f'https://files/{name}-{version}-py3-none-any.whl',
                    'digests': {'sha256': hashlib.sha256(wheel).hexdigest()},
                }
            )
        info = {'info': {'version': version, 'requires_dist': requires}, 'urls': files}
        return type('R', (), {'json': lambda self: info})()


def test_install_resolves_missing_dependencies(tmp_path: Any) -> None:
    pypi = FakePypi(
        {
            'fancytool': (
                '1.0',
                ['zzdep>=1', 'other; extra == "dev"', 'old; python_version < "3.8"'],
                make_wheel({'fancytool/__init__.py': 'X = 1\n'}),
            ),
            'zzdep': ('2.0', [], make_wheel({'zzdep/__init__.py': ''})),
        }
    )
    done = packages.install('fancytool', http_get=pypi, log=lambda line: None, target=str(tmp_path))
    assert done == ['zzdep 2.0', 'fancytool 1.0']
    assert os.path.isfile(tmp_path / 'fancytool' / '__init__.py')


def test_install_refuses_compiled_only_packages(tmp_path: Any) -> None:
    pypi = FakePypi({'torchish': ('2.0', [], None)})
    with pytest.raises(packages.PackageError, match='compiled code'):
        packages.install('torchish', http_get=pypi, log=lambda line: None, target=str(tmp_path))


def test_requirement_parsing_and_markers() -> None:
    assert packages.parse_requirement('urllib3[socks]>=1.25; extra == "https"') == (
        'urllib3',
        '>=1.25',
        'extra == "https"',
    )
    assert packages.marker_applies('python_version >= "3.8"')
    assert not packages.marker_applies('python_version < "3.8"')
    assert not packages.marker_applies('sys_platform == "win32"')


def test_version_specifiers() -> None:
    assert packages.satisfies('1.5.0', '>=1.5,<2')
    assert not packages.satisfies('1.0.0', '>=1.5,<2')
    assert packages.satisfies('2.4.1', '~=2.4')
    assert not packages.satisfies('3.0', '~=2.4')
    assert packages.satisfies('1.2.9', '==1.2.*')
    assert packages.satisfies('anything', '')


def test_outdated_bundled_dependency_is_upgraded(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(packages, 'installed_version', lambda name: '1.0.0' if name == 'oldlib' else None)
    pypi = FakePypi(
        {
            'newtool': ('1.0', ['oldlib>=1.5'], make_wheel({'newtool/__init__.py': ''})),
            'oldlib': ('1.6', [], make_wheel({'oldlib/__init__.py': ''})),
        }
    )
    done = packages.install('newtool', http_get=pypi, log=lambda line: None, target=str(tmp_path))
    assert done == ['oldlib 1.6', 'newtool 1.0']


def test_tokens_only_go_to_github() -> None:
    assert vcs.is_github('https://github.com/owner/repo.git')
    assert not vcs.is_github('https://github.com.evil.example/owner/repo.git')
    assert not vcs.is_github('https://gitlab.com/owner/repo.git')
