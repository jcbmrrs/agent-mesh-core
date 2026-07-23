import json

from agent_mesh_core.bootstrap import DEFAULT_AGENT_IDS, bootstrap_mesh


def test_bootstrap_integration_default_tree(mesh_root):
    bootstrap_mesh(mesh_root)

    for agent_id in DEFAULT_AGENT_IDS:
        assert (mesh_root / "agents" / agent_id / "inbox").is_dir()
    assert (mesh_root / "locks").is_dir()
    rules = json.loads((mesh_root / "config" / "local_rules.json").read_text())
    assert rules["schema_version"] == 1
