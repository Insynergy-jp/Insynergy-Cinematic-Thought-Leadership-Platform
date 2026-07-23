# Insynergy Cinematic Thought Leadership Platform

Master Specification v2.1 の9文書を実行可能なPlatform v3.4.0として実装した、決定論的な映像ビルド・プラットフォームです。Markdown記事を、任意のPersona Council、Story、Screenplay、Shot/Storyboard、任意のAgent Review、GPT-5.6／GPT Image／FFmpegによるzero-Runway Storyboard Preview、ハイブリッド・レンダー、品質ゲート、段階的な人間承認、公開パッケージへ変換します。

## 実装されているもの

- Part 1のProduct／Objective／Layer／Flow／Governance／Authorityを一つに束ねた実行可能Architecture Contract。20項目のfail-closed検査、Provider隔離監査、Buildごとの不変な検証証拠
- 記事の構造化、主張分類、単一テーマ・単一主人公・単一葛藤・単一ドラマティッククエスチョンの生成
- 三層Conflict、構造化された不可逆Stakes、観客に見えるTime Pressure、6段Story Arc、時間配分付き三幕、因果的Emotionを強制するStory Engine v3.3契約
- 三幕構成、感情アーク、Act 3に限定したコンセプト配置
- Story成果物のみを入力にするScreenplay EngineとFountain出力
- 8 scene／三幕、4–10秒、単一purpose/conflict、緊張台詞、明示的silence、7次元continuityをfail-closedで強制するScreenplay Engine v3.3契約
- Council承認済みCreative Brief内の`creative-scenario` JSONを、Brief hashに結び付けたStory成果物としてScreenplay／Shot／Storyboardへ伝播する任意経路。既定テンプレートは維持し、authored経路だけ3–10秒のsceneと小数秒を許可
- 連続性を保持したShot List、Camera Plan、Blocking、Storyboard
- Runway Video、Animated Still、Motion Graphics、Typographyを使う決定論的なハイブリッド戦略
- Storyboardだけを入力にするPrompt Assembly
- 完全一致キーによるCAS／Render Cache。キャッシュヒット時はQueueとProviderを迂回
- `VideoProvider`契約、オフライン用ローカルFFmpegプロバイダー、Runway HTTPアダプター
- 並列ショット実行、技術検証、0.90のレンダー品質ゲート、fail-closed集約
- FFmpeg合成、最終動画検証、再現可能ZIPパッケージ
- OpenAI Speech APIによる本番ナレーション、YouTube向け1080p mastering、SRT字幕、AI音声開示
- `hybrid`または全8ショットを生成する`all_shots` Runway scope、480-credit上限、実秒数ベースの費用見積り
- 不変Artifact Envelope、SHA-256 provenance、明示状態遷移、append-onlyイベント
- 実行前承認と公開前承認。承認対象ハッシュが変わると承認は無効
- OpenAI Agents SDKによるread-only `Agent Review Mode`。1 Agent、1 turn、tools/handoffsなし、8観点のtyped review、厳密な証拠参照、完全一致キャッシュ
- Agent Review ReportとExecution Planのhash pairを人間承認に封印。非PASSは理由付き例外承認が必要で、構造・証拠・ハッシュ不備は例外不可
- OpenAI Agents SDKのmanager-owned agents-as-toolsによるPersona Council。3提案、1 Red-Team、1 Managerに固定し、Persona Quality Gateと人間承認前はStoryを開始しない
- HMAC仮名化した視聴者評価の追記専用hash-chain、理解・7日以降の自由想起・reaction subject・accuracyを集計するHTML/JSON運用ダッシュボード
- CLI、`/api/v2` HTTP JSON API、Part 9の全スキーマ名を含むSchema Registry
- GitHub ActionsによるCI、計画、承認後実行、公開の分離ワークフロー
- GPT-5.6の構造化Previsualization、Responses APIの画像生成tool、完全一致Cache、`NOT FINAL`入りFFmpeg Animatic、Preview Quality Gate、実GitHub Environment Reviewerに結び付けた`storyboard-preview-approval`
- `storyboard_animatic`有効時はPreview承認と独立したexecution/render承認の両方をhash検証し、いずれかが欠ける・古い・改ざん済みならRunway Provider初期化前にfail closed

## Platform v3.3.0 — Persona Council

Persona Councilは、Insight記事と明示的なCreative Briefから、30秒の物語を担える一人の主人公ペルソナを作る上流工程です。自由形式のAgent会話ではなく、Persona Managerが4つの専門Agentを限定されたtoolsとして呼び出し、有限の審議を管理します。

```text
Article + Creative Brief
  -> Audience Researcher / Empathy and Narrative Analyst / Brand Strategist
  -> Red-Team Critic
  -> Persona Manager
  -> deterministic Persona Quality Gate
  -> human Persona Approval
  -> Story Engine
```

- 提案Agentは3役・各1回、Red-Teamは1回、Manager統合は1回に固定
- handoff、再帰的議論、外部tools、レンダー、承認、公開権限を禁止
- 根拠のない属性、架空の発言、病歴・トラウマ・病室などの感情的ショートカットを拒否
- 各設定をArticle／Creative Briefの根拠または明示的なAssumptionとして記録
- `persona.json`とQuality Reportを人間が承認するまでStory Engineを停止
- Agent Review Modeは従来どおり単一Agent・read-onlyの独立した後段レビューとして維持
- Persona Councilのコストはplanning AI予算として管理し、Runway creditやrender retryには影響させない

v3.3.0の規範成果物は次の6つです。

```text
persona-proposals.json
persona-red-team-report.json
persona-deliberation.json
persona.json
persona-quality-report.json
persona-approval-binding.json
```

`persona-deliberation.json`には構造化された判断・異論・解決だけを保存し、chain-of-thoughtや無制限の会話ログは保存しません。GitHub Actionsでは`planning-ai` EnvironmentでAgentを実行し、新設するsecretlessな`persona-approval` EnvironmentでStory生成前の人間承認を行う仕様です。承認jobはGitHub review historyから実Reviewerを解決し、Workflow initiatorとEnvironment reviewerを別フィールドで記録します。reviewer不明、承認履歴の曖昧性、Required reviewer以外の承認はfail-closedです。自己承認の可否はGitHub Environmentの`prevent_self_review`実設定へ追従し、設定自体もhash-boundします。

### Authored Creative Scenario

Creative Briefが厳密なシーン設計を必要とする場合は、Brief本文に一つだけ`creative-scenario` JSON fenceを含められます。この経路は`persona-mode=council`かつ`preview`／`final` profileでのみ有効です。JSONは8シーン、三幕、3–10秒の各尺、宣言した合計尺、発話上限、感情連続性、減少するcountdown、camera、render strategy、UI後処理文字列を入力時に検証します。

抽出後の`creative_scenario` artifactは元のCreative Brief hashを保持します。Story cache、Screenplay cache、品質ゲート、Shot、Storyboardにもscenario hashを伝播するため、Briefを一文字でも変更すると既存Persona承認と下流計画は再利用されません。fenceがないCreative Briefと`persona-mode=off`の既定経路は従来どおり4–10秒の決定論テンプレートを使います。

````markdown
```creative-scenario
{
  "schema_version": "creative-scenario/1",
  "title": "Example",
  "duration_seconds": 30.0,
  "language": "ja",
  "spoken_line_limit": 1,
  "scenes": [
    "... exactly eight validated scene objects ..."
  ]
}
```
````

公式設計根拠：OpenAI Agents SDKの[Orchestration and handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration)、[Agent definitions](https://developers.openai.com/api/docs/guides/agents/define-agents)、[Guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)、[Integrations and observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability)。

| 区分 | バージョン | 状態 |
| --- | --- | --- |
| 現行ランタイム | 3.4.0 | 実装済み（ライブOpenAI評価は明示実行） |
| Persona Council | 3.3.0 | ライブ実行、品質、承認、Actions経路を実装済み |
| Viewer Outcomes Dashboard | 3.3.0 | 追記保存、長期想起判定、HTML/JSONを実装済み |
| Zero-Runway Storyboard Preview | 3.4.0 | CLI、HTTP API、6 Schema、Quality Gate、Cache、FFmpeg、Actions承認経路を実装済み |

## Platform v3.4.0 — Zero-Runway Storyboard Preview

Runway APIを呼び出す前に、**シーン構成、演出、カメラワーク、ナレーション、テンポ**を人が確認する機能です。Runwayで低品質Previewを生成するのではなく、GPT-5.6の構造化Previsualization、GPT Imageの静止画、FFmpegのAnimaticを使い、Runway request・task・attempt・creditがすべてゼロの状態で計画をレビューします。

```text
Insight Article
  -> approved Story
  -> approved Screenplay (canonical Script)
  -> GPT-5.6 Storyboard / Shot / Camera / Narration / Tempo plan
  -> Image Prompt Set + sealed Video Prompt Set
  -> GPT Image Storyboard frames
  -> FFmpeg storyboard-preview.mp4 + storyboard-review.html
  -> Storyboard Preview Quality Gate
  -> human storyboard-preview-approval
  -> independent render-approval
  -> Runway
  -> final MP4
```

責務の境界は次のとおりです。

| 処理 | 担当 | 境界 |
| --- | --- | --- |
| Scene分割、演出、Camera intent、Narration、Tempo、Storyboard、Shot List、Image/Video Prompt、品質評価 | `gpt-5.6-sol`を既定候補とするGPT-5.6 Previsualization | 型付き提案を生成する。決定論的Validatorと人間承認を上書きしない。 |
| Storyboard静止画 | Responses APIの`image_generation` tool／GPT Image | GPT-5.6がtoolを統括するが、画像pixelを生成するのはGPT Image model。OpenAI画像費用は発生する。 |
| Preview MP4 | FFmpeg | 静止画、字幕、仮Narration、正確な尺をAnimatic化する。生成Motion videoではない。 |
| Video Promptから最終MP4 | Runway `VideoProvider` | GPT-5.6では代替しない。Soraを採用する場合も別のVideo provider／ADR／予算／承認が必要。 |

ReviewerはShotごとに次を確認します。

- Scene purpose、Dramatic beat、Shot coverage、順序、尺
- 目に見えるAction、Blocking、Performance intent、Transition
- Shot size、Angle、Lens intent、Camera position、Movement intent、Composition
- Narration本文、Lineage、Timecode、Silence、Caption／仮音声
- Shot duration、累積Runtime、Cut rhythm、Tempo class
- Storyboard frame、Image Prompt、まだ実行を許可されていないVideo Prompt
- 決定論的FindingとGPT-5.6の助言Finding、OpenAI Preview費用、Runway credit `0`

Animaticは構成、意図したCamera work、Narration、Shot order、Tempoの確認に使えます。一方、実際のMotion fidelity、Shot内の時間的一貫性、Lip sync、Actor performance、Physics、Video artifact、最終Photorealismは証明できません。Previewには`STORYBOARD PREVIEW — NOT FINAL`を表示し、公開やFinal Render Cacheへの昇格を禁止します。

v3.4.0では次の6 Artifact Schemaを追加し、`schemas/`、package data、Schema Registryへ同梱しています。

```text
previsualization-plan.json
image-prompt-set.json
video-prompt-set.json
storyboard-preview-manifest.json
storyboard-preview-quality-report.json
storyboard-preview-approval-binding.json
```

`storyboard-preview-approval`はsecretlessなGitHub Environmentとして、Creative intentと完全一致のPreview bundleを承認します。既存`render-approval`はProvider実行計画と費用を承認します。両方が有効になるまでRunway clientを初期化しません。既存の`runway_preview`は、必要な場合だけStoryboard approval後に行う任意のMotion Previewとして扱います。

このモデル／ツール境界は、OpenAI公式の[Using GPT-5.6](https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6)、[Image generation](https://developers.openai.com/api/docs/guides/image-generation)、[Video generation with Sora](https://developers.openai.com/api/docs/guides/video-generation)に合わせています。詳細な規範契約は[Vision / Architecture](1.%20Vision_Architecture.md)、[Shot Planner / Storyboard](4.Short%20Planner_Story%20Board..md)、[Rendering / Runway](5.Rendering%20Platform%20%26%20Runway%20Integration.md)、[Acceptance Criteria](9.Acceptance%20Criteria.md)を参照してください。

> **実装状態:** 非課金のfake-provider受け入れ試験と全静的監査は実装済みです。実OpenAI呼び出しは費用を伴うため通常CIでは行わず、`planning-ai` Environmentから明示実行します。

## 必要環境

- Python 3.11以上（`off` モードは外部Pythonパッケージなし）
- FFmpeg / FFprobe

Agent Reviewを実行する場合だけ、OpenAI Agents SDKを追加します。

```bash
python3 -m pip install -e '.[agent-review]'
```

Storyboard Previewを実行する場合はResponses API adapterを追加します。

```bash
python3 -m pip install -e '.[previsualization]'
```

macOS Homebrewでは `brew install ffmpeg`、Ubuntuでは `apt-get install ffmpeg` で用意できます。

## クイックスタート

リポジトリ直下で次を実行します。

```bash
PYTHONPATH=src python3 -m insynergy_cinematic health
PYTHONPATH=src python3 -m insynergy_cinematic plan examples/decision-boundary.md
```

`plan` は `AWAITING_EXECUTION_APPROVAL` で停止し、JSONに `build_id` を返します。高コスト領域へ進むには、明示的な承認が必要です。本番ナレーションでは、計画と実行の両方で`--profile final --narration-provider openai`を指定します。全ショットをGen-4.5で生成する場合は`--provider runway --runway-scope all_shots`も指定します。

zero-Runway Storyboard Previewを有効にすると、`plan`は`PLANNED`で停止します。`previsualize`がGPT-5.6計画、GPT Image frame、FFmpeg Animatic、review HTML、Quality Reportを生成し、`AWAITING_STORYBOARD_PREVIEW_APPROVAL`へ進めます。Preview承認後もexecution承認は別に必要です。すべてのコマンドで同じmodeを指定してください。

```bash
PYTHONPATH=src python3 -m insynergy_cinematic \
  --pre-render-preview-mode storyboard_animatic \
  plan examples/decision-boundary.md
PYTHONPATH=src python3 -m insynergy_cinematic \
  --pre-render-preview-mode storyboard_animatic \
  preview-preflight BUILD_ID
export OPENAI_API_KEY='...'
PYTHONPATH=src python3 -m insynergy_cinematic \
  --pre-render-preview-mode storyboard_animatic \
  previsualize BUILD_ID
open .insynergy/builds/BUILD_ID/previsualization/storyboard-review.html
PYTHONPATH=src python3 -m insynergy_cinematic \
  --pre-render-preview-mode storyboard_animatic \
  approve BUILD_ID --gate storyboard-preview --actor "Ryoji Morii"
PYTHONPATH=src python3 -m insynergy_cinematic \
  --pre-render-preview-mode storyboard_animatic \
  approve BUILD_ID --gate execution --actor "Ryoji Morii"
PYTHONPATH=src python3 -m insynergy_cinematic \
  --pre-render-preview-mode storyboard_animatic execute BUILD_ID
```

既定上限は12画像、最大10 USD（既定の事前見積り5 USD）です。`preview-preflight`はOpenAI／RunwayのcredentialなしでPlanning hash、Shot数、画像上限、費用上限を検証します。Shot数または費用が上限を超える場合はOpenAI Providerを生成する前に拒否します。生成画像と計画は完全一致keyで再利用し、Preview成果物は`non_publishable=true`、`final_cache_eligible=false`です。

Persona Councilを使う場合は、Creative Briefを指定します。初回`plan`は`AWAITING_PERSONA_APPROVAL`で停止し、承認後に同じ入力で`plan`を再実行するとStory以降へ進みます。

```bash
export OPENAI_API_KEY='...'
PYTHONPATH=src python3 -m insynergy_cinematic --persona-mode council \
  plan examples/decision-boundary.md --creative-brief path/to/creative-brief.md
PYTHONPATH=src python3 -m insynergy_cinematic --persona-mode council \
  approve BUILD_ID --gate persona --actor "Ryoji Morii"
PYTHONPATH=src python3 -m insynergy_cinematic --persona-mode council \
  plan examples/decision-boundary.md --creative-brief path/to/creative-brief.md
```

```bash
PYTHONPATH=src python3 -m insynergy_cinematic approve BUILD_ID --gate execution --actor "Ryoji Morii"
PYTHONPATH=src python3 -m insynergy_cinematic execute BUILD_ID
PYTHONPATH=src python3 -m insynergy_cinematic approve BUILD_ID --gate publish --actor "Ryoji Morii"
PYTHONPATH=src python3 -m insynergy_cinematic publish BUILD_ID
```

ローカル検証だけで承認も含めて一度に実行する場合は、監査主体を明記します。

```bash
PYTHONPATH=src python3 -m insynergy_cinematic build examples/decision-boundary.md \
  --auto-approve --actor "local-evaluation"
```

生成物は `.insynergy/builds/<build_id>/` に置かれます。

```text
.insynergy/
├── builds/<build_id>/
│   ├── manifest.json
│   ├── artifacts/
│   ├── previsualization/
│   │   ├── frames/
│   │   ├── storyboard-preview.mp4
│   │   └── storyboard-review.html
│   ├── output/master.mp4
│   └── package/<build_id>.zip
├── cas/
├── outcomes/
│   ├── evaluations/
│   ├── ledger.json
│   ├── dashboard.html
│   └── dashboard.json
├── render-cache/
└── providers/
```

`.insynergy/` はランタイム状態なのでGit管理対象外です。

## Agent Review Mode

`off` が既定で、従来の決定論的な計画経路を維持します。`review` では `plan` が `PLANNED` で停止し、独立した `agent-review` コマンドが封印済み計画だけを読み取ってレポートを生成します。Agentは計画を変更せず、レンダー・承認・公開の権限も持ちません。

```bash
export OPENAI_API_KEY='...'
export OPENAI_MODEL_REVIEW='gpt-5.6-sol'
export OPENAI_REASONING_EFFORT='medium'
export OPENAI_TRACE_MODE='disabled'

PYTHONPATH=src python3 -m insynergy_cinematic \
  --agent-review-mode review plan examples/decision-boundary.md
PYTHONPATH=src python3 -m insynergy_cinematic \
  --agent-review-mode review agent-review BUILD_ID
```

`PASS` は通常のexecution承認へ進みます。`MANUAL_REVIEW_REQUIRED`、`UNAVAILABLE`、`ERROR` を承認する場合は、GitHub Environmentの承認に加えて理由を監査記録へ明示します。

```bash
PYTHONPATH=src python3 -m insynergy_cinematic approve BUILD_ID \
  --gate execution --actor "Ryoji Morii" \
  --allow-agent-exception \
  --agent-exception-reason "Evidence owner confirmed the intended interpretation."
```

SDK tracingは既定で無効です。`metadata` を選んだ場合も、入力本文・モデル出力・資格情報をtraceへ含めません。APIキー、prompt本文、raw response、chain-of-thoughtはManifestとイベントへ保存されません。

## CLI

```text
plan ARTICLE                         計画成果物を生成し、品質ゲートを評価
agent-review BUILD_ID                封印済み計画をread-onlyでレビュー
preview-preflight BUILD_ID           credentialなしで画像・費用budgetを事前検証
previsualize BUILD_ID                GPT計画・静止画・FFmpeg AnimaticをRunwayなしで生成
recompose-preview BUILD_ID           provider secretなしでAnimaticを再合成・hash検証
approve BUILD_ID --gate GATE        persona / storyboard-preview / execution / publish承認を記録
record-viewer-outcome BUILD_ID       理解・想起・reaction・accuracy評価を追記
outcomes-dashboard                   長期視聴者評価のHTML/JSONを生成
execute BUILD_ID                    承認済み計画をレンダー・合成・検証
publish BUILD_ID                    公開承認済みマスターをパッケージ化
build ARTICLE [--auto-approve]      エンドツーエンド実行
status BUILD_ID                     Manifest、イベント、状態を表示
list                                Build一覧
pause|resume|cancel BUILD_ID        ライフサイクル制御
health                              FFmpegなどのreadinessを表示
part1-coverage                      Part 1の実装Coverage証拠行列を表示
part2-coverage                      Part 2の実装Coverage証拠行列を表示
part3-coverage                      Part 3の実装Coverage証拠行列を表示
audit-architecture                  Part 1トポロジーとProvider隔離を監査
serve                               /api/v2を起動
export-schemas [DESTINATION]        Part 9 JSON Schemaを出力
```

共通オプションは `--workspace`、`--config`、`--profile draft|preview|final`、`--provider local|runway`、`--runway-scope hybrid|all_shots`、`--narration-provider offline|openai`、`--agent-review-mode off|review`、`--pre-render-preview-mode off|storyboard_animatic`、`--persona-mode off|council`、`--compact` です。オプションはサブコマンドより前に置きます。

視聴者IDをshell履歴へ残さない場合は標準入力を使います。成功判定は既定で理解精度`0.80`、自由想起`0.70`、視聴後`168`時間以上、5件以上を要求します。`MEDIUM`または`MIXED` reaction、accuracy失敗、誤理解、長期想起失敗はいずれも決定的な失敗です。

```bash
printf '%s\n' 'viewer@example.com' | PYTHONPATH=src python3 -m insynergy_cinematic \
  record-viewer-outcome BUILD_ID --viewer-id-stdin \
  --idea-restatement-accuracy 0.92 --unaided-recall 0.84 \
  --reaction-subject IDEA --accuracy-gate-result PASS \
  --retention-hours 168 --cohort executive-pilot \
  --idempotency-key survey-001

PYTHONPATH=src python3 -m insynergy_cinematic outcomes-dashboard --window-days 365
```

## HTTP API

```bash
PYTHONPATH=src python3 -m insynergy_cinematic serve --host 127.0.0.1 --port 8080
```

主なエンドポイントは次のとおりです。

```text
GET  /api/v2/health
GET  /api/v2/builds
POST /api/v2/builds
GET  /api/v2/builds/{build_id}
GET  /api/v2/builds/{build_id}/preview-preflight
POST /api/v2/builds/{build_id}/approve
POST /api/v2/builds/{build_id}/review
POST /api/v2/builds/{build_id}/previsualize
POST /api/v2/builds/{build_id}/execute
POST /api/v2/builds/{build_id}/publish
POST /api/v2/builds/{build_id}/pause
POST /api/v2/builds/{build_id}/resume
POST /api/v2/builds/{build_id}/cancel
POST /api/v2/outcomes
GET  /api/v2/outcomes/dashboard
```

全mutationは `Idempotency-Key` ヘッダー必須です。例:

```bash
curl -X POST http://127.0.0.1:8080/api/v2/builds \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: plan-example-001' \
  -d '{"article_path":"/absolute/path/to/article.md"}'
```

Loopback以外へbindする場合は `INSYNERGY_API_TOKEN` が必須で、全API要求（healthを除く）に `Authorization: Bearer ...` を付けます。TokenはBuild設定スナップショットにも監査Artifactにも保存されません。

## Runway

デフォルトは費用の発生しない `local` プロバイダーです。実際のRunway実行では、仕様書5.3.4の境界に従い、資格情報とRunway固有設定を環境からConfiguration Loaderだけが解決します。

v3.4.0は`storyboard_animatic`有効時、zero-Runway Preview bundleと`storyboard-preview-approval`を検証した後でなければexecution承認へ進めません。`execute`はPreview frame、Animatic、review sheet、Quality Report、実Reviewer bindingを再検証し、その後にだけRunway Providerを初期化します。`off`はv3.3互換経路です。

```bash
export INSYNERGY_RENDER_PROVIDER=runway
export RUNWAY_BASE_URL='https://api.dev.runwayml.com'
export RUNWAY_API_KEY='...'
export RUNWAY_MODEL_GEN45='gen4.5'
PYTHONPATH=src python3 -m insynergy_cinematic --provider runway execute BUILD_ID
```

アダプターはRunway API version `2024-11-06` を固定し、Gen-4.5のテキスト入力を `POST /v1/text_to_video`、画像入力を `POST /v1/image_to_video` へ送信します。状態確認とキャンセルには `/v1/tasks/{id}` を使用します。Gen-4.5の出力は署名付きURLから即時にローカル保存し、選択したプロファイルが必要とする解像度・フレームレート・音声ストリームへFFmpegで正規化します。

APIキーはManifest、Queue、Event、Artifact、署名付きアセットURLへの要求に記録・送信されません。RunwayアダプターはPromptを変更せず、物語、台詞、ペーシング、カメラ判断を行いません。Runway APIにサーバー側idempotency contractがないため、受理済みTask IDを `.insynergy/providers/runway/jobs.json` に保存して再実行時の重複課金を防ぎます。送信結果が不明なネットワークタイムアウトでは、自動再送せずfail closedします。実アカウントへの送信は費用を伴うため、ローカルテストでは実行していません。

GitHub Actionsでは、APIキーを `RUNWAY_API_KEY` という名前の `render-approval` Environment Secretとして登録します。Repository Secret、Variable、Workflow inputには置きません。

```text
Settings → Environments → render-approval → Environment secrets
RUNWAY_API_KEY = <Runway API key>
OPENAI_TTS_API_KEY = <Dedicated OpenAI Speech API project key>
```

同じEnvironmentのVariablesに `RUNWAY_BASE_URL=https://api.dev.runwayml.com` と `RUNWAY_MODEL_GEN45=gen4.5` を登録します。`Plan Article` と `Execute Approved Plan` の両方で同じProfile、Provider、Runway Scope、Narration Providerを選択してください。`all_shots`はscene-alignedな8ショットをGen-4.5へ送り、480 creditsを上限にします（既定の8×4秒計画は384 credits）。Runwayタスクは自動再生成しません。`final + openai`は1080p H.264 High、BT.709、AAC 48kHz、Fast StartのMasterに加え、`captions.en.srt`とAI音声開示文を生成します。詳しくは [GitHub Actions Runbook](docs/runbooks/github-actions.md) を参照してください。

## GitHub Planning AI設定

GitHubの `planning-ai` Environmentに次を設定します。OpenAIキーはPersona Council、Agent Review、Storyboard Preview jobだけに公開し、通常の決定論Planning、`storyboard-preview-approval`、`render-approval`、`publication-approval`には渡しません。

```text
Environment secret
OPENAI_API_KEY = <OpenAI API key>

Environment variables
OPENAI_MODEL_REVIEW = gpt-5.6-sol
OPENAI_REASONING_EFFORT = medium
OPENAI_TRACE_MODE = disabled
OPENAI_MODEL_PREVIEW = gpt-5.6-sol
OPENAI_PREVIEW_REASONING_EFFORT = medium
```

`Plan Article`で`pre_render_preview_mode=storyboard_animatic`を選び、完了後に`Storyboard Preview` workflowへPlanning Run IDとBuild IDを渡します。Workflowは最初にprotected Environmentを持たない`preflight` jobでPlanning hash、画像数、費用を検証し、成功時だけ`planning-ai` jobを開始します。Preview生成後、secretlessな`storyboard-preview-approval` Environmentが実ReviewerをDeployment review履歴から取得して完全なbundleへ結び付けます。次の`Execute Approved Plan`にはStoryboard Preview workflowのRun IDを渡します。`off`ではOpenAI Preview SDKもSecretも使いません。

`storyboard-preview-approval` Environmentにはsecretを置かず、Required reviewerを`Insynergy-jp`、Deployment branchesをcustom policyの`main` 1件だけに限定します。Workflow initiatorも`Insynergy-jp`で同一ユーザー承認を許可する運用ではPrevent self-reviewを無効にします。有効にしたまま同一ユーザーが承認すると、review履歴取得後のapplication gateでもfail closedになります。Workflowは実行時にReviewer login/ID、Prevent self-review、`main`限定branch policyをGitHub APIから再検証し、review履歴hashとEnvironment policy hashを承認bindingへ封印します。

Provider生成後にsecretless再合成だけが失敗した場合は、`Storyboard Preview`を`provider_run_id`付きで再実行できます。復旧経路は元Runが`main`上の失敗したStoryboard Previewであること、対応するPlan Articleが同じcommitで成功していること、Planning evidence／Build ID／Profile／Preview manifestが一致することをGitHub APIとbundle内hashで検証します。検証後は既存のProvider artifactを再利用し、`planning-ai`、OpenAI、Runwayを呼ばずに再合成とEnvironment承認へ進みます。

Secretless再合成はsealed MP4を先にhash検証し、別の一時ディレクトリへ出力するため原本を上書きしません。入力Frame hash、Shot順、時間、解像度、FPS、Codec、watermark／overlay契約を厳密に検証し、runner間で変動し得るMP4 container byte列の代わりにdecoded映像のSSIM `0.999`以上を要求します。失敗時の構造化エラーはActions logへ安全に出力されます。

## Schema

現行v3.4.0のPart 9 schema bundleを出力できます。監査対象は72件の登録Schemaと共通定義を合わせた73 Schema IDです。`schema-registry.json`と`compatibility-baseline.json`は別のRegistry／互換性証拠です。

```bash
PYTHONPATH=src python3 -m insynergy_cinematic export-schemas schemas
```

Artifactは共通して、schema/contract version、artifact/build identity、content hash、入力hash、generator、determinism宣言を持ちます。中核成果物には追加の必須フィールドと規範的不変条件があります。既存v2.x baselineをbyte-compatibleのまま維持し、v2.1 Agent Review、v3.3 Persona Council、v3.4 Storyboard PreviewのSchemaを追加しています。6 Preview Schemaはclosed object、zero-Runway counter、公開不可、承認bindingを検証します。

## テスト

```bash
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

135件のテストは、従来の決定論、Story／Screenplay／Persona／Outcome／Agent Review／Render／Schemaに加え、fake GPT planning、fixture image、hash検証付きCache replay、FFmpeg durationとwatermark、非破壊secretless再合成、失敗Run復旧binding、Prompt分離、provider-free budget preflight、実Reviewer login/ID、Environment policy、自己承認policy、Frame／Cache改ざん、Secret隔離、Runway Provider初期化spyを検証します。通常CIはfake providerを使い、実OpenAI／Runway呼び出しを行いません。

## 重要な運用境界

- Renderingは承認済み計画を読み取るだけで、Story、Screenplay、Storyboardを変更しません。
- `storyboard_animatic`有効時は、GPT-5.6／GPT Image／FFmpegによるPreview bundleと独立したPreview／execution承認が揃うまでRunwayを呼びません。
- Agent Reviewは助言証拠だけを生成し、決定論的成果物、人間承認、レンダーを変更・代行しません。
- Persona CouncilはStoryより前だけで動作し、専門Agent間handoff、再帰、外部write、自己承認を行いません。
- Viewer Outcomeはraw viewer IDと自由記述を保存せず、仮名化イベントと集計だけをDashboardへ出します。
- Quality Gate、実行承認、公開承認を迂回するAPIはありません。
- 1ショットでも品質未達または技術的無効なら、Build全体はfail closedします。
- Provider、Provider Version、Profile、Prompt、Shotのいずれかが違えばキャッシュミスです。
- 同じ記事とProfileは同じBuild IDと同じ計画Artifactを作ります。
- Provider資格情報はConfiguration Loaderから具象アダプターへだけ渡されます。

視聴者測定の入力・判定・privacy運用は [Viewer Outcomes Dashboard Runbook](docs/runbooks/viewer-outcomes.md)、実装と9仕様書の対応は [Specification Traceability](docs/architecture/specification-traceability.md) にまとめています。
