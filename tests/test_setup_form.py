from __future__ import annotations

import unittest
from unittest.mock import patch

from codex_serverops_mcp.config import ConnectionType
from codex_serverops_mcp.setup import form_state as state_module
from codex_serverops_mcp.setup.draft import CredentialMode
from codex_serverops_mcp.setup.form_state import (
    CONNECTION_LABELS,
    CREDENTIAL_LABELS,
    ProfileFormState,
)


class FakeVariable:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self) -> object:
        return self.value

    def set(self, value: object) -> None:
        self.value = value


class SetupFormTests(unittest.TestCase):
    def _state(self) -> ProfileFormState:
        def variable(_master: object, *, value: object) -> FakeVariable:
            return FakeVariable(value)

        with (
            patch.object(state_module.tk, "StringVar", side_effect=variable),
            patch.object(state_module.tk, "BooleanVar", side_effect=variable),
        ):
            return ProfileFormState(
                object(),  # type: ignore[arg-type]
                profile_name="hetzner-test",
                profile=None,
                suggested_host="192.0.2.1",
                suggested_user="deploy",
            )

    def test_new_direct_profile_uses_helpful_connection_defaults(self) -> None:
        state = self._state()

        self.assertEqual(state.port.get(), "22")
        self.assertEqual(state.target.get(), "192.0.2.1")
        self.assertEqual(state.display_name.get(), "192.0.2.1")
        self.assertEqual(state.user.get(), "deploy")

    def test_alias_hides_direct_auth_choices_by_normalizing_to_openssh(self) -> None:
        state = self._state()
        state.install_public_key.set(True)
        state.connection_type.set(CONNECTION_LABELS[ConnectionType.SSH_CONFIG.value])

        state.normalize_connection()

        self.assertEqual(
            state.credential_mode.get(),
            CREDENTIAL_LABELS[CredentialMode.OPENSSH.value],
        )
        self.assertFalse(state.install_public_key.get())

    def test_auth_step_rejects_mismatched_new_key_passphrases(self) -> None:
        state = self._state()
        state.credential_mode.set(CREDENTIAL_LABELS[CredentialMode.NEW_KEY.value])
        state.key_passphrase.set("first")
        state.key_passphrase_repeat.set("second")

        with self.assertRaisesRegex(ValueError, "stimmen nicht überein"):
            state.validate_authentication()


if __name__ == "__main__":
    unittest.main()
