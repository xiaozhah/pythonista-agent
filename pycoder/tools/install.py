"""install_package: add a pure-Python package from PyPI."""

from __future__ import annotations

from ..host import packages
from .base import Tool, ToolContext, ToolError, prop


def install_package(ctx: ToolContext, name: str) -> str:
    try:
        done = packages.install(name, log=lambda line: ctx.frontend.run_output(line))
    except packages.PackageError as e:
        raise ToolError(str(e)) from e
    if not done:
        return f'{name} is already installed'
    return 'Installed: {} (into {})'.format(', '.join(done), packages.site_packages())


TOOLS = [
    Tool(
        'install_package',
        'Install a pure-Python package from PyPI (and its missing dependencies) into Pythonista. '
        'Accepts "name" or "name==version". Packages with compiled code cannot be installed on '
        'iOS; check first whether Pythonista already ships the module (numpy, requests, PIL, ...).',
        {'name': prop('string', 'Package name, optionally pinned, e.g. "tabulate" or "dulwich==0.22.8"')},
        install_package,
        required=['name'],
        readonly=False,
    ),
]
