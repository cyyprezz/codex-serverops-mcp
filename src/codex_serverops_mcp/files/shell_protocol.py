from __future__ import annotations

from dataclasses import dataclass

from .wire import FileWireCommand, encode_argument, new_wire_token


@dataclass(frozen=True, slots=True)
class FileShellProtocol:
    allowed_roots: tuple[str, ...]

    def wrap(self, body: str) -> FileWireCommand:
        token = new_wire_token()
        roots = " ".join(encode_argument(root) for root in self.allowed_roots)
        begin = f"__SERVEROPS_FILE_BEGIN_{token}__"
        end = f"__SERVEROPS_FILE_END_{token}__"
        prologue = f"""(
set +e
_serverops_begin='{begin}'
_serverops_end='{end}'
_serverops_roots='{roots}'
_serverops_encode() {{ base64 | tr -d '\\r\\n'; }}
_serverops_decode() {{ printf '%s' "$1" | base64 -d; }}
_serverops_row() {{
  _serverops_row_key=$1
  shift
  printf '%s' "$_serverops_row_key"
  for _serverops_row_value in "$@"; do
    printf '\\t'
    printf '%s' "$_serverops_row_value" | _serverops_encode
  done
  printf '\\n'
}}
_serverops_blob() {{
  printf '%s\\t' "$1"
  _serverops_encode
  printf '\\n'
}}
_serverops_error() {{
  printf '%s\\n' "$_serverops_begin"
  _serverops_row status error
  _serverops_row code "$1"
  _serverops_row message "$2"
  printf '%s\\n' "$_serverops_end"
  exit 0
}}
_serverops_success() {{
  printf '%s\\n' "$_serverops_begin"
  _serverops_row status ok
}}
_serverops_finish() {{ printf '%s\\n' "$_serverops_end"; exit 0; }}
_serverops_allowed() {{
  _serverops_candidate=$1
  for _serverops_encoded_root in $_serverops_roots; do
    _serverops_root_input=$(_serverops_decode "$_serverops_encoded_root") || return 2
    _serverops_root=$(realpath -- "$_serverops_root_input" 2>/dev/null) || return 2
    if [ "$_serverops_root" = / ]; then return 0; fi
    case "$_serverops_candidate" in
      "$_serverops_root"|"$_serverops_root"/*) return 0 ;;
    esac
  done
  return 1
}}
_serverops_is_root() {{
  _serverops_candidate=$1
  for _serverops_encoded_root in $_serverops_roots; do
    _serverops_root_input=$(_serverops_decode "$_serverops_encoded_root") || continue
    _serverops_root=$(realpath -- "$_serverops_root_input" 2>/dev/null) || continue
    [ "$_serverops_candidate" = "$_serverops_root" ] && return 0
  done
  return 1
}}
_serverops_valid_name() {{
  [ -n "$1" ] && [ "$1" != . ] && [ "$1" != .. ] && [ "${{1#-}}" = "$1" ]
}}
_serverops_owned_tree() {{
  _serverops_foreign=$(find "$1" ! -user "$(id -u)" -print -quit 2>/dev/null) || return 1
  [ -z "$_serverops_foreign" ]
}}
"""
        return FileWireCommand(token, prologue + body + "\n)\n")
