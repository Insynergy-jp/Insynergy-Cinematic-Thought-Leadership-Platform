# GitHub Actions Runbook

Repository administrators must create four scoped GitHub Environments before production use.

- `planning-ai`: trusted branches and actors only; provides the OpenAI credential solely to isolated Persona Council and Agent Review jobs.
- `persona-approval`: required Persona reviewer before Story generation; contains no secrets.
- `render-approval`: requires at least one editorial reviewer and prevents self-approval where the organization policy supports it.
- `publication-approval`: requires the final publication authority and has no deployment branch other than the protected default branch.

Repository settings are part of the production acceptance boundary. Require the
`Quality Gates` check on the default/release branches, restrict deployments for
all four Environments to trusted branches, configure required reviewers, and
disable release bypass where organization policy permits. Forks must not be
allowed to deploy to any protected Environment. Capture screenshots or API
exports of these settings as live acceptance evidence; workflow YAML cannot
prove repository-side protection by itself.

Configure the following values on `planning-ai`:

| Type | Name | Value |
| --- | --- | --- |
| Environment secret | `OPENAI_API_KEY` | OpenAI project API key |
| Environment variable | `OPENAI_MODEL_REVIEW` | `gpt-5.6-sol` |
| Environment variable | `OPENAI_REASONING_EFFORT` | `medium` |
| Environment variable | `OPENAI_TRACE_MODE` | `disabled` |

`OPENAI_API_KEY` must not be a repository secret, variable, workflow input, checked-in file, cache value, job output, or command argument. Empty or non-allow-listed model, reasoning, and trace settings fail preflight. `planning-ai` must not contain `RUNWAY_API_KEY` or publication credentials.

Create `persona-approval` with required reviewers and trusted deployment branches,
but do not add any secret. Its only authority is to release the exact sealed
Persona hash set into deterministic Story generation; it does not satisfy
`render-approval` or `publication-approval`.

The `persona-approval` job grants its `GITHUB_TOKEN` only `actions: read` and
`contents: read`. After GitHub releases the protected job, the job reads
`GET /repos/{owner}/{repo}/actions/runs/{run_id}/approvals`, resolves the exact
approved `persona-approval` record, and stores `workflow_initiator` and
`environment_reviewer` separately. It also reads and hash-binds the live
Required reviewers rule. Missing, rejected, malformed, ambiguous, or
non-required review history fails closed. When the live rule enables
`prevent_self_review`, the reviewer must differ from the workflow initiator;
when disabled, one attributable operator may initiate and approve. The resolved
review record is hash-bound into `persona-approval-binding.json`.

Configure the following values on the protected `render-approval` Environment:

| Type | Name | Value |
| --- | --- | --- |
| Environment secret | `RUNWAY_API_KEY` | Runway API key |
| Environment secret | `OPENAI_TTS_API_KEY` | Dedicated OpenAI project key for Speech API narration |
| Environment variable | `RUNWAY_BASE_URL` | `https://api.dev.runwayml.com` |
| Environment variable | `RUNWAY_MODEL_GEN45` | `gen4.5` |

The Runway and TTS API keys must be Environment secrets, not repository secrets, variables, workflow inputs, checked-in files, cache values, job outputs, or command arguments. The workflow exposes them only to their adapters inside `render-approval`; the Configuration Loader excludes both from the immutable Build snapshot, Manifest, Events, and Artifacts. `OPENAI_TTS_API_KEY` should be a dedicated project key for Speech API use. `render-approval` must not contain the Agents SDK credential named `OPENAI_API_KEY`.

The adapter pins Runway API version `2024-11-06`. It submits to `/v1/text_to_video` or `/v1/image_to_video`, polls and cancels through `/v1/tasks/{id}`, and downloads the successful task's signed output URL without forwarding the API key. Accepted task IDs are persisted under the ignored `.insynergy/providers/runway/` runtime directory for client-side replay protection. An ambiguous submission timeout is never automatically retried because that could create a second billable task.

Operation sequence:

1. Run `Plan Article`; select `persona_mode: off` for the compatibility path or `council` with a repository-relative Creative Brief. Select `agent_review_mode: off` or `review`, plus the Render, Runway, and Narration settings. The `off` planning path receives no provider secret.
2. In `council`, `persona-deliberation` alone enters `planning-ai`. The following `persona-quality` job has no secret and validates the five sealed artifacts. The `persona-approval` Environment contains no configured secret and must be approved before the same Build can generate Story. Its read-only workflow token resolves the actual Environment reviewer from GitHub review history; the approved binding separately records the workflow initiator and reviewer and is hash-bound to the review record, Article, Brief, Persona, deliberation, policy, and quality evidence.
3. In `review`, the isolated `agent-review` job enters `planning-ai`, validates the sealed planning bundle, executes one typed model turn, validates all evidence pointers, and publishes the immutable `planning-<run_id>` artifact. `off` creates the same artifact without importing the SDK or resolving an OpenAI secret.
4. Review the planning bundle, deterministic gate summary, Agent disposition, report hash, blocking finding codes, and evidence locations.
5. Run `Execute Approved Plan` with the planning run ID, Build ID, identical Profile, Provider, Runway Scope, and Narration Provider. `render-approval` approval becomes the actor recorded by the platform and is bound to both the Execution Plan hash and Agent Review Report hash.
6. If disposition is not `PASS`, set `allow_agent_exception: true` and provide a non-empty `agent_exception_reason`. This records an attributable human exception. Missing reports, invalid schemas, unresolved evidence, and hash mismatches remain non-waivable.
7. Review the validated Master and evidence artifact.
8. Before publication, inspect the immutable Build Quality Report, per-Gate drill-down hashes, Gate Chain `halted_at`, approval audit, Metadata/Packaging Gate, and Publication Gate. A missing report, failed mandatory Check, evidence/hash mismatch, or unresolved non-waivable finding blocks release.
9. Run `Publish Approved Build` with the execution run ID and Build ID. `publication-approval` remains a separate approval barrier.
10. Download `publication-<run_id>`. The Artifact root contains `master.mp4`, `<build_id>.zip`, `manifest.json`, and `publication-result.json`. Final-profile packages also contain `captions.en.srt` and `youtube-description.txt` with the required AI-voice disclosure.

Every cross-run bundle contains `workflow-evidence.json`. It binds every
transported file to a SHA-256 hash and binds the bundle to its stage, Build ID,
Profile, source workflow, repository, run ID, run attempt, and source commit.
Execute verifies the planning evidence before entering provider preflight;
Publish verifies the execution evidence before recording publication approval.
Run a downstream workflow from the same source commit as its upstream bundle.
A different commit, Profile, Build ID, source run, missing file, changed byte,
symbolic link, or detected credential pattern fails closed and requires a fresh
upstream run and approval.

Each successful stage writes a secret-safe `$GITHUB_STEP_SUMMARY` containing
only allow-listed state, identifiers, hashes, counts, and applicable cost/gate metadata.
Article bodies, prompt bodies, raw model responses, provider output URLs, and
credentials are prohibited from summaries. Failure diagnostics are retained for
seven days; planning/execution handoffs for thirty days; publication packages
for ninety days. GitHub artifacts are transport and reviewer surfaces only—the
Manifest and CAS remain authoritative.

`hybrid` execution limits paid generation to storyboard frames classified as `runway_video`; the remaining frames use deterministic local rendering. `all_shots` routes all eight approved frames through Gen-4.5. The platform estimates credits at 12 credits per generated second, fails before submission above the configured 480-credit ceiling, and never automatically resubmits a failed Runway task. `none` prohibits spoken audio and requires an empty narration timeline with no dialogue-caption asset. `offline` narration uses `espeak-ng` without an API call. `openai` narration uses the Speech API with `gpt-4o-mini-tts` and the configured voice. Final-profile Masters are encoded as H.264 High Profile, BT.709, 4:2:0, AAC stereo at 48 kHz, and Fast Start at the planned canvas, including native 1080×1920 Shorts; the delivery gate fails closed if those characteristics are absent. Composition validation also rejects missing or silent audio and visually uniform placeholder video.

Workflows use read-only repository permissions, pinned external Action SHAs, explicit timeouts, non-cancelling Build concurrency, and validated `workflow_dispatch` inputs. Required pull-request CI uses the fake review provider and never performs a live OpenAI call. Provider secrets remain confined to their own Environment and never cross the planning, rendering, or publication boundary.

The CI policy additionally rejects forbidden privileged triggers, broad token
permissions, missing Job timeouts, checkout credential persistence, direct
GitHub-expression interpolation in shell, non-strict shell blocks, unexpected
Environment/Secret bindings, and artifact uploads without explicit missing-file
or retention behavior. Run it locally with:

```bash
python3 tools/validate_workflows.py
PYTHONPATH=src python3 -m unittest tests.test_github_actions -v
PYTHONPATH=src python3 -m insynergy_cinematic part8-coverage
```

For a failed or interrupted execution, first inspect the seven-day diagnostics
and the authoritative Manifest. Use `verify` to check integrity and `recover` to
generate a non-mutating Recovery Plan. Use `resume` only from that verified
state; idempotency keys and provider task identities prevent duplicate external
effects. Use `pause` for a drainable hold and `cancel` for a domain cancellation.
Do not edit the Manifest or replay provider calls manually:

```bash
PYTHONPATH=src python3 -m insynergy_cinematic verify BUILD_ID
PYTHONPATH=src python3 -m insynergy_cinematic recover BUILD_ID
PYTHONPATH=src python3 -m insynergy_cinematic resume BUILD_ID
PYTHONPATH=src python3 -m insynergy_cinematic pause BUILD_ID
PYTHONPATH=src python3 -m insynergy_cinematic cancel BUILD_ID
```
