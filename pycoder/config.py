"""Constants and user-adjustable settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2026-10-21'

BETA_FALLBACK = 'server-side-fallback-2026-07-01'  # retry a declined request on another model
BETA_COMPACTION = 'compact-2026-09-04'  # on-demand compaction
BETA_THINKING_BINDING = 'thinking-binding-controls-2026-08-01'  # drop, don't reject, stale thinking

KEYCHAIN_SERVICE = 'pycoder'
KEYCHAIN_ACCOUNT = 'anthropic_api_key'

# Project instructions, read from the workspace root in this order (CLAUDE.md is shared with Claude Code)
INSTRUCTION_FILES = ('CLAUDE.md', '.claude/CLAUDE.md', 'CLAUDE.local.md')
FALLBACK_INSTRUCTIONS = 'AGENTS.md'  # read when none of those exist (used by other coding agents)


# The web_search and web_fetch tool versions: the latest (with dynamic filtering) is documented
# for Opus and Sonnet only; other models get the basic ones, which every model accepts
WEB_TOOLS_LATEST = ('web_search_20260209', 'web_fetch_20260209')
WEB_TOOLS_BASIC = ('web_search_20250305', 'web_fetch_20250910')


@dataclass(frozen=True)
class ModelInfo:
    id: str
    short: str
    description: str
    prices: tuple[float, float, float, float]  # $ per million tokens: input, output, cache read, cache write
    server_fallback: bool = True
    web_tools: tuple[str, str] = WEB_TOOLS_LATEST  # (web_search, web_fetch) tool types
    long_prompt: int = 0  # a request whose whole prompt is over this many tokens costs LONG_PROMPT_PRICE×


MODELS: tuple[ModelInfo, ...] = (
    ModelInfo('claude-opus-5-5', 'opus', 'most capable, for complex tasks', (4.00, 20.00, 0.20, 5.00)),
    ModelInfo(
        'claude-sonnet-5-5',
        'sonnet',
        'faster and cheaper, fine for everyday coding',
        (2.00, 10.00, 0.10, 2.50),
    ),
    ModelInfo(
        'claude-haiku-5-5',
        'haiku',
        'very fast and very cheap, for simple questions',
        (0.10, 0.50, 0.01, 0.125),
        server_fallback=False,
        web_tools=WEB_TOOLS_BASIC,
        long_prompt=100_000,
    ),
)
LONG_PROMPT_PRICE = 5
WEB_SEARCH_PRICE = 0.01  # dollars per search
MODEL_BY_ID = {m.id: m for m in MODELS}
DEFAULT_MODEL = 'claude-opus-5-5'

# Models a server-side fallback may answer with; used only to price their usage
FALLBACK_PRICES = {
    'claude-opus-5': (5.00, 25.00, 0.50, 6.25),
    'claude-opus-4-8': (5.00, 25.00, 0.50, 6.25),
    'claude-sonnet-5': (2.00, 10.00, 0.20, 2.50),
}

EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
CACHE_TTLS = ('5m', '1h')
CONTEXT_WINDOW = 1_000_000  # tokens, for every model pycoder offers

MAX_TOKENS = 64000  # per response; requests stream, so a large cap is safe
COMPACT_MAX_TOKENS = 16000  # the summary request
MAX_TOOL_OUTPUT = 40000  # characters returned by one tool result
MAX_LIST_ENTRIES = 500
MAX_SEARCH_HITS = 200
SUBAGENT_MAX_TURNS = 25
WRITING_SUBAGENT_MAX_TURNS = 50

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTALL_DIR = os.path.dirname(PACKAGE_DIR)  # pycoder's repository: the package, skills, install.py


def home_for(install_dir: str) -> str:
    """Your home (~): where the console's shell starts, what it never leaves, and where settings and sessions
    are kept. It is the folder that holds the repository, i.e. Pythonista's Documents; an install at
    the top of Documents (the old layout) is its own home. A clone a git app keeps for Pythonista sits
    in a folder iOS doesn't let us read or write: then it is Pythonista's own Documents."""
    if os.path.basename(install_dir) == 'Documents':
        return install_dir
    parent = os.path.dirname(install_dir)
    return parent if _usable(parent) else os.path.realpath(os.path.expanduser('~/Documents'))


def _usable(folder: str) -> bool:
    try:
        os.listdir(folder)
    except OSError:
        return False
    return os.access(folder, os.W_OK)


HOME_DIR = home_for(INSTALL_DIR)
DATA_DIR = os.path.join(HOME_DIR, '.pycoder')  # your settings, sessions and memory: not code
SESSIONS_DIR = os.path.join(DATA_DIR, 'sessions')
SET_ASIDE_DIR = os.path.join(DATA_DIR, 'set-aside')  # moved and deleted files, for /rewind
LEARNED_SKILLS_DIR = os.path.join(DATA_DIR, 'skills')  # skills made on this device, when asked (save_skill)
WORKTREES_DIR = os.path.join(DATA_DIR, 'worktrees')  # subagents' own copies of the workspace
MEMORY_DIR = os.path.join(DATA_DIR, 'memory')  # auto memory, a folder per workspace
# What comes with pycoder and how it is extended; kept in the repository, so git shares them
SKILLS_DIR = os.path.join(INSTALL_DIR, 'skills')
COMMANDS_DIR = os.path.join(INSTALL_DIR, 'commands')  # Markdown prompt commands
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')  # /config; on this device, not in git
UPDATE_STATE = os.path.join(DATA_DIR, 'version.json')  # what the last update was, for rollback
STAGE_DIR = os.path.join(DATA_DIR, 'staged')  # an update downloaded in the background, for the next start
UPDATE_CHECK_EVERY = 30 * 60  # seconds between background checks for a new version

# Where /update gets new versions of pycoder
UPDATE_REPO = 'xiaozhah/pythonista-agent'
UPDATE_BRANCH = 'main'


def price_for(model: str) -> tuple[float, float, float, float]:
    if model in MODEL_BY_ID:
        return MODEL_BY_ID[model].prices
    return FALLBACK_PRICES.get(model, MODEL_BY_ID[DEFAULT_MODEL].prices)


def cost_of(usage: Any, model: str) -> float:
    """Dollars for one response's usage, at list prices. 1-hour cache writes cost 2× input, 5-minute
    ones 1.25×. Not in the usage, so not counted: US-only inference and fast mode."""
    p_in, p_out, p_read, p_write = price_for(model)
    fresh = int(usage.get('input_tokens') or 0)
    read = int(usage.get('cache_read_input_tokens') or 0)
    written = int(usage.get('cache_creation_input_tokens') or 0)
    hour = int((usage.get('cache_creation') or {}).get('ephemeral_1h_input_tokens') or 0)
    tokens = (
        fresh * p_in
        + int(usage.get('output_tokens') or 0) * p_out
        + read * p_read
        + (written - hour) * p_write
        + hour * p_in * 2
    ) / 1e6
    info = MODEL_BY_ID.get(model)
    if info is not None and info.long_prompt and fresh + read + written > info.long_prompt:
        tokens *= LONG_PROMPT_PRICE
    searches = int((usage.get('server_tool_use') or {}).get('web_search_requests') or 0)
    return tokens + searches * WEB_SEARCH_PRICE


def resolve_model(arg: str) -> str | None:
    """Model id from a number (1-based), a short name or part of an id; None if unknown."""
    arg = arg.strip().lower()
    if arg.isdigit() and 1 <= int(arg) <= len(MODELS):
        return MODELS[int(arg) - 1].id
    return next((m.id for m in MODELS if arg and (arg == m.short or arg in m.id)), None)
