from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CheckLevel(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class CheckResult:
    code: str
    level: CheckLevel
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "level": self.level.value, "message": self.message}


@dataclass(frozen=True, slots=True)
class CheckReport:
    checks: tuple[CheckResult, ...]

    @property
    def status(self) -> str:
        if any(check.level is CheckLevel.FAIL for check in self.checks):
            return "failed"
        if any(check.level is CheckLevel.WARNING for check in self.checks):
            return "ready_with_warnings"
        return "ready"

    @property
    def succeeded(self) -> bool:
        return self.status != "failed"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
        }


def passed(code: str, message: str) -> CheckResult:
    return CheckResult(code, CheckLevel.PASS, message)


def warning(code: str, message: str) -> CheckResult:
    return CheckResult(code, CheckLevel.WARNING, message)


def failed(code: str, message: str) -> CheckResult:
    return CheckResult(code, CheckLevel.FAIL, message)
