# Local Build Runbook

1. `python3 -m insynergy_cinematic health` でFFmpeg readinessを確認する。
2. `plan` を実行し、4つのcreative gateとStoryboardをレビューする。
3. `approve --gate execution` でレビュー主体を記録する。
4. `execute` を実行する。失敗時はManifestの`events`、`render_tasks`、`gates`を確認する。
5. `output/master.mp4` を人間がレビューする。
6. `approve --gate publish` でMaster hashに承認を結び付ける。
7. `publish` を実行し、`package/*.zip` とpackage hashを保管する。

承認後に計画またはMasterが変わった場合、再承認が必要です。Quality Gateを下げて処理を続けてはいけません。

