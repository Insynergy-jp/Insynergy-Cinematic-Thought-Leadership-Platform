# GitHub Actions Runbook

Repository administrators must create two protected GitHub Environments before production use.

- `render-approval`: requires at least one editorial reviewer and prevents self-approval where the organization policy supports it.
- `publication-approval`: requires the final publication authority and has no deployment branch other than the protected default branch.

Configure the following values on the protected `render-approval` Environment:

| Type | Name | Value |
| --- | --- | --- |
| Environment secret | `RUNWAY_API_KEY` | Runway API key |
| Environment variable | `RUNWAY_BASE_URL` | Approved Runway API base URL |
| Environment variable | `RUNWAY_MODEL_GEN45` | Concrete model ID bound to the `gen4.5` profile |

The API key must be a GitHub Actions secret, not a workflow input, repository file, repository variable, or command argument. An Environment secret is recommended because it binds credential access to `render-approval`; a Repository secret with the same name is also resolved by the workflow. The workflow exposes it only to the provider-validation and execution steps. GitHub masks the secret, and the Configuration Loader excludes it from the immutable Build snapshot, Manifest, Events, and Artifacts.

Operation sequence:

1. Run `Plan Article`, choose `provider: runway`, and review its `planning-<run_id>` artifact.
2. Run `Execute Approved Plan` with the planning run ID, Build ID, identical Profile, and identical Provider. GitHub Environment approval becomes the actor recorded by the platform.
3. Review the validated Master and evidence artifact.
4. Run `Publish Approved Build` with the execution run ID and Build ID. The publication Environment is a separate approval barrier.

Workflows use read-only repository permissions, pinned external Action SHAs, explicit timeouts, non-cancelling Build concurrency, and validated `workflow_dispatch` inputs. Provider secrets belong only in the `render-approval` Environment and must never be placed in repository variables or workflow inputs.
