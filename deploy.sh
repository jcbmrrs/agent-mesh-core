#!/usr/bin/env bash
set -euo pipefail

MESH_ROOT="${MESH_ROOT:-/Users/Shared/AgentMesh}"
AGENT_IDS="${AGENT_IDS:-agent_mac_mini,agent_mbp,agent_ollama_local}"

uv run agent-mesh-bootstrap --mesh-root "$MESH_ROOT" --agent-ids "$AGENT_IDS"
