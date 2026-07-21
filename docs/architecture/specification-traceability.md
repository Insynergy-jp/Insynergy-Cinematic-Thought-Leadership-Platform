# Specification Traceability

この文書はMaster Specification v2.1の9 PartとPlatform v3.0参照実装の対応表です。仕様書本文が規範であり、この表は実装上の入口を示します。

| Part | 実装 | 主な強制条件 |
| --- | --- | --- |
| 1 Vision / Architecture | `orchestrator.py`, `models.py`, `storage.py`, `agent_review.py` | 単方向パイプライン、任意のread-only Agent Review、唯一のrender fork、FFmpeg convergence、計画と高コスト実行の承認分離、不変Artifact |
| 2 Story Engine | `story.py` | 単一Premise/Theme/Protagonist/Conflict/Question、定量Stakes、三幕、感情進行、Concept ratio、決定論 |
| 3 Screenplay Engine | `screenplay.py` | Story-only入力、1 scene/1 purpose/1 conflict、observable action、Act 3 concept、Fountain/JSON、continuity |
| 4 Shot Planner / Storyboard | `shot_planner.py` | 厳密なShot順序、Camera/Blocking、Character/Location/Time continuity、Hybrid routing、Shot/Storyboard gates |
| 5 Rendering / Runway | `rendering.py`, `prompt.py`, `providers/`, `media.py` | facade、provider contract、Runway API `2024-11-06` containment、Task API、client-side replay protection、1 task/shot、signed-output保存、exact cache、prompt provenance、technical/quality validation |
| 6 Performance / Orchestration | `orchestrator.py`, `storage.py`, `rendering.py`, `providers/openai_agents.py` | CAS、single-flight exact review cache、bounded model turn/input/output/timeout、Manifest authority、explicit state、resume/idempotency、budget preflight |
| 7 Quality Gates | `quality.py`, `agent_review.py`および各Engineのreport | blocking、fail closed、8 review dimensions、evidence resolution、理由付き人間例外、0.90 render threshold、human authority |
| 8 GitHub Actions | `.github/workflows/`, `.github/actions/` | secret-free plan、`planning-ai` Agent Review、`render-approval` execution、`publication-approval`、least privilege、pinned actions、artifact handoff |
| 9 JSON Schema | `schemas.py`, `schemas/` | Draft 2020-12、v2.0互換56 schema、v2.1 Agent Review 2 schema、strict envelope、provenance、registry |

## Layer adjacency

```text
Article Loader
  -> Story Engine
  -> Screenplay Engine
  -> Shot Planner / Storyboard
  -> Agent Review (optional, read-only evidence)
  -> Render Strategy
       -> Local deterministic assets
       -> Runway adapter
  -> FFmpeg Composer
  -> Quality Gates
  -> Human Publish Approval
  -> Publish Package
```

非隣接レイヤーの直接呼び出しはありません。ScreenplayはArticleを受け取らず、PromptはStoryboard Frameを受け取り、Providerは組み立て済みPromptだけを受け取ります。

## State ownership

`BuildRepository` がBuild stateとManifest versionの唯一の書き込み所有者です。`RenderingPlatform`はRender結果を返し、Build stateを変更しません。QueueまたはCacheはauthoritative stateではありません。

```text
CREATED -> PLANNING -> PLANNED -> [optional Agent Review] -> AWAITING_EXECUTION_APPROVAL
        -> EXECUTING -> COMPOSING -> VALIDATING -> READY
        -> AWAITING_PUBLISH_APPROVAL -> PUBLISHED
```

違法遷移は `STATE_CONFLICT` で拒否されます。`PAUSED`、`CANCELLED`、`FAILED` も明示状態です。

## Acceptance evidence

`tests/` がローカル受け入れ証拠です。CIはcompile、unit/integration、schema再生成差分を確認します。実Runway sandbox、長時間soak、実運用負荷、GitHub Environment保護設定は外部環境を必要とするため、コード外の運用受け入れ項目です。
