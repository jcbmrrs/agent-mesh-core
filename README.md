# agent-mesh-core

`agent-mesh-core` is a personal AgentMesh reference implementation for
coordinating trusted local AI agents across machines. A Mac mini owns the
live mesh directory on local disk; Claude Code, Codex, and Ollama-side
tooling talk to it over a private Tailscale network through MCP and HTTP
services.

This is experimental personal infrastructure, not a general-purpose
multi-tenant coordination service. The trust boundary is your private
tailnet. Callers are trusted; the app layer does not authenticate users,
authorize agents, or prevent one trusted caller from passing another
`agent_id`.

## What It Does

- Maintains per-agent inboxes, state files, and directory-based locks under
  a local mesh root.
- Writes JSON atomically with local-disk `os.replace` semantics.
- Uses claim-then-acknowledge inbox processing so dropped network clients
  do not silently lose claimed messages.
- Exposes the same dispatch layer through `agent-mesh-mcp-server` for
  Claude Code/Codex and `agent-mesh-http-server` for tools that cannot
  speak MCP.

Background and design rationale:

- [Problem statement](docs/PROBLEM_STATEMENT.md)
- [Implementation plan](docs/IMPLEMENTATION_PLAN_v2.md)
- [Operations guide](docs/OPERATIONS.md)
- [Roadmap](docs/ROADMAP.md)

## Trust Model

This project assumes one human operator, trusted machines on a private
Tailscale network, and trusted local tools that are allowed to call the
MCP/HTTP services.

This project does not provide multi-user authorization, per-client
authentication, agent ID anti-spoofing, or a security boundary between
tools already allowed to reach the service. If you need those properties,
treat this repo as a design reference rather than deployable software.

## Architecture

The live mesh root is local to the Mac mini:

```text
AgentMesh/
├── config/
│   └── local_rules.json
├── agents/
│   ├── agent_mac_mini/
│   │   ├── inbox/
│   │   └── state.json
│   ├── agent_mbp/
│   │   ├── inbox/
│   │   └── state.json
│   └── agent_ollama_local/
│       ├── inbox/
│       └── state.json
└── locks/
```

Other machines never mount or write this directory. They call services
running on the Mac mini:

- MCP: `http://<mac-mini-tailscale-host>:8000/mcp`
- HTTP wrapper: `http://<mac-mini-tailscale-host>:8001`

## New Client Setup

Use this when the Mac mini services are already deployed and you want a new
Mac, Linux, or Windows machine to talk to the mesh.

1. Install and log into Tailscale on the new machine.
2. Confirm the machine can reach the Mac mini Tailscale IP or MagicDNS name:

   ```bash
   tailscale status
   ```

3. Register the MCP server with Claude Code:

   ```bash
   claude mcp add --transport http agent-mesh http://<mac-mini-tailscale-host>:8000/mcp
   claude mcp list
   ```

4. Register the MCP server with Codex:

   ```bash
   codex mcp add agent-mesh --url http://<mac-mini-tailscale-host>:8000/mcp
   ```

Use the Mac mini's Tailscale IP if startup-time DNS resolution is a concern.
MagicDNS is easier to read, but a raw tailnet IP avoids depending on DNS
during launchd startup.

## Per-OS Notes

The MCP registration commands are the same across operating systems. The
platform-specific part is getting Tailscale installed and authenticated.

- macOS: install Tailscale from the App Store, direct download, or package
  manager; log into the same tailnet as the Mac mini.
- Linux: install Tailscale using the distribution instructions from
  Tailscale, start the service, and run `tailscale up`.
- Windows: install Tailscale for Windows, log into the same tailnet, and
  run the Codex/Claude commands from a shell that has those CLIs on `PATH`.

No SMB mount is needed on any client OS.

## Mac Mini Setup

Use this when setting up the host role from scratch or doing local
development.

1. Clone the repo and install dependencies:

   ```bash
   git clone <repo-url>
   cd agent-mesh-core
   uv sync
   ```

2. Run tests and lint:

   ```bash
   UV_CACHE_DIR=.uv-cache uv run pytest -q
   UV_CACHE_DIR=.uv-cache uv run ruff check .
   ```

3. Bootstrap a mesh root:

   ```bash
   MESH_ROOT=/Users/Shared/AgentMesh \
   AGENT_IDS=agent_mac_mini,agent_mbp,agent_ollama_local \
   ./deploy.sh
   ```

4. Render and load the MCP and HTTP launchd services.

   See [docs/OPERATIONS.md](docs/OPERATIONS.md) for the exact commands,
   logging paths, and validation steps.

## Ollama Integration

Ollama does not speak MCP and does not provide a built-in hook that makes
arbitrary coordination calls before or after inference. The deployed HTTP
wrapper exists for Ollama-side glue code to call explicitly.

Expected integration shape:

1. Keep `agent-mesh-http-server` running on the Mac mini.
2. Write or use an Ollama-side script/proxy that calls HTTP routes such as
   `POST /send_message`, `POST /claim_inbox_messages`,
   `POST /acknowledge_claims`, `POST /read_local_rules`, and
   `POST /health_check`.
3. Have that script identify itself with the provisioned agent ID
   `agent_ollama_local`.

Example health check:

```bash
curl -sS -X POST \
  http://<mac-mini-tailscale-host>:8001/health_check \
  -H "Content-Type: application/json" \
  -d '{}'
```

Example send:

```bash
curl -sS -X POST \
  http://<mac-mini-tailscale-host>:8001/send_message \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent_ollama_local",
    "target_agent_id": "agent_mbp",
    "message_type": "task.note",
    "body": {"text": "hello from ollama-side tooling"}
  }'
```

A reference poller that closes this loop end-to-end — claiming inbox
messages, routing them to a local Ollama model, and replying to the
sender — lives at
[examples/ollama/mesh_poller.py](examples/ollama/mesh_poller.py), with
the task-routing rationale (what's a good fit for Ollama vs. what should
stay on Claude Code/Codex) in
[examples/ollama/README.md](examples/ollama/README.md). It's example
code, not a deployed service — copy it into your own always-on process
(launchd/systemd) if you want it running continuously.

## Development

Useful commands:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest -q
UV_CACHE_DIR=.uv-cache uv run ruff check .
UV_CACHE_DIR=.uv-cache uv run agent-mesh-bootstrap --mesh-root /tmp/AgentMesh --agent-ids agent_mac_mini,agent_mbp,agent_ollama_local
UV_CACHE_DIR=.uv-cache uv run agent-mesh-recover-processing --mesh-root /tmp/AgentMesh --agent-id agent_mbp --dry-run
```

Runtime paths such as `agents/`, `locks/`, and live `config/*.json` files
are ignored by git. Keep the live mesh as data-only; source code and
templates belong in this repository.

## Status & Support

This is experimental personal infrastructure, maintained in spare time for a
single operator's own machines — not a supported product with an SLA.
Issues and PRs are welcome, but there's no commitment on response time, and
feature requests outside the single-operator/private-tailnet scope
described in [Trust Model](#trust-model) are likely to be declined rather
than accepted. See [SECURITY.md](SECURITY.md) for the trust boundary and how
to report a real security concern.

## License

[MIT](LICENSE)
