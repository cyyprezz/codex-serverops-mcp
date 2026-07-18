from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from .errors import InvalidSessionState


class SessionState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    AUTHENTICATION_REQUIRED = "authentication_required"
    READY = "ready"
    EXECUTING = "executing"
    INTERACTIVE = "interactive"
    LOST = "lost"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


ALLOWED_TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.CREATED: frozenset({SessionState.STARTING, SessionState.CLOSING}),
    SessionState.STARTING: frozenset(
        {
            SessionState.AUTHENTICATION_REQUIRED,
            SessionState.READY,
            SessionState.LOST,
            SessionState.FAILED,
            SessionState.CLOSING,
        }
    ),
    SessionState.AUTHENTICATION_REQUIRED: frozenset(
        {
            SessionState.STARTING,
            SessionState.EXECUTING,
            SessionState.LOST,
            SessionState.FAILED,
            SessionState.CLOSING,
        }
    ),
    SessionState.READY: frozenset(
        {
            SessionState.EXECUTING,
            SessionState.INTERACTIVE,
            SessionState.LOST,
            SessionState.FAILED,
            SessionState.CLOSING,
        }
    ),
    SessionState.EXECUTING: frozenset(
        {
            SessionState.AUTHENTICATION_REQUIRED,
            SessionState.READY,
            SessionState.LOST,
            SessionState.FAILED,
            SessionState.CLOSING,
        }
    ),
    SessionState.INTERACTIVE: frozenset(
        {
            SessionState.READY,
            SessionState.LOST,
            SessionState.FAILED,
            SessionState.CLOSING,
        }
    ),
    SessionState.LOST: frozenset({SessionState.CLOSING, SessionState.CLOSED}),
    SessionState.FAILED: frozenset({SessionState.CLOSING, SessionState.CLOSED}),
    SessionState.CLOSING: frozenset({SessionState.CLOSED}),
    SessionState.CLOSED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    state: SessionState
    generation: int
    changed_at: float


class SessionStateMachine:
    def __init__(self) -> None:
        self._state = SessionState.CREATED
        self._generation = 0
        self._changed_at = time.monotonic()
        self._auth_return_state: SessionState | None = None
        self._lock = RLock()

    @property
    def state(self) -> SessionState:
        with self._lock:
            return self._state

    def snapshot(self) -> StateSnapshot:
        with self._lock:
            return StateSnapshot(self._state, self._generation, self._changed_at)

    def require(self, *states: SessionState) -> None:
        with self._lock:
            if self._state not in states:
                expected = ", ".join(state.value for state in states)
                raise InvalidSessionState(
                    f"operation requires state {expected}; current state is {self._state.value}"
                )

    def transition(self, target: SessionState) -> StateSnapshot:
        with self._lock:
            if target not in ALLOWED_TRANSITIONS[self._state]:
                raise InvalidSessionState(
                    f"invalid session transition: {self._state.value} -> {target.value}"
                )
            self._state = target
            self._generation += 1
            self._changed_at = time.monotonic()
            return StateSnapshot(self._state, self._generation, self._changed_at)

    def begin_authentication(self) -> None:
        with self._lock:
            if self._state not in {
                SessionState.STARTING,
                SessionState.EXECUTING,
            }:
                raise InvalidSessionState(
                    f"authentication prompt is invalid in state {self._state.value}"
                )
            self._auth_return_state = self._state
            self.transition(SessionState.AUTHENTICATION_REQUIRED)

    def finish_authentication(self) -> None:
        with self._lock:
            if self._state is not SessionState.AUTHENTICATION_REQUIRED:
                raise InvalidSessionState("authentication is not active")
            target = self._auth_return_state
            self._auth_return_state = None
            if target is None:
                raise InvalidSessionState("authentication return state is unavailable")
            self.transition(target)

    def begin_close(self) -> bool:
        with self._lock:
            if self._state is SessionState.CLOSED:
                return False
            if self._state is SessionState.CLOSING:
                return True
            self._auth_return_state = None
            self.transition(SessionState.CLOSING)
            return True
