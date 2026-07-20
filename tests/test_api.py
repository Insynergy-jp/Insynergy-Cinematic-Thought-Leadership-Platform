from pathlib import Path
import tempfile
import unittest

from insynergy_cinematic.api import serve
from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.orchestrator import BuildOrchestrator


class APISecurityTests(unittest.TestCase):
    def test_non_loopback_binding_requires_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(Path(temporary), environ={})
            with self.assertRaises(ValidationError):
                serve(orchestrator, "0.0.0.0", 0)

    def test_token_is_resolved_but_not_recorded_in_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(
                Path(temporary), environ={"INSYNERGY_API_TOKEN": "highly-secret-token"}
            )
            self.assertEqual(orchestrator.config.api_token, "highly-secret-token")
            self.assertNotIn("highly-secret-token", str(orchestrator._config_snapshot()))


if __name__ == "__main__":
    unittest.main()
