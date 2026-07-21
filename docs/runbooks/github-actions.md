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
| Environment secret | `OPENAI_TTS_API_KEY` | Dedicated OpenAI project key for Speech API narration |
| Environment variable | `RUNWAY_BASE_URL` | `https://api.dev.runwayml.com` |
| Environment variable | `RUNWAY_MODEL_GEN45` | `gen4.5` |

The Runway and TTS API keys must be Environment secrets, not repository secrets, variables, workflow inputs, checked-in files, cache values, job outputs, or command arguments. The workflow exposes them only to their adapters inside `render-approval`; the Configuration Loader excludes both from the immutable Build snapshot, Manifest, Events, and Artifacts. `OPENAI_TTS_API_KEY` should be a dedicated project key for Speech API use. `render-approval` must not contain the Agents SDK credential named `OPENAI_API_KEY`.

The adapter pins Runway API version `2024-11-06`. It submits to `/v1/text_to_video` or `/v1/image_to_video`, polls and cancels through `/v1/tasks/{id}`, and downloads the successful task's signed output URL without forwarding the API key. Accepted task IDs are persisted under the ignored `.insynergy/providers/runway/` runtime directory for client-side replay protection. An ambiguous submission timeout is never automatically retried because that could create a second billable task.

Operation sequence:

1. Run `Plan Article`; select `agent_review_mode: off` for compatibility or `review` for the Agents SDK review. Select `runway_scope: hybrid` for one paid cinematic shot or `all_shots` for all six shots. Select `narration_provider: offline` for zero-cost previews or `openai` for production narration. The deterministic `plan` job receives no provider secret.
2. In `review`, the isolated `agent-review` job enters `planning-ai`, validates the sealed planning bundle, executes one typed model turn, validates all evidence pointers, and publishes the immutable `planning-<run_id>` artifact. `off` creates the same artifact without importing the SDK or resolving an OpenAI secret.
3. Review the planning bundle, deterministic gate summary, Agent disposition, report hash, blocking finding codes, and evidence locations.
4. Run `Execute Approved Plan` with the planning run ID, Build ID, identical Profile, Provider, Runway Scope, and Narration Provider. `render-approval` approval becomes the actor recorded by the platform and is bound to both the Execution Plan hash and Agent Review Report hash.
5. If disposition is not `PASS`, set `allow_agent_exception: true` and provide a non-empty `agent_exception_reason`. This records an attributable human exception. Missing reports, invalid schemas, unresolved evidence, and hash mismatches remain non-waivable.
6. Review the validated Master and evidence artifact.
7. Run `Publish Approved Build` with the execution run ID and Build ID. `publication-approval` remains a separate approval barrier.
8. Download `publication-<run_id>`. The Artifact root contains `master.mp4`, `<build_id>.zip`, `manifest.json`, and `publication-result.json`. Final-profile packages also contain `captions.en.srt` and `youtube-description.txt` with the required AI-voice disclosure.

`hybrid` execution limits paid generation to storyboard frames classified as `runway_video`; the remaining frames use deterministic local rendering. `all_shots` routes all six approved frames through Gen-4.5. The platform estimates credits at 12 credits per generated second, fails before submission above the configured 360-credit ceiling, and never automatically resubmits a failed Runway task. `offline` narration uses `espeak-ng` without an API call. `openai` narration uses the Speech API with `gpt-4o-mini-tts` and the `marin` voice. Final-profile Masters are encoded as 1080p SDR H.264 High Profile, BT.709, 4:2:0, AAC stereo at 48 kHz, and Fast Start; the delivery gate fails closed if those characteristics are absent. Composition validation also rejects missing or silent audio and visually uniform placeholder video.

Workflows use read-only repository permissions, pinned external Action SHAs, explicit timeouts, non-cancelling Build concurrency, and validated `workflow_dispatch` inputs. Required pull-request CI uses the fake review provider and never performs a live OpenAI call. Provider secrets remain confined to their own Environment and never cross the planning, rendering, or publication boundary.
