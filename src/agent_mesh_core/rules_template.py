from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_mesh_core.coordinator import AgentMeshCoordinator, MeshJsonWriter

DEFAULT_LOCAL_RULES: dict[str, Any] = {
    "schema_version": 1,
    "network_context": {
        "transport": "mcp_server_over_tailscale",
        "mesh_root_writer": "mac_mini_only",
    },
    "model_overrides": {},
    "file_tree_exclusions": [
        ".git",
        "__pycache__",
        ".venv",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
    ],
}


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def build_local_rules(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if overrides is None:
        return deepcopy(DEFAULT_LOCAL_RULES)
    return deep_merge(DEFAULT_LOCAL_RULES, overrides)


def write_local_rules_template(
    mesh_root: str | Path,
    overrides: dict[str, Any] | None = None,
    force: bool = False,
    coordinator: AgentMeshCoordinator | None = None,
) -> dict[str, Any]:
    mesh_root = Path(mesh_root)
    target = mesh_root / "config" / "local_rules.json"
    if target.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing local rules: {target}")
    writer = coordinator or MeshJsonWriter(mesh_root)
    rules = build_local_rules(overrides)
    writer.atomic_write_json(target, rules)
    return rules


def read_local_rules(mesh_root: str | Path) -> dict[str, Any]:
    target = Path(mesh_root) / "config" / "local_rules.json"
    if not target.exists():
        raise FileNotFoundError(f"local rules file does not exist: {target}")
    with target.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"local rules file must contain a JSON object: {target}")
    return data
