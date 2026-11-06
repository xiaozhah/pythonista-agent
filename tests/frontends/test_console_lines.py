"""Pythonista's console as the shell: which lines are commands, and what they leave behind."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from typing import Any

import pytest

from pycoder.frontends.console import lines
from pycoder.host import env
from pycoder.shell.terminal import Terminal

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def console_names(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    main = types.ModuleType('__main__')
    monkeypatch.setitem(sys.modules, '__main__', main)
    return vars(main)


@pytest.mark.parametrize(
    'line',
    [
        'ls',
        'ls -l',
        'pwd',
        'cd ..',
        'cd /local',
        'git status',
        'pip install rich',
        'cat a.py',
        'pwd > out.txt',
        'pwd; ls',
        'cd a && ls',
        'pycoder',
        'pycoder -c',
        'claude fix it',
        'clear',
        'history',
        'bridge',
        'bridge stop',
        'help',
    ],
)
def test_the_shells_lines(line: str, console_names: dict[str, Any]) -> None:
    assert lines.is_command(line)


@pytest.mark.parametrize(
    'line',
    ['', '1+1', 'ls = 5', 'ls[0]', 'nosuchname', 'print(1)', 'help(int)', 'import os', 'x = ls', 'open'],
)
def test_pythons_lines(line: str, console_names: dict[str, Any]) -> None:
    assert not lines.is_command(line)


def test_a_name_defined_in_the_console_means_what_it_was_defined_as(console_names: dict[str, Any]) -> None:
    console_names['ls'] = 5
    assert not lines.is_command('ls')
    assert not lines.is_command('ls * 2')
    assert lines.is_command('ls -l x')  # not Python, whatever ls is
    del console_names['ls']
    assert lines.is_command('ls')


@pytest.fixture
def at_home(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    (tmp_path / 'project').mkdir()
    monkeypatch.setattr(lines, 'state', types.SimpleNamespace(cwd='', previous='', running=None))
    monkeypatch.setattr(
        lines,
        'Terminal',
        lambda frontend: Terminal(
            home=str(tmp_path), history_file=str(tmp_path / 'history'), frontend=frontend
        ),
    )
    cwd = os.getcwd()
    yield tmp_path
    os.chdir(cwd)


def test_the_folder_lasts_from_line_to_line(at_home: Any, capsys: pytest.CaptureFixture[str]) -> None:
    lines.run('cd project')
    assert os.path.realpath(os.getcwd()) == os.path.realpath(at_home / 'project')  # for Python too
    lines.run('pwd')
    assert str(at_home / 'project').split(os.sep)[-1] in capsys.readouterr().out
    lines.run('cd -')
    assert os.path.realpath(lines.state.cwd) == os.path.realpath(at_home)


def test_a_folder_that_has_gone_is_left_for_home(at_home: Any) -> None:
    lines.state.cwd = str(at_home / 'gone')
    assert os.path.realpath(lines._terminal().cwd) == os.path.realpath(at_home)


def test_tab_completes_what_the_shell_knows(at_home: Any) -> None:
    assert lines.complete('cd pro') == ('cd project/', ['project/'])
    assert lines.complete('cd nothing') is None
    done = lines.complete('pyc')
    assert done is not None
    assert done[0] == 'pycoder '


def test_a_first_word_is_offered_the_commands_it_could_be() -> None:
    assert 'pycoder' in lines.suggest('pyco')
    assert 'ls' in lines.suggest('l')
    assert lines.suggest('nosuchcommand') == []
    assert lines.suggest('') == []
    assert lines.suggest('cd ') == []


def test_an_error_is_told_and_the_console_goes_on(at_home: Any, capsys: pytest.CaptureFixture[str]) -> None:
    lines.run('cat nothing.txt')
    assert 'nothing.txt' in capsys.readouterr().out


def load_install() -> Any:
    spec = importlib.util.spec_from_file_location('install_under_test', os.path.join(ROOT, 'install.py'))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_startup_file_keeps_what_it_had() -> None:
    install = load_install()
    first = install.with_block('import mine\n', '/repo')
    assert first.startswith('import mine\n')
    assert "'/repo'" in first
    compile(first, 'pythonista_startup.py', 'exec')
    moved = install.with_block(first, '/elsewhere')
    assert moved.startswith('import mine\n')
    assert moved.count(install.BEGIN) == 1
    assert '/repo' not in moved
    assert "'/elsewhere'" in moved
    assert install.with_block('', '/repo').startswith(install.BEGIN)


@pytest.mark.skipif(env.IN_PYTHONISTA, reason='needs another Python to start, which iOS has not')
def test_a_script_outside_can_import_pycoder_through_the_shim(tmp_path) -> None:
    import subprocess

    from pycoder import config
    from pycoder.frontends.console.hooks import write_import_shim

    write_import_shim(str(tmp_path), config.INSTALL_DIR)
    write_import_shim(str(tmp_path), config.INSTALL_DIR)  # the second start of the app finds it there
    code = 'import pycoder.host.metal as m, pycoder; print(m.__file__); print(pycoder.__file__)'
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    out = subprocess.run(
        [sys.executable, '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True, check=True
    )
    package = os.path.join(config.INSTALL_DIR, 'pycoder')
    assert out.stdout.splitlines() == [
        os.path.join(package, 'host', 'metal.py'),
        os.path.join(package, '__init__.py'),
    ]
