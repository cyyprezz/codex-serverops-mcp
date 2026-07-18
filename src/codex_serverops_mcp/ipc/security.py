from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

if os.name != "nt":  # pragma: no cover - product IPC is Windows-only
    raise ImportError("Windows named-pipe security is available only on Windows")

import ntsecuritycon
import pywintypes
import win32api
import win32con
import win32security

from .constants import PIPE_PREFIX
from .errors import PipeSecurityError

PIPE_ROLE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


@dataclass(frozen=True, slots=True)
class PipeSecurityReport:
    owner_sid: str
    allowed_sids: tuple[str, ...]
    denied_sids: tuple[str, ...]

    @property
    def current_user_only(self) -> bool:
        current = current_user_sid_string()
        return self.owner_sid == current and set(self.allowed_sids) == {current}


def current_user_sid() -> pywintypes.SIDType:
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid, _attributes = win32security.GetTokenInformation(token, win32security.TokenUser)
        return sid
    finally:
        token.Close()


def current_user_sid_string() -> str:
    return win32security.ConvertSidToStringSid(current_user_sid())


def pipe_name_for_current_user(role: str) -> str:
    if not PIPE_ROLE.fullmatch(role):
        raise ValueError("pipe role has an invalid format")
    digest = hashlib.sha256(current_user_sid_string().encode("ascii")).hexdigest()[:20]
    return rf"\\.\pipe\{PIPE_PREFIX}-{role}-{digest}"


def current_user_security_attributes() -> pywintypes.SECURITY_ATTRIBUTES:
    descriptor = _current_user_descriptor(inherit=False)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    return attributes


def _current_user_descriptor(*, inherit: bool) -> pywintypes.SECURITY_DESCRIPTORType:
    sid = current_user_sid()
    dacl = win32security.ACL()
    ace_flags = 0
    if inherit:
        ace_flags = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE
    dacl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        ace_flags,
        ntsecuritycon.GENERIC_ALL,
        sid,
    )
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(sid, False)
    descriptor.SetSecurityDescriptorGroup(sid, False)
    descriptor.SetSecurityDescriptorDacl(True, dacl, False)
    return descriptor


def secure_path_for_current_user(path: str, *, directory: bool = False) -> None:
    descriptor = _current_user_descriptor(inherit=directory)
    owner = descriptor.GetSecurityDescriptorOwner()
    dacl = descriptor.GetSecurityDescriptorDacl()
    existing = win32security.GetNamedSecurityInfo(
        path,
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION,
    )
    existing_owner = existing.GetSecurityDescriptorOwner()
    security_information = (
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION
    )
    owner_to_set = None
    if existing_owner is None or (
        win32security.ConvertSidToStringSid(existing_owner)
        != win32security.ConvertSidToStringSid(owner)
    ):
        security_information |= win32security.OWNER_SECURITY_INFORMATION
        owner_to_set = owner
    win32security.SetNamedSecurityInfo(
        path,
        win32security.SE_FILE_OBJECT,
        security_information,
        owner_to_set,
        None,
        dacl,
        None,
    )


def inspect_path_security(path: str) -> PipeSecurityReport:
    descriptor = win32security.GetNamedSecurityInfo(
        path,
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
    )
    return _security_report(descriptor)


def inspect_pipe_security(handle: object) -> PipeSecurityReport:
    descriptor = win32security.GetSecurityInfo(
        handle,
        win32security.SE_KERNEL_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
    )
    return _security_report(descriptor)


def _security_report(descriptor: object) -> PipeSecurityReport:
    owner = descriptor.GetSecurityDescriptorOwner()  # type: ignore[attr-defined]
    dacl = descriptor.GetSecurityDescriptorDacl()  # type: ignore[attr-defined]
    if owner is None or dacl is None:
        raise PipeSecurityError("named pipe has no explicit owner or DACL")
    allowed: list[str] = []
    denied: list[str] = []
    for index in range(dacl.GetAceCount()):
        ace = dacl.GetAce(index)
        ace_type = ace[0][0]
        sid_string = win32security.ConvertSidToStringSid(ace[2])
        if ace_type == win32security.ACCESS_ALLOWED_ACE_TYPE:
            allowed.append(sid_string)
        elif ace_type == win32security.ACCESS_DENIED_ACE_TYPE:
            denied.append(sid_string)
    return PipeSecurityReport(
        owner_sid=win32security.ConvertSidToStringSid(owner),
        allowed_sids=tuple(allowed),
        denied_sids=tuple(denied),
    )


def require_current_user_only(handle: object) -> PipeSecurityReport:
    report = inspect_pipe_security(handle)
    if not report.current_user_only:
        raise PipeSecurityError(
            "named pipe DACL must grant access only to the current Windows user SID"
        )
    return report
