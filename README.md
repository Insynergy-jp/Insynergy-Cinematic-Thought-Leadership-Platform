# Insynergy Cinematic Thought Leadership Platform

Specification v2.0 の9文書を実行可能な参照実装にした、決定論的な映像ビルド・プラットフォームです。Markdown記事を、Story、Screenplay、Shot/Storyboard、ハイブリッド・レンダー、FFmpeg合成、品質ゲート、2段階の人間承認、公開パッケージへ変換します。

## 実装されているもの

- 記事の構造化、主張分類、単一テーマ・単一主人公・単一葛藤・単一ドラマティッククエスチョンの生成
- 三幕構成、感情アーク、Act 3に限定したコンセプト配置
- Story成果物のみを入力にするScreenplay EngineとFountain出力
- 連続性を保持したShot List、Camera Plan、Blocking、Storyboard
- Runway Video、Animated Still、Motion Graphics、Typographyを使う決定論的なハイブリッド戦略
- Storyboardだけを入力にするPrompt Assembly
- 完全一致キーによるCAS／Render Cache。キャッシュヒット時はQueueとProviderを迂回
- `VideoProvider`契約、オフライン用ローカルFFmpegプロバイダー、Runway HTTPアダプター
- 並列ショット実行、技術検証、0.90のレンダー品質ゲート、fail-closed集約
- FFmpeg合成、最終動画検証、再現可能ZIPパッケージ
- 不変Artifact Envelope、SHA-256 provenance、明示状態遷移、append-onlyイベント
- 実行前承認と公開前承認。承認対象ハッシュが変わると承認は無効
- CLI、`/api/v2` HTTP JSON API、Part 9の全スキーマ名を含むSchema Registry
- GitHub ActionsによるCI、計画、承認後実行、公開の分離ワークフロー

## 必要環境

- Python 3.11以上（外部Pythonパッケージなし）
- FFmpeg / FFprobe

macOS Homebrewでは `brew install ffmpeg`、Ubuntuでは `apt-get install ffmpeg` で用意できます。

## クイックスタート

リポジトリ直下で次を実行します。

```bash
PYTHONPATH=src python3 -m insynergy_cinematic health
PYTHONPATH=src python3 -m insynergy_cinematic plan examples/decision-boundary.md
```

`plan` は `AWAITING_EXECUTION_APPROVAL` で停止し、JSONに `build_id` を返します。高コスト領域へ進むには、明示的な承認が必要です。

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
├── render-cache/
└── providers/
```

`.insynergy/` はランタイム状態なのでGit管理対象外です。

## CLI

```text
plan ARTICLE                         計画成果物を生成し、品質ゲートを評価
approve BUILD_ID --gate GATE        execution / publish承認を記録
execute BUILD_ID                    承認済み計画をレンダー・合成・検証
publish BUILD_ID                    公開承認済みマスターをパッケージ化
build ARTICLE [--auto-approve]      エンドツーエンド実行
status BUILD_ID                     Manifest、イベント、状態を表示
list                                Build一覧
pause|resume|cancel BUILD_ID        ライフサイクル制御
health                              FFmpegなどのreadinessを表示
serve                               /api/v2を起動
export-schemas [DESTINATION]        Part 9 JSON Schemaを出力
```

共通オプションは `--workspace`、`--config`、`--profile draft|preview|final`、`--provider local|runway`、`--compact` です。オプションはサブコマンドより前に置きます。

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
POST /api/v2/builds/{build_id}/execute
POST /api/v2/builds/{build_id}/publish
POST /api/v2/builds/{build_id}/pause
POST /api/v2/builds/{build_id}/resume
POST /api/v2/builds/{build_id}/cancel
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
export RUNWAY_BASE_URL='https://your-approved-runway-endpoint.example'
export RUNWAY_API_KEY='...'
export RUNWAY_MODEL_GEN45='...'
PYTHONPATH=src python3 -m insynergy_cinematic --provider runway execute BUILD_ID
```

APIキーはManifest、Queue、Event、Artifactへ記録されません。RunwayアダプターはPromptを変更せず、物語、台詞、ペーシング、カメラ判断を行いません。実アカウントへの送信は費用を伴うため、ローカルテストでは実行していません。

GitHub Actionsでは、APIキーを `RUNWAY_API_KEY` という名前のActions Secretとして登録します。承認境界を保つため、`render-approval` Environment Secretとしての登録を推奨します。Repository Secretとして登録した場合も同じWorkflow参照で利用できます。

```text
Settings → Environments → render-approval → Environment secrets
RUNWAY_API_KEY = <Runway API key>
```

同じEnvironmentのVariablesに `RUNWAY_BASE_URL` と `RUNWAY_MODEL_GEN45` を登録します。`Plan Article` と `Execute Approved Plan` の両方で同じProfileと `provider: runway` を選択してください。詳しくは [GitHub Actions Runbook](docs/runbooks/github-actions.md) を参照してください。

## Schema

Part 9に列挙された全56 Artifact Schemaと共通定義、Schema Registryを出力できます。

```bash
PYTHONPATH=src python3 -m insynergy_cinematic export-schemas schemas
```

Artifactは共通して、schema/contract version、artifact/build identity、content hash、入力hash、generator、determinism宣言を持ちます。中核成果物には追加の必須フィールドと規範的不変条件があります。
56件のcanonical schemaはPart 9の各 `Canonical Schema` JSONブロックから抽出して同梱しており、全 `$ref` の解決をテストします。

## テスト

```bash
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

テストは決定論、単一性、Act 3コンセプト配置、Storyboard-only Prompt、承認障壁、違法状態遷移拒否、完全一致キャッシュキー、全Schema出力、ローカルE2E（レンダーから公開ZIPまで）を検証します。

## 重要な運用境界

- Renderingは承認済み計画を読み取るだけで、Story、Screenplay、Storyboardを変更しません。
- Quality Gate、実行承認、公開承認を迂回するAPIはありません。
- 1ショットでも品質未達または技術的無効なら、Build全体はfail closedします。
- Provider、Provider Version、Profile、Prompt、Shotのいずれかが違えばキャッシュミスです。
- 同じ記事とProfileは同じBuild IDと同じ計画Artifactを作ります。
- Provider資格情報はConfiguration Loaderから具象アダプターへだけ渡されます。

実装と9仕様書の対応は [docs/architecture/specification-traceability.md](docs/architecture/specification-traceability.md) にまとめています。
