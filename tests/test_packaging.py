"""Packaging/path-isolation checks for the vendored engine migration."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "harness2-cli"


class TestVendoredPackaging(unittest.TestCase):
    def test_vendored_engine_metadata_and_license_present(self) -> None:
        self.assertTrue((VENDOR / "LICENSE").is_file())
        pyproject = (VENDOR / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('name = "harness2-cli"', pyproject)
        self.assertIn('requires-python = ">=3.12,<3.14"', pyproject)
        self.assertTrue((VENDOR / "harness2" / "core" / "schedule.py").is_file())

    def test_lock_records_vendored_pin(self) -> None:
        lock = json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["cli"]["commit"],
                         "0c811344a4edfe34960b2fc8f286369d7e81fb27")
        self.assertEqual(lock["cli"]["vendored_path"], "vendor/harness2-cli")
        self.assertEqual(lock["cli"]["patches"], [])

    def test_uv_project_declares_local_source_dependency(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"harness2-cli==0.1.0"', pyproject)
        self.assertIn('harness2-cli = { path = "vendor/harness2-cli", editable = true }',
                      pyproject)
        uv_lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
        self.assertIn('name = "harness2-cli"', uv_lock)
        self.assertIn('source = { editable = "vendor/harness2-cli" }', uv_lock)

    def test_project_metadata_declares_dependency(self) -> None:
        import importlib.metadata

        requires = importlib.metadata.requires("h2portable") or []
        self.assertTrue(any(r.startswith("harness2-cli") for r in requires), requires)
        self.assertEqual(importlib.metadata.version("harness2-cli"), "0.1.0")

    def test_imports_resolve_to_vendored_or_installed_engine(self) -> None:
        import harness2
        import h2portable

        engine_file = str(Path(harness2.__file__).resolve())
        self.assertNotIn("upstream/cli", engine_file)
        self.assertNotIn("upstream/official", engine_file)
        self.assertTrue(
            "vendor/harness2-cli" in engine_file or "site-packages" in engine_file,
            engine_file)
        self.assertNotIn("upstream", str(Path(h2portable.__file__).resolve()))
        injected = [entry for entry in sys.path if "upstream/cli" in entry
                    or "upstream/official" in entry]
        self.assertEqual(injected, [])

    def test_dockerfile_has_no_path_injection_or_external_copy(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("PYTHONPATH", dockerfile)
        self.assertNotIn("upstream-cli/harness2", dockerfile)
        self.assertIn("/opt/wheels", dockerfile)

    def test_no_external_checkout_required_by_fixture(self) -> None:
        fixture = (ROOT / "fixtures" / "custom_workflow.py").read_text(encoding="utf-8")
        self.assertNotIn("--upstream-cli", fixture)
        self.assertNotIn("H2_UPSTREAM_CLI", fixture)
        self.assertNotIn("sys.path.insert", fixture)


if __name__ == "__main__":
    unittest.main()
