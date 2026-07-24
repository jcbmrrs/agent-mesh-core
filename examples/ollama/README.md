# Ollama task-routing example

`mesh_poller.py` is a reference implementation of how to get real
leverage out of a local Ollama install through this mesh: route it work
that is high-volume, low-stakes, and where an occasional wrong answer is
cheap to catch, and keep anything correctness-critical on Claude Code or
Codex.

It is example code, not a deployed service — see README.md's "Ollama
Integration" section for the current status of a productionized wrapper.
Run it manually, or adapt it into your own launchd/systemd unit.

## Why route work to Ollama at all

Ollama's ceiling is model quality, not orchestration. The mesh gives it
free, zero-session-limit access to the same coordination primitives every
other agent uses (inbox, locks, state) — the leverage comes from *what*
you route to it, not from making it smarter. Good fits:

- **Bulk/parallel grunt work** — summarizing large batches of logs, inbox
  history, or `state.json` heartbeats before a human or a paid-session
  agent looks at them.
- **The polling loop itself** — since v1 of this mesh is polling-only (see
  AGENTS.md's "Filesystem watchers are a v2 concern"), a local Ollama
  process is a free place to run a tight poll loop against
  `claim_inbox_messages`/`health_check` without spending Claude Code or
  Codex session budget on it.
- **Draft-then-review** — Ollama produces a first-pass draft (a summary, a
  changelog entry, a commit message candidate); a Claude Code/Codex agent
  reviews and finalizes it. Cheap iteration, expensive judgment stays
  gated.
- **Pre-filtering/triage** — classify or rank inbox messages by type or
  priority before a paid-session agent claims them, so it doesn't burn
  context scanning noise.

Anything where a wrong answer is expensive to catch later — logic
changes, anything touching the lock/claim/atomic-write invariants in
AGENTS.md, anything that ships without a human or a stronger model
reviewing it — stays off this path.

## Message contract

Send `mesh_poller.py` work the same way any agent sends any other agent a
message: `send_message` (over MCP from Claude Code/Codex, or `POST
/send_message` over HTTP) targeting `agent_ollama_local` with:

```json
{
  "agent_id": "agent_mbp",
  "target_agent_id": "agent_ollama_local",
  "message_type": "mesh.ollama.task",
  "body": {
    "prompt": "Summarize this log excerpt in two sentences: ...",
    "model": "llama3.2",
    "reply_to": "agent_mbp",
    "reply_type": "mesh.ollama.result"
  }
}
```

Only `prompt` is required — `model` defaults to the poller's `--model`
flag, `reply_to` defaults to the sender, and `reply_type` defaults to
`mesh.ollama.result`. The poller claims the message, runs it through
`POST /api/generate` on a local Ollama server, and sends the result (or
an `error` field on failure) back as a new message via `send_message`.
Anything sent to `agent_ollama_local` with a different `message_type` is
acknowledged and dropped — the poller only understands this one shape.

## Running it

```bash
# make sure Ollama is running locally, and agent-mesh-http-server is
# reachable (either on this machine or over Tailscale)
python examples/ollama/mesh_poller.py \
    --mesh-http-url http://127.0.0.1:8001 \
    --ollama-url http://127.0.0.1:11434 \
    --model llama3.2 \
    --poll-interval 5

# single pass, useful for testing without a long-running loop
python examples/ollama/mesh_poller.py --once
```

No extra dependencies — the script uses only the Python standard library
(`urllib`), matching the rest of the runtime dependency footprint in
`pyproject.toml`.
