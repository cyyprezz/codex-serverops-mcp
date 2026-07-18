from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .shell_protocol import FileShellProtocol
from .wire import FileWireCommand, encode_argument


@dataclass(frozen=True, slots=True)
class FileShellBuilder:
    allowed_roots: tuple[str, ...]

    def list_directory(self, path: str, limit: int) -> FileWireCommand:
        body = self._existing(path) + f"""
[ -d "$_serverops_resolved" ] || _serverops_error not_a_directory 'Remote path is not a directory.'
_serverops_success
_serverops_row path "$_serverops_resolved"
_serverops_count=0
_serverops_truncated=false
while IFS= read -r -d '' _serverops_child; do
  if [ "$_serverops_count" -ge {limit} ]; then
    _serverops_truncated=true
    break
  fi
  _serverops_name=${{_serverops_child##*/}}
  if [ -L "$_serverops_child" ]; then _serverops_type=symlink
  elif [ -d "$_serverops_child" ]; then _serverops_type=directory
  elif [ -f "$_serverops_child" ]; then _serverops_type=file
  else _serverops_type=other
  fi
  _serverops_size=$(stat -c %s -- "$_serverops_child" 2>/dev/null) || _serverops_size=0
  _serverops_mtime=$(stat -c %Y -- "$_serverops_child" 2>/dev/null) || _serverops_mtime=0
  _serverops_mode=$(stat -c %a -- "$_serverops_child" 2>/dev/null) || _serverops_mode=''
  _serverops_row entry "$_serverops_name" "$_serverops_type" \
    "$_serverops_size" "$_serverops_mtime" "$_serverops_mode"
  _serverops_count=$((_serverops_count + 1))
done < <(find "$_serverops_resolved" -mindepth 1 -maxdepth 1 -print0 2>/dev/null | LC_ALL=C sort -z)
_serverops_row truncated "$_serverops_truncated"
_serverops_finish
"""
        return self._wrap(body)

    def stat(self, path: str) -> FileWireCommand:
        body = self._existing(path) + """
if [ -L "$_serverops_path" ]; then _serverops_type=symlink
elif [ -d "$_serverops_resolved" ]; then _serverops_type=directory
elif [ -f "$_serverops_resolved" ]; then _serverops_type=file
else _serverops_type=other
fi
_serverops_size=$(stat -c %s -- "$_serverops_resolved" 2>/dev/null) || \
  _serverops_error stat_failed 'Remote metadata could not be read.'
_serverops_mtime=$(stat -c %Y -- "$_serverops_resolved" 2>/dev/null) || \
  _serverops_error stat_failed 'Remote metadata could not be read.'
_serverops_mode=$(stat -c %a -- "$_serverops_resolved" 2>/dev/null) || \
  _serverops_error stat_failed 'Remote metadata could not be read.'
_serverops_success
_serverops_row path "$_serverops_resolved"
_serverops_row type "$_serverops_type"
_serverops_row size "$_serverops_size"
_serverops_row modified_epoch "$_serverops_mtime"
_serverops_row mode "$_serverops_mode"
_serverops_finish
"""
        return self._wrap(body)

    def hash(self, path: str) -> FileWireCommand:
        body = self._existing(path) + """
[ -f "$_serverops_resolved" ] || _serverops_error not_a_file 'Remote path is not a regular file.'
_serverops_sha=$(sha256sum -- "$_serverops_resolved" 2>/dev/null | awk '{print $1}') || \
  _serverops_error hash_failed 'Remote file hash could not be calculated.'
_serverops_success
_serverops_row path "$_serverops_resolved"
_serverops_row sha256 "$_serverops_sha"
_serverops_finish
"""
        return self._wrap(body)

    def read_text(
        self,
        path: str,
        byte_limit: int,
        start_line: int | None,
        end_line: int | None,
    ) -> FileWireCommand:
        body = self._existing(path) + """
[ -f "$_serverops_resolved" ] || _serverops_error not_a_file 'Remote path is not a regular file.'
_serverops_sha=$(sha256sum -- "$_serverops_resolved" 2>/dev/null | awk '{print $1}') || \
  _serverops_error hash_failed 'Remote file hash could not be calculated.'
"""
        if start_line is None:
            body += """
_serverops_selected_size=$(wc -c < "$_serverops_resolved") || \
  _serverops_error read_failed 'Remote file size could not be read.'
_serverops_success
_serverops_row path "$_serverops_resolved"
_serverops_row sha256 "$_serverops_sha"
_serverops_row selected_bytes "$_serverops_selected_size"
if [ "$_serverops_selected_size" -gt BYTE_LIMIT ]; then _serverops_row truncated true
else _serverops_row truncated false
fi
head -c BYTE_LIMIT -- "$_serverops_resolved" | _serverops_blob content
_serverops_finish
""".replace("BYTE_LIMIT", str(byte_limit))
        else:
            assert end_line is not None
            sed_range = f"{start_line},{end_line}p"
            body += f"""
_serverops_selected_size=$(sed -n '{sed_range}' -- "$_serverops_resolved" | wc -c) || \
  _serverops_error read_failed 'Remote line range could not be read.'
_serverops_success
_serverops_row path "$_serverops_resolved"
_serverops_row sha256 "$_serverops_sha"
_serverops_row selected_bytes "$_serverops_selected_size"
if [ "$_serverops_selected_size" -gt {byte_limit} ]; then _serverops_row truncated true
else _serverops_row truncated false
fi
sed -n '{sed_range}' -- "$_serverops_resolved" | head -c {byte_limit} | _serverops_blob content
_serverops_finish
"""
        return self._wrap(body)

    def search_text(self, path: str, query: str, limit: int) -> FileWireCommand:
        encoded_query = encode_argument(query)
        body = self._existing(path) + f"""
_serverops_query=$(_serverops_decode '{encoded_query}') || \
  _serverops_error invalid_query 'Search text could not be decoded.'
_serverops_success
_serverops_row path "$_serverops_resolved"
_serverops_count=0
_serverops_truncated=false
while IFS= read -r -d '' _serverops_match_file; do
  _serverops_match_resolved=$(realpath -- "$_serverops_match_file" 2>/dev/null) || continue
  _serverops_allowed "$_serverops_match_resolved" || continue
  if od -An -v -tx1 "$_serverops_match_resolved" 2>/dev/null | \
      grep -Eq '(^|[[:space:]])00([[:space:]]|$)'; then
    continue
  fi
  while IFS= read -r _serverops_match; do
    if [ "$_serverops_count" -ge {limit} ]; then
      _serverops_truncated=true
      break 2
    fi
    _serverops_line=${{_serverops_match%%:*}}
    _serverops_text=${{_serverops_match#*:}}
    _serverops_row match "$_serverops_match_resolved" "$_serverops_line" "$_serverops_text"
    _serverops_count=$((_serverops_count + 1))
  done < <(LC_ALL=C grep -n -F -- "$_serverops_query" "$_serverops_match_resolved" 2>/dev/null)
done < <(find "$_serverops_resolved" -type f -print0 2>/dev/null)
_serverops_row truncated "$_serverops_truncated"
_serverops_finish
"""
        return self._wrap(body)

    def write_text(
        self,
        path: str,
        content: bytes,
        expected_sha256: str | None,
    ) -> FileWireCommand:
        encoded_path = encode_argument(path)
        encoded_content = encode_argument(content.decode("utf-8"))
        content_arguments = " \\\n".join(
            f"  '{encoded_content[index : index + 512]}'"
            for index in range(0, len(encoded_content), 512)
        )
        content_hash = hashlib.sha256(content).hexdigest()
        expected = "" if expected_sha256 is None else expected_sha256
        body = f"""
_serverops_path=$(_serverops_decode '{encoded_path}') || \
  _serverops_error invalid_path 'Remote path could not be decoded.'
_serverops_expected='{expected}'
_serverops_existing=false
if [ -e "$_serverops_path" ] || [ -L "$_serverops_path" ]; then
  _serverops_existing=true
  _serverops_target=$(realpath -- "$_serverops_path" 2>/dev/null) || \
    _serverops_error path_not_found 'Remote path could not be resolved.'
  _serverops_allowed "$_serverops_target"
  _serverops_allowed_status=$?
  [ "$_serverops_allowed_status" -eq 0 ] || \
    _serverops_error path_outside_roots 'Remote path is outside allowed roots.'
  [ -f "$_serverops_target" ] || _serverops_error not_a_file 'Remote path is not a regular file.'
  [ -w "$_serverops_target" ] || _serverops_error permission_denied 'Remote file is not writable.'
  _serverops_parent=$(dirname -- "$_serverops_target")
  _serverops_before=$(sha256sum -- "$_serverops_target" | awk '{{print $1}}') || \
    _serverops_error hash_failed 'Remote file hash could not be calculated.'
  [ -z "$_serverops_expected" ] || [ "$_serverops_before" = "$_serverops_expected" ] || \
    _serverops_error file_conflict 'Remote file does not match expected_sha256.'
  _serverops_owner=$(stat -c %u -- "$_serverops_target") || \
    _serverops_error stat_failed 'Remote ownership could not be read.'
  _serverops_mode=$(stat -c %a -- "$_serverops_target") || \
    _serverops_error stat_failed 'Remote mode could not be read.'
  _serverops_group=$(stat -c %g -- "$_serverops_target") || \
    _serverops_error stat_failed 'Remote group could not be read.'
  [ "$_serverops_owner" = "$(id -u)" ] || \
    _serverops_error ownership_unsupported 'Structured writes require a file owned by the SSH user.'
else
  [ -z "$_serverops_expected" ] || \
    _serverops_error file_conflict 'Expected file does not exist.'
  _serverops_parent_input=$(dirname -- "$_serverops_path")
  _serverops_name=$(basename -- "$_serverops_path")
  _serverops_valid_name "$_serverops_name" || \
    _serverops_error invalid_path 'New file name is invalid.'
  _serverops_parent=$(realpath -- "$_serverops_parent_input" 2>/dev/null) || \
    _serverops_error parent_not_found 'Remote parent directory could not be resolved.'
  _serverops_allowed "$_serverops_parent" || \
    _serverops_error path_outside_roots 'Remote parent is outside allowed roots.'
  _serverops_target="$_serverops_parent/$_serverops_name"
fi
[ -w "$_serverops_parent" ] || \
  _serverops_error permission_denied 'Remote parent directory is not writable.'
_serverops_temp=$(mktemp -- "$_serverops_parent/.serverops.XXXXXX") || \
  _serverops_error temporary_file_failed 'Remote temporary file could not be created.'
trap 'rm -f -- "$_serverops_temp"' EXIT
printf '%s' \\
{content_arguments} | base64 -d > "$_serverops_temp" || \
  _serverops_error transfer_failed 'Remote text transfer failed.'
_serverops_temp_hash=$(sha256sum -- "$_serverops_temp" | awk '{{print $1}}') || \
  _serverops_error hash_failed 'Temporary file hash could not be calculated.'
[ "$_serverops_temp_hash" = '{content_hash}' ] || \
  _serverops_error transfer_failed 'Transferred text hash does not match.'
if [ "$_serverops_existing" = true ]; then
  chmod "$_serverops_mode" -- "$_serverops_temp" || \
    _serverops_error metadata_failed 'Existing file mode could not be preserved.'
  chgrp "$_serverops_group" -- "$_serverops_temp" || \
    _serverops_error metadata_failed 'Existing file group could not be preserved.'
  _serverops_now=$(realpath -- "$_serverops_path" 2>/dev/null) || \
    _serverops_error file_conflict 'Remote file changed before replacement.'
  [ "$_serverops_now" = "$_serverops_target" ] || \
    _serverops_error file_conflict 'Remote path target changed before replacement.'
  _serverops_now_hash=$(sha256sum -- "$_serverops_target" | awk '{{print $1}}') || \
    _serverops_error file_conflict 'Remote file changed before replacement.'
  [ "$_serverops_now_hash" = "$_serverops_before" ] || \
    _serverops_error file_conflict 'Remote file changed before replacement.'
else
  if [ -e "$_serverops_target" ] || [ -L "$_serverops_target" ]; then
    _serverops_error file_conflict 'Remote destination appeared before replacement.'
  fi
fi
sync "$_serverops_temp" 2>/dev/null || true
mv -f -- "$_serverops_temp" "$_serverops_target" || \
  _serverops_error replace_failed 'Remote atomic replacement failed.'
trap - EXIT
_serverops_after=$(sha256sum -- "$_serverops_target" | awk '{{print $1}}') || \
  _serverops_error hash_failed 'Replaced file hash could not be calculated.'
[ "$_serverops_after" = '{content_hash}' ] || \
  _serverops_error replace_failed 'Replaced file hash does not match.'
_serverops_success
_serverops_row path "$_serverops_target"
_serverops_row sha256 "$_serverops_after"
_serverops_row created "$([ "$_serverops_existing" = false ] && printf true || printf false)"
_serverops_finish
"""
        return self._wrap(body)

    def mkdir(self, path: str) -> FileWireCommand:
        prefix = self._new_entry(path)
        body = prefix + """
mkdir -m 700 -- "$_serverops_target" || \
  _serverops_error mkdir_failed 'Remote directory could not be created.'
_serverops_resolved=$(realpath -- "$_serverops_target" 2>/dev/null) || \
  _serverops_error mkdir_failed 'Created directory could not be resolved.'
_serverops_allowed "$_serverops_resolved" || \
  _serverops_error path_outside_roots 'Created directory is outside allowed roots.'
_serverops_success
_serverops_row path "$_serverops_resolved"
_serverops_finish
"""
        return self._wrap(body)

    def rename(self, source: str, destination: str) -> FileWireCommand:
        source_setup = self._entry_reference(source, "source")
        destination_setup = self._new_entry(destination, prefix="destination")
        body = source_setup + """
_serverops_is_root "$_serverops_source_resolved" && \
  _serverops_error protected_root 'An allowed root cannot be renamed.'
_serverops_owned_tree "$_serverops_source_entry" || \
  _serverops_error ownership_unsupported 'Structured edits require paths owned by the SSH user.'
""" + destination_setup + """
_serverops_source_now=$(realpath -- "$_serverops_source_entry" 2>/dev/null) || \
  _serverops_error file_conflict 'Remote source changed before rename.'
[ "$_serverops_source_now" = "$_serverops_source_resolved" ] || \
  _serverops_error file_conflict 'Remote source target changed before rename.'
mv -- "$_serverops_source_entry" "$_serverops_destination_target" || \
  _serverops_error rename_failed 'Remote path could not be renamed.'
_serverops_result=$(realpath -- "$_serverops_destination_target" 2>/dev/null) || \
  _serverops_error rename_failed 'Renamed path could not be resolved.'
_serverops_success
_serverops_row source "$_serverops_source_resolved"
_serverops_row destination "$_serverops_result"
_serverops_finish
"""
        return self._wrap(body)

    def remove(
        self,
        path: str,
        *,
        recursive: bool,
        expected_sha256: str | None,
    ) -> FileWireCommand:
        body = self._entry_reference(path, "target") + """
_serverops_is_root "$_serverops_target_resolved" && \
  _serverops_error protected_root 'An allowed root cannot be removed.'
"""
        if expected_sha256 is not None:
            body += f"""
[ -f "$_serverops_target_resolved" ] || \
  _serverops_error file_conflict 'expected_sha256 requires a regular file.'
_serverops_remove_hash=$(sha256sum -- "$_serverops_target_resolved" | awk '{{print $1}}') || \
  _serverops_error hash_failed 'Remote file hash could not be calculated.'
[ "$_serverops_remove_hash" = '{expected_sha256}' ] || \
  _serverops_error file_conflict 'Remote file does not match expected_sha256.'
"""
        body += """
_serverops_target_now=$(realpath -- "$_serverops_target_entry" 2>/dev/null) || \
  _serverops_error file_conflict 'Remote target changed before removal.'
[ "$_serverops_target_now" = "$_serverops_target_resolved" ] || \
  _serverops_error file_conflict 'Remote target changed before removal.'
"""
        if recursive:
            body += """
_serverops_owned_tree "$_serverops_target_entry" || \
  _serverops_error ownership_unsupported 'Recursive removal contains a foreign-owned path.'
rm -rf -- "$_serverops_target_entry" || \
  _serverops_error remove_failed 'Remote path could not be removed.'
"""
        else:
            body += """
if [ -d "$_serverops_target_entry" ] && [ ! -L "$_serverops_target_entry" ]; then
  rmdir -- "$_serverops_target_entry" || \
    _serverops_error directory_not_empty 'Remote directory is not empty; recursive is required.'
else
  rm -- "$_serverops_target_entry" || \
    _serverops_error remove_failed 'Remote path could not be removed.'
fi
"""
        body += """
_serverops_success
_serverops_row path "$_serverops_target_resolved"
_serverops_finish
"""
        return self._wrap(body)

    def _existing(self, path: str) -> str:
        encoded = encode_argument(path)
        return f"""
_serverops_path=$(_serverops_decode '{encoded}') || \
  _serverops_error invalid_path 'Remote path could not be decoded.'
_serverops_resolved=$(realpath -- "$_serverops_path" 2>/dev/null) || \
  _serverops_error path_not_found 'Remote path could not be resolved.'
_serverops_allowed "$_serverops_resolved"
_serverops_allowed_status=$?
[ "$_serverops_allowed_status" -eq 0 ] || \
  _serverops_error path_outside_roots 'Remote path is outside allowed roots.'
"""

    def _new_entry(self, path: str, *, prefix: str = "") -> str:
        encoded = encode_argument(path)
        variable = f"_serverops_{prefix}_" if prefix else "_serverops_"
        return f"""
{variable}path=$(_serverops_decode '{encoded}') || \
  _serverops_error invalid_path 'Remote path could not be decoded.'
{variable}parent_input=$(dirname -- "${{{variable}path}}")
{variable}name=$(basename -- "${{{variable}path}}")
_serverops_valid_name "${{{variable}name}}" || \
  _serverops_error invalid_path 'New path name is invalid.'
{variable}parent=$(realpath -- "${{{variable}parent_input}}" 2>/dev/null) || \
  _serverops_error parent_not_found 'Remote parent directory could not be resolved.'
_serverops_allowed "${{{variable}parent}}" || \
  _serverops_error path_outside_roots 'Remote parent is outside allowed roots.'
[ -w "${{{variable}parent}}" ] || \
  _serverops_error permission_denied 'Remote parent directory is not writable.'
{variable}target="${{{variable}parent}}/${{{variable}name}}"
if [ -e "${{{variable}target}}" ] || [ -L "${{{variable}target}}" ]; then
  _serverops_error destination_exists 'Remote destination already exists.'
fi
"""

    def _entry_reference(self, path: str, prefix: str) -> str:
        encoded = encode_argument(path)
        variable = f"_serverops_{prefix}_"
        return f"""
{variable}path=$(_serverops_decode '{encoded}') || \
  _serverops_error invalid_path 'Remote path could not be decoded.'
{variable}parent_input=$(dirname -- "${{{variable}path}}")
{variable}name=$(basename -- "${{{variable}path}}")
_serverops_valid_name "${{{variable}name}}" || \
  _serverops_error invalid_path 'Remote path name is invalid.'
{variable}parent=$(realpath -- "${{{variable}parent_input}}" 2>/dev/null) || \
  _serverops_error parent_not_found 'Remote parent directory could not be resolved.'
{variable}entry="${{{variable}parent}}/${{{variable}name}}"
{variable}resolved=$(realpath -- "${{{variable}entry}}" 2>/dev/null) || \
  _serverops_error path_not_found 'Remote path could not be resolved.'
_serverops_allowed "${{{variable}parent}}" || \
  _serverops_error path_outside_roots 'Remote parent is outside allowed roots.'
_serverops_allowed "${{{variable}resolved}}" || \
  _serverops_error path_outside_roots 'Remote path target is outside allowed roots.'
{variable}owner=$(stat -c %u -- "${{{variable}entry}}" 2>/dev/null) || \
  _serverops_error stat_failed 'Remote ownership could not be read.'
[ "${{{variable}owner}}" = "$(id -u)" ] || \
  _serverops_error ownership_unsupported 'Structured edits require paths owned by the SSH user.'
"""

    def _wrap(self, body: str) -> FileWireCommand:
        return FileShellProtocol(self.allowed_roots).wrap(body)
