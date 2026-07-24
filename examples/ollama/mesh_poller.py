#!/usr/bin/env python3
"""Example Ollama-side poller for agent-mesh-core.

This is the reference implementation of the task-routing pattern described
in README.md's "Ollama Integration" section: run this next to a local
Ollama install, and it polls `agent_ollama_local`'s inbox for cheap,
high-volume, non-critical work, runs it through a local model, and replies
to whoever sent it. It never runs anything correctness-critical itself —
that judgment call belongs to whichever agent decides to route a task here
in the first place.

Message contract this poller understands (anything else is left alone):

    type: "mesh.ollama.task"
    body: {
        "prompt": str,                # required - sent to Ollama verbatim
        "model": str,                 # optional - defaults to --model
        "reply_to": str,              # optional - defaults to the sender
        "reply_type": str,            # optional - defaults to "mesh.ollama.result"
    }

Reply sent back via `send_message`:

    type: <reply_type>
    body: {
        "prompt": str,
        "model": str,
        "response": str,              # present on success
        "error": str,                 # present on failure instead of "response"
    }

This script only talks to the exposed HTTP routes (`dispatch.EXPOSED_OPERATIONS`)
and a local Ollama server - it has no filesystem access to the mesh root,
same as every other non-Mac-mini caller. It is a reference example, not a
deployed service: run it manually, or wrap it in your own launchd/systemd
unit if you want it always-on.

Usage:

    python mesh_poller.py \\
        --mesh-http-url http://127.0.0.1:8001 \\
        --ollama-url http://127.0.0.1:11434 \\
        --model llama3.2 \\
        --poll-interval 5

    python mesh_poller.py --once   # single poll pass, useful for testing
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

AGENT_ID = "agent_ollama_local"
TASK_MESSAGE_TYPE = "mesh.ollama.task"
DEFAULT_REPLY_TYPE = "mesh.ollama.result"


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _ollama_generate(ollama_url: str, model: str, prompt: str) -> str:
    result = _post_json(
        f"{ollama_url.rstrip('/')}/api/generate",
        {"model": model, "prompt": prompt, "stream": False},
    )
    return result["response"]


def _claim_messages(mesh_http_url: str, max_messages: int) -> dict[str, Any]:
    return _post_json(
        f"{mesh_http_url.rstrip('/')}/claim_inbox_messages",
        {"agent_id": AGENT_ID, "max_messages": max_messages},
    )


def _acknowledge(mesh_http_url: str, claim_id: str, claim_token: str) -> None:
    _post_json(
        f"{mesh_http_url.rstrip('/')}/acknowledge_claims",
        {"agent_id": AGENT_ID, "claims": [{"claim_id": claim_id, "claim_token": claim_token}]},
    )


def _send_reply(
    mesh_http_url: str, target_agent_id: str, message_type: str, body: dict[str, Any]
) -> None:
    _post_json(
        f"{mesh_http_url.rstrip('/')}/send_message",
        {
            "agent_id": AGENT_ID,
            "target_agent_id": target_agent_id,
            "message_type": message_type,
            "body": body,
        },
    )


def _handle_task(
    mesh_http_url: str, ollama_url: str, default_model: str, envelope: dict[str, Any]
) -> None:
    body = envelope["body"]
    prompt = body["prompt"]
    model = body.get("model", default_model)
    reply_to = body.get("reply_to", envelope["sender"])
    reply_type = body.get("reply_type", DEFAULT_REPLY_TYPE)

    reply_body: dict[str, Any] = {"prompt": prompt, "model": model}
    try:
        reply_body["response"] = _ollama_generate(ollama_url, model, prompt)
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        reply_body["error"] = str(exc)

    _send_reply(mesh_http_url, reply_to, reply_type, reply_body)


def poll_once(mesh_http_url: str, ollama_url: str, default_model: str, max_messages: int) -> int:
    claimed = _claim_messages(mesh_http_url, max_messages)["claimed"]
    for item in claimed:
        envelope = item["message"]
        if envelope.get("type") == TASK_MESSAGE_TYPE:
            _handle_task(mesh_http_url, ollama_url, default_model, envelope)
        # Anything else is acknowledged without action - this poller only
        # claims its own inbox, so an unrecognized type here means a caller
        # sent it the wrong message type, not a real task to run.
        _acknowledge(mesh_http_url, item["claim_id"], item["claim_token"])
    return len(claimed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mesh-http-url", default="http://127.0.0.1:8001")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="llama3.2")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--max-messages", type=int, default=10)
    parser.add_argument("--once", action="store_true", help="poll a single time and exit")
    args = parser.parse_args(argv)

    if args.once:
        count = poll_once(args.mesh_http_url, args.ollama_url, args.model, args.max_messages)
        print(f"processed {count} message(s)")
        return 0

    print(
        f"polling {args.mesh_http_url} as {AGENT_ID} every {args.poll_interval}s (Ctrl+C to stop)"
    )
    while True:
        try:
            poll_once(args.mesh_http_url, args.ollama_url, args.model, args.max_messages)
        except urllib.error.URLError as exc:
            print(f"poll failed: {exc}", file=sys.stderr)
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    raise SystemExit(main())
