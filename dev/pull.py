"""Update this device's clone from GitHub, sent by `client.py --device NAME pull`: pycoder's code is
loaded afresh for each thing the bridge runs, so only a change to bridge.py itself needs a restart.
The first time, it installs dulwich and asks on the device for a GitHub token (kept in its keychain)."""

from __future__ import annotations

import os
import sys

ROOT = os.getcwd()  # the bridge runs code in the repository
sys.path.insert(0, ROOT)

from pycoder.cancel import CancelToken  # noqa: E402
from pycoder.events import Frontend  # noqa: E402
from pycoder.state.checkpoints import Checkpoints  # noqa: E402
from pycoder.state.session import Session  # noqa: E402
from pycoder.state.workspace import Workspace  # noqa: E402
from pycoder.tools import git  # noqa: E402
from pycoder.tools.base import ToolContext  # noqa: E402


class AskOnDevice(Frontend):
    def run_output(self, text: str) -> None:
        print(text)

    def ask_text(self, title: str, message: str = '', secret: bool = False) -> str | None:
        import console

        try:
            return console.password_alert(title, message) if secret else console.input_alert(title, message)
        except KeyboardInterrupt:
            return None


workspace = Workspace(ROOT)
session = Session.new(ROOT, '', '', web=False)
ctx = ToolContext(workspace, AskOnDevice(), session, Checkpoints(session, workspace), CancelToken())
print(git.git(ctx, 'pull'))
print(git.git(ctx, 'log', count=1))
