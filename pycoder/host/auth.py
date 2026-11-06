"""Secrets (the Anthropic API key, a GitHub token): environment, then the iOS keychain, then ask once."""

from __future__ import annotations

import os
from collections.abc import Callable

from .. import config
from .env import IN_PYTHONISTA

GITHUB_ACCOUNT = 'github_token'


class MissingSecret(Exception):
    pass


def get_secret(account: str, env_var: str, ask: Callable[[], str | None], reset: bool = False) -> str:
    """Return a stored secret, or ask for one (ask returns None on cancel) and store it."""
    if not reset:
        value = os.environ.get(env_var) or _keychain_get(account)
        if value:
            return value
    value = (ask() or '').strip()
    if not value:
        raise MissingSecret(f'No {account} provided')
    _keychain_set(account, value)
    return value


def get_api_key(ask: Callable[[], str | None], reset: bool = False) -> str:
    return get_secret(config.KEYCHAIN_ACCOUNT, 'ANTHROPIC_API_KEY', ask, reset)


def get_github_token(ask: Callable[[], str | None], reset: bool = False) -> str:
    return get_secret(GITHUB_ACCOUNT, 'GITHUB_TOKEN', ask, reset)


def _keychain_get(account: str) -> str | None:
    if not IN_PYTHONISTA:
        return None
    import keychain

    return keychain.get_password(config.KEYCHAIN_SERVICE, account)


def _keychain_set(account: str, value: str) -> None:
    if IN_PYTHONISTA:
        import keychain

        keychain.set_password(config.KEYCHAIN_SERVICE, account, value)
