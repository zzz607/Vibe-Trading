"""Per-conversation LLM session identity.

Some relays require a stable per-conversation identifier on every request.
OpenCode Go rejects calls that lack ``x-opencode-session`` (HTTP 400
``MissingSessionID``) because it uses the id for routing and prompt caching.

The agent loop binds the active Vibe session id here for the duration of a
run; provider adapters read it at request time. A ``ContextVar`` keeps the
binding thread- and task-local, so concurrent sessions never see each other's
id and nothing has to be threaded through every LangChain call site.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_LLM_SESSION_ID: ContextVar[str] = ContextVar("vibe_llm_session_id", default="")

# Fixed namespace for turning Vibe's own session id into a UUID. Vibe ids are
# short hex tokens (``uuid4().hex[:12]``) while OpenCode Go expects a
# 36-character UUID in ``x-opencode-session``; ``uuid5`` maps one to the other
# deterministically, so a conversation keeps the same id across requests,
# processes and restarts.
_SESSION_NAMESPACE = uuid.UUID("6f0f2c1a-4b8e-4d55-9c31-2a7d5e8b41c6")


def _session_uuid(raw: str) -> str:
    """Return the 36-character UUID derived from a Vibe session id."""
    return str(uuid.uuid5(_SESSION_NAMESPACE, raw))


def bind_llm_session_id(session_id: str | None) -> Token[str]:
    """Bind ``session_id`` as the active LLM session in the current context.

    Args:
        session_id: Vibe session id; empty or ``None`` clears the binding.

    Returns:
        Token to pass to :func:`reset_llm_session_id` when the run ends.

    The bound value is a 36-character UUID derived from ``session_id`` with
    :func:`uuid.uuid5`: relays such as OpenCode Go require that shape, and a
    deterministic mapping keeps one conversation on one id everywhere.
    """
    raw = (session_id or "").strip()
    return _LLM_SESSION_ID.set(_session_uuid(raw) if raw else "")


def reset_llm_session_id(token: Token[str]) -> None:
    """Restore the binding that was active before :func:`bind_llm_session_id`."""
    _LLM_SESSION_ID.reset(token)


def current_llm_session_id() -> str:
    """Return the active LLM session id, or ``""`` outside a bound run."""
    return _LLM_SESSION_ID.get()
