from __future__ import annotations

import unittest

from codex_serverops_mcp.setup.form import STEP_NAMES, ProfileForm


class FakeState:
    def __init__(self) -> None:
        self.validations: list[str] = []

    def validate_connection(self) -> None:
        self.validations.append("connection")

    def validate_authentication(self) -> None:
        self.validations.append("authentication")

    def draft(self, allowed_roots: str) -> str:
        self.validations.append(f"draft:{allowed_roots}")
        return "draft"


class FakePermissionsPage:
    @staticmethod
    def allowed_roots() -> str:
        return "/opt/app"


class FakeReviewPage:
    def __init__(self) -> None:
        self.rendered: object | None = None

    def render(self, draft: object) -> None:
        self.rendered = draft


class SetupWizardTests(unittest.TestCase):
    def _form(self) -> ProfileForm:
        form = object.__new__(ProfileForm)
        form.current_step = 0
        form.pages = (object(), object(), object(), object())  # type: ignore[assignment]
        form.state = FakeState()  # type: ignore[assignment]
        form.permissions_page = FakePermissionsPage()  # type: ignore[assignment]
        form.review_page = FakeReviewPage()  # type: ignore[assignment]
        form.on_step_change = lambda: None
        form._show_current_page = lambda: None  # type: ignore[method-assign]
        return form

    def test_four_focused_steps_validate_before_advancing(self) -> None:
        form = self._form()

        form.go_next()
        form.go_next()
        form.go_next()

        self.assertEqual(STEP_NAMES, ("Verbindung", "Anmeldung", "Zugriff", "Prüfen"))
        self.assertEqual(form.current_step, 3)
        self.assertEqual(
            form.state.validations,  # type: ignore[attr-defined]
            ["connection", "authentication", "draft:/opt/app"],
        )
        self.assertEqual(form.review_page.rendered, "draft")  # type: ignore[attr-defined]

    def test_back_navigation_never_underflows(self) -> None:
        form = self._form()

        form.go_back()
        form.go_next()
        form.go_back()

        self.assertEqual(form.current_step, 0)


if __name__ == "__main__":
    unittest.main()
