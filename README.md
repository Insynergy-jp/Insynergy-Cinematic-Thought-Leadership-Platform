# Insynergy Cinematic Thought Leadership Platform

Master Specification v2.1 の9文書を実行可能なPlatform v3.3.0として実装した、決定論的な映像ビルド・プラットフォームです。Markdown記事を、任意のPersona Council、Story、Screenplay、Shot/Storyboard、任意のAgent Review、ハイブリッド・レンダー、FFmpeg合成、品質ゲート、段階的な人間承認、公開パッケージへ変換します。

## 実装されているもの

- Part 1のProduct／Objective／Layer／Flow／Governance／Authorityを一つに束ねた実行可能Architecture Contract。20項目のfail-closed検査、Provider隔離監査、Buildごとの不変な検証証拠
- 記事の構造化、主張分類、単一テーマ・単一主人公・単一葛藤・単一ドラマティッククエスチョンの生成
- 三層Conflict、構造化された不可逆Stakes、観客に見えるTime Pressure、6段Story Arc、時間配分付き三幕、因果的Emotionを強制するStory Engine v3.3契約
- 三幕構成、感情アーク、Act 3に限定したコンセプト配置
- Story成果物のみを入力にするScreenplay EngineとFountain出力
- 8 scene／三幕、4–10秒、単一purpose/conflict、緊張台詞、明示的silence、7次元continuityをfail-closedで強制するScreenplay Engine v3.3契約
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

公式設計根拠：OpenAI Agents SDKの[Orchestration and handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration)、[Agent definitions](https://developers.openai.com/api/docs/guides/agents/define-agents)、[Guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)、[Integrations and observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability)。

| 区分 | バージョン | 状態 |
| --- | --- | --- |
| 現行ランタイム | 3.3.0 | 実装済み |
| Persona Council | 3.3.0 | ライブ実行、品質、承認、Actions経路を実装済み |
| Viewer Outcomes Dashboard | 3.3.0 | 追記保存、長期想起判定、HTML/JSONを実装済み |

## 必要環境

- Python 3.11以上（`off` モードは外部Pythonパッケージなし）
- FFmpeg / FFprobe

Agent Reviewを実行する場合だけ、OpenAI Agents SDKを追加します。

```bash
python3 -m pip install -e '.[agent-review]'
```

macOS Homebrewでは `brew install ffmpeg`、Ubuntuでは `apt-get install ffmpeg` で用意できます。

## クイックスタート

リポジトリ直下で次を実行します。

```bash
PYTHONPATH=src python3 -m insynergy_cinematic health
PYTHONPATH=src python3 -m insynergy_cinematic plan examples/decision-boundary.md
```

`plan` は `AWAITING_EXECUTION_APPROVAL` で停止し、JSONに `build_id` を返します。高コスト領域へ進むには、明示的な承認が必要です。本番ナレーションでは、計画と実行の両方で`--profile final --narration-provider openai`を指定します。全ショットをGen-4.5で生成する場合は`--provider runway --runway-scope all_shots`も指定します。

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
approve BUILD_ID --gate GATE        persona / execution / publish承認を記録
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

共通オプションは `--workspace`、`--config`、`--profile draft|preview|final`、`--provider local|runway`、`--runway-scope hybrid|all_shots`、`--narration-provider offline|openai`、`--agent-review-mode off|review`、`--persona-mode off|council`、`--compact` です。オプションはサブコマンドより前に置きます。

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
POST /api/v2/builds/{build_id}/approve
POST /api/v2/builds/{build_id}/review
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

## GitHub Agent Review設定

GitHubの `planning-ai` Environmentに次を設定します。OpenAIキーはこのEnvironmentのAgent Review jobにだけ公開され、`plan`、`render-approval`、`publication-approval` には渡りません。

```text
Environment secret
OPENAI_API_KEY = <OpenAI API key>

Environment variables
OPENAI_MODEL_REVIEW = gpt-5.6-sol
OPENAI_REASONING_EFFORT = medium
OPENAI_TRACE_MODE = disabled
```

`Plan Article` の `agent_review_mode` で `review` を選ぶと `planning-ai` jobを実行し、`off` ではSDKもOpenAI Secretも使いません。

## Schema

Part 9に列挙された全58 Artifact Schemaと共通定義、Schema Registryを出力できます。

```bash
PYTHONPATH=src python3 -m insynergy_cinematic export-schemas schemas
```

Artifactは共通して、schema/contract version、artifact/build identity、content hash、入力hash、generator、determinism宣言を持ちます。中核成果物には追加の必須フィールドと規範的不変条件があります。
既存56件のv2.0 schemaはbyte-compatibleのまま維持し、v2.1の `AgentReviewReport` と `ReviewApprovalBinding` を追加しています。全58件はPart 9の規範JSONブロックから抽出して同梱しています。

## テスト

```bash
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

テストは決定論、単一性、Act 3コンセプト配置、Storyboard-only Prompt、Personaの有限実行／single-flight／承認前停止／改ざん拒否、視聴者評価ledger／プライバシー／長期判定、Agent Review、全Schema出力、ローカルE2Eを検証します。必須CIはfake providerを使い、実OpenAI呼び出しを行いません。

## 重要な運用境界

- Renderingは承認済み計画を読み取るだけで、Story、Screenplay、Storyboardを変更しません。
- Agent Reviewは助言証拠だけを生成し、決定論的成果物、人間承認、レンダーを変更・代行しません。
- Persona CouncilはStoryより前だけで動作し、専門Agent間handoff、再帰、外部write、自己承認を行いません。
- Viewer Outcomeはraw viewer IDと自由記述を保存せず、仮名化イベントと集計だけをDashboardへ出します。
- Quality Gate、実行承認、公開承認を迂回するAPIはありません。
- 1ショットでも品質未達または技術的無効なら、Build全体はfail closedします。
- Provider、Provider Version、Profile、Prompt、Shotのいずれかが違えばキャッシュミスです。
- 同じ記事とProfileは同じBuild IDと同じ計画Artifactを作ります。
- Provider資格情報はConfiguration Loaderから具象アダプターへだけ渡されます。

視聴者測定の入力・判定・privacy運用は [Viewer Outcomes Dashboard Runbook](docs/runbooks/viewer-outcomes.md)、実装と9仕様書の対応は [Specification Traceability](docs/architecture/specification-traceability.md) にまとめています。
