"""pycoder: an agentic coding assistant that runs inside Pythonista.

Packages, from the screens down (each depends only on those below it):

    frontends/   the screens: chat, console
    app/         the application: controller, slash commands, @mentions, reports
    shell/       the built-in shell and a session of it at the console
    agent/       one model turn: the tool-use loop, permissions, system prompt, compaction
    tools/       what the model can call
    api/         the streaming Claude API client
    state/       what persists: workspace, sessions, checkpoints, memory, settings
    host/        what Pythonista and iOS provide

Top-level modules: config (constants), types, cancel, events (the Frontend interface), launch
(start-up) and updater (self-update).
"""

__version__ = '0.3.0'

from .host import main_thread

main_thread.install()  # before anything imports on_main_thread from objc_util
