from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent_mesh_core.dispatch import MeshDispatch
from agent_mesh_core.mcp_server import validate_mesh_root

# Exceptions MeshDispatch lets propagate unmapped for expected, caller-facing
# failures. Mapped to an HTTP status code here, at this wrapper's own
# boundary - the same "let it raise, map at the boundary" rule mcp_server.py
# applies for ToolError, just with a different target error shape. Never
# force-fit these into one status: a bad argument (ValueError) is not the
# same failure as a missing resource (FileNotFoundError).
_STATUS_FOR_EXCEPTION: dict[type[Exception], int] = {
    ValueError: 400,
    FileNotFoundError: 404,
    NotADirectoryError: 409,
    FileExistsError: 409,
    TypeError: 400,
}


def _status_for(exc: Exception) -> int | None:
    for exc_type, status in _STATUS_FOR_EXCEPTION.items():
        if isinstance(exc, exc_type):
            return status
    return None


def _handler(fn: Callable[[dict[str, Any]], Any]) -> Callable[[Request], Any]:
    async def endpoint(request: Request) -> JSONResponse:
        try:
            body_bytes = await request.body()
            body = json.loads(body_bytes) if body_bytes else {}
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            result = fn(body)
        except json.JSONDecodeError:
            return JSONResponse({"error": "malformed JSON request body"}, status_code=400)
        except tuple(_STATUS_FOR_EXCEPTION) as exc:
            status = _status_for(exc)
            return JSONResponse({"error": str(exc)}, status_code=status)
        return JSONResponse(result)

    return endpoint


def build_app(mesh_root: str | Path) -> Starlette:
    dispatch = MeshDispatch(mesh_root)

    routes = [
        Route(
            "/acquire_lock",
            _handler(lambda body: dispatch.acquire_lock(**body)),
            methods=["POST"],
        ),
        Route(
            "/release_lock",
            _handler(lambda body: dispatch.release_lock(**body)),
            methods=["POST"],
        ),
        Route(
            "/update_state",
            _handler(lambda body: dispatch.update_state(**body)),
            methods=["POST"],
        ),
        Route(
            "/send_message",
            _handler(lambda body: dispatch.send_message(**body)),
            methods=["POST"],
        ),
        Route(
            "/claim_inbox_messages",
            _handler(lambda body: dispatch.claim_inbox_messages(**body)),
            methods=["POST"],
        ),
        Route(
            "/acknowledge_claims",
            _handler(lambda body: dispatch.acknowledge_claims(**body)),
            methods=["POST"],
        ),
        Route(
            "/read_local_rules",
            _handler(lambda body: dispatch.read_local_rules(**body)),
            methods=["POST"],
        ),
        Route(
            "/health_check",
            _handler(lambda body: dispatch.health_check(**body)),
            methods=["POST"],
        ),
    ]
    return Starlette(routes=routes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-mesh-http-server")
    parser.add_argument("--mesh-root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)

    try:
        mesh_root = validate_mesh_root(args.mesh_root)
    except ValueError as exc:
        print(f"agent-mesh-http-server: {exc}", file=sys.stderr)
        return 2

    app = build_app(mesh_root)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
