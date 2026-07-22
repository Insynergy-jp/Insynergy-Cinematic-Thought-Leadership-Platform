"""Dependency-free HTTP JSON adapter for the canonical /api/v2 surface."""

from __future__ import annotations

import json
import hmac
import ipaddress
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .errors import AuthenticationError, PlatformError, ValidationError
from .orchestrator import BuildOrchestrator
from .outcomes import OutcomeDashboard, ViewerOutcomeRepository
from .util import PLATFORM_VERSION, now_iso, stable_id


class APIHandler(BaseHTTPRequestHandler):
    orchestrator: BuildOrchestrator
    server_version = "InsynergyCinematic/3.3"

    def log_message(self, format: str, *args: object) -> None:
        # The API intentionally leaves structured access logging to its host.
        return

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValidationError("Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValidationError("Request body must be a JSON object")
        return value

    def _send(self, status: int, data: Any = None, error: Any = None) -> None:
        request_id = self.headers.get("X-Request-Id") or stable_id(
            "request", {"path": self.path, "time": now_iso()}
        )
        value = {
            "request_id": request_id,
            "correlation_id": request_id,
            "status": status,
            "data": data,
            "error": error,
            "metadata": {
                "api_version": "v2",
                "server_version": PLATFORM_VERSION,
                "occurred_at": now_iso(),
            },
        }
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _mutation_guard(self) -> str:
        key = self.headers.get("Idempotency-Key", "").strip()
        if not key:
            raise ValidationError("Idempotency-Key header is required for mutations")
        return key

    def _authorization_guard(self) -> None:
        configured = self.orchestrator.config.api_token
        if not configured:
            return
        authorization = self.headers.get("Authorization", "")
        supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, configured):
            raise AuthenticationError("Authentication failed")

    def _run_operation(
        self,
        *,
        key: str,
        operation_type: str,
        request: dict[str, Any],
        callback: Any,
    ) -> dict[str, Any]:
        operation, owned = self.orchestrator.repository.begin_operation(
            idempotency_key=key,
            operation_type=operation_type,
            request=request,
        )
        if not owned:
            return operation
        try:
            result = callback()
        except PlatformError as exc:
            self.orchestrator.repository.finish_operation(
                operation, error=exc.as_dict()
            )
            raise
        except Exception as exc:
            self.orchestrator.repository.finish_operation(
                operation,
                error={"code": "INTERNAL_ERROR", "message": str(exc)},
            )
            raise
        return self.orchestrator.repository.finish_operation(
            operation, result=result
        )

    def _route(self, method: str) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/") or "/"
        if method == "GET" and path == "/api/v2/health":
            self._send(HTTPStatus.OK, self.orchestrator.health())
            return
        self._authorization_guard()
        if method == "GET" and path == "/api/v2/builds":
            self._send(HTTPStatus.OK, self.orchestrator.list_builds())
            return
        if method == "GET" and path == "/api/v2/outcomes/dashboard":
            query = parse_qs(parsed_url.query, keep_blank_values=False)
            build_id = query.get("build_id", [None])[0]
            raw_window = query.get("window_days", [None])[0]
            try:
                window_days = int(raw_window) if raw_window is not None else None
            except ValueError as exc:
                raise ValidationError("window_days must be an integer") from exc
            self._send(
                HTTPStatus.OK,
                OutcomeDashboard(self.orchestrator.workspace).report(
                    build_id=build_id,
                    window_days=window_days,
                ),
            )
            return
        if method == "POST" and path == "/api/v2/outcomes":
            key = self._mutation_guard()
            body = self._body()
            viewer_id = body.get("viewer_id")
            if not isinstance(viewer_id, str) or not viewer_id.strip():
                raise ValidationError("viewer_id is required")
            result = ViewerOutcomeRepository(self.orchestrator.workspace).record(
                build_id=str(body.get("build_id", "")),
                viewer_id=viewer_id,
                idea_restatement_accuracy=body.get("idea_restatement_accuracy"),
                unaided_recall=body.get("unaided_recall"),
                reaction_subject=str(body.get("reaction_subject", "")),
                accuracy_gate_result=str(body.get("accuracy_gate_result", "")),
                retention_interval_hours=body.get("retention_interval_hours"),
                cohort=str(body.get("cohort", "all")),
                observed_at=body.get("observed_at"),
                idempotency_key=key,
            )
            self._send(HTTPStatus.CREATED if result["created"] else HTTPStatus.OK, result)
            return
        match = re.fullmatch(r"/api/v2/builds/([^/]+)", path)
        if method == "GET" and match:
            self._send(HTTPStatus.OK, self.orchestrator.inspect(match.group(1)))
            return
        runtime_match = re.fullmatch(
            r"/api/v2/builds/([^/]+)/(recovery|verification)", path
        )
        if method == "GET" and runtime_match:
            build_id, surface = runtime_match.groups()
            result = (
                self.orchestrator.recover(build_id)
                if surface == "recovery"
                else self.orchestrator.verify(build_id)
            )
            self._send(HTTPStatus.OK, result)
            return
        if method == "POST" and path == "/api/v2/builds":
            key = self._mutation_guard()
            body = self._body()
            article_path = body.get("article_path")
            if not article_path:
                raise ValidationError("article_path is required")
            creative_brief_path = body.get("creative_brief_path")
            request = {
                "article_path": str(Path(article_path).resolve()),
                "creative_brief_path": (
                    str(Path(creative_brief_path).resolve())
                    if creative_brief_path
                    else None
                ),
            }
            operation = self._run_operation(
                key=key,
                operation_type="BUILD_PLAN",
                request=request,
                callback=lambda: self.orchestrator.plan(
                    Path(article_path),
                    creative_brief_path=(
                        Path(creative_brief_path) if creative_brief_path else None
                    ),
                ),
            )
            self._send(HTTPStatus.ACCEPTED, operation)
            return
        action_match = re.fullmatch(
            r"/api/v2/builds/([^/]+)/(review|approve|execute|publish|pause|resume|cancel)",
            path,
        )
        if method == "POST" and action_match:
            key = self._mutation_guard()
            build_id, action = action_match.groups()
            body = self._body()
            request = {"build_id": build_id, "action": action, "body": body}

            def mutate() -> dict[str, Any]:
                if action == "approve":
                    return self.orchestrator.approve(
                        build_id,
                        gate=body.get("gate", "execution"),
                        actor=body.get("actor", "api-operator"),
                        decision=body.get("decision", "APPROVED"),
                        comment=body.get("comment", ""),
                        allow_agent_exception=body.get("allow_agent_exception", False)
                        is True,
                        agent_exception_reason=body.get(
                            "agent_exception_reason", ""
                        ),
                    )
                return getattr(self.orchestrator, action)(build_id)

            operation = self._run_operation(
                key=key,
                operation_type=f"BUILD_{action.upper()}",
                request=request,
                callback=mutate,
            )
            self._send(HTTPStatus.ACCEPTED, operation)
            return
        self._send(HTTPStatus.NOT_FOUND, error={"code": "ROUTE_NOT_FOUND", "message": path})

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._route("GET")
        except PlatformError as exc:
            self._send(_status_for(exc), error=exc.as_dict())
        except Exception as exc:
            self._send(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                error={"code": "INTERNAL_ERROR", "message": str(exc)},
            )

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._route("POST")
        except PlatformError as exc:
            self._send(_status_for(exc), error=exc.as_dict())
        except Exception as exc:
            self._send(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                error={"code": "INTERNAL_ERROR", "message": str(exc)},
            )


def _status_for(error: PlatformError) -> int:
    return {
        3: HTTPStatus.UNAUTHORIZED,
        4: HTTPStatus.FORBIDDEN,
        5: HTTPStatus.NOT_FOUND,
        6: HTTPStatus.CONFLICT,
        7: HTTPStatus.UNPROCESSABLE_ENTITY,
    }.get(error.exit_code, HTTPStatus.BAD_REQUEST)


def serve(orchestrator: BuildOrchestrator, host: str, port: int) -> None:
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.casefold() == "localhost"
    if not loopback and not orchestrator.config.api_token:
        raise ValidationError(
            "INSYNERGY_API_TOKEN is required when the API binds beyond loopback"
        )
    handler = type("BoundAPIHandler", (APIHandler,), {"orchestrator": orchestrator})
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
