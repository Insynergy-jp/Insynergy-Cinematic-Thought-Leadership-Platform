# Full Auto — Persona Council Report

Status: Completed for creative development
Council topology: three bounded proposals → one Red-Team review → one Manager synthesis
Proposal roles: Audience Researcher, Empathy & Narrative Analyst, Brand Strategist
Approval boundary: This report recommends a persona; it does not impersonate a human approval or the repository’s six signed Persona runtime artifacts.

## Post-approval creative revision — 2026-07-23

The Council decision below remains the historical evaluation of the previously approved Brief. The canonical Brief has since been revised to use `It'll be done by morning.` in Shot 01 and `I'm such a fucking idiot!` in Shot 07 so that both spoken lines match the film's English interface and brand language. The existing Shot 03 agent-multiplication design, Shot 05 completed-task and rising-usage sequence, Shot 06 mouse-controlled STOP interaction, and Shot 07 anger, panic, regret, natural-white eyes, and non-gory vascular tension remain unchanged. Build `20260723-002` has therefore been marked `REJECTED` at the Storyboard Preview approval gate and must not advance. A future pipeline-generated preview requires a new Brief-bound Persona Council run and approval; no rerun or MP4 generation was performed as part of this revision.

## Manager decision

`PASS FOR STORYBOARD DEVELOPMENT`

The Council selects one protagonist: an autonomous coding-agent operator who wants a completed result without staying awake to supervise it, believes a manual STOP preserves control, and discovers that the authority to request a stop is not the same as a designed stopping boundary.

The protagonist is competent and plausible. The film must never frame the error as stupidity, malicious AI, or a particular provider’s failure. The visible loss is rising spend; the deeper loss is the protagonist’s mistaken belief that they retained control after removing the conditions that made control meaningful.

## Canonical persona

| Field | Selected value | Basis |
| --- | --- | --- |
| `role` | Developer who configures and starts an autonomous coding-agent run | Creative Brief |
| `job_to_be_done` | Have the run complete useful work overnight so results are ready in the morning | Creative Brief |
| `dominant_desire` | Gain speed and completion without remaining present to supervise | Creative Brief + low-risk inference from closing the computer and leaving |
| `dominant_fear` | Discover too late that execution and spend cannot be brought back under immediate control | Creative Brief |
| `internal_contradiction` | Enables “continue until complete” to gain control over completion while removing the limits that make autonomous execution controllable | Creative Brief |
| `decision_pressure` | At 00:18, the promise of waking to finished work makes immediate unsupervised execution more attractive than boundary design | Creative Brief |
| `authority_boundary` | May initiate and request a stop, but has not defined spend, approval, escalation, concurrency, or forced-stop conditions before execution | Source Article + Creative Brief |
| `current_workaround` | Leave every autonomy control on, rely on a usage alert, then react with a manual STOP after consequence is visible | Creative Brief |
| `emotional_arc_candidate` | Quiet confidence → absence → frozen recognition → urgent intervention → failed control recovery → silence → recognition of the missing judgment structure | Creative Brief |

## Evidence used

- The run begins at 00:18 with Full Auto, parallel work, automatic retry, continued execution, and no spending limit.
- The protagonist leaves the room while `RUN #001` remains active.
- Workers and run counts multiply to 184 without a human present.
- A morning alert shows `$512.43`; the live total then rises beyond `$731.88`.
- STOP becomes a request that must wait for 12 active workers.
- The system states that the task was executed as configured.
- The final structure shows Approval, Spending Limit, Escalation, and Decision Boundary, with Spending Limit missing.
- The end proposition explicitly distinguishes system execution from human judgment design.

## Red-Team findings and resolutions

| Finding | Severity | Resolution |
| --- | --- | --- |
| The original durations total 30.5 seconds, not 30.0 | Blocking | Shot 02 is reduced from 3.5 to 3.0 seconds. Final runtime is 30.00. |
| The draft contains two spoken lines despite the “one line” constraint | Blocking | Keep only `なんで止まらなかった…` in Shot 07. Shot 01 communicates confidence through performance. |
| Real product names and familiar UI could imply a claim about a provider | Blocking | Use an entirely generic runtime, phone alert, and UI geometry. Composite exact text in post. |
| The story could read as a careless individual’s expensive mistake | Blocking | Direct the protagonist as competent; connect the personal omission to missing approval, spend, escalation, and stopping architecture. |
| Rising money could become comedy or horror | Major | Keep the number changes small, dry, and silent. The emotional center is the failed control boundary, not bill shock. |
| “STOP” could falsely imply immediate termination | Major | Show `STOP REQUESTED`, `WAITING FOR ACTIVE WORKERS…`, and `12 ACTIVE AGENTS` together. |
| Floating concept labels could become an exposition graphic | Major | Reveal the missing edge and leaking execution pulse first; resolve labels only after the visual metaphor is understood. |
| `The AI did exactly what it was told.` could be read as a factual claim about output correctness | Advisory | Preserve the user’s specified thematic line, but frame the entire film as an original fictional composite and make `TASK EXECUTED AS CONFIGURED.` the narrower in-world claim. |

## Explicit assumptions

- The amounts, task count, worker count, and drain behavior are fictional examples, not a statement about any product’s pricing or guaranteed behavior.
- The protagonist seeks relief from supervision; this is inferred from leaving the run overnight and is not a biographical claim.
- The film treats the missing spending limit as the visible member of a broader institutional boundary-design failure.
- No age, nationality, employer, title, family status, health condition, trauma, or personal history belongs to the persona. Casting details in image prompts are production continuity choices, not Persona facts.

## Persona Quality Gate

| Check | Result |
| --- | --- |
| Three proposal roles completed | PASS |
| Red-Team objections resolved or exposed | PASS |
| One Manager synthesis | PASS |
| Source and Creative Brief evidence separated from assumptions | PASS |
| No invented biography or vulnerable setting | PASS |
| Exactly one persona | PASS |
| Usable for a 30-second human decision story | PASS |
| Brand and provider neutrality | PASS |

Overall: `PASS FOR STORYBOARD DEVELOPMENT`

## Repository live-runtime status

The project now has a dedicated `.venv` with the required OpenAI packages. Health checks with `persona-mode=council` and `storyboard_animatic` report the credential, SDK, and FFmpeg paths as `HEALTHY`.

Five live runs were attempted:

- Build `20260722-002`: the medium-reasoning Council reached the configured 180-second limit and failed without sealing Persona artifacts.
- Build `20260722-003`: the complete bounded Council topology returned five valid pre-approval artifacts, but the deterministic Persona Quality Gate returned `MANUAL_REVIEW_REQUIRED`. Because non-PASS Council outputs are not cached or sealed by design, the build stopped before Persona approval.
- Build `20260722-004`: an explicitly authorized medium-reasoning retry used a 360-second limit. The Manager response returned proposal-role identifiers that did not match the contract’s fixed role enum, so the runtime rejected it with `Persona proposal roles are invalid` before content quality evaluation.
- Build `20260722-005`: the provider contract was upgraded to `persona-manager-v2` / `persona-council-v2`, replacing the unconstrained proposal list with one typed slot per specialist role. The live Council then produced all five pre-approval artifacts, but a different deterministic Persona check returned `MANUAL_REVIEW_REQUIRED`. The current exception payload records the sealed artifact hashes but not the failed check identifier, so no human approval was possible.
- Build `20260722-006`: the improved v2 runtime completed in about 195 seconds. All five pre-approval artifacts were sealed, cross-artifact validation passed, and all ten deterministic Persona Quality Gate checks returned `PASS`. Estimated planning-AI cost was 1.0 USD. The build is held at `AWAITING_PERSONA_APPROVAL`.

## Live Persona awaiting human approval

- Role: `A competent leader or hands-on builder who authorizes or operates autonomous AI agents.`
- Job to be done: gain autonomous productivity while defining spend, approval, escalation, and stop-versus-retry boundaries before execution.
- Desire: unattended productivity without losing accountable human judgment.
- Fear: discovering unacceptable cost or governance consequences too late.
- Contradiction: wants independent execution while retaining human judgment over spend, uncertainty, divergence, and continuation.
- Authority boundary: may authorize execution but must define approval events, spending limits, escalation ownership, and mandatory stop conditions.
- Workaround: relies on monitoring, alerts, and emergency STOP after execution starts.
- Emotional arc: confident enablement → uncontrolled continuation → recognition of the missing human-designed Decision Boundary.

The live Persona has two LOW-risk assumptions and one unresolved editorial question: whether to narrow the canonical role to an executive decision-maker or a hands-on operator. The supplied film scenario explicitly shows a developer, so narrowing to a hands-on operator would improve downstream Story specificity. The following section records the operator’s subsequent approval decision.

## Persona approval and downstream planning audit

Ryoji Morii approved the sealed live Persona for Build `20260722-006`. Approval binding `PAB-bdc1d736a16616312d18` was recorded with explicit acceptance of the broad role and both LOW-risk assumptions. Story, Screenplay, Shot, and Storyboard deterministic gates then returned `PASS`.

The downstream semantic audit found a blocking product limitation: the current Screenplay Engine does not consume the Creative Brief’s required narrative spine. It generated the fixed 32-second template `The Empty Approval Field`, set entirely in an Executive Review Room, instead of the approved `Full Auto` home-office scenario. The generated Storyboard has eight 4-second frames about an unsigned approval record and therefore must not be sent to paid previsualization.

The secret-free Storyboard Preview preflight itself passed with eight shots, a 5 USD estimate, a 10 USD hard cap, and zero initialized OpenAI or Runway providers. Paid previsualization was intentionally not started because the sealed Screenplay is semantically wrong for this film.

No human approval, storyboard-preview approval, rendering, or publication action was performed. A further live retry may incur additional planning-AI cost and therefore requires an explicit operator decision.

## Authored-scenario implementation continuation

The platform limitation identified above has now been addressed with an opt-in `creative-scenario/1` contract embedded inside the Creative Brief. The default deterministic Screenplay remains unchanged when the block is absent. In approved Council mode, the structured scenario is instead extracted, validated, sealed to the Creative Brief hash, added to Story cache identity, and preserved through Screenplay, Shot, Storyboard, and previsualization inputs.

The Full Auto contract now fixes:

- eight scenes and exact 30.0-second runtime (`3.5, 3.0, 4.0, 3.5, 4.0, 4.0, 4.0, 4.0`);
- one spoken line, `なんで止まらなかった…`, with every other scene explicitly sealed as silence;
- the generic full-auto controls, `$512.43` alert, `184 TASKS`, rising `$731.88` total, late STOP request, and `12 ACTIVE AGENTS`;
- the missing Spending Limit structure and final Decision Design proposition;
- authored camera, lighting, performance, post-UI, sound, and hybrid render assignments;
- two `runway_video` shots, one deterministic `motion_graphics` shot, four `animated_still` shots, and one deterministic `title_card` shot.

An offline full-pipeline acceptance run using the bounded fake Persona provider reached `AWAITING_EXECUTION_APPROVAL` with screenplay title `Full Auto`, runtime `30.0`, eight shots, and only the then-specified Japanese lines in the audio script. The complete repository suite passed 140 tests at the time, including default-template regression, Persona runtime, schema audit, Full Auto scenario, Shot/Storyboard, and zero-Runway previsualization.

Adding the structured block changes the Creative Brief hash to `sha256:89d65440db009d4d35a93cbae4e07f4deb196a06fe5f195ee30751b79651eb2d`; the sealed scenario hash is `sha256:47813cfca5e6ea3b36c1e6d1544042e49b356344db5fd934cffd102dcfceead2`. Build `20260722-006` and approval binding `PAB-bdc1d736a16616312d18` remain valid historical evidence for the earlier Brief, but cannot authorize the modified Brief. A new live Persona Council and human approval are therefore required before paid storyboard previsualization. No additional paid API call was made during this implementation continuation.
