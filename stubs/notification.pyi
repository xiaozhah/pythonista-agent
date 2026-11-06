from typing import Any

def schedule(
    message: str | None = ...,
    delay: float = ...,
    sound_name: str | None = ...,
    action_url: str | None = ...,
    title: str | None = ...,
    subtitle: str | None = ...,
    **kwargs: Any,
) -> Any: ...
def cancel(identifier: str) -> None: ...
