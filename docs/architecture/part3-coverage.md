# Part 3 Implementation Coverage

Part 3 is measured with a fixed twenty-cluster capability matrix. `FULL` is one
point, `PARTIAL` is half a point, and `MISSING` is zero points. The executable
matrix is `part3_coverage_report()` in `src/insynergy_cinematic/screenplay.py`:

```bash
PYTHONPATH=src python3 -m insynergy_cinematic part3-coverage
```

## Result

| Status | Clusters | Points |
| --- | ---: | ---: |
| Full | 18 | 18.0 |
| Partial | 2 | 1.0 |
| Missing | 0 | 0.0 |
| **Total** | **20** | **19.0 / 20 = 95.0%** |

## Evidence matrix

| # | Capability cluster | Status | Executable evidence |
| ---: | --- | --- | --- |
| 1 | Story-only boundary | FULL | `ScreenplayEngine.REQUIRED_INPUTS`; no Article or Agent dependency |
| 2 | Scene cardinality and three-act structure | FULL | 8 ordered scenes; `scene_count_in_range`, `three_acts_present` |
| 3 | Purpose, conflict, and objectives | FULL | controlled singular fields and blocking checks |
| 4 | Subtext and emotional progression | FULL | per-scene visual subtext and linked emotion endpoints |
| 5 | Observable action | FULL | interior-action predicate fails closed |
| 6 | Dialogue and silence | FULL | 15-word/two-line limits, six categories, explicit silence |
| 7 | Timing, transitions, and concepts | FULL | 4–10 seconds, controlled transitions, Act 3-only concepts |
| 8 | Fountain and JSON | FULL | standard Fountain plus canonical machine artifact bundle |
| 9 | Seven-dimension continuity | FULL | character, wardrobe, location, time, emotion, countdown, props |
| 10 | Screenplay Quality Gate | FULL | 17 mandatory predicates and central Gate registration |
| 11 | Computed metrics | FULL | action/dialogue ratio, duration, scene count, continuity score |
| 12 | Immutable external configuration | FULL | frozen settings loaded from `config/default.json` and sealed snapshot |
| 13 | Exact cache and determinism | FULL | Story/version/profile/config key; only validated bundles cached |
| 14 | Operational state | FULL | forward-only screenplay and per-scene state artifacts |
| 15 | Public interfaces | FULL | generator, dialogue, continuity, exporter, gate, state, cache classes |
| 16 | Agent Review boundary | FULL | sealed outputs reviewed read-only after deterministic validation |
| 17 | Automated acceptance | FULL | positive, negative, cache, state, Persona, downstream, and E2E tests |
| 18 | Persona continuity | FULL | live approved Persona lineage is preserved and invalidates downstream cache/approval |
| 19 | Human screenplay approval | PARTIAL | `AwaitingApproval` is explicit; approval is currently aggregate execution approval |
| 20 | Operational dashboard | PARTIAL | viewer outcomes and core Screenplay metrics are trended; exhaustive lifecycle timing remains follow-up |

The two partials remain visible by design. A dedicated Screenplay approval and
the complete lifecycle-timing series are not inferred from adjacent controls.
