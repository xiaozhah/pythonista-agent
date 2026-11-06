"""HTTP transport, request headers, retries, streaming turns and on-demand compaction."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from .. import config
from ..cancel import CancelToken
from ..events import Frontend
from ..types import JSON, Block, Usage
from .sse import iter_sse
from .stream import AssistantMessage, StreamError, consume_stream

RETRYABLE_STATUS = (408, 429, 500, 502, 503, 504, 529)
MAX_ATTEMPTS = 5
MAX_RETRY_AFTER = 60.0  # longer than this, giving up (and saying why) is better than a silent wait


class ApiError(Exception):
    def __init__(self, message: str, retryable: bool = False, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after  # seconds the server asked to wait (429, 529)


class Response(Protocol):
    status_code: int
    encoding: str | None

    @property
    def text(self) -> str: ...
    def json(self) -> Any: ...
    def iter_lines(self, chunk_size: int | None = ..., decode_unicode: bool = ...) -> Iterator[Any]: ...
    def close(self) -> None: ...


class Transport(Protocol):
    def post(self, url: str, headers: dict[str, str], body: JSON, stream: bool) -> Response: ...


class TransportError(Exception):
    """A network failure (connection reset, timeout, ...); always worth a retry."""


def _is_network_error(error: Exception) -> bool:
    if isinstance(error, (OSError, TransportError)):
        return True
    try:
        import requests
    except ImportError:
        return False
    return isinstance(error, requests.exceptions.RequestException)


class RequestsTransport:
    """HTTP through one requests.Session: each step of a turn reuses the open connection instead of
    paying a new TLS handshake (slow on mobile data)."""

    def __init__(self) -> None:
        self._session: Any = None

    def __del__(self) -> None:
        """Close the connection, rather than leave an open socket to warn when it is collected: the
        collector may run in the middle of a user's tests, where warnings are errors."""
        if self._session is not None:
            self._session.close()

    def post(self, url: str, headers: dict[str, str], body: JSON, stream: bool) -> Response:
        import requests

        if self._session is None:
            self._session = requests.Session()
        try:
            # a stream sends something every few seconds (pings while it thinks): 2 minutes of silence
            # is a stalled connection on mobile data, worth a retry; a whole answer can take longer
            response: Response = self._session.post(
                url, headers=headers, json=body, stream=stream, timeout=(15, 120 if stream else 600)
            )
        except requests.exceptions.RequestException as e:
            raise TransportError(str(e)) from e
        return response


@dataclass
class CompactResult:
    block: Block | None  # the compaction block to put first in `messages`, or None if no summary came back
    stop_reason: str | None
    usage: Usage = field(default_factory=dict)


class ApiClient:
    def __init__(self, api_key: str, transport: Transport | None = None, sleep: Any = None) -> None:
        self.api_key = api_key
        self.transport = transport or RequestsTransport()
        self.sleep = sleep

    def headers(self, model: str) -> dict[str, str]:
        betas = [config.BETA_COMPACTION, config.BETA_THINKING_BINDING]
        info = config.MODEL_BY_ID.get(model)
        if info is None or info.server_fallback:
            betas.append(config.BETA_FALLBACK)
        return {
            'content-type': 'application/json',
            'x-api-key': self.api_key,
            'anthropic-version': config.API_VERSION,
            'anthropic-beta': ','.join(betas),
        }

    def stream_turn(self, body: JSON, frontend: Frontend, cancel: CancelToken) -> AssistantMessage:
        """One streamed response; retries transient failures with backoff."""
        body = dict(body, stream=True)
        delay = 2.0
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._post(body, stream=True)
                # lines as bytes: decoded first, a U+2028 in a reply would split a line in two
                try:
                    with cancel.on_cancel(response.close):  # Stop ends a silent wait at once
                        return consume_stream(iter_sse(response.iter_lines()), frontend, cancel)
                finally:
                    response.close()
            except StreamError as e:
                error = ApiError(str(e), e.retryable)
            except ApiError as e:
                error = e
            except KeyboardInterrupt:
                raise
            except ValueError as e:  # a stream cut in the middle of a line
                error = ApiError(f'Incomplete reply: {e}', retryable=True)
            except Exception as e:  # the connection dropped while reading (requests raises its own types)
                if not _is_network_error(e):
                    raise
                error = ApiError(f'Connection lost: {e}', retryable=True)
            cancel.check()  # stopped: this error may only be the connection that Stop closed
            if not error.retryable or attempt == MAX_ATTEMPTS - 1:
                raise error
            wait = max(delay, min(error.retry_after, MAX_RETRY_AFTER))  # what the server asked for
            frontend.stream_discarded()  # the failed attempt's partial reply goes away
            frontend.notice('(%s, retrying in %ds)' % (str(error)[:100], wait), 'warn')
            if self.sleep:
                self.sleep(wait)
            else:
                cancel.wait(wait)
            delay *= 2
        raise AssertionError('unreachable')

    def complete(self, body: JSON, cancel: CancelToken | None = None) -> JSON:
        """One response, not streamed; transient failures are retried like a turn's, and a Stop
        ends the wait between tries."""
        body = dict(body, stream=False)
        delay = 2.0
        for attempt in range(MAX_ATTEMPTS):
            try:
                data: JSON = self._post(body, stream=False).json()
                return data
            except ApiError as e:
                if not e.retryable or attempt == MAX_ATTEMPTS - 1:
                    raise
                wait = max(delay, min(e.retry_after, MAX_RETRY_AFTER))
                if self.sleep:
                    self.sleep(wait)
                elif cancel is not None:
                    cancel.wait(wait)
                delay *= 2
        raise AssertionError('unreachable')

    def compact(self, body: JSON, instructions: str, cancel: CancelToken | None = None) -> CompactResult:
        """Ask for a summary of the conversation in `body` (on-demand compaction)."""
        body = dict(
            body,
            stream=False,
            max_tokens=config.COMPACT_MAX_TOKENS,
            compaction={'type': 'summarize', 'instructions': instructions},
        )
        body.pop('fallbacks', None)
        data = self.complete(body, cancel)
        blocks = [b for b in data.get('content', []) if b.get('type') == 'compaction']
        return CompactResult(blocks[0] if blocks else None, data.get('stop_reason'), data.get('usage') or {})

    def _post(self, body: JSON, stream: bool) -> Response:
        try:
            headers = self.headers(body['model'])
            response = self.transport.post(config.API_URL, headers, body, stream)
        except TransportError as e:
            raise ApiError(f'Network error: {e}', retryable=True) from e
        if response.status_code != 200:
            try:
                detail = response.json().get('error', {}).get('message', response.text)
            except ValueError:
                detail = response.text
            response.close()
            try:
                retry_after = float((getattr(response, 'headers', None) or {}).get('retry-after') or 0)
            except ValueError:
                retry_after = 0.0
            raise ApiError(
                'HTTP %d: %s' % (response.status_code, detail),
                retryable=response.status_code in RETRYABLE_STATUS,
                retry_after=retry_after,
            )
        return response
