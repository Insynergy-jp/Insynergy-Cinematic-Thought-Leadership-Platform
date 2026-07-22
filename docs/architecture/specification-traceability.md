# Specification Traceability

この文書はMaster Specification v2.1の9 PartとPlatform v3.3.0参照実装の対応表です。仕様書本文が規範であり、この表は実装上の入口を示します。

| Part | 実装 | 主な強制条件 |
| --- | --- | --- |
| 1 Vision / Architecture | `architecture.py`, `orchestrator.py`, `persona.py`, `outcomes.py`, `models.py`, `storage.py` | 実行可能Architecture、Provider隔離、有限Persona Council、唯一のrender fork、段階承認、不変Artifact、長期視聴者理解・想起Dashboard |
| 2 Story Engine | `story.py` | 単一Premise/Theme/Protagonist/Question、三層Conflict、定量・不可逆Stakes、Time Pressure、6段Arc、時間配分付き三幕、因果的感情進行、Concept ratio、決定論Cache、Persona lineage |
| 3 Screenplay Engine | `screenplay.py` | Story-only入力、1 scene/1 purpose/1 conflict、observable action、Act 3 concept、Fountain/JSON、continuity |
| 4 Shot Planner / Storyboard | `shot_planner.py` | 厳密なShot順序、Camera/Blocking、Character/Location/Time continuity、Hybrid routing、Shot/Storyboard gates |
| 5 Rendering / Runway | `rendering.py`, `prompt.py`, `providers/`, `media.py` | facade、provider contract、Runway API `2024-11-06` containment、Task API、client-side replay protection、1 task/shot、signed-output保存、exact cache、prompt provenance、technical/quality validation |
| 6 Performance / Orchestration | `orchestrator.py`, `runtime.py`, `storage.py`, `rendering.py`, `providers/openai_agents.py` | Performance Plan artifacts、CAS、Manifest CAS/history、durable Queue、generation-fenced leases、content-addressed Checkpoints、Recovery Plan、hash-chained Events、Backpressure、durable API operations、resume/idempotency、budget preflight |
| 7 Quality Gates | `quality.py`, `storage.py`, `agent_review.py`および各Engineのreport | 共通Gate/Check契約、必須Floor、非迂回Chain、固定Lifecycle、Evidence binding、CAS Report、Stage/Cross-stage Gate、Build Quality Report、理由付き人間例外、approval audit、human authority |
| 8 GitHub Actions | `.github/workflows/`, `.github/actions/`, `github_actions.py`, `tools/validate_workflows.py` | `planning-ai` Persona/Review隔離、secretless Persona quality、`persona-approval`、独立render/publication承認、least privilege、改ざん検知handoff、Secret scan |
| 9 JSON Schema | `schemas.py`, `schema_validation.py`, `schemas/` | Draft 2020-12、v2.0/v2.1 byte-compatibility baseline、v3.3 Persona Council 6 schema、strict envelope、provenance、owned/versioned registry、参照・fixity監査、stable error codes |

## Layer adjacency

```text
Article Loader
  -> Story Engine
  -> Screenplay Engine
  -> Shot Planner / Storyboard
  -> Planning Quality Gates
  -> Agent Review (optional, read-only evidence)
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
        -> PLANNING -> PLANNED -> [optional Agent Review] -> AWAITING_EXECUTION_APPROVAL
        -> EXECUTING -> COMPOSING -> VALIDATING -> READY
        -> AWAITING_PUBLISH_APPROVAL -> PUBLISHED
```

違法遷移は `STATE_CONFLICT` で拒否されます。`PAUSED`、`CANCELLED`、`FAILED` も明示状態です。

## Acceptance evidence

`tests/` がローカル受け入れ証拠です。CIはcompile、unit/integration、schema再生成差分を確認します。実Runway sandbox、長時間soak、実運用負荷、GitHub Environment保護設定は外部環境を必要とするため、コード外の運用受け入れ項目です。

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
