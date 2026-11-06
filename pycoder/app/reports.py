"""What /context, /status and /usage show: computed here, drawn by each frontend.

The context breakdown is an estimate (about 4 characters per token) scaled to the size the API
reported for the last request, so the total is real and the split between categories is close.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .. import __version__, config
from ..agent import compaction
from ..agent.loop import WEB_TOOLS
from ..agent.prompt import project_instructions
from ..host import env
from ..state import memory
from ..tools.registry import main_tools
from ..types import Message

if TYPE_CHECKING:
    from .controller import Controller

GRID = 10  # the context grid is GRID × GRID cells


@dataclass(frozen=True)
class Category:
    name: str
    tokens: int
    color: str  # for the app
    symbol: str  # for text


@dataclass(frozen=True)
class ContextUsage:
    model: str
    window: int
    categories: tuple[Category, ...]  # what is used, then free space and the autocompact buffer
    measured: int  # tokens of the last request (0 before the first one)
    compact_at: int

    @property
    def used(self) -> int:
        return sum(c.tokens for c in self.categories if c.name not in (FREE, BUFFER))

    def cells(self) -> list[Category]:
        """GRID² cells: every used category gets at least one, the buffer fills the end."""
        total = GRID * GRID
        cells: list[Category] = []
        for c in self.categories:
            if c.name in (FREE, BUFFER) or not c.tokens:
                continue
            cells += [c] * max(1, round(c.tokens / self.window * total))
        buffer = next((c for c in self.categories if c.name == BUFFER), None)
        buffer_cells = round(buffer.tokens / self.window * total) if buffer else 0
        free = next(c for c in self.categories if c.name == FREE)
        cells = cells[: total - buffer_cells]
        cells += [free] * (total - buffer_cells - len(cells))
        return cells + ([buffer] * buffer_cells if buffer else [])


FREE = 'Free space'
BUFFER = 'Autocompact buffer'
_STYLE = {
    'System prompt': ('#8e8e93', '⛁'),
    'Tools': ('#5e5ce6', '⛁'),
    'Skills': ('#ff9f0a', '⛁'),
    'Memory files': ('#ff375f', '⛁'),
    'Messages': ('#0a84ff', '⛁'),
    FREE: ('#d1d1d6', '⛶'),
    BUFFER: ('#8e8e93', '⛝'),
}


def _category(name: str, tokens: int) -> Category:
    color, symbol = _STYLE[name]
    return Category(name, tokens, color, symbol)


def context_usage(c: Controller) -> ContextUsage:
    session = c.session
    skills = len(c.skills.prompt_section())
    memory_chars = sum(len(text) for _, text in project_instructions(session.root))
    if session.memory_dir:
        memory_chars += len(
            memory.MemoryStore(session.memory_dir).prompt_section(memory.global_store(session.memory_dir))
        )
    definitions = [t.schema() for t in main_tools(with_memory=bool(session.memory_dir))]
    tools = len(json.dumps(definitions + (WEB_TOOLS if session.web else [])))
    chars = {
        'System prompt': max(0, len(session.system) - skills - memory_chars),
        'Tools': tools,
        'Skills': skills,
        'Memory files': memory_chars,
        'Messages': sum(message_breakdown(session.messages).values()),
    }
    estimate = sum(chars.values()) / 4 or 1
    measured = compaction.context_tokens(session.last_usage) if session.last_usage else 0
    scale = measured / estimate if measured else 1.0
    tokens = {name: round(n / 4 * scale) for name, n in chars.items()}
    if measured:  # rounding each part can leave the sum off by a few tokens; keep the total exact
        largest = max(tokens, key=lambda name: tokens[name])
        tokens[largest] += measured - sum(tokens.values())
    window = config.CONTEXT_WINDOW
    compact_at = c.settings.compact_at
    buffer = window - compact_at if 0 < compact_at < window else 0
    used = sum(tokens.values())
    categories = [_category(name, n) for name, n in tokens.items()]
    categories.append(_category(FREE, max(0, window - used - buffer)))
    if buffer:
        categories.append(_category(BUFFER, buffer))
    return ContextUsage(session.model, window, tuple(categories), measured, compact_at)


def context_text(u: ContextUsage) -> str:
    """The grid as text, with a legend beside it, as in Claude Code's /context."""
    cells = u.cells()
    rows = [' '.join(c.symbol for c in cells[i * GRID : (i + 1) * GRID]) for i in range(GRID)]
    legend = [f'{u.model} · {_k(u.used)}/{_k(u.window)} tokens ({100 * u.used / u.window:.1f}%)']
    legend.append('' if u.measured else '(estimated: nothing sent yet)')
    for c in u.categories:
        if c.tokens or c.name in (FREE,):
            legend.append(f'{c.name}: {_k(c.tokens)} ({100 * c.tokens / u.window:.1f}%)')
    lines = []
    for i in range(max(GRID, len(legend))):
        grid = rows[i] if i < GRID else ' ' * (2 * GRID - 1)
        lines.append(f'{grid}   {legend[i] if i < len(legend) else ""}'.rstrip())
    return 'Context usage\n' + '\n'.join(lines)


def _k(n: int) -> str:
    if n >= 1_000_000:
        return f'{n / 1_000_000:.1f}M'
    return f'{n / 1000:.1f}k' if n >= 1000 else str(n)


def message_breakdown(messages: Sequence[Message]) -> dict[str, int]:
    """Characters of the conversation by kind."""
    out = {
        'conversation text': 0,
        'thinking': 0,
        'tool calls': 0,
        'tool results': 0,
        'images': 0,
        'summary': 0,
    }
    for message in messages:
        content = message['content']
        if isinstance(content, str):
            out['conversation text'] += len(content)
            continue
        for block in content:
            kind = str(block.get('type'))
            if kind == 'text':
                out['conversation text'] += len(block.get('text', ''))
            elif kind == 'thinking':
                out['thinking'] += len(block.get('thinking', ''))
            elif kind in ('tool_use', 'server_tool_use'):
                out['tool calls'] += len(json.dumps(block.get('input', {})))
            elif kind == 'tool_result' or kind.endswith('_tool_result'):
                out['tool results'] += len(json.dumps(block.get('content', '')))
            elif kind == 'image':
                out['images'] += 6400  # ~1600 tokens for a typical image
            elif kind == 'compaction':
                out['summary'] += len(str(block.get('content', '')))
    return out


# ---- /status and /usage


def status(c: Controller) -> list[tuple[str, str]]:
    s, session = c.settings, c.session
    model = config.MODEL_BY_ID.get(s.model)
    store = c.memory_store()
    notes = f'{len(store.all())} for this project · {len(memory.global_store(store.directory).all())} global'
    return [
        ('Version', f'pycoder v{__version__}'),
        ('Device', env.describe()),
        ('Session', f'{session.title or "(untitled)"} · {session.id}'),
        ('Workspace', c.folder_label()),
        ('Model', f'{model.short} ({s.model})' if model else s.model),
        ('Effort', s.effort),
        ('Permission mode', s.mode),
        ('Rules', f'{len(s.allow)} allow · {len(s.ask)} ask · {len(s.deny)} deny'),
        ('Memory', notes if s.memory else 'off'),
        ('Instructions', ', '.join(n for n, _ in project_instructions(session.root)) or 'none'),
        ('Web tools', 'on' if session.web else 'off'),
        ('Skills', str(len(c.skills.all()))),
        ('Prompt cache', s.cache_ttl),
        *api_rows(c),
        ('Updates from', f'github.com/{config.UPDATE_REPO} ({config.UPDATE_BRANCH})'),
    ]


def api_rows(c: Controller) -> list[tuple[str, str]]:
    """What this device has spent with the API, from the saved sessions: the Console shows the whole
    account, and its balance."""
    now = time.time()
    month = time.strftime('%Y%m')
    tokens = cached = fresh = 0
    spent = saved = 0.0
    sessions = {i.id: (i.cost, i.updated, i.model, i.usage) for i in c.store.list()}
    current = c.session
    sessions[current.id] = (current.cost, time.time(), current.model, current.usage)
    for cost, updated, model, used in sessions.values():
        if time.strftime('%Y%m', time.localtime(updated)) == month:
            spent += cost
        if updated <= now - 7 * 24 * 3600:
            continue
        price_in, _, price_read, price_write = config.price_for(model)
        read, written = used.get('cache_read', 0), used.get('cache_write', 0)
        tokens += used.get('input', 0) + used.get('output', 0) + read + written
        cached += read
        fresh += used.get('input', 0) + read + written
        saved += (read * (price_in - price_read) - written * (price_write - price_in)) / 1e6
    rate = f'{cached / fresh:.0%} hit rate' if fresh else 'no requests yet'
    return [
        ('Spent this month', f'${spent:.2f} on this device (estimated from list prices)'),
        ('Prompt caching', f'{rate} · about ${saved:.2f} saved, last 7 days'),
        ('Tokens', f'{_k(tokens)}, last 7 days'),
    ]


def usage(c: Controller) -> list[tuple[str, str]]:
    """Tokens and cost: this session, then all saved sessions by day."""
    u = c.session.usage
    rows = [
        ('This session', f'${c.session.cost:.4f} · {len(c.session.turns)} requests'),
        (
            'Tokens',
            f'in {_k(u["input"])} · cache read {_k(u["cache_read"])} · cache write {_k(u["cache_write"])}'
            f' · out {_k(u["output"])}',
        ),
    ]
    now = time.time()
    day = 24 * 3600
    totals = {'Today': 0.0, 'Last 7 days': 0.0, 'Last 30 days': 0.0, 'All saved sessions': 0.0}
    for cost, updated in _saved_costs(c):
        totals['All saved sessions'] += cost
        if updated > now - 30 * day:
            totals['Last 30 days'] += cost
        if updated > now - 7 * day:
            totals['Last 7 days'] += cost
        if time.strftime('%Y%m%d', time.localtime(updated)) == time.strftime('%Y%m%d'):
            totals['Today'] += cost
    rows += [(name, f'${total:.2f}') for name, total in totals.items()]
    rows.append(('Note', 'costs are estimated from list prices; sessions are counted on their last day'))
    return rows


def _saved_costs(c: Controller) -> list[tuple[float, float]]:
    saved = c.store.list()
    out = [(c.session.cost if i.id == c.session.id else i.cost, i.updated) for i in saved]
    if c.session.id not in {i.id for i in saved}:
        out.append((c.session.cost, time.time()))
    return out


def table(rows: Sequence[tuple[str, str]]) -> str:
    width = max((len(k) for k, _ in rows), default=0)
    return '\n'.join(f'{k:<{width}}  {v}' for k, v in rows)
