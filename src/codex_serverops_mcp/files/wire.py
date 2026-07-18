from __future__ import annotations

import base64
import binascii
import re
import secrets
from dataclasses import dataclass

from .errors import RemoteFileError

WIRE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MAX_WIRE_TEXT_BYTES = 8_388_608


@dataclass(frozen=True, slots=True)
class FileWireCommand:
    token: str
    command: str


@dataclass(frozen=True, slots=True)
class FileWireResponse:
    rows: dict[str, tuple[tuple[bytes, ...], ...]]

    def one(self, name: str) -> str:
        values = self.rows.get(name, ())
        if len(values) != 1 or len(values[0]) != 1:
            raise RemoteFileError("file_protocol_error", f"invalid remote field: {name}")
        return _text(values[0][0])

    def optional(self, name: str) -> str | None:
        values = self.rows.get(name, ())
        if not values:
            return None
        if len(values) != 1 or len(values[0]) != 1:
            raise RemoteFileError("file_protocol_error", f"invalid remote field: {name}")
        return _text(values[0][0])

    def one_bytes(self, name: str) -> bytes:
        values = self.rows.get(name, ())
        if len(values) != 1 or len(values[0]) != 1:
            raise RemoteFileError("file_protocol_error", f"invalid remote field: {name}")
        return values[0][0]

    def many(self, name: str, *, width: int) -> tuple[tuple[str, ...], ...]:
        values = self.rows.get(name, ())
        if any(len(value) != width for value in values):
            raise RemoteFileError("file_protocol_error", f"invalid remote rows: {name}")
        return tuple(tuple(_text(cell) for cell in value) for value in values)


def new_wire_token() -> str:
    return secrets.token_hex(16)


def encode_argument(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def parse_file_response(output: str, token: str) -> FileWireResponse:
    if len(output.encode("utf-8", errors="replace")) > MAX_WIRE_TEXT_BYTES:
        raise RemoteFileError("file_protocol_error", "remote file response exceeds its limit")
    begin = f"__SERVEROPS_FILE_BEGIN_{token}__"
    end = f"__SERVEROPS_FILE_END_{token}__"
    lines = output.replace("\r\n", "\n").replace("\r", "").split("\n")
    try:
        begin_index = lines.index(begin)
        end_index = lines.index(end, begin_index + 1)
    except ValueError as error:
        raise RemoteFileError(
            "file_protocol_error",
            "remote file response markers are missing",
        ) from error
    if end_index != len(lines) - 1 and any(lines[end_index + 1 :]):
        raise RemoteFileError("file_protocol_error", "unexpected data follows file response")
    parsed: dict[str, list[tuple[bytes, ...]]] = {}
    for line in lines[begin_index + 1 : end_index]:
        cells = line.split("\t")
        key = cells[0]
        if not WIRE_KEY.fullmatch(key) or len(cells) < 2:
            raise RemoteFileError("file_protocol_error", "remote file response row is invalid")
        values = tuple(_decode_cell(cell) for cell in cells[1:])
        parsed.setdefault(key, []).append(values)
    response = FileWireResponse({key: tuple(values) for key, values in parsed.items()})
    status = response.one("status")
    if status == "error":
        raise RemoteFileError(response.one("code"), response.one("message"))
    if status != "ok":
        raise RemoteFileError("file_protocol_error", "remote file response status is invalid")
    return response


def _decode_cell(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as error:
        raise RemoteFileError(
            "file_protocol_error",
            "remote file response contains invalid base64",
        ) from error


def _text(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RemoteFileError(
            "file_protocol_error",
            "remote file response contains invalid encoded text",
        ) from error
