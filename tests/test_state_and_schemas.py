from pathlib import Path
import json
import tempfile
import unittest
from urllib.parse import urlparse

from insynergy_cinematic.errors import StateConflictError
from insynergy_cinematic.models import BuildState
from insynergy_cinematic.schemas import SCHEMA_NAMES, export_schemas
from insynergy_cinematic.storage import BuildRepository


class StateAndSchemaTests(unittest.TestCase):
    def test_illegal_state_transition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = BuildRepository(Path(temporary))
            manifest = repository.create(
                "build-1234", {"content_hash": "sha256:x"}, "preview", {}
            )
            with self.assertRaises(StateConflictError):
                repository.transition(manifest, BuildState.EXECUTING, "bypass")

    def test_all_part_9_schemas_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            count = export_schemas(Path(temporary))
            self.assertEqual(count, len(SCHEMA_NAMES) + 2)
            self.assertTrue((Path(temporary) / "render-manifest.schema.json").is_file())
            self.assertTrue((Path(temporary) / "quality-gate-registry.schema.json").is_file())

    def test_every_schema_reference_resolves(self) -> None:
        root = Path(__file__).resolve().parents[1] / "schemas"
        documents = {path.name: json.loads(path.read_text()) for path in root.rglob("*.schema.json")}

        def references(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    yield value["$ref"]
                for child in value.values():
                    yield from references(child)
            elif isinstance(value, list):
                for child in value:
                    yield from references(child)

        for filename, document in documents.items():
            for reference in references(document):
                target, _, fragment = reference.partition("#")
                target_document = document
                if target:
                    target_name = Path(urlparse(target).path).name
                    self.assertIn(target_name, documents, f"{filename}: {reference}")
                    target_document = documents[target_name]
                if fragment:
                    current = target_document
                    for token in fragment.lstrip("/").split("/"):
                        token = token.replace("~1", "/").replace("~0", "~")
                        self.assertIn(token, current, f"{filename}: {reference}")
                        current = current[token]


if __name__ == "__main__":
    unittest.main()
