# Recovery Runbook

- `status BUILD_ID` でauthoritative Manifestと最後の状態遷移を確認する。
- `verify_artifacts`相当の整合性確認は`execute`再開時に自動実行される。
- `PAUSED`なら`resume`する。承認hashが不一致なら再計画・再承認する。
- `FAILED`と`CANCELLED`は終端状態である。同じ入力から新しいProfileまたは修正記事で新Buildを作る。
- Provider側jobが不明な場合、Manifestのtask idとidempotency keyで照合する。blind redispatchは禁止する。
- Cache entryのasset hashが一致しない場合、そのentryは自動的にmissとして扱われる。

