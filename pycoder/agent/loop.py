"""The tool-use loop for one user turn, shared by the main conversation and subagents."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass

from .. import config
from ..api import ApiClient, ApiError, AssistantMessage
from ..api.stream import echo_content
from ..cancel import CancelToken
from ..events import Frontend
from ..host import background
from ..state.checkpoints import Checkpoints
from ..state.session import Session
from ..state.workspace import Workspace
from ..tools import jobs
from ..tools.base import Tool, ToolContext, ToolError, validate_input
from ..tools.describe import doing
from ..types import JSON, Block, Message, Usage
from . import compaction, permissions
from .permissions import Policy

# Added when the user stops a response, so the next request doesn't pick the abandoned one back up
INTERRUPTED_NOTE: Block = {
    'type': 'text',
    'text': "<system-reminder>The user stopped the response above. Don't continue that work unless "
    'they ask again.</system-reminder>',
}

# Added when the conversation was summarized in the middle of a request, so the model carries on
CONTINUE_NOTE: Block = {
    'type': 'text',
    'text': '<system-reminder>The conversation was summarized to make room while you were working on '
    "the user's request; continue it from the summary.</system-reminder>",
}


def web_tools(model: str) -> list[JSON]:
    """web_search and web_fetch in the versions the model accepts."""
    info = config.MODEL_BY_ID.get(model)
    search, fetch = info.web_tools if info else config.WEB_TOOLS_BASIC
    return [
        {'type': search, 'name': 'web_search', 'max_uses': 5},
        {'type': fetch, 'name': 'web_fetch', 'max_uses': 5},
    ]


WEB_TOOLS = web_tools(config.DEFAULT_MODEL)


@dataclass
class TurnResult:
    status: str  # 'done', 'exhausted' (out of steps), 'interrupted', 'error' or 'refused'
    text: str = ''
    model: str = ''
    usage: Usage | None = None  # usage of the last response, for deciding when to compact
    rolled_back: bool = False  # the conversation is as it was before the request


@dataclass
class AgentSettings:
    model: str
    effort: str
    system: str
    web: bool
    max_steps: int = 200  # responses per turn; subagents get fewer
    cache_ttl: str = '5m'
    compact_at: int = 0  # context tokens at which to compact between steps of a turn (0: never)


class Agent:
    def __init__(
        self,
        client: ApiClient,
        tools: list[Tool],
        settings: AgentSettings,
        frontend: Frontend,
        cancel: CancelToken,
        workspace: Workspace,
        session: Session,
        checkpoints: Checkpoints,
        policy: Policy,
        on_usage: Callable[[Usage, str | None], None],
        on_attention: Callable[[str], None] | None = None,
        compact: Callable[[], bool] | None = None,
        on_step: Callable[[], None] | None = None,
    ) -> None:
        self.client = client
        self.tools = {t.name: t for t in tools}
        self.settings = settings
        self.frontend = frontend
        self.cancel = cancel
        self.workspace = workspace
        self.session = session
        self.checkpoints = checkpoints
        self.policy = policy
        self.on_usage = on_usage
        self.on_attention = on_attention or (lambda message: None)  # the user is needed (a notification)
        self.on_step = on_step or (lambda: None)  # a reply and its tools are done: save what happened
        # summarize the conversation given to run_turn in place (True if it did), when it grows too big
        self.compact = compact

    def get_mode(self) -> str:
        return self.policy.get_mode()

    def set_mode(self, mode: str) -> None:
        self.policy.set_mode(mode)

    # ---- requests

    def request_body(self, messages: list[Message]) -> JSON:
        s = self.settings
        body: JSON = {
            'model': s.model,
            'max_tokens': config.MAX_TOKENS,
            'system': s.system,
            'tools': [t.schema() for t in self.tools.values()],
            'messages': messages,
            'thinking': {
                'type': 'adaptive',
                'display': 'summarized',
                # if history ever changes under a thinking block, drop the block instead of failing
                'block_binding': {'prefix_mismatch_behavior': 'drop_block'},
            },
            'output_config': {'effort': s.effort},
            'cache_control': {'type': 'ephemeral', **({'ttl': '1h'} if s.cache_ttl == '1h' else {})},
        }
        # server-side tools run without asking anyone, so the policy decides here whether they are
        # offered: a deny rule turns them off
        if s.web:
            body['tools'] += [w for w in web_tools(s.model) if not self._refused(w['name'])]
        info = config.MODEL_BY_ID.get(s.model)
        if info is None or info.server_fallback:
            body['fallbacks'] = 'default'  # a declined request is retried server-side on another model
        return body

    def _refused(self, name: str) -> bool:
        """Whether a server-side tool stays out of the request: the policy never sees its calls, so
        one that must ask can't be offered."""
        tool = Tool(name, '', {}, lambda ctx: '')
        return self.policy.decide(tool, {}).action != 'allow'

    # ---- the loop

    def run_turn(self, messages: list[Message], content: list[Block]) -> TurnResult:
        """Append the user's content, then call the model and run tools until it stops.

        `messages` is updated in place. On an API error or a refusal before any tool ran, the turn is
        rolled back, so the conversation stays as it was; once tools have run (files may have
        changed) what happened is kept, with a note that the request then failed, as it is on
        interruption.
        """
        snapshot_len = len(messages)
        snapshot_last = json.dumps(messages[-1]) if messages else None
        add_user_content(messages, content)

        tools_ran = False

        paused = 0  # replies at the end of the conversation whose server tools haven't finished

        def forget_paused() -> None:
            """Those can only be followed by asking the model to go on, so they can't stay when the
            turn ends: anything after them makes every later request fail."""
            if paused:
                del messages[-paused:]

        def give_up(status: str, why: str) -> TurnResult:
            forget_paused()
            if tools_ran:  # keep the record of what was done; say the rest didn't happen
                note = f'<system-reminder>The request failed after the tool calls above ({why}).'
                note += '</system-reminder>'
                add_user_content(messages, [{'type': 'text', 'text': note}])
                return TurnResult(status, why)
            del messages[snapshot_len:]
            if snapshot_last is not None:
                messages[-1] = json.loads(snapshot_last)
            return TurnResult(status, why, rolled_back=True)

        msg: AssistantMessage | None = None
        for _ in range(self.settings.max_steps):
            if (
                not paused and 'job_output' in self.tools
            ):  # the agent that runs background jobs hears when they end
                notes = jobs.ended_notes()
                if notes:
                    add_user_content(messages, [{'type': 'text', 'text': '\n'.join(notes)}])
            try:
                msg = self.client.stream_turn(self.request_body(messages), self.frontend, self.cancel)
            except KeyboardInterrupt as e:
                forget_paused()
                partial = getattr(e, 'text', '')
                if partial:  # keep what was shown, so history and the next request match the screen
                    messages.append({'role': 'assistant', 'content': [{'type': 'text', 'text': partial}]})
                add_user_content(messages, [INTERRUPTED_NOTE])
                self.frontend.notice('Interrupted')
                return TurnResult('interrupted')
            except ApiError as e:
                self.frontend.notice(f'✗ {e}', 'error')
                return give_up('error', str(e))
            self.on_usage(msg.usage, msg.model)

            if msg.stop_reason == 'refusal':
                category = (msg.stop_details or {}).get('category')
                self.frontend.notice(f'✗ Request declined ({category})', 'error')
                return give_up('refused', f'declined: {category}')

            reply = echo_content(msg.content)
            if reply:
                messages.append({'role': 'assistant', 'content': reply})
            if msg.stop_reason == 'pause_turn':
                paused += 1 if reply else 0
                continue  # a server tool needs another round
            paused = 0
            tool_uses = [b for b in reply if b['type'] == 'tool_use']
            if not tool_uses:
                if msg.stop_reason == 'max_tokens':
                    self.frontend.notice('(output hit the max_tokens limit and was cut off)', 'warn')
                return TurnResult('done', msg.text, msg.model or self.settings.model, msg.usage)
            tools_ran = True
            if not self._run_tools(messages, msg, tool_uses):
                return TurnResult('interrupted')
            self.on_step()
            if (
                self.compact
                and compaction.needs_compaction(msg.usage, self.settings.compact_at)
                and self.compact()
            ):
                add_user_content(messages, [CONTINUE_NOTE])

        self.frontend.notice('(stopped after %d steps)' % self.settings.max_steps, 'warn')
        return TurnResult(
            'exhausted', msg.text if msg else '', self.settings.model, msg.usage if msg else None
        )

    def _run_tools(self, messages: list[Message], msg: AssistantMessage, tool_uses: list[Block]) -> bool:
        """Run the calls and append their results; False if the user interrupted.

        Every call gets a result, whatever happens: a tool_use without one makes every later
        request fail.
        """
        results: list[Block] = []
        try:
            for batch in _batches(tool_uses):
                self.cancel.check()
                if msg.stop_reason == 'max_tokens':
                    cut = 'Output was cut off by max_tokens, so the input is incomplete and was not run. '
                    results += [
                        tool_result(b['id'], cut + 'Split the work into smaller steps.', True) for b in batch
                    ]
                elif len(batch) > 1:
                    results += self._run_together(batch, msg.invalid_json)
                else:
                    results.append(self.run_tool(batch[0], msg.invalid_json))
        except BaseException as e:
            interrupted = isinstance(e, KeyboardInterrupt)
            why = 'The user interrupted execution' if interrupted else f'Not run: {type(e).__name__}: {e}'
            done = {r['tool_use_id'] for r in results}
            results += [tool_result(b['id'], why, True) for b in tool_uses if b['id'] not in done]
            add_user_content(messages, [*results, *([INTERRUPTED_NOTE] if interrupted else [])])
            if not interrupted:
                raise
            self.frontend.notice('Interrupted')
            return False
        add_user_content(messages, results)
        return True

    def run_tool(self, block: Block, invalid_json: dict[str, str]) -> Block:
        """Run one call."""
        self.frontend.tool_run(block)
        background.say(doing(block['name'], block['input']))
        result = None
        try:
            result = self._guarded(block, invalid_json)
            return result
        finally:
            self.frontend.tool_done(block, _result_text(result))

    def _run_together(self, blocks: list[Block], invalid_json: dict[str, str]) -> list[Block]:
        """Run calls at the same time (subagents, which take minutes each); the results come back in
        the calls' order. A Stop interrupts them all."""
        self.frontend.tools_run(blocks)
        background.say(f'{len(blocks)} tasks')
        done: dict[str, Block] = {}
        failed: list[BaseException] = []

        def run(block: Block) -> None:
            try:
                done[block['id']] = self._guarded(block, invalid_json)
            except BaseException as e:  # an interruption; raised again once they have all ended
                failed.append(e)

        threads = [threading.Thread(target=run, args=(b,), daemon=True) for b in blocks]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for block in blocks:
            self.frontend.tool_done(block, _result_text(done.get(block['id'])))
        if failed:
            raise failed[0]
        return [done[b['id']] for b in blocks]

    def _guarded(self, block: Block, invalid_json: dict[str, str]) -> Block:
        """Anything that goes wrong (in the tool, a preview, saving a rule) is an
        error result for the model, not the end of the turn."""
        try:
            return self._run_tool(block, invalid_json)
        except Exception as e:
            message = str(e) if isinstance(e, ToolError) else f'{type(e).__name__}: {e}'
            self.frontend.tool_error(message)
            return tool_result(block['id'], message, True)

    def _run_tool(self, block: Block, invalid_json: dict[str, str]) -> Block:
        name, inp, tid = block['name'], block.get('input') or {}, block['id']
        if tid in invalid_json:
            self.frontend.tool_error('invalid JSON input')
            return tool_result(tid, json.dumps({'INVALID_JSON': invalid_json[tid]}, ensure_ascii=False), True)
        tool = self.tools.get(name)
        if tool is None:
            return tool_result(tid, f'Unknown tool {name}', True)
        problem = validate_input(tool, inp)
        if problem:
            self.frontend.tool_error(problem)
            return tool_result(tid, problem, True)
        ctx = ToolContext(
            self.workspace, self.frontend, self.session, self.checkpoints, self.cancel, self, tid
        )
        decision = self.policy.decide(tool, inp)
        if decision.action == 'deny':
            self.frontend.tool_error(decision.reason, 'denied')
            return tool_result(tid, f'Not allowed: {decision.reason}.', True)
        if decision.action == 'plan':
            self.frontend.tool_error('plan mode: not run', 'denied')
            return tool_result(
                tid,
                'Plan mode is on, so nothing can be changed yet. Finish researching, then '
                'call exit_plan_mode with your plan for the user to approve.',
                True,
            )
        if decision.action == 'ask':
            # show the exact change before asking; a change that can't apply fails without a question
            preview = tool.preview(ctx, **inp) if tool.preview else None
            rule = permissions.rule_for(name, inp, self.workspace.root)
            self.on_attention(f'Approval needed: {name} {permissions.target(name, inp)}'.strip())
            answer, note = self.frontend.confirm(name, inp, preview, rule)
            self.cancel.check()  # Stop while the question was open: interrupted, not denied
            if answer == 'always' and rule:
                self.policy.always_allow(rule)
            elif answer != 'yes':
                self.frontend.tool_error('denied', 'denied')
                return tool_result(
                    tid, 'The user denied this action.' + (' User note: ' + note if note else ''), True
                )
        scan = ctx.checkpoints.scan() if tool.writes_anywhere and tool.needs_confirmation(inp) else None
        try:
            return tool_result(tid, tool.run(ctx, **inp))
        finally:
            ctx.checkpoints.record(scan)


# calls that run at the same time as calls of the same kind next to them in one reply: subagents
CONCURRENT = {'task'}


def _batches(tool_uses: list[Block]) -> list[list[Block]]:
    """The calls of a reply in the order to run them: each alone, except neighbouring subagents."""
    batches: list[list[Block]] = []
    for block in tool_uses:
        if batches and block['name'] in CONCURRENT and batches[-1][0]['name'] in CONCURRENT:
            batches[-1].append(block)
        else:
            batches.append([block])
    return batches


def _result_text(result: Block | None) -> str:
    if result is None:
        return ''
    content = result['content']
    return content if isinstance(content, str) else '\n'.join(b.get('text', '') for b in content)


def _valid_text(text: str) -> str:
    """Without lone surrogates, which a tool can print and the API can't take."""
    return text.encode('utf-8', 'replace').decode('utf-8')


def tool_result(tool_use_id: str, content: object, is_error: bool = False) -> Block:
    """The result block for a call. content is the result text, or content blocks when a tool
    returns images; anything else (None, a number, a dict) becomes text. Text
    is cut at MAX_TOOL_OUTPUT characters, also inside blocks, and is never empty."""
    body: str | list[Block]
    if isinstance(content, list) and content and all(isinstance(b, dict) and 'type' in b for b in content):
        body, budget = [], config.MAX_TOOL_OUTPUT
        for b in content:
            if b['type'] == 'text':
                text = str(b.get('text') or '')
                if not text:
                    continue  # an empty text block is invalid
                b = {**b, 'text': _truncate(_valid_text(text), budget)}
                budget = max(0, budget - len(text))
            body.append(b)
        body = body or '(no output)'
    else:
        if content is None or isinstance(content, str):
            text = content or ''
        elif isinstance(content, (dict, list)):
            text = json.dumps(content, ensure_ascii=False, default=str)
        else:
            text = str(content)
        body = _truncate(_valid_text(text), config.MAX_TOOL_OUTPUT) or '(no output)'
    result: Block = {'type': 'tool_result', 'tool_use_id': tool_use_id, 'content': body}
    if is_error:
        result['is_error'] = True
    return result


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + '\n... [output too long, truncated; %d characters total]' % len(text)


def settled(messages: list[Message]) -> list[Message]:
    """A copy of the conversation that a request can send while a turn runs: an assistant message
    whose tool calls have no results yet is left out. Messages are copied, so adding to the copy's
    last one leaves the conversation as it is."""
    copy = [dict(m) for m in messages]
    while copy and copy[-1]['role'] == 'assistant':
        content = copy[-1]['content']
        if isinstance(content, str) or not any(b.get('type') == 'tool_use' for b in content):
            break
        copy.pop()
    return copy


def add_user_content(messages: list[Message], blocks: list[Block]) -> None:
    """Append to the last user message if there is one at the end, else start a new one."""
    if messages and messages[-1]['role'] == 'user':
        previous = messages[-1]['content']
        if isinstance(previous, str):
            previous = [{'type': 'text', 'text': previous}]
        messages[-1]['content'] = previous + blocks
    else:
        messages.append({'role': 'user', 'content': blocks})
