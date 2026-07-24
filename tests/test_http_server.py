import json

from starlette.testclient import TestClient

from agent_mesh_core import AgentMeshCoordinator
from agent_mesh_core.dispatch import EXPOSED_OPERATIONS
from agent_mesh_core.http_server import build_app, main
from agent_mesh_core.rules_template import write_local_rules_template


def _client(mesh_root) -> TestClient:
    return TestClient(build_app(mesh_root))


def test_main_validates_mesh_root_before_building_app(tmp_path, monkeypatch):
    missing = tmp_path / "missing"

    def fail_if_called(mesh_root):
        raise AssertionError(f"build_app should not be called for {mesh_root}")

    monkeypatch.setattr("agent_mesh_core.http_server.build_app", fail_if_called)

    assert main(["--mesh-root", str(missing)]) == 2


def test_main_reports_validation_error_on_stderr(tmp_path, capsys):
    missing = tmp_path / "missing"

    main(["--mesh-root", str(missing)])

    captured = capsys.readouterr()
    assert "does not exist" in captured.err


def test_exposes_exactly_the_documented_routes(mesh_root):
    app = build_app(mesh_root)
    paths = {route.path.lstrip("/") for route in app.routes}

    assert paths == EXPOSED_OPERATIONS
    assert "recover_processing" not in paths
    assert "bootstrap_mesh" not in paths
    assert "atomic_write_json" not in paths


def test_lock_routes_round_trip(mesh_root):
    with _client(mesh_root) as client:
        acquired = client.post(
            "/acquire_lock", json={"agent_id": "agent_a", "lock_name": "shared"}
        ).json()
        assert acquired["lock_name"] == "shared"
        assert acquired["token"]

        blocked = client.post(
            "/acquire_lock",
            json={
                "agent_id": "agent_b",
                "lock_name": "shared",
                "timeout": 0,
                "retry_interval": 0,
            },
        ).json()
        assert blocked is None

        client.post(
            "/release_lock",
            json={"agent_id": "agent_a", "lock_name": "shared", "token": acquired["token"]},
        )

        reacquired = client.post(
            "/acquire_lock", json={"agent_id": "agent_b", "lock_name": "shared"}
        ).json()
        assert reacquired["token"]


def test_update_state_route_writes_state_file(mesh_root):
    with _client(mesh_root) as client:
        response = client.post(
            "/update_state",
            json={
                "agent_id": "agent_a",
                "status": "busy",
                "tasks": ["t1"],
                "extra_metadata": {"x": 1},
            },
        )
        assert response.status_code == 200

    payload = json.loads((mesh_root / "agents" / "agent_a" / "state.json").read_text())
    assert payload["status"] == "busy"
    assert payload["active_tasks"] == ["t1"]
    assert payload["metadata"] == {"x": 1}


def test_send_message_route_writes_envelope(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_b")

    with _client(mesh_root) as client:
        response = client.post(
            "/send_message",
            json={
                "agent_id": "agent_a",
                "target_agent_id": "agent_b",
                "message_type": "task.assigned",
                "body": {"x": 1},
            },
        )

    assert response.status_code == 200
    envelope = response.json()
    assert envelope["sender"] == "agent_a"
    assert envelope["target_agent_id"] == "agent_b"
    files = list((mesh_root / "agents" / "agent_b" / "inbox").glob("*.json"))
    assert len(files) == 1


def test_send_message_route_maps_missing_inbox_to_404(mesh_root):
    with _client(mesh_root) as client:
        response = client.post(
            "/send_message",
            json={
                "agent_id": "agent_a",
                "target_agent_id": "agent_b",
                "message_type": "task.assigned",
                "body": {},
            },
        )

    assert response.status_code == 404
    assert "does not exist" in response.json()["error"]


def test_acquire_lock_route_maps_invalid_name_to_400(mesh_root):
    with _client(mesh_root) as client:
        response = client.post(
            "/acquire_lock", json={"agent_id": "agent_a", "lock_name": "../bad"}
        )

    assert response.status_code == 400
    assert "error" in response.json()


def test_route_maps_missing_required_arguments_to_400(mesh_root):
    with _client(mesh_root) as client:
        response = client.post("/acquire_lock", json={})

    assert response.status_code == 400
    assert "missing" in response.json()["error"]


def test_route_maps_non_object_json_to_400(mesh_root):
    with _client(mesh_root) as client:
        response = client.post("/acquire_lock", json=[])

    assert response.status_code == 400
    assert "JSON object" in response.json()["error"]


def test_route_maps_malformed_json_to_400(mesh_root):
    with _client(mesh_root) as client:
        response = client.post(
            "/acquire_lock",
            content="not-json",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert "malformed JSON" in response.json()["error"]


def test_claim_and_acknowledge_routes_round_trip(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    sender.send_message("agent_a", "task.assigned", {"x": 1})

    with _client(mesh_root) as client:
        claimed = client.post(
            "/claim_inbox_messages", json={"agent_id": "agent_a"}
        ).json()
        assert len(claimed["claimed"]) == 1
        item = claimed["claimed"][0]
        assert item["message"]["body"] == {"x": 1}

        claim = {"claim_id": item["claim_id"], "claim_token": item["claim_token"]}
        acked = client.post(
            "/acknowledge_claims", json={"agent_id": "agent_a", "claims": [claim]}
        ).json()
        assert acked == [{"claim_id": item["claim_id"], "status": "acknowledged"}]

    claim_dir = mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / item["claim_id"]
    assert not claim_dir.exists()


def test_read_local_rules_route(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_mac_mini")
    rules = write_local_rules_template(mesh_root, coordinator=coordinator)

    with _client(mesh_root) as client:
        response = client.post("/read_local_rules", json={})

    assert response.status_code == 200
    assert response.json() == rules


def test_read_local_rules_route_missing_maps_to_404(mesh_root):
    with _client(mesh_root) as client:
        response = client.post("/read_local_rules", json={})

    assert response.status_code == 404
    assert "does not exist" in response.json()["error"]


def test_health_check_route_shape(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    sender.send_message("agent_a", "task.assigned", {})

    with _client(mesh_root) as client:
        response = client.post("/health_check", json={})

    assert response.status_code == 200
    health = response.json()
    assert health["status"] == "ok"
    assert {"agent_id", "processing_claims"} <= health["agents"][0].keys()
    assert health["locks"] == []
