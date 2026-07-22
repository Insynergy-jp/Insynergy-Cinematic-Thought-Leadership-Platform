# Viewer Outcomes Dashboard Runbook

This service measures the terminal product criterion: whether viewers understand
the idea, remember it without aid, react to the idea rather than the medium, and
retain conceptual accuracy. Production impressiveness is not a success signal.

## Measurement protocol

Record one event per viewer and assessment interval. Use a stable idempotency key
from the survey system. The default long-term threshold is seven days (`168`
hours); immediate or short-term responses remain `PENDING_RETENTION` and cannot
produce a successful verdict.

```bash
printf '%s\n' "$VIEWER_REFERENCE" | PYTHONPATH=src python3 -m insynergy_cinematic \
  record-viewer-outcome BUILD_ID --viewer-id-stdin \
  --idea-restatement-accuracy 0.92 \
  --unaided-recall 0.84 \
  --reaction-subject IDEA \
  --accuracy-gate-result PASS \
  --retention-hours 168 \
  --cohort executive-pilot \
  --observed-at 2026-07-22T09:00:00Z \
  --idempotency-key survey-system-event-001
```

`idea_restatement_accuracy` and `unaided_recall` are ratios from `0` through
`1`. `reaction_subject` is `IDEA`, `MEDIUM`, or `MIXED`; any value other than
`IDEA` is a medium-foregrounding failure. `accuracy_gate_result` is `PASS` or
`FAIL` and represents an externally scored rigor check.

Generate the static operational surface and its machine-readable counterpart:

```bash
PYTHONPATH=src python3 -m insynergy_cinematic outcomes-dashboard --window-days 365
```

The default destinations are `.insynergy/outcomes/dashboard.html` and
`.insynergy/outcomes/dashboard.json`. Filters and thresholds are explicit CLI
arguments. The report includes aggregate and per-Build verdicts, cohort and
monthly trends, 95% Wilson intervals, memory-interval buckets, and available
Story/Screenplay production context.

## Verdict policy

- `SUCCESS` requires at least five total and five long-term eligible outcomes,
  comprehension at or above `0.80`, recall at or above `0.70`, `IDEA` reaction,
  and accuracy `PASS`.
- `INSUFFICIENT_EVIDENCE` means no decisive failure exists but sample or
  retention maturity is below the configured floor.
- `FAIL` is decisive when any outcome records misunderstanding, medium
  foregrounding, rigor loss, or an eligible long-term recall failure.

## Privacy and integrity

The raw viewer reference is transformed with HMAC-SHA-256 and is never written
to an event, response, dashboard, or log by the outcome service. Free-text
responses are not accepted. Cohorts are controlled identifiers rather than
personal attributes. The local HMAC key is stored with owner-only permissions.

Every immutable evaluation has a canonical content hash. `ledger.json` binds
the event files in a sequence-numbered hash chain; missing, altered, duplicated,
or unledgered event files stop dashboard generation. Dashboard rows are
aggregates and never include viewer tokens.

The API equivalents are `POST /api/v2/outcomes` with an `Idempotency-Key` header
and `GET /api/v2/outcomes/dashboard`. When an external survey system is used,
send the viewer reference only over authenticated TLS and keep the API token and
survey mapping outside the platform artifact store.
