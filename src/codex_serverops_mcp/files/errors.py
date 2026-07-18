from __future__ import annotations

from codex_serverops_mcp.errors import ServerOpsError


class RemoteFileError(ServerOpsError):
    code = "remote_file_error"

    def __init__(self, remote_code: str, message: str) -> None:
        super().__init__(message)
        self.code = remote_code


class FileConflictError(RemoteFileError):
    def __init__(
        self,
        message: str = "the remote file changed before it could be replaced",
    ) -> None:
        super().__init__("file_conflict", message)
