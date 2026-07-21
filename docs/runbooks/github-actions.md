# GitHub Actions Runbook

Repository administrators must create three scoped GitHub Environments before production use.

- `planning-ai`: trusted branches and actors only; provides the OpenAI credential solely to the isolated Agent Review job.
- `render-approval`: requires at least one editorial reviewer and prevents self-approval where the organization policy supports it.
- `publication-approval`: requires the final publication authority and has no deployment branch other than the protected default branch.

Configure the following values on `planning-ai`:

| Type | Name | Value |
| --- | --- | --- |
| Environment secret | `OPENAI_API_KEY` | OpenAI project API key |
| Environment variable | `OPENAI_MODEL_REVIEW` | `gpt-5.6-sol` |
| Environment variable | `OPENAI_REASONING_EFFORT` | `medium` |
| Environment variable | `OPENAI_TRACE_MODE` | `disabled` |

`OPENAI_API_KEY` must not be a repository secret, variable, workflow input, checked-in file, cache value, job output, or command argument. Empty or non-allow-listed model, reasoning, and trace settings fail preflight. `planning-ai` must not contain `RUNWAY_API_KEY` or publication credentials.

Configure the following values on the protected `render-approval` Environment:

| Type | Name | Value |
| --- | --- | --- |
| Environment secret | `RUNWAY_API_KEY` | Runway API key |
| Environment variable | `RUNWAY_BASE_URL` | `https://api.dev.runwayml.com` |
| Environment variable | `RUNWAY_MODEL_GEN45` | `gen4.5` |

The Runway API key must be an Environment secret, not a repository secret, workflow input, repository file, repository variable, or command argument. The workflow exposes it only to provider validation and execution inside `render-approval`. GitHub masks the secret, and the Configuration Loader excludes it from the immutable Build snapshot, Manifest, Events, and Artifacts. `render-approval` must not contain `OPENAI_API_KEY`.

The adapter pins Runway API version `2024-11-06`. It submits to `/v1/text_to_video` or `/v1/image_to_video`, polls and cancels through `/v1/tasks/{id}`, and downloads the successful task's signed output URL without forwarding the API key. Accepted task IDs are persisted under the ignored `.insynergy/providers/runway/` runtime directory for client-side replay protection. An ambiguous submission timeout is never automatically retried because that could create a second billable task.

Operation sequence:

1. Run `Plan Article`; select `agent_review_mode: off` for compatibility or `review` for the Agents SDK review. The deterministic `plan` job receives no provider secret.
2. In `review`, the isolated `agent-review` job enters `planning-ai`, validates the sealed planning bundle, executes one typed model turn, validates all evidence pointers, and publishes the immutable `planning-<run_id>` artifact. `off` creates the same artifact without importing the SDK or resolving an OpenAI secret.
3. Review the planning bundle, deterministic gate summary, Agent disposition, report hash, blocking finding codes, and evidence locations.
4. Run `Execute Approved Plan` with the planning run ID, Build ID, identical Profile, and identical Provider. `render-approval` approval becomes the actor recorded by the platform and is bound to both the Execution Plan hash and Agent Review Report hash.
5. If disposition is not `PASS`, set `allow_agent_exception: true` and provide a non-empty `agent_exception_reason`. This records an attributable human exception. Missing reports, invalid schemas, unresolved evidence, and hash mismatches remain non-waivable.
6. Review the validated Master and evidence artifact.
7. Run `Publish Approved Build` with the execution run ID and Build ID. `publication-approval` remains a separate approval barrier.
8. Download `publication-<run_id>`. The Artifact root contains `master.mp4`, `<build_id>.zip`, `manifest.json`, and `publication-result.json`; no hidden directory navigation or nested ZIP extraction is required to play the Master.

Preview execution limits paid generation to storyboard frames classified as `runway_video`. The remaining frames are rendered as deterministic, text-bearing local motion graphics. English narration is synthesized offline with `espeak-ng` and mixed into the Master without an API call. Composition validation rejects missing or silent audio and visually uniform placeholder video; an audio stream by itself is not sufficient to pass.

Workflows use read-only repository permissions, pinned external Action SHAs, explicit timeouts, non-cancelling Build concurrency, and validated `workflow_dispatch` inputs. Required pull-request CI uses the fake review provider and never performs a live OpenAI call. Provider secrets remain confined to their own Environment and never cross the planning, rendering, or publication boundary.
