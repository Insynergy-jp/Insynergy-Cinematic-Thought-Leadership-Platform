# Part 8 Implementation Coverage

Part 8 is measured with a fixed twenty-cluster matrix. The scoring method is:

- `FULL` = 1 point;
- `PARTIAL` = 0.5 points;
- `MISSING` = 0 points.

The executable source is `part8_coverage_report()` in
`src/insynergy_cinematic/github_actions.py`:

```bash
PYTHONPATH=src python3 -m insynergy_cinematic part8-coverage
```

## Result

| Status | Clusters | Points |
| --- | ---: | ---: |
| Full | 18 | 18.0 |
| Partial | 2 | 1.0 |
| Missing | 0 | 0.0 |
| **Total** | **20** | **19.0 / 20 = 95.0%** |

## Full

1. Host/domain boundary: workflows invoke host-agnostic orchestrator verbs.
2. Typed trigger contracts and fail-closed input validation.
3. Secret-free deterministic planning and immutable planning handoff.
4. Optional Agent Review isolated in `planning-ai`.
5. Independent `render-approval` and `publication-approval` decisions.
6. Execution identity, configuration, budget, and approval preflight.
7. Quality and runtime verification blocks publication.
8. Build-scoped concurrency and domain idempotency/replay protection.
9. Portable Manifest, Checkpoint, and Recovery Plan projection.
10. Durable backpressure, provider limits, and cost admission before spend.
11. Job- and Environment-scoped provider credentials.
12. Read-only, least-privilege `GITHUB_TOKEN` permissions.
13. External Action SHA pinning, allowlist enforcement, and local actions.
14. Secret-free pull-request CI, strict shell blocks, and env-only expression
    transfer.
15. Cross-run artifact sealing with file SHA-256, Build/Profile/Run/Commit
    binding, secret-pattern scanning, and bounded retention.
16. Allow-listed job summaries and bounded failure diagnostics.
17. Workflow policy/contract tests, local E2E tests, and operator runbooks.
18. Persona Council isolated in `planning-ai`, secretless quality validation,
    protected secretless `persona-approval`, and deterministic Story handoff.

## Partial

1. Runner, OIDC, and telemetry infrastructure: bounded ephemeral hosted runners
   are used, while the self-hosted fleet, OIDC federation, and external metrics
   exporter remain deployment work.
2. Live protection acceptance: workflow contracts and the administrator
   checklist exist, while branch rules, required checks, protected Environment
   reviewers, and no-bypass behavior must be evidenced in the live repository.

## Missing

None. Repository-side Environment protection and external runner/telemetry
evidence remain partial because workflow YAML cannot prove those live settings.
