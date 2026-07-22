# Recovery Runbook

1. `verify BUILD_ID`でManifest history、Event chain、Artifact、Checkpoint、Queueを検証する。1つでも不一致ならfail closedし、再実行しない。
2. `recover BUILD_ID`で副作用のないRecovery Planを生成する。`RESUME`または`RECONCILE`だけが再開可能である。
3. `status BUILD_ID`でauthoritative Manifest、execution generation、Queue snapshot、Checkpoint履歴、durable Operationを確認する。
4. `PAUSED`なら`resume`する。再開前にRecovery PlanがCASとBuild recovery履歴へ永続化される。新execution generationが旧Leaseをfenceし、完了Taskを保持し、未完了Taskだけを再配達する。
5. Provider側jobが不明な場合、Manifest/Queueのtask id、cache key、provider idempotency keyで照合する。blind redispatchは禁止する。
6. 承認hashが不一致なら再計画・再承認する。`FAILED`と`CANCELLED`は終端状態なので、修正入力から新Buildを作る。
7. Cache entryのasset hashが一致しない場合、そのentryは自動的にmissとして扱われる。

API Mutationは`Idempotency-Key`ごとに`.insynergy/operations/`へreference-before-effectで記録される。同じキーと同じ要求は保存済み結果を返し、異なる要求へのキー再利用は拒否される。
