# Specification Traceability

この文書はMaster Specification v2.0の9 Partと参照実装の対応表です。仕様書本文が規範であり、この表は実装上の入口を示します。

| Part | 実装 | 主な強制条件 |
| --- | --- | --- |
| 1 Vision / Architecture | `orchestrator.py`, `models.py`, `storage.py` | 単方向パイプライン、唯一のrender fork、FFmpeg convergence、計画と高コスト実行の承認分離、不変Artifact |
| 2 Story Engine | `story.py` | 単一Premise/Theme/Protagonist/Conflict/Question、定量Stakes、三幕、感情進行、Concept ratio、決定論 |
| 3 Screenplay Engine | `screenplay.py` | Story-only入力、1 scene/1 purpose/1 conflict、observable action、Act 3 concept、Fountain/JSON、continuity |
| 4 Shot Planner / Storyboard | `shot_planner.py` | 厳密なShot順序、Camera/Blocking、Character/Location/Time continuity、Hybrid routing、Shot/Storyboard gates |
| 5 Rendering / Runway | `rendering.py`, `prompt.py`, `providers/`, `media.py` | facade、provider contract、Runway containment、async-shaped job contract、1 task/shot、exact cache、prompt provenance、technical/quality validation |
| 6 Performance / Orchestration | `orchestrator.py`, `storage.py`, `rendering.py` | CAS、incremental build、bounded parallelism、Manifest authority、explicit state、resume/idempotency、budget preflight |
| 7 Quality Gates | `quality.py`および各Engineのreport | blocking、fail closed、0.90 render threshold、creative/composition/package gates、human authority |
| 8 GitHub Actions | `.github/workflows/`, `.github/actions/` | PR CI、planning、environment approval、execution、publication、least privilege、pinned actions、artifact handoff |
| 9 JSON Schema | `schemas.py`, `schemas/` | Draft 2020-12、共通定義、全canonical schema name、strict envelope、provenance、registry |

## Layer adjacency

```text
Article Loader
  -> Story Engine
  -> Screenplay Engine
  -> Shot Planner / Storyboard
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
CREATED -> PLANNING -> PLANNED -> AWAITING_EXECUTION_APPROVAL
        -> EXECUTING -> COMPOSING -> VALIDATING -> READY
        -> AWAITING_PUBLISH_APPROVAL -> PUBLISHED
```

違法遷移は `STATE_CONFLICT` で拒否されます。`PAUSED`、`CANCELLED`、`FAILED` も明示状態です。

## Acceptance evidence

`tests/` がローカル受け入れ証拠です。CIはcompile、unit/integration、schema再生成差分を確認します。実Runway sandbox、長時間soak、実運用負荷、GitHub Environment保護設定は外部環境を必要とするため、コード外の運用受け入れ項目です。

