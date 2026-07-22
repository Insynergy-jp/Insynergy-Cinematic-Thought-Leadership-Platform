from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.schema_validation import (
    ERROR_CODES,
    PERSONA_NAMES,
    audit_schema_bundle,
    part9_coverage_report,
    validate_persona_bundle,
    validate_schema_document,
)
from insynergy_cinematic.schemas import (
    SCHEMA_BUNDLE_FILE_COUNT,
    SCHEMA_METADATA,
    SCHEMA_NAMES,
    export_schemas,
)
from insynergy_cinematic.util import content_hash
from tests.persona_fixture import golden_persona_bundle


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def reseal(document: dict) -> None:
    document["content_hash"] = content_hash(
        {key: value for key, value in document.items() if key != "content_hash"}
    )


def error_codes(exception: ValidationError) -> set[str]:
    return {
        item["code"]
        for item in exception.details.get("errors", [])
        if isinstance(item, dict) and "code" in item
    } | ({exception.details["code"]} if "code" in exception.details else set())


class JSONSchemaArchitectureTests(unittest.TestCase):
    def test_part9_coverage_reaches_exact_target(self) -> None:
        report = part9_coverage_report()
        self.assertEqual(report["cluster_count"], 20)
        self.assertEqual((report["full"], report["partial"], report["missing"]), (17, 2, 1))
        self.assertEqual(report["coverage_percent"], 90.0)
        self.assertEqual(
            {
                row["cluster"]
                for row in report["clusters"]
                if row["status"] == "MISSING"
            },
            {"public_schema_distribution"},
        )

    def test_complete_bundle_passes_dialect_registry_reference_and_baseline_audit(self) -> None:
        report = audit_schema_bundle(SCHEMAS)
        self.assertTrue(report["passed"])
        self.assertEqual(report["schema_count"], len(SCHEMA_NAMES) + 1)
        self.assertEqual(report["registered_count"], len(SCHEMA_NAMES))
        self.assertEqual(report["unique_id_count"], len(SCHEMA_NAMES) + 1)
        self.assertGreaterEqual(report["object_closure_percent"], 90.0)
        self.assertTrue(report["persona_closed_objects"])

    def test_registry_is_exhaustive_owned_versioned_and_hash_bound(self) -> None:
        registry = json.loads((SCHEMAS / "schema-registry.json").read_text())
        entries = registry["schemas"]
        self.assertEqual([entry["name"] for entry in entries], list(SCHEMA_NAMES))
        self.assertEqual(len({entry["id"] for entry in entries}), len(entries))
        self.assertEqual(registry["content_hash"], content_hash(entries))
        for entry in entries:
            self.assertEqual(
                {key: entry[key] for key in ("version", "owner", "chapter")},
                SCHEMA_METADATA[entry["name"]],
            )

    def test_export_is_byte_identical_and_includes_persona_and_compatibility_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            count = export_schemas(destination)
            self.assertEqual(count, SCHEMA_BUNDLE_FILE_COUNT)
            for source in SCHEMAS.rglob("*.json"):
                target = destination / source.relative_to(SCHEMAS)
                self.assertTrue(target.is_file(), source.name)
                self.assertEqual(target.read_bytes(), source.read_bytes(), source.name)
            for name in PERSONA_NAMES:
                self.assertTrue((destination / f"{name}.schema.json").is_file())
            self.assertTrue((destination / "compatibility-baseline.json").is_file())

    def test_golden_persona_bundle_validates_all_six_schemas_and_invariants(self) -> None:
        bundle = golden_persona_bundle()
        self.assertEqual(set(bundle), set(PERSONA_NAMES))
        for name, document in bundle.items():
            self.assertTrue(validate_schema_document(name, document)["passed"])
        result = validate_persona_bundle(bundle)
        self.assertTrue(result["passed"])
        self.assertEqual((result["artifact_count"], result["proposal_count"]), (6, 3))

    def test_schema_errors_are_stable_for_required_extra_enum_pattern_format_and_bounds(self) -> None:
        cases = []
        missing = golden_persona_bundle()["persona"]
        del missing["role"]
        cases.append((missing, "E-SCHEMA-001"))
        extra = golden_persona_bundle()["persona"]
        extra["raw_transcript"] = "prohibited"
        cases.append((extra, "E-SCHEMA-003"))
        enum = golden_persona_bundle()["persona"]
        enum["role"]["basis"] = "INVENTED"
        cases.append((enum, "E-SCHEMA-004"))
        pattern = golden_persona_bundle()["persona"]
        pattern["persona_id"] = "invalid"
        cases.append((pattern, "E-SCHEMA-005"))
        formatted = golden_persona_bundle()["persona"]
        formatted["generated_at"] = "yesterday"
        cases.append((formatted, "E-SCHEMA-006"))
        bounded = golden_persona_bundle()["persona"]
        bounded["source_fidelity"] = 1.1
        cases.append((bounded, "E-SCHEMA-007"))
        for document, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(ValidationError) as raised:
                validate_schema_document("persona", document)
            self.assertIn(expected, error_codes(raised.exception))

    def test_content_and_individual_proposal_hash_tampering_fail_closed(self) -> None:
        bundle = golden_persona_bundle()
        bundle["persona"]["role"]["value"] = "Different executive"
        with self.assertRaises(ValidationError) as raised:
            validate_schema_document("persona", bundle["persona"])
        self.assertIn("E-FIX-001", error_codes(raised.exception))

        bundle = golden_persona_bundle()
        proposal = bundle["persona-proposals"]["proposals"][0]
        proposal["persona_fields"]["role"]["value"] = "Different executive"
        reseal(bundle["persona-proposals"])
        with self.assertRaises(ValidationError) as raised:
            validate_persona_bundle(bundle)
        self.assertIn("E-FIX-001", error_codes(raised.exception))

    def test_cross_artifact_stale_binding_and_unresolved_objection_fail_closed(self) -> None:
        stale = golden_persona_bundle()
        stale["persona"]["role"]["value"] = "Chief Risk Officer"
        reseal(stale["persona"])
        with self.assertRaises(ValidationError) as raised:
            validate_persona_bundle(stale)
        self.assertIn("E-REF-001", error_codes(raised.exception))

        unresolved = golden_persona_bundle()
        unresolved["persona-deliberation"]["resolutions"] = []
        reseal(unresolved["persona-deliberation"])
        with self.assertRaises(ValidationError) as raised:
            validate_persona_bundle(unresolved)
        self.assertIn("E-REF-002", error_codes(raised.exception))

    def test_proposal_role_cardinality_and_high_risk_assumptions_fail_closed(self) -> None:
        roles = golden_persona_bundle()
        proposal = roles["persona-proposals"]["proposals"][1]
        proposal["role"] = "audience_researcher"
        proposal["proposal_hash"] = content_hash(
            {key: value for key, value in proposal.items() if key != "proposal_hash"}
        )
        reseal(roles["persona-proposals"])
        with self.assertRaises(ValidationError) as raised:
            validate_schema_document("persona-proposals", roles["persona-proposals"])
        self.assertIn("E-SCHEMA-007", error_codes(raised.exception))

        risk = golden_persona_bundle()
        risk["persona"]["assumptions"][0]["risk"] = "HIGH"
        reseal(risk["persona"])
        with self.assertRaises(ValidationError) as raised:
            validate_persona_bundle(risk)
        self.assertIn("E-APPROVAL-001", error_codes(raised.exception))

    def test_legacy_schema_baseline_and_duplicate_ids_detect_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "schemas"
            shutil.copytree(SCHEMAS, copied)
            path = copied / "theme.schema.json"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaises(ValidationError) as raised:
                audit_schema_bundle(copied)
            self.assertIn("E-IMMUT-001", error_codes(raised.exception))

        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "schemas"
            shutil.copytree(SCHEMAS, copied)
            persona = json.loads((copied / "persona.schema.json").read_text())
            persona["$id"] = json.loads(
                (copied / "persona-proposals.schema.json").read_text()
            )["$id"]
            (copied / "persona.schema.json").write_text(json.dumps(persona))
            with self.assertRaises(ValidationError) as raised:
                audit_schema_bundle(copied)
            self.assertIn("E-REF-002", error_codes(raised.exception))

    def test_error_registry_is_routed_and_has_no_generic_invalid_code(self) -> None:
        self.assertGreaterEqual(len(ERROR_CODES), 12)
        self.assertTrue(all(code.startswith("E-") for code in ERROR_CODES))
        self.assertNotIn("INVALID", ERROR_CODES)


if __name__ == "__main__":
    unittest.main()
