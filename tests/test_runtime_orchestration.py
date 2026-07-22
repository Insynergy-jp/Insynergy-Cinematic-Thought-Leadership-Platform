from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from insynergy_cinematic.errors import StateConflictError, ValidationError
from insynergy_cinematic.models import BuildState
from insynergy_cinematic.orchestrator import BuildOrchestrator
from insynergy_cinematic.runtime import DurableTaskQueue
from insynergy_cinematic.runtime import part6_coverage_report
from insynergy_cinematic.storage import BuildRepository
from insynergy_cinematic.util import atomic_write_json, read_json


ROOT = Path(__file__).resolve().parents[1]


def request(task_id: str, shot_id: str, provider: str = "local") -> dict:
    return {
        "render_task_id": task_id,
        "shot_id": shot_id,
        "provider": provider,
        "cache_key": "sha256:" + task_id[-1] * 64,
        "estimated_cost_usd": 0.0,
    }


class RuntimeOrchestrationTests(unittest.TestCase):
    def test_part6_coverage_matrix_reaches_target_without_hiding_gaps(self) -> None:
        report = part6_coverage_report()
        self.assertEqual(report["cluster_count"], 21)
        self.assertEqual((report["full"], report["partial"], report["missing"]), (15, 4, 2))
        self.assertGreaterEqual(report["coverage_percent"], 80.0)
        missing = {
            row["cluster"]
            for row in report["clusters"]
            if row["status"] == "MISSING"
        }
        self.assertEqual(
            missing, {"compensation_and_rollback", "production_transition"}
        )

    def test_manifest_compare_and_swap_rejects_stale_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = BuildRepository(Path(temporary))
            repository.create(
                "20260722-001", {"content_hash": "sha256:x"}, "preview", {}
            )
            first = repository.load("20260722-001")
            stale = deepcopy(first)
            first["metrics"]["writer"] = "first"
            repository.save(first)
            stale["metrics"]["writer"] = "stale"
            with self.assertRaises(StateConflictError):
                repository.save(stale)

    def test_manifest_and_event_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = BuildRepository(Path(temporary))
            manifest = repository.create(
                "20260722-001", {"content_hash": "sha256:x"}, "preview", {}
            )
            repository.record_event(manifest, "custom", {"safe": True})
            repository.record_event(manifest, "custom", {"safe": True})
            self.assertEqual(len(manifest["events"]), 2)
            manifest = repository.save(manifest)

            broken_chain = deepcopy(manifest)
            broken_chain["events"][-1]["payload"]["safe"] = False
            with self.assertRaises(ValidationError):
                repository.verify_event_chain(broken_chain)

            stored = read_json(repository.manifest_path(manifest["build_id"]))
            stored["state"] = BuildState.PUBLISHED.value
            atomic_write_json(repository.manifest_path(manifest["build_id"]), stored)
            with self.assertRaises(ValidationError):
                repository.load(manifest["build_id"])

    def test_durable_queue_enforces_backpressure_and_idempotent_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = DurableTaskQueue(
                Path(temporary) / "queue.json",
                build_id="20260722-001",
                max_in_flight=1,
                provider_limits={"local": 1, "runway": 1},
                budget_usd=1.0,
            )
            queue.initialize(
                [request("task-1", "shot-1"), request("task-2", "shot-2")],
                generation=1,
            )
            first = queue.claim("task-1", worker_id="worker-a")
            self.assertEqual(first["outcome"], "CLAIMED")
            duplicate_claim = queue.claim("task-1", worker_id="worker-c")
            self.assertEqual(
                duplicate_claim,
                {"outcome": "DEFERRED", "reason": "TASK_ALREADY_LEASED"},
            )
            deferred = queue.claim("task-2", worker_id="worker-b")
            self.assertEqual(deferred, {"outcome": "DEFERRED", "reason": "GLOBAL_CAPACITY"})

            result = {"state": "COMPLETED", "asset_hash": "sha256:" + "a" * 64}
            recorded = queue.complete(
                "task-1", lease_id=first["lease_id"], result=result
            )
            self.assertEqual(recorded["outcome"], "RECORDED")
            duplicate = queue.complete(
                "task-1", lease_id=first["lease_id"], result=result
            )
            self.assertEqual(duplicate["outcome"], "ALREADY_RECORDED")
            with self.assertRaises(StateConflictError):
                queue.complete(
                    "task-1",
                    lease_id=first["lease_id"],
                    result={"state": "FAILED"},
                )
            second = queue.claim("task-2", worker_id="worker-b")
            self.assertEqual(second["outcome"], "CLAIMED")
            snapshot = queue.snapshot()
            self.assertEqual(snapshot["state_counts"], {"COMPLETED": 1, "LEASED": 1})
            self.assertEqual(snapshot["metrics"]["backpressure_deferrals"], 2)

    def test_new_generation_fences_unfinished_lease_and_preserves_terminal_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = DurableTaskQueue(
                Path(temporary) / "queue.json",
                build_id="20260722-001",
                max_in_flight=2,
                provider_limits={"local": 2, "runway": 1},
                budget_usd=1.0,
            )
            requests = [request("task-1", "shot-1"), request("task-2", "shot-2")]
            queue.initialize(requests, generation=1)
            first = queue.claim("task-1", worker_id="old-worker")
            second = queue.claim("task-2", worker_id="old-worker")
            completed = {"state": "CACHED", "asset_hash": "sha256:" + "b" * 64}
            queue.complete("task-2", lease_id=second["lease_id"], result=completed)

            snapshot = queue.initialize(requests, generation=2)
            self.assertEqual(snapshot["state_counts"], {"CACHED": 1, "READY": 1})
            replacement = queue.claim("task-1", worker_id="new-worker")
            self.assertNotEqual(first["lease_id"], replacement["lease_id"])
            with self.assertRaises(StateConflictError):
                queue.complete(
                    "task-1", lease_id=first["lease_id"], result=completed
                )

    def test_checkpoint_and_recovery_plan_are_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = BuildRepository(Path(temporary))
            manifest = repository.create(
                "20260722-001", {"content_hash": "sha256:x"}, "preview", {}
            )
            manifest = repository.publish_checkpoint(
                manifest, "created", clean=True
            )
            reference = manifest["checkpoints"][0]
            checkpoint = repository.verify_checkpoint(reference)
            self.assertEqual(checkpoint["stage"], "created")
            self.assertEqual(repository.recovery_plan(manifest)["outcome"], "RESTART_STAGE")
            self.assertEqual(
                repository.recovery_plan(manifest),
                repository.recovery_plan(manifest),
            )

            tampered = read_json(Path(reference["path"]))
            tampered["clean"] = False
            atomic_write_json(Path(reference["path"]), tampered)
            with self.assertRaises(ValidationError):
                repository.verify_checkpoint(reference)

    def test_resume_persists_recovery_plan_before_runtime_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = BuildRepository(Path(temporary))
            manifest = repository.create(
                "20260722-001", {"content_hash": "sha256:x"}, "preview", {}
            )
            for state in (
                BuildState.PLANNING,
                BuildState.PLANNED,
                BuildState.AWAITING_EXECUTION_APPROVAL,
                BuildState.EXECUTING,
                BuildState.PAUSED,
            ):
                manifest = repository.transition(manifest, state, "test")
            manifest = repository.publish_checkpoint(
                manifest, "paused", clean=True
            )
            plan, persisted = repository.prepare_recovery(manifest)
            self.assertEqual(plan["outcome"], "RESUME")
            self.assertEqual(len(persisted["runtime"]["recovery_attempts"]), 1)
            reference = persisted["runtime"]["recovery_attempts"][0]
            self.assertEqual(repository.verify_recovery_plan(reference), plan)
            verification = repository.verify_runtime(persisted)
            self.assertEqual(verification["recovery_plan_count"], 1)

    def test_durable_operations_replay_and_reject_key_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = BuildRepository(Path(temporary))
            operation, owned = repository.begin_operation(
                idempotency_key="request-1",
                operation_type="BUILD_PLAN",
                request={"article_path": "/article.md"},
            )
            self.assertTrue(owned)
            finished = repository.finish_operation(
                operation, result={"build_id": "20260722-001", "state": "PLANNED"}
            )
            replay, replay_owned = repository.begin_operation(
                idempotency_key="request-1",
                operation_type="BUILD_PLAN",
                request={"article_path": "/article.md"},
            )
            self.assertFalse(replay_owned)
            self.assertEqual(replay, finished)
            with self.assertRaises(StateConflictError):
                repository.begin_operation(
                    idempotency_key="request-1",
                    operation_type="BUILD_EXECUTE",
                    request={"build_id": "20260722-001"},
                )

    def test_planning_publishes_verified_recovery_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(Path(temporary), profile="preview")
            planned = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            verification = orchestrator.verify(planned["build_id"])
            self.assertTrue(verification["passed"])
            self.assertGreaterEqual(verification["checkpoint_count"], 1)
            self.assertEqual(
                verification["recovery"]["outcome"], "WAIT_FOR_APPROVAL"
            )

    def test_planning_seals_part6_plan_dependency_budget_and_config_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(Path(temporary), profile="preview")
            planned = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            required = {
                "performance_budget",
                "dependency_graph",
                "build_profile",
                "performance_config",
                "execution_plan",
                "operational_state",
            }
            self.assertTrue(required.issubset(planned["artifacts"]))
            manifest = orchestrator.repository.load(planned["build_id"])
            graph = orchestrator.repository.load_artifact(
                manifest, "dependency_graph"
            )["data"]
            plan = orchestrator.repository.load_artifact(
                manifest, "execution_plan"
            )["data"]
            self.assertTrue(graph["acyclic"])
            self.assertEqual(plan["dependency_graph_ref"], planned["artifacts"]["dependency_graph"]["content_hash"])
            self.assertEqual(
                planned["execution_plan_content_hash"],
                planned["artifacts"]["execution_plan"]["content_hash"],
            )

    def test_end_to_end_runtime_queue_and_checkpoints_are_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(Path(temporary), profile="preview")
            planned = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            build_id = planned["build_id"]
            orchestrator.approve(build_id, gate="execution", actor="runtime-test")
            ready = orchestrator.execute(build_id)
            self.assertEqual(ready["state"], BuildState.READY.value)
            queue = ready["runtime"]["queue_snapshot"]
            self.assertEqual(queue["task_count"], 8)
            self.assertEqual(
                sum(queue["state_counts"].get(value, 0) for value in ("COMPLETED", "CACHED")),
                8,
            )
            verification = orchestrator.verify(build_id)
            self.assertTrue(verification["passed"])
            self.assertGreaterEqual(verification["checkpoint_count"], 5)
            self.assertEqual(verification["recovery"]["outcome"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
