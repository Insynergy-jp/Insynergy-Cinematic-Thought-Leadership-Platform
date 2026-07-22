# JSON Schema Governance Runbook

## Routine verification

Run the complete bundle audit before review:

```bash
PYTHONPATH=src python3 -m insynergy_cinematic audit-schemas
```

The command fails closed for invalid dialects, duplicate or mismatched `$id`
values, unresolved `$ref` or JSON Pointer targets, incomplete registry entries,
registry hash drift, open Persona object boundaries, and v2.0/v2.1 compatibility
baseline drift.

Confirm the packaged export is byte-identical to the canonical source:

```bash
schema_tmp="$(mktemp -d)"
PYTHONPATH=src python3 -m insynergy_cinematic export-schemas "$schema_tmp"
diff -ru schemas "$schema_tmp"
```

## Validate an artifact

```bash
PYTHONPATH=src python3 -m insynergy_cinematic \
  validate-schema persona path/to/persona.json
```

Validate all six Persona Council artifacts and their cross-artifact bindings:

```bash
PYTHONPATH=src python3 -m insynergy_cinematic \
  validate-persona-bundle path/to/persona-bundle
```

The directory must contain `persona-proposals.json`,
`persona-red-team-report.json`, `persona-deliberation.json`, `persona.json`,
`persona-quality-report.json`, and `persona-approval-binding.json`.

## Change process

1. Add or change the canonical schema under `schemas/`.
2. Preserve existing v2.0/v2.1 files byte-for-byte. A breaking change requires
   a new schema ID and version instead of baseline replacement.
3. Update `SCHEMA_NAMES` and `SCHEMA_METADATA` for a newly registered schema.
4. Run `python3 tools/refresh_schema_catalog.py` to refresh the registry and
   packaged copies.
5. Run the audit, schema tests, and full unit test suite.

`schemas/compatibility-baseline.json` is an immutable acceptance baseline. The
initializer flag exists only to bootstrap a repository with no baseline and
refuses to overwrite an existing file. Do not edit hashes to make drift pass;
restore the compatible file or introduce a new versioned schema.
