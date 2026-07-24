import asyncio
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_mesh_core import AgentMeshCoordinator
from agent_mesh_core.mcp_server import EXPOSED_TOOL_NAMES, build_server
from agent_mesh_core.rules_template import write_local_rules_template


def _run(coro):
    return asyncio.run(coro)


def test_exposes_exactly_the_documented_tool_set(mesh_root):
    server = build_server(mesh_root)

    async def go():
        async with Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    names = _run(go())
    assert names == EXPOSED_TOOL_NAMES
    assert "recover_processing" not in names
    assert "bootstrap_mesh" not in names
    assert "atomic_write_json" not in names


def test_lock_tools_round_trip(mesh_root):
    server = build_server(mesh_root)

    async def go():
        async with Client(server) as client:
            acquired = (
                await client.call_tool(
                    "acquire_lock", {"agent_id": "agent_a", "lock_name": "shared"}
                )
            ).data
            assert acquired["lock_name"] == "shared"
            assert acquired["token"]

            blocked = (
                await client.call_tool(
                    "acquire_lock",
                    {
                        "agent_id": "agent_b",
                        "lock_name": "shared",
                        "timeout": 0,
                        "retry_interval": 0,
                    },
                )
            ).data
            assert blocked is None

            await client.call_tool(
                "release_lock",
                {"agent_id": "agent_a", "lock_name": "shared", "token": acquired["token"]},
            )

            reacquired = (
                await client.call_tool(
                    "acquire_lock", {"agent_id": "agent_b", "lock_name": "shared"}
                )
            ).data
            assert reacquired["token"]

    _run(go())


def test_update_state_tool_writes_state_file(mesh_root):
    server = build_server(mesh_root)

    async def go():
        async with Client(server) as client:
            await client.call_tool(
                "update_state",
                {
                    "agent_id": "agent_a",
                    "status": "busy",
                    "tasks": ["t1"],
                    "extra_metadata": {"x": 1},
                },
            )

    _run(go())

    payload = json.loads((mesh_root / "agents" / "agent_a" / "state.json").read_text())
    assert payload["status"] == "busy"
    assert payload["active_tasks"] == ["t1"]
    assert payload["metadata"] == {"x": 1}


def test_send_message_tool_writes_envelope(mesh_root):
    server = build_server(mesh_root)
    AgentMeshCoordinator(mesh_root, "agent_b")

    async def go():
        async with Client(server) as client:
            return (
                await client.call_tool(
                    "send_message",
                    {
                        "agent_id": "agent_a",
                        "target_agent_id": "agent_b",
                        "message_type": "task.assigned",
                        "body": {"x": 1},
                    },
                )
            ).data

    envelope = _run(go())
    assert envelope["sender"] == "agent_a"
    assert envelope["target_agent_id"] == "agent_b"
    files = list((mesh_root / "agents" / "agent_b" / "inbox").glob("*.json"))
    assert len(files) == 1


def test_send_message_tool_maps_missing_inbox_to_tool_error(mesh_root):
    server = build_server(mesh_root)

    async def go():
        async with Client(server) as client:
            await client.call_tool(
                "send_message",
                {
                    "agent_id": "agent_a",
                    "target_agent_id": "agent_b",
                    "message_type": "task.assigned",
                    "body": {},
                },
            )

    with pytest.raises(ToolError, match="does not exist"):
        _run(go())


def test_claim_and_acknowledge_tools_round_trip(mesh_root):
    server = build_server(mesh_root)
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    sender.send_message("agent_a", "task.assigned", {"x": 1})
    claim_id_box: dict[str, str] = {}

    async def go():
        async with Client(server) as client:
            claimed = (
                await client.call_tool("claim_inbox_messages", {"agent_id": "agent_a"})
            ).data
            assert len(claimed["claimed"]) == 1
            item = claimed["claimed"][0]
            assert item["message"]["body"] == {"x": 1}
            claim_id_box["id"] = item["claim_id"]

            claim = {"claim_id": item["claim_id"], "claim_token": item["claim_token"]}
            acked = (
                await client.call_tool(
                    "acknowledge_claims",
                    {"agent_id": "agent_a", "claims": [claim]},
                )
            ).data
            assert acked == [{"claim_id": item["claim_id"], "status": "acknowledged"}]

    _run(go())

    claim_dir = mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / claim_id_box["id"]
    assert not claim_dir.exists()


def test_read_local_rules_tool(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_mac_mini")
    rules = write_local_rules_template(mesh_root, coordinator=coordinator)
    server = build_server(mesh_root)

    async def go():
        async with Client(server) as client:
            return (await client.call_tool("read_local_rules", {})).data

    result = _run(go())
    assert result == rules


def test_read_local_rules_tool_missing_maps_to_tool_error(mesh_root):
    server = build_server(mesh_root)

    async def go():
        async with Client(server) as client:
            await client.call_tool("read_local_rules", {})

    with pytest.raises(ToolError, match="does not exist"):
        _run(go())


def test_health_check_tool_shape(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    sender.send_message("agent_a", "task.assigned", {})
    server = build_server(mesh_root)

    async def go():
        async with Client(server) as client:
            return (await client.call_tool("health_check", {})).data

    health = _run(go())
    assert health["status"] == "ok"
    assert {"agent_id", "processing_claims"} <= health["agents"][0].keys()
    assert health["locks"] == []
