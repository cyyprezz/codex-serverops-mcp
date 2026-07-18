from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .errors import AuthenticationProtocolError

MAX_AUTH_RESPONSE_BYTES = 4_096


class AuthResponseKind(IntEnum):
    SECRET = 1
    CONFIRM = 2
    REJECT = 3
    CANCEL = 4
    TIMEOUT = 5


@dataclass(slots=True)
class AuthResponse:
    kind: AuthResponseKind
    secret: bytearray | None = None

    @property
    def status(self) -> str:
        return {
            AuthResponseKind.SECRET: "submitted",
            AuthResponseKind.CONFIRM: "confirmed",
            AuthResponseKind.REJECT: "rejected",
            AuthResponseKind.CANCEL: "cancelled",
            AuthResponseKind.TIMEOUT: "timed_out",
        }[self.kind]

    def clear(self) -> None:
        if self.secret is not None:
            self.secret[:] = b"\0" * len(self.secret)


def secret_response_frame(secret: bytearray) -> bytearray:
    if not secret or len(secret) > MAX_AUTH_RESPONSE_BYTES:
        raise AuthenticationProtocolError("authentication response has an invalid length")
    if b"\r" in secret or b"\n" in secret:
        raise AuthenticationProtocolError("authentication response contains a line ending")
    frame = bytearray((AuthResponseKind.SECRET,))
    frame.extend(secret)
    return frame


def decision_response_frame(kind: AuthResponseKind) -> bytes:
    if kind is AuthResponseKind.SECRET:
        raise AuthenticationProtocolError("a secret response requires response bytes")
    return bytes((kind,))


def decode_auth_response(frame: bytes) -> AuthResponse:
    if not frame:
        raise AuthenticationProtocolError("authentication response is empty")
    try:
        kind = AuthResponseKind(frame[0])
    except ValueError as error:
        raise AuthenticationProtocolError("authentication response type is unknown") from error
    if kind is AuthResponseKind.SECRET:
        secret = bytearray(frame[1:])
        try:
            if not secret or len(secret) > MAX_AUTH_RESPONSE_BYTES:
                raise AuthenticationProtocolError(
                    "authentication response has an invalid length"
                )
            if b"\r" in secret or b"\n" in secret:
                raise AuthenticationProtocolError(
                    "authentication response contains a line ending"
                )
            return AuthResponse(kind, secret)
        except BaseException:
            secret[:] = b"\0" * len(secret)
            raise
    if len(frame) != 1:
        raise AuthenticationProtocolError("authentication decision contains unexpected data")
    return AuthResponse(kind)
