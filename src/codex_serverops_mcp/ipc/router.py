from __future__ import annotations

from collections.abc import Callable, Mapping

from .messages import Envelope

MessageHandler = Callable[[Mapping[str, object]], dict[str, object]]


class MessageRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, MessageHandler] = {}

    def register(self, message_type: str, handler: MessageHandler) -> None:
        if message_type in self._handlers:
            raise ValueError(f"message handler is already registered: {message_type}")
        Envelope.create(message_type)
        self._handlers[message_type] = handler

    def dispatch(self, request: Envelope) -> Envelope:
        handler = self._handlers.get(request.message_type)
        if handler is None:
            return Envelope.create(
                "error",
                {
                    "code": "unknown_message_type",
                    "message_type": request.message_type,
                },
                message_id=request.message_id,
            )
        return Envelope.create(
            f"{request.message_type}.result",
            handler(request.payload),
            message_id=request.message_id,
        )
