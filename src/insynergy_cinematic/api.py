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
from urllib.parse import urlparse

from .errors import AuthenticationError, PlatformError, ValidationError
from .orchestrator import BuildOrchestrator
from .util import now_iso, stable_id


class APIHandler(BaseHTTPRequestHandler):
    orchestrator: BuildOrchestrator
    server_version = "InsynergyCinematic/3.0"

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
                "server_version": "3.2.0",
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

    def _route(self, method: str) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if method == "GET" and path == "/api/v2/health":
            self._send(HTTPStatus.OK, self.orchestrator.health())
            return
        self._authorization_guard()
        if method == "GET" and path == "/api/v2/builds":
            self._send(HTTPStatus.OK, self.orchestrator.list_builds())
            return
        match = re.fullmatch(r"/api/v2/builds/([^/]+)", path)
        if method == "GET" and match:
            self._send(HTTPStatus.OK, self.orchestrator.inspect(match.group(1)))
            return
        if method == "POST" and path == "/api/v2/builds":
            key = self._mutation_guard()
            body = self._body()
            article_path = body.get("article_path")
            if not article_path:
                raise ValidationError("article_path is required")
            view = self.orchestrator.plan(Path(article_path))
            operation = {
                "operation_id": stable_id("operation", {"key": key, "build": view["build_id"]}),
                "operation_type": "BUILD_PLAN",
                "state": "SUCCEEDED",
                "build_id": view["build_id"],
                "result": view,
            }
            self._send(HTTPStatus.ACCEPTED, operation)
            return
        action_match = re.fullmatch(
            r"/api/v2/builds/([^/]+)/(review|approve|execute|publish|pause|resume|cancel)",
            path,
        )
        if method == "POST" and action_match:
            self._mutation_guard()
            build_id, action = action_match.groups()
            body = self._body()
            if action == "approve":
                result = self.orchestrator.approve(
                    build_id,
                    gate=body.get("gate", "execution"),
                    actor=body.get("actor", "api-operator"),
                    decision=body.get("decision", "APPROVED"),
                    comment=body.get("comment", ""),
                    allow_agent_exception=body.get("allow_agent_exception", False) is True,
                    agent_exception_reason=body.get("agent_exception_reason", ""),
                )
            else:
                result = getattr(self.orchestrator, action)(build_id)
            self._send(HTTPStatus.ACCEPTED, result)
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
