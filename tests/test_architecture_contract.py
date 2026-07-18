from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "codex_serverops_mcp"
MAX_PRODUCT_FILE_LINES = 450


def _product_python_files() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if "spike" not in path.relative_to(PACKAGE_ROOT).parts
    )


def _absolute_imports(path: Path) -> list[tuple[str, int]]:
    imports: list[tuple[str, int]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.module or "", node.lineno))
    return imports


class ArchitectureContractTests(unittest.TestCase):
    def test_product_modules_stay_below_the_file_size_boundary(self) -> None:
        oversized = {
            str(path.relative_to(REPOSITORY_ROOT)): len(
                path.read_text(encoding="utf-8").splitlines()
            )
            for path in _product_python_files()
            if len(path.read_text(encoding="utf-8").splitlines())
            > MAX_PRODUCT_FILE_LINES
        }
        self.assertEqual(oversized, {})

    def test_product_modules_never_import_spike_code(self) -> None:
        violations: list[str] = []
        for path in _product_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [node.module or ""]
                else:
                    continue
                if any(
                    name == "codex_serverops_mcp.spike"
                    or name.startswith("codex_serverops_mcp.spike.")
                    for name in imported
                ):
                    violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}")
        self.assertEqual(violations, [])

    def test_workers_never_import_broker_implementation(self) -> None:
        violations: list[str] = []
        for path in sorted((PACKAGE_ROOT / "worker").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [node.module or ""]
                else:
                    continue
                if any(
                    name == "codex_serverops_mcp.broker"
                    or name.startswith("codex_serverops_mcp.broker.")
                    for name in imported
                ):
                    violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}")
        self.assertEqual(violations, [])

    def test_auth_and_broker_keep_the_direct_secret_boundary(self) -> None:
        violations: list[str] = []
        boundaries = {
            "auth": ("codex_serverops_mcp.broker", "codex_serverops_mcp.worker"),
            "broker": ("codex_serverops_mcp.auth",),
        }
        for package, forbidden_prefixes in boundaries.items():
            for path in sorted((PACKAGE_ROOT / package).rglob("*.py")):
                for imported, line in _absolute_imports(path):
                    if any(
                        imported == prefix or imported.startswith(f"{prefix}.")
                        for prefix in forbidden_prefixes
                    ):
                        violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{line}")
        self.assertEqual(violations, [])

    def test_product_uses_composition_instead_of_mixins(self) -> None:
        violations: list[str] = []
        for path in _product_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name.endswith("Mixin"):
                    violations.append(
                        f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}:{node.name}"
                    )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
