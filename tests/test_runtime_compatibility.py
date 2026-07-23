from __future__ import annotations

import subprocess
from pathlib import Path
import tempfile
import unittest

from insynergy_cinematic.errors import ValidationError
from tools.verify_runtime_compatibility import verify_runtime_compatibility


class RuntimeCompatibilityTests(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def _repository(self, root: Path) -> tuple[str, str]:
        self._git(root, "init")
        self._git(root, "config", "user.name", "Runtime Test")
        self._git(root, "config", "user.email", "runtime@example.invalid")
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / "src" / "insynergy_cinematic" / "providers").mkdir(parents=True)
        execute = root / ".github" / "workflows" / "execute.yml"
        prompt = root / "src" / "insynergy_cinematic" / "prompt.py"
        provider = root / "src" / "insynergy_cinematic" / "providers" / "runway.py"
        rendering = root / "src" / "insynergy_cinematic" / "rendering.py"
        execute.write_text("runtime: approved\n", encoding="utf-8")
        prompt.write_text("contract = 'storyboard-only'\n", encoding="utf-8")
        provider.write_text("duration = 'approved'\n", encoding="utf-8")
        rendering.write_text("provider = 'runway'\n", encoding="utf-8")
        self._git(root, "add", ".github", "src")
        self._git(root, "commit", "-m", "approved planning source")
        planning_sha = self._git(root, "rev-parse", "HEAD")
        execute.write_text("runtime: compatible-recovery\n", encoding="utf-8")
        prompt.write_text(
            "contract = 'storyboard-only-bounded'\n", encoding="utf-8"
        )
        provider.write_text("duration = 'integer-and-trimmed'\n", encoding="utf-8")
        rendering.write_text("provider = 'runway-bounded'\n", encoding="utf-8")
        self._git(root, "add", ".github", "src")
        self._git(root, "commit", "-m", "bounded runtime")
        execution_sha = self._git(root, "rev-parse", "HEAD")
        return planning_sha, execution_sha

    def test_allows_descendant_runtime_only_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            planning_sha, execution_sha = self._repository(root)
            result = verify_runtime_compatibility(
                root=root,
                planning_source_sha=planning_sha,
                execution_source_sha=execution_sha,
            )
            self.assertTrue(result["passed"])
            self.assertEqual(
                {change["path"] for change in result["changes"]},
                {
                    ".github/workflows/execute.yml",
                    "src/insynergy_cinematic/prompt.py",
                    "src/insynergy_cinematic/providers/runway.py",
                    "src/insynergy_cinematic/rendering.py",
                },
            )
            self.assertTrue(result["diff_hash"].startswith("sha256:"))

    def test_rejects_payload_change_or_reverse_ancestry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            planning_sha, runtime_sha = self._repository(root)
            (root / "creative").mkdir()
            (root / "creative" / "brief.md").write_text(
                "changed approved payload\n", encoding="utf-8"
            )
            self._git(root, "add", "creative/brief.md")
            self._git(root, "commit", "-m", "unexpected payload change")
            payload_sha = self._git(root, "rev-parse", "HEAD")
            with self.assertRaises(ValidationError):
                verify_runtime_compatibility(
                    root=root,
                    planning_source_sha=planning_sha,
                    execution_source_sha=payload_sha,
                )
            with self.assertRaises(ValidationError):
                verify_runtime_compatibility(
                    root=root,
                    planning_source_sha=runtime_sha,
                    execution_source_sha=planning_sha,
                )

    def test_rejects_deletion_even_for_allowlisted_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            planning_sha, _ = self._repository(root)
            (root / "src" / "insynergy_cinematic" / "prompt.py").unlink()
            self._git(root, "add", "src/insynergy_cinematic/prompt.py")
            self._git(root, "commit", "-m", "delete runtime")
            deletion_sha = self._git(root, "rev-parse", "HEAD")
            with self.assertRaises(ValidationError):
                verify_runtime_compatibility(
                    root=root,
                    planning_source_sha=planning_sha,
                    execution_source_sha=deletion_sha,
                )


if __name__ == "__main__":
    unittest.main()
