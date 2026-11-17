"""Local pre-send limits on Messages API attempts, independent of advisory task budgets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from anthropic import APIRequest, CallNext

if TYPE_CHECKING:
    from learn_it.config import Settings


class AgentError(RuntimeError):
    """The agent stopped without a usable answer."""


class SessionLimitError(AgentError):
    """A local limit rejected a request before any HTTP attempt was forwarded."""

    def __init__(self, limit: int, *, compaction: bool = False) -> None:
        self.compaction = compaction
        super().__init__(f"Limite locale atteinte : {limit} tentative(s) de requête API.")


@dataclass
class SessionLimits:
    """Share one instance across a command's repairs, or across every chat question.

    The request limit counts each forwarded HTTP attempt, including automatic retries,
    thread recovery and compaction. It cannot count the provider's internal operations.
    max_output_tokens caps each request's max_tokens; neither limit is a financial cap.
    """

    max_requests: int | None = None
    max_output_tokens: int = 16_000
    requests_sent: int = field(default=0, init=False)
    responses_observed: int = field(default=0, init=False)
    _lock: Any = field(default_factory=Lock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.max_requests is not None and (
            type(self.max_requests) is not int or self.max_requests < 1
        ):
            raise ValueError("La limite de requêtes doit être un entier positif.")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("La limite de tokens de sortie doit être un entier positif.")

    @classmethod
    def from_settings(cls, settings: Settings) -> SessionLimits:
        return cls(settings.max_requests, settings.max_output_tokens)

    def ensure_available(self, *, compaction: bool = False) -> None:
        """Preflight before staging a new chat question or allocating another API client."""
        with self._lock:
            self._ensure_available(compaction=compaction)

    def _ensure_available(self, *, compaction: bool) -> None:
        if self.max_requests is not None and self.requests_sent >= self.max_requests:
            raise SessionLimitError(self.max_requests, compaction=compaction)

    def observe_response(self) -> None:
        with self._lock:
            self.responses_observed += 1

    @property
    def has_unobserved_attempts(self) -> bool:
        with self._lock:
            return self.requests_sent > self.responses_observed

    def middleware(self, request: APIRequest, call_next: CallNext):
        """Public SDK hook: enforce limits before each individual network attempt."""
        if (
            request.method.lower() != "post"
            or urlsplit(request.url).path.rstrip("/") != "/v1/messages"
        ):
            return call_next(request)
        body = request.json
        if not isinstance(body, Mapping):
            raise AgentError("Impossible d'appliquer la limite locale à une requête non JSON.")
        requested = body.get("max_tokens", self.max_output_tokens)
        if type(requested) is not int or requested < 1:
            raise AgentError("La requête doit contenir un max_tokens entier positif.")
        with self._lock:
            self._ensure_available(compaction=bool(body.get("compaction")))
            forwarded = request.copy(
                body={
                    **body,
                    "max_tokens": min(requested, self.max_output_tokens),
                }
            )
            # Redirects can issue extra POSTs inside one SDK attempt, beyond this guard.
            # Set the per-request option on the copy; never mutate the caller's request.
            forwarded.options.follow_redirects = False
            # Reserve immediately before call_next; failed/unknown attempts still count.
            self.requests_sent += 1
        return call_next(forwarded)
