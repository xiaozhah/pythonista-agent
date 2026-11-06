"""The Claude Messages API over raw HTTP (the official SDK can't be installed in Pythonista)."""

from .client import ApiClient, ApiError, CompactResult
from .stream import AssistantMessage

__all__ = ['ApiClient', 'ApiError', 'AssistantMessage', 'CompactResult']
