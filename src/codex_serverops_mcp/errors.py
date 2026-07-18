from __future__ import annotations


class ServerOpsError(RuntimeError):
    """Base class for controlled, user-actionable ServerOps failures."""

    code = "serverops_error"


class ConfigurationError(ServerOpsError):
    code = "configuration_invalid"


class ConfigVersionError(ConfigurationError):
    code = "configuration_version_unsupported"


class ConfigConflictError(ConfigurationError):
    code = "configuration_conflict"


class ConfigLockTimeout(ConfigurationError):
    code = "configuration_lock_timeout"
