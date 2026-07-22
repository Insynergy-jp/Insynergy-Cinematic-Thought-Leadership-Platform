# Specification Traceability

この文書はMaster Specification v2.1の9 PartとPlatform v3.4.0参照実装の対応表です。仕様書本文が規範であり、この表は実装上の入口を示します。

## Platform v3.4.0 implementation status

Parts 1–9のv3.4.0 Amendmentに対し、GPT-5.6のclosed structured output、Responses API `image_generation`、hash検証付き完全一致Plan/Frame Cache、provider-free budget preflight、watermark付きFFmpeg Animatic、独立したPreview Quality／Human Approval、実GitHub Environment Reviewer login/IDとmain限定policy binding、Runway Provider初期化前の再検証、6つのv3.4 schemaを実装しています。通常CIはfake providerで134 testsを実行し、実OpenAI／Runway費用は発生させません。bounded live OpenAI評価は外部運用acceptanceとして残します。

```text
v3.4 implemented path:
Screenplay -> GPT-5.6 Storyboard/Shot/Prompt plan
           -> GPT Image still frames
           -> FFmpeg storyboard animatic
           -> storyboard-preview-approval
           -> render-approval
           -> Runway
```

| Part | 実装 | 主な強制条件 |
| --- | --- | --- |
| 1 Vision / Architecture | `architecture.py`, `orchestrator.py`, `previsualization.py`, `persona.py`, `outcomes.py`, `models.py`, `storage.py` | 実行可能Architecture、Provider隔離、有限Persona Council、zero-Runway Preview境界、Preview／execution／publicationの段階承認、不変Artifact、長期視聴者理解・想起Dashboard |
| 2 Story Engine | `story.py` | 単一Premise/Theme/Protagonist/Question、三層Conflict、定量・不可逆Stakes、Time Pressure、6段Arc、時間配分付き三幕、因果的感情進行、Concept ratio、決定論Cache、Persona lineage |
| 3 Screenplay Engine | `screenplay.py` | Story-only入力、1 scene/1 purpose/1 conflict、observable action、Act 3 concept、Fountain/JSON、continuity |
| 4 Shot Planner / Storyboard | `shot_planner.py`, `previsualization.py` | 厳密なShot順序、Camera/Blocking、Character/Location/Time continuity、Image/Video Prompt分離、per-shot review dimensions、Shot/Storyboard/Preview gates |
| 5 Rendering / Runway | `rendering.py`, `prompt.py`, `previsualization.py`, `providers/`, `media.py` | zero-Runway admission、OpenAI planning/imageとVideoProviderの分離、Runway API containment、Task API、replay protection、exact cache、prompt provenance、technical/quality validation |
| 6 Performance / Orchestration | `orchestrator.py`, `previsualization.py`, `runtime.py`, `storage.py`, `rendering.py` | Plan/Frame cache、画像・費用preflight、CAS、Manifest history、durable Queue、Checkpoints、Recovery Plan、hash-chained Events、provider-secret-free recomposition、resume/idempotency |
| 7 Quality Gates | `quality.py`, `previsualization.py`, `storage.py`, `agent_review.py`および各Engineのreport | Preview deterministic/advisory分離、zero Runway counters、watermark／非公開性、必須Floor、Evidence binding、CAS Report、approval audit、human authority |
| 8 GitHub Actions | `.github/workflows/preview.yml`, `.github/workflows/`, `.github/actions/`, `github_actions.py`, `tools/validate_workflows.py` | `planning-ai`隔離、provider-secret-free FFmpeg再合成、secretless `storyboard-preview-approval`、実Reviewer解決、独立render/publication承認、改ざん検知handoff、Secret scan |
| 9 JSON Schema | `schemas.py`, `schema_validation.py`, `schemas/` | Draft 2020-12、既存baseline byte互換、v3.3 Persona 6 schema、v3.4 Preview 6 schema、closed contracts、owned/versioned registry、参照・fixity監査、stable error codes |

## Layer adjacency

```text
Article Loader
  -> Story Engine
  -> Screenplay Engine
  -> Shot Planner / Storyboard
  -> Planning Quality Gates
  -> Agent Review (optional, read-only evidence)
  -> Storyboard Previsualization (optional, zero Runway)
  -> Storyboard Preview Human Approval (required when enabled)
  -> Human Execution Approval
  -> Render Strategy
       -> Local deterministic assets
       -> Runway adapter
  -> FFmpeg Composer
  -> Quality Gates
  -> Human Final / Publish Approval
  -> Publish Package
```

非隣接レイヤーの直接呼び出しはありません。ScreenplayはArticleを受け取らず、PromptはStoryboard Frameを受け取り、Providerは組み立て済みPromptだけを受け取ります。

## State ownership

`BuildRepository` がBuild stateとManifest versionの唯一の書き込み所有者です。`RenderingPlatform`はRender結果を返し、Build stateを変更しません。QueueまたはCacheはauthoritative stateではありません。

```text
CREATED -> [optional PERSONA_PLANNING -> AWAITING_PERSONA_APPROVAL]
        -> PLANNING -> PLANNED -> [optional Agent Review]
        -> [optional Previsualization -> AWAITING_STORYBOARD_PREVIEW_APPROVAL]
        -> AWAITING_EXECUTION_APPROVAL
        -> EXECUTING -> COMPOSING -> VALIDATING -> READY
        -> AWAITING_PUBLISH_APPROVAL -> PUBLISHED
```

違法遷移は `STATE_CONFLICT` で拒否されます。`PAUSED`、`CANCELLED`、`FAILED` も明示状態です。

## Acceptance evidence

`tests/` がローカル受け入れ証拠です。CIはcompile、134 unit/integration tests、schema再生成差分、Architecture／Schema／Workflow監査を確認します。実OpenAI preview、実Runway sandbox、長時間soak、実運用負荷、GitHub Environment保護設定は外部環境を必要とするため、コード外の運用受け入れ項目です。

## Part 1 coverage

Part 1は20能力クラスター中、20 Full、0 Partial、0 Missingです。**20/20 = 100.0%** です。95%目標を超え、有限Persona Councilと長期視聴者評価Dashboardを実行可能証拠として含みます。

## Part 2 coverage

Part 2は20能力クラスター中、19 Full、1 Partial、0 Missingです。**19.5/20 = 97.5%** です。Dashboardは長期Outcomeと中核Story指標を提供し、全KSIの個別時系列はPartialとして残します。

## Part 3 coverage

Part 3は20能力クラスター中、18 Full、2 Partial、0 Missingです。**19/20 = 95.0%** です。Persona runtimeはFull、専用Screenplay承認と全lifecycle timing系列をPartialとして残します。

## Part 6 coverage

Part 6は21能力クラスター中、15 Full、4 Partial、2 Missingです。`Full=1 / Partial=0.5 / Missing=0`で **17/21 = 81.0%** です。機械可読な評価は `part6-coverage` CLI、詳細は [Part 6 Implementation Coverage](part6-coverage.md) を参照してください。未実装として汎用Compensation/Rollback Engineと段階的Production Transitionを明示的に残しています。

## Part 7 coverage

Part 7は20能力クラスター中、19 Full、1 Partial、0 Missingです。**19.5/20 = 97.5%** です。Persona Quality Gateと長期Outcome DashboardをFull、実Provider・代表編集評価をPartialとしています。

## Part 8 coverage

Part 8は20能力クラスター中、18 Full、2 Partial、0 Missingです。**19/20 = 95.0%** です。Persona Council WorkflowはFull、実Repository保護設定と外部InfrastructureはPartialです。

## Part 9 coverage

Part 9は20能力クラスター中、17 Full、2 Partial、1 Missingです。同じ評価式で **18/20 = 90.0%** です。機械可読な評価は `part9-coverage` CLI、詳細は [Part 9 Implementation Coverage](part9-coverage.md) を参照してください。全旧成果物を横断する汎用semantic validatorと外部consumer互換試験はPartial、canonical `$id`での公開配信サービスはMissingとして残しています。
