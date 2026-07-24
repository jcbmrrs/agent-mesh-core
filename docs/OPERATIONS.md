# AgentMesh Operations

## MCP server on launchd

The launchd template lives at
`deploy/launchd/com.jacobmorris.agent-mesh-core.mcp-server.plist.template`.
Render the installed plist on the Mac mini with:

```bash
deploy/launchd/render_mcp_launchd_plist.py \
  --uv-bin /opt/homebrew/bin/uv \
  --repo-dir /path/to/agent-mesh-core \
  --mesh-root /Users/Shared/AgentMesh \
  --tailscale-host <mac-mini-tailscale-ip-or-magicdns> \
  --port 8000
```

The render script writes the plist to
`~/Library/LaunchAgents/com.jacobmorris.agent-mesh-core.mcp-server.plist`
by default and creates the log directory before writing the plist.

Deployment-specific values:

- `__UV_BIN__`: absolute path to `uv` on the Mac mini, for example
  `/opt/homebrew/bin/uv`
- `__REPO_DIR__`: absolute path to this repo checkout on the Mac mini
- `__MESH_ROOT__`: live local mesh root, normally `/Users/Shared/AgentMesh`
- `__TAILSCALE_HOST__`: the Mac mini Tailscale IP or MagicDNS bind host
- `__PORT__`: MCP server port, normally `8000`
- `__LOG_DIR__`: log directory, normally
  `/Users/jacobmorris/Library/Logs/agent-mesh-core`

The plist runs:

```bash
uv run agent-mesh-mcp-server --mesh-root "$MESH_ROOT" --host "$TAILSCALE_HOST" --port "$PORT"
```

`RunAtLoad` and `KeepAlive` are enabled. stdout goes to `mcp_server.log`;
stderr goes to `mcp_server.err.log`. v1 intentionally has no log rotation.

Before starting FastMCP, `agent-mesh-mcp-server` validates that the mesh root
already exists, is a directory, and is writable. Invalid startup config exits
with status `2` and a clear stderr message.
